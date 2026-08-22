from __future__ import annotations

import asyncio
from datetime import datetime
from html import escape


def reminder_text(kind: str, title: str, scheduled: datetime) -> str:
    safe_title = escape(title)
    messages = {
        "week": f"Через неделю у вас <b>{safe_title}</b>\n{scheduled:%d.%m.%Y в %H:%M}.",
        "day": f"Уже завтра: <b>{safe_title}</b>\n{scheduled:%d.%m.%Y в %H:%M}. Вы с нами?",
        "hours": f"Уже через несколько часов: <b>{safe_title}</b>\nНачало в {scheduled:%H:%M}.",
        "event": f"Пора! Сегодня вы планировали <b>{safe_title}</b> 🚀",
        "followup": (
            f"Ну как прошло <b>{safe_title}</b>? Откройте «📍 Текущая активность», "
            "подтвердите участие и добавьте фото."
        ),
    }
    return messages[kind]


async def reminder_loop(db, bot, *, interval_seconds: int = 60) -> None:
    while True:
        for user_id, kind, title, scheduled in await db.due_reminders(datetime.now()):
            try:
                await bot.send_message(user_id, reminder_text(kind, title, scheduled))
            except Exception:
                # A blocked bot must not stop reminders for everyone else.
                continue
        await asyncio.sleep(interval_seconds)

