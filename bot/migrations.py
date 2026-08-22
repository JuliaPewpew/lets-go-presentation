from __future__ import annotations

from collections.abc import Awaitable, Callable

import aiosqlite

Migration = Callable[[aiosqlite.Connection], Awaitable[None]]


async def _add_idea_description(db: aiosqlite.Connection) -> None:
    columns = {row["name"] for row in await (await db.execute("PRAGMA table_info(ideas)")).fetchall()}
    if "description" not in columns:
        await db.execute("ALTER TABLE ideas ADD COLUMN description TEXT")


async def _add_extended_reminder_flags(db: aiosqlite.Connection) -> None:
    columns = {row["name"] for row in await (await db.execute("PRAGMA table_info(activities)")).fetchall()}
    if "reminder_week_sent" not in columns:
        await db.execute("ALTER TABLE activities ADD COLUMN reminder_week_sent INTEGER NOT NULL DEFAULT 0")
    if "reminder_hours_sent" not in columns:
        await db.execute("ALTER TABLE activities ADD COLUMN reminder_hours_sent INTEGER NOT NULL DEFAULT 0")


MIGRATIONS: tuple[tuple[int, str, Migration], ...] = (
    (1, "idea descriptions", _add_idea_description),
    (2, "extended reminder flags", _add_extended_reminder_flags),
)


async def apply_migrations(db: aiosqlite.Connection) -> None:
    """Apply idempotent, ordered SQLite migrations and keep an audit trail."""
    await db.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations(
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    applied = {
        row["version"]
        for row in await (await db.execute("SELECT version FROM schema_migrations")).fetchall()
    }
    for version, name, migration in MIGRATIONS:
        if version in applied:
            continue
        await migration(db)
        await db.execute(
            "INSERT INTO schema_migrations(version,name) VALUES(?,?)",
            (version, name),
        )

