from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

REMINDER_KEYS = ("reminder_week", "reminder_day", "reminder_hours", "reminder_event", "reminder_followup")
PHOTO_CONTENT_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024
REACTIONS = frozenset({"👍", "❤️", "🔥"})


class ValidationError(ValueError):
    """A safe validation message that can be shown to an end user."""


@dataclass(frozen=True)
class IdeaInput:
    title: str
    description: str | None
    difficulty: int
    budget: int
    duration: int
    anonymous: bool

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "IdeaInput":
        title = str(values.get("title", "")).strip()[:180]
        if len(title) < 4:
            raise ValidationError("Название слишком короткое")
        try:
            ratings = tuple(int(values.get(key, 0)) for key in ("difficulty", "budget", "duration"))
        except (TypeError, ValueError) as error:
            raise ValidationError("Оценки должны быть от 1 до 5") from error
        if any(rating not in range(1, 6) for rating in ratings):
            raise ValidationError("Оценки должны быть от 1 до 5")
        return cls(
            title=title,
            description=str(values.get("description", "")).strip()[:1000] or None,
            difficulty=ratings[0],
            budget=ratings[1],
            duration=ratings[2],
            anonymous=bool(values.get("anonymous")),
        )


def future_datetime(value: Any, *, now: datetime | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValidationError("Укажите корректную дату и время") from error
    if parsed <= (now or datetime.now()):
        raise ValidationError("Выберите будущую дату")
    return parsed

