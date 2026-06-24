import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
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
        created_at=doc.created_at.isoformat(),
    ).model_dump()


async def _process_document(doc_id: UUID, user_id: str, file_path: Path, file_type: str) -> None:
    from app.services import embeddings, parser, vector_store

    async with async_session() as db:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        try:
            doc_id_str = str(doc_id)
            if file_type == "pdf":
                pages = parser.parse_pdf(str(file_path))
            elif file_type == "docx":
                pages = parser.parse_docx(str(file_path))
            else:
                doc.status = "error"
                await db.commit()
                return

            chunks = parser.chunk_text(pages, doc_id_str)
            if not chunks:
                doc.status = "error"
                await db.commit()
                return

            texts = [c["text"] for c in chunks]
            chunk_embeddings = await asyncio.to_thread(embeddings.embed_chunks, texts)
            await asyncio.to_thread(
                vector_store.add_document, doc_id_str, chunks, chunk_embeddings
            )

            doc.status = "ready"
            doc.chunk_count = len(chunks)
            await db.commit()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("Document processing failed: %s", exc)
            doc.status = "error"
            await db.commit()


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
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

    stored_name, file_path = await save_upload_file(str(current_user.id), file)

    doc = Document(
        user_id=current_user.id,
        filename=stored_name,
        original_name=file.filename or stored_name,
        file_type=file_type,
        file_size=len(content),
        status="processing",
    )
    db.add(doc)
    await db.flush()

    background_tasks.add_task(
        _process_document, doc.id, str(current_user.id), file_path, file_type
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
