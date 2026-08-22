from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .domain import MAX_PHOTO_BYTES, PHOTO_CONTENT_TYPES, ValidationError


class PhotoStorage:
    """Stores uploaded activity photos independently from HTTP and Telegram."""

    def __init__(self, database_path: str):
        self.directory = Path(database_path).resolve().parent / "photos"

    def save(self, content: bytes, content_type: str) -> Path:
        if content_type not in PHOTO_CONTENT_TYPES:
            raise ValidationError("Нужно изображение JPG, PNG или WebP")
        if not content or len(content) > MAX_PHOTO_BYTES:
            raise ValidationError("Фото должно быть не больше 10 МБ")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{uuid4().hex}.{PHOTO_CONTENT_TYPES[content_type]}"
        path.write_bytes(content)
        return path

