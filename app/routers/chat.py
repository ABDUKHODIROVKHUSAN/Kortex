import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ChatMessage, Document, User
from app.schemas.document import ChatMessageResponse, ChatSessionSummary, DocumentChatStats
from app.utils.auth import get_current_user
from app.services import usage as usage_service

router = APIRouter()


def _message_response(msg: ChatMessage) -> dict:
    return ChatMessageResponse(
        id=str(msg.id),
        document_id=str(msg.document_id),
        role=msg.role,
        content=msg.content,
        sources=msg.sources,
        created_at=msg.created_at.isoformat(),
    ).model_dump()


async def _get_user_document(
    doc_id: UUID, user: User, db: AsyncSession
) -> Document:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is not ready for chat",
        )
    return doc


@router.get("/usage")
async def chat_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await usage_service.get_usage(db, current_user.id, current_user.subscription_tier)
    return {
        "success": True,
        "data": data,
        "message": "Chat usage retrieved",
    }


@router.get("/stats")
async def chat_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs_result = await db.execute(
        select(Document).where(Document.user_id == current_user.id)
    )
    docs = {str(d.id): d for d in docs_result.scalars().all()}
    if not docs:
        return {"success": True, "data": [], "message": "Chat stats retrieved"}

    msgs_result = await db.execute(
        select(ChatMessage).where(ChatMessage.user_id == current_user.id)
    )
    by_doc: dict[str, list[ChatMessage]] = {}
    for msg in msgs_result.scalars().all():
        key = str(msg.document_id)
        by_doc.setdefault(key, []).append(msg)

    stats: list[dict] = []
    for doc_id, messages in by_doc.items():
        if doc_id not in docs:
            continue
        messages.sort(key=lambda m: m.created_at)
        question_count = sum(1 for m in messages if m.role == "user")
        stats.append(
            DocumentChatStats(
                document_id=doc_id,
                message_count=len(messages),
                question_count=question_count,
                last_activity_at=messages[-1].created_at.isoformat(),
            ).model_dump()
        )

    return {"success": True, "data": stats, "message": "Chat stats retrieved"}


@router.get("/sessions")
async def chat_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs_result = await db.execute(
        select(Document).where(Document.user_id == current_user.id)
    )
    docs = {str(d.id): d for d in docs_result.scalars().all()}

    msgs_result = await db.execute(
        select(ChatMessage).where(ChatMessage.user_id == current_user.id)
    )
    by_doc: dict[str, list[ChatMessage]] = {}
    for msg in msgs_result.scalars().all():
        key = str(msg.document_id)
        by_doc.setdefault(key, []).append(msg)

    sessions: list[dict] = []
    for doc_id, messages in by_doc.items():
        doc = docs.get(doc_id)
        if not doc or not messages:
            continue
        messages.sort(key=lambda m: m.created_at)
        user_messages = [m for m in messages if m.role == "user"]
        first_question = (
            user_messages[0].content if user_messages else messages[0].content
        )
        sessions.append(
            ChatSessionSummary(
                document_id=doc_id,
                document_name=doc.original_name,
                first_question=first_question[:240],
                message_count=len(messages),
                last_activity_at=messages[-1].created_at.isoformat(),
            ).model_dump()
        )

    sessions.sort(key=lambda s: s["last_activity_at"], reverse=True)

    return {
        "success": True,
        "data": sessions,
        "message": "Chat sessions retrieved",
    }


@router.get("/stream")
async def chat_stream(
    doc_id: UUID = Query(...),
    query: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_user_document(doc_id, current_user, db)
    await usage_service.ensure_can_chat(db, current_user.id, current_user.subscription_tier)

    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.document_id == doc_id)
        .order_by(ChatMessage.created_at.asc())
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in history_result.scalars().all()
    ]

    user_msg = ChatMessage(
        document_id=doc.id,
        user_id=current_user.id,
        role="user",
        content=query,
        sources=[],
    )
    db.add(user_msg)
    await db.flush()

    user_id = current_user.id
    user_email = current_user.email
    document_id = doc.id
    subscription_tier = current_user.subscription_tier

    async def event_generator():
        from app.database import async_session
        from app.services.agent import stream_chat
        from app.services.admin_failures import record_system_failure

        full_response = ""
        sources: list | None = None
        usage_data: dict | None = None

        try:
            async for token, src in stream_chat(
                str(doc_id),
                query,
                history,
                user_id=user_id,
                user_email=user_email,
            ):
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                if src is not None:
                    sources = src

            tokens = usage_service.estimate_tokens(query, full_response)

            async with async_session() as session:
                assistant_msg = ChatMessage(
                    document_id=document_id,
                    user_id=user_id,
                    role="assistant",
                    content=full_response,
                    sources=sources or [],
                )
                session.add(assistant_msg)
                usage_data = await usage_service.record_chat_usage(
                    session, user_id, subscription_tier, tokens
                )
                await session.commit()

            yield f"data: {json.dumps({'type': 'done', 'sources': sources or [], 'usage': usage_data})}\n\n"
        except Exception as exc:
            try:
                await record_system_failure(
                    message=str(exc),
                    error_type="chat_stream_failed",
                    user_id=user_id,
                    user_email=user_email,
                    document_id=document_id,
                    query_preview=query,
                )
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history/{doc_id}")
async def chat_history(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_user_document(doc_id, current_user, db)

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.document_id == doc_id, ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()

    return {
        "success": True,
        "data": [_message_response(m) for m in messages],
        "message": "Chat history retrieved",
    }


@router.delete("/history/{doc_id}")
async def clear_chat_history(
    doc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_user_document(doc_id, current_user, db)

    await db.execute(
        delete(ChatMessage).where(
            ChatMessage.document_id == doc_id,
            ChatMessage.user_id == current_user.id,
        )
    )
    await db.flush()

    return {
        "success": True,
        "data": None,
        "message": "Chat history cleared",
    }
