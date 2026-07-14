from datetime import datetime

from pydantic import BaseModel


class AdminUserItem(BaseModel):
    id: str
    email: str
    full_name: str
    subscription_tier: str
    is_admin: bool
    document_count: int
    created_at: datetime | None = None


class AdminStats(BaseModel):
    total_users: int
    total_documents: int
    free_users: int
    pro_users: int
    business_users: int
    unread_failures: int


class AdminFailureItem(BaseModel):
    id: str
    user_id: str | None
    user_email: str | None
    document_id: str | None
    error_type: str
    message: str
    query_preview: str | None
    is_read: bool
    created_at: datetime | None = None
