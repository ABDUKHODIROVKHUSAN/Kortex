import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models import Document, User
from app.schemas.document import DocumentResponse, DocumentUpdate
from app.utils.auth import get_current_user
from app.services.tiers import is_format_allowed
from app.utils.file_handler import delete_file, get_document_path, save_upload_file

router = APIRouter()

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}
MAX_FILE_SIZE = 50 * 1024 * 1024


def _detect_file_type(filename: str | None, content_type: str | None) -> str | None:
    ext = Path(filename or "").suffix.lower()
    if ext == ".pdf" or content_type == "application/pdf":
        return "pdf"
    if ext == ".docx" or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    if ext == ".doc" or content_type == "application/msword":
        return "doc"
    return None


def _clamp_chunk_settings(chunk_size: int, chunk_overlap: int) -> tuple[int, int]:
    size = max(256, min(2048, int(chunk_size)))
    overlap = max(0, min(200, int(chunk_overlap)))
    if overlap >= size:
        overlap = max(0, size // 10)
    return size, overlap


def _doc_response(doc: Document) -> dict:
    return DocumentResponse(
        id=str(doc.id),
        user_id=str(doc.user_id),
        filename=doc.filename,
        original_name=doc.original_name,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        chunk_count=doc.chunk_count,
        progress_percent=getattr(doc, "progress_percent", 0) or 0,
        progress_stage=getattr(doc, "progress_stage", "queued") or "queued",
        chunk_size=getattr(doc, "chunk_size", 500) or 500,
        chunk_overlap=getattr(doc, "chunk_overlap", 50) or 50,
        created_at=doc.created_at.isoformat(),
    ).model_dump()


async def _set_progress(db: AsyncSession, doc: Document, percent: int, stage: str) -> None:
    doc.progress_percent = max(0, min(100, percent))
    doc.progress_stage = stage
    await db.commit()


async def _process_document(
    doc_id: UUID,
    user_id: str,
    file_path: Path,
    file_type: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> None:
    from app.services import embeddings, parser, vector_store

    chunk_size, chunk_overlap = _clamp_chunk_settings(chunk_size, chunk_overlap)

    async with async_session() as db:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        try:
            doc_id_str = str(doc_id)
            await _set_progress(db, doc, 8, "extracting")

            if file_type == "pdf":
                pages = await asyncio.to_thread(parser.parse_pdf, str(file_path))
            elif file_type == "docx":
                pages = await asyncio.to_thread(parser.parse_docx, str(file_path))
            else:
                doc.status = "error"
                doc.progress_stage = "error"
                doc.progress_percent = 0
                await db.commit()
                return

            await _set_progress(db, doc, 18, "chunking")
            chunks = await asyncio.to_thread(
                parser.chunk_text, pages, doc_id_str, chunk_size, chunk_overlap
            )
            if not chunks:
                doc.status = "error"
                doc.progress_stage = "error"
                doc.progress_percent = 0
                await db.commit()
                return

            doc.chunk_count = len(chunks)
            await _set_progress(db, doc, 22, "embedding")

            texts = [c["text"] for c in chunks]
            chunk_embeddings: list[list[float]] = []
            batch_size = 32
            total = len(texts)
            for start in range(0, total, batch_size):
                batch = texts[start : start + batch_size]
                batch_emb = await asyncio.to_thread(embeddings.embed_chunks, batch)
                chunk_embeddings.extend(batch_emb)
                done = min(start + batch_size, total)
                # Embedding is the long stretch: 22% → 90%
                pct = 22 + int(68 * done / total)
                await _set_progress(db, doc, pct, "embedding")

            await _set_progress(db, doc, 93, "storing")
            await asyncio.to_thread(
                vector_store.add_document, doc_id_str, chunks, chunk_embeddings
            )

            doc.status = "ready"
            doc.chunk_count = len(chunks)
            doc.progress_percent = 100
            doc.progress_stage = "ready"
            await db.commit()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("Document processing failed: %s", exc)
            doc.status = "error"
            doc.progress_stage = "error"
            doc.progress_percent = 0
            await db.commit()


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_type = _detect_file_type(file.filename, file.content_type)
    if not file_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type",
        )

    if not is_format_allowed(current_user.subscription_tier, file_type):
        if file_type == "docx":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="DOCX uploads are only available on Pro and Business plans. Upgrade now.",
            )
        if file_type == "doc":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="DOC uploads are only available on the Business plan. Upgrade now.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This file type is not available on your plan. Upgrade now.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds 50MB limit",
        )

    await file.seek(0)
    chunk_size, chunk_overlap = _clamp_chunk_settings(chunk_size, chunk_overlap)

    stored_name, file_path = await save_upload_file(str(current_user.id), file)

    doc = Document(
        user_id=current_user.id,
        filename=stored_name,
        original_name=file.filename or stored_name,
        file_type=file_type,
        file_size=len(content),
        status="processing",
        progress_percent=3,
        progress_stage="queued",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    db.add(doc)
    await db.flush()

    background_tasks.add_task(
        _process_document,
        doc.id,
        str(current_user.id),
        file_path,
        file_type,
        chunk_size,
        chunk_overlap,
    )

    return {
        "success": True,
        "data": _doc_response(doc),
        "message": "Document uploaded and processing started",
    }


@router.get("/")
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return {
        "success": True,
        "data": [_doc_response(d) for d in docs],
        "message": "Documents retrieved",
    }


@router.get("/{doc_id}")
async def get_document(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id, Document.user_id == current_user.id
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return {
        "success": True,
        "data": _doc_response(doc),
        "message": "Document retrieved",
    }


@router.get("/{doc_id}/file")
async def download_document_file(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream the original uploaded file (used by the in-app PDF citation viewer)."""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id, Document.user_id == current_user.id
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    file_path = get_document_path(str(current_user.id), doc.filename)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")

    media = (
        "application/pdf"
        if doc.file_type == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        path=str(file_path),
        media_type=media,
        filename=doc.original_name,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.patch("/{doc_id}")
async def update_document(
    doc_id: UUID,
    body: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    name = body.original_name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document name cannot be empty",
        )

    result = await db.execute(
        select(Document).where(
            Document.id == doc_id, Document.user_id == current_user.id
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    doc.original_name = name[:512]
    await db.flush()

    return {
        "success": True,
        "data": _doc_response(doc),
        "message": "Document updated",
    }


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id, Document.user_id == current_user.id
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    file_path = get_document_path(str(current_user.id), doc.filename)
    delete_file(file_path)
    from app.services import vector_store

    vector_store.delete_document(str(doc_id))

    await db.delete(doc)
    await db.flush()

    return {
        "success": True,
        "data": None,
        "message": "Document deleted",
    }
