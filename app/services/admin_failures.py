"""Record platform failures for the admin dashboard."""

from uuid import UUID

from app.database import async_session
from app.models import SystemFailure


async def record_system_failure(
    *,
    message: str,
    error_type: str = "llm_request_failed",
    user_id: UUID | None = None,
    user_email: str | None = None,
    document_id: str | UUID | None = None,
    query_preview: str | None = None,
) -> None:
    doc_uuid: UUID | None = None
    if document_id:
        try:
            doc_uuid = UUID(str(document_id))
        except ValueError:
            doc_uuid = None

    preview = (query_preview or "")[:500] or None
    clean_message = (message or "Unknown error")[:4000]

    async with async_session() as session:
        session.add(
            SystemFailure(
                user_id=user_id,
                user_email=user_email,
                document_id=doc_uuid,
                error_type=error_type,
                message=clean_message,
                query_preview=preview,
                is_read=False,
            )
        )
        await session.commit()
