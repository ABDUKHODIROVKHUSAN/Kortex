from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    filename: str
    original_name: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    progress_percent: int = 0
    progress_stage: str = "queued"
    created_at: str


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    role: str
    content: str
    sources: list | None
    created_at: str


class DocumentUpdate(BaseModel):
    original_name: str


class ChatSessionSummary(BaseModel):
    document_id: str
    document_name: str
    first_question: str
    message_count: int
    last_activity_at: str


class DocumentChatStats(BaseModel):
    document_id: str
    message_count: int
    question_count: int
    last_activity_at: str | None
