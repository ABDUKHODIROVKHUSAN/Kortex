import os
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings


def ensure_upload_dir(user_id: str) -> Path:
    path = Path(settings.UPLOAD_DIR) / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_upload_file(user_id: str, file: UploadFile) -> tuple[str, Path]:
    ext = Path(file.filename or "").suffix.lower()
    stored_name = f"{uuid.uuid4()}{ext}"
    user_dir = ensure_upload_dir(user_id)
    file_path = user_dir / stored_name

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    return stored_name, file_path


def delete_file(file_path: Path) -> None:
    if file_path.exists():
        os.remove(file_path)


def get_document_path(user_id: str, filename: str) -> Path:
    return Path(settings.UPLOAD_DIR) / user_id / filename
