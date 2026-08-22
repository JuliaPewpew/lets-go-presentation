from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime

import aiosqlite

from .migrations import apply_migrations
from .schema import SCHEMA


class Database:
    def __init__(self, path: str):
        self.path = path

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        try:
            yield db
        finally:
            await db.close()

    async def init(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        async with self.connect() as db:
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA synchronous = NORMAL")
            await db.executescript(SCHEMA)
            await apply_migrations(db)
            await db.execute("PRAGMA optimize")
            await db.commit()

    async def upsert_user(self, user_id: int, username: str | None, name: str) -> None:
        async with self.connect() as db:
            await db.execute(
                """INSERT INTO users(id, username, display_name) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET username=excluded.username, display_name=excluded.display_name""",
                (user_id, username, name),
            )
            await db.commit()

    async def create_company(self, user_id: int, name: str) -> tuple[int, str]:
        code = secrets.token_urlsafe(6)
        now = datetime.now().isoformat()
        async with self.connect() as db:
            cursor = await db.execute(
                "INSERT INTO companies(name, invite_code, owner_id, created_at) VALUES(?,?,?,?)",
                (name, code, user_id, now),
            )
            company_id = cursor.lastrowid
            await db.execute("INSERT INTO members VALUES(?,?,?)", (company_id, user_id, now))
            await db.execute("UPDATE users SET active_company_id=? WHERE id=?", (company_id, user_id))
            await db.commit()
        return int(company_id), code

    async def join_company(self, user_id: int, code: str) -> str | None:
        async with self.connect() as db:
            company = await (await db.execute("SELECT id,name FROM companies WHERE invite_code=?", (code,))).fetchone()
            if not company:
                return None
            await db.execute(
                "INSERT OR IGNORE INTO members VALUES(?,?,?)",
                (company["id"], user_id, datetime.now().isoformat()),
            )
            await db.execute("UPDATE users SET active_company_id=? WHERE id=?", (company["id"], user_id))
            await db.commit()
            return str(company["name"])

    async def active_company(self, user_id: int):
        async with self.connect() as db:
            return await (await db.execute(
                """SELECT c.* FROM companies c JOIN users u ON u.active_company_id=c.id WHERE u.id=?""",
                (user_id,),
            )).fetchone()

    async def user_companies(self, user_id: int):
        async with self.connect() as db:
            return await (await db.execute(
                """SELECT c.*,c.id=u.active_company_id active
                FROM members m
                JOIN companies c ON c.id=m.company_id
                JOIN users u ON u.id=m.user_id
                WHERE m.user_id=? ORDER BY active DESC,c.name""",
                (user_id,),
            )).fetchall()

    async def switch_company(self, user_id: int, company_id: int) -> str | None:
        async with self.connect() as db:
            company = await (await db.execute(
                """SELECT c.name FROM companies c JOIN members m ON m.company_id=c.id
                WHERE c.id=? AND m.user_id=?""",
                (company_id, user_id),
            )).fetchone()
            if not company:
                return None
            await db.execute("UPDATE users SET active_company_id=? WHERE id=?", (company_id, user_id))
            await db.commit()
            return str(company["name"])

    async def leave_company(self, user_id: int, company_id: int) -> str | None:
        """Leave a company, transferring ownership to its oldest other member."""
        async with self.connect() as db:
            company = await (
                await db.execute(
                    """SELECT c.owner_id FROM companies c JOIN members m ON m.company_id=c.id
                    WHERE c.id=? AND m.user_id=?""",
                    (company_id, user_id),
                )
            ).fetchone()
            if not company:
                raise LookupError("Компания недоступна")
            new_owner_name = None
            if company["owner_id"] == user_id:
                successor = await (
                    await db.execute(
                        """SELECT m.user_id,u.display_name FROM members m
                        JOIN users u ON u.id=m.user_id
                        WHERE m.company_id=? AND m.user_id!=?
                        ORDER BY m.joined_at,m.user_id LIMIT 1""",
                        (company_id, user_id),
                    )
                ).fetchone()
                if not successor:
                    raise ValueError(
                        "Вы единственный участник. Сначала пригласите друга, чтобы передать ему компанию."
                    )
                await db.execute(
                    "UPDATE companies SET owner_id=? WHERE id=?",
                    (successor["user_id"], company_id),
                )
                new_owner_name = str(successor["display_name"])
            await db.execute(
                "DELETE FROM members WHERE company_id=? AND user_id=?",
                (company_id, user_id),
            )
            fallback = await (
                await db.execute(
                    "SELECT company_id FROM members WHERE user_id=? ORDER BY joined_at LIMIT 1",
                    (user_id,),
                )
            ).fetchone()
            await db.execute(
                "UPDATE users SET active_company_id=? WHERE id=?",
                (fallback["company_id"] if fallback else None, user_id),
            )
            await db.commit()
            return new_owner_name

    async def add_idea(self, company_id: int, author_id: int, title: str, difficulty: int, budget: int, duration: int, anonymous: bool, description: str | None = None) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """INSERT INTO ideas(company_id,author_id,title,description,difficulty,budget,duration,anonymous,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (company_id, author_id, title, description, difficulty, budget, duration, int(anonymous), datetime.now().isoformat()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def ideas(self, company_id: int):
        async with self.connect() as db:
            return await (await db.execute(
                """SELECT i.*,u.display_name author FROM ideas i JOIN users u ON u.id=i.author_id
                WHERE i.company_id=? AND i.status='active' ORDER BY i.id DESC""",
                (company_id,),
            )).fetchall()

    async def create_round(self, company_id: int, user_id: int) -> int:
        async with self.connect() as db:
            current = await (await db.execute("SELECT id FROM voting_rounds WHERE company_id=? AND status='open'", (company_id,))).fetchone()
            if current:
                return int(current["id"])
            cursor = await db.execute(
                "INSERT INTO voting_rounds(company_id,created_by,created_at) VALUES(?,?,?)",
                (company_id, user_id, datetime.now().isoformat()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def vote(self, round_id: int, user_id: int, idea_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                """INSERT INTO votes(round_id,user_id,idea_id) VALUES(?,?,?)
                ON CONFLICT(round_id,user_id) DO UPDATE SET idea_id=excluded.idea_id""",
                (round_id, user_id, idea_id),
            )
            await db.commit()

    async def voting_status(self, round_id: int):
        async with self.connect() as db:
            voting_round = await (await db.execute(
                """SELECT r.*,u.display_name organizer,c.owner_id
                FROM voting_rounds r
                JOIN users u ON u.id=r.created_by
                JOIN companies c ON c.id=r.company_id
                WHERE r.id=?""",
                (round_id,),
            )).fetchone()
            if not voting_round:
                return None, []
            members = await (await db.execute(
                """SELECT u.id,u.display_name,i.title idea_title
                FROM members m
                JOIN users u ON u.id=m.user_id
                LEFT JOIN votes v ON v.round_id=? AND v.user_id=u.id
                LEFT JOIN ideas i ON i.id=v.idea_id
                WHERE m.company_id=? ORDER BY u.display_name""",
                (round_id, voting_round["company_id"]),
            )).fetchall()
            return voting_round, members

    async def can_close_round(self, round_id: int, user_id: int) -> bool:
        voting_round, _ = await self.voting_status(round_id)
        return bool(voting_round and user_id in (voting_round["created_by"], voting_round["owner_id"]))

    async def close_round(self, round_id: int):
        async with self.connect() as db:
            winner = await (await db.execute(
                """SELECT i.*,COUNT(v.user_id) vote_count FROM votes v JOIN ideas i ON i.id=v.idea_id
                WHERE v.round_id=? GROUP BY i.id ORDER BY vote_count DESC,i.id ASC LIMIT 1""",
                (round_id,),
            )).fetchone()
            if winner:
                await db.execute("UPDATE voting_rounds SET status='closed' WHERE id=?", (round_id,))
                await db.commit()
            return winner

    async def create_activity(self, company_id: int, idea_id: int, scheduled_at: datetime, creator_id: int) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                "INSERT INTO activities(company_id,idea_id,scheduled_at,created_by,created_at) VALUES(?,?,?,?,?)",
                (company_id, idea_id, scheduled_at.isoformat(), creator_id, datetime.now().isoformat()),
            )
            activity_id = int(cursor.lastrowid)
            await db.execute(
                """INSERT INTO activity_participants(activity_id,user_id)
                SELECT ?,user_id FROM members WHERE company_id=?""",
                (activity_id, company_id),
            )
            await db.execute("UPDATE ideas SET status='planned' WHERE id=?", (idea_id,))
            await db.commit()
            return activity_id

    async def current_activity(self, company_id: int):
        async with self.connect() as db:
            return await (await db.execute(
                """SELECT a.*,i.title FROM activities a JOIN ideas i ON i.id=a.idea_id
                WHERE a.company_id=? AND a.status!='completed' ORDER BY a.id DESC LIMIT 1""",
                (company_id,),
            )).fetchone()

    async def reschedule_activity(
        self,
        company_id: int,
        activity_id: int,
        user_id: int,
        scheduled_at: datetime,
    ) -> list[int]:
        """Change a planned activity date and reset reminders for the new schedule."""
        async with self.connect() as db:
            activity = await (
                await db.execute(
                    """SELECT a.created_by,c.owner_id FROM activities a
                    JOIN companies c ON c.id=a.company_id
                    WHERE a.id=? AND a.company_id=? AND a.status='planned'""",
                    (activity_id, company_id),
                )
            ).fetchone()
            if not activity:
                raise LookupError("Активность не найдена")
            if user_id not in (activity["created_by"], activity["owner_id"]):
                raise PermissionError("Изменить дату может организатор или владелец компании")
            await db.execute(
                """UPDATE activities SET scheduled_at=?,
                reminder_week_sent=0,reminder_day_sent=0,reminder_hours_sent=0,
                reminder_event_sent=0,reminder_followup_sent=0
                WHERE id=?""",
                (scheduled_at.isoformat(), activity_id),
            )
            participants = await (
                await db.execute(
                    "SELECT user_id FROM activity_participants WHERE activity_id=?",
                    (activity_id,),
                )
            ).fetchall()
            await db.commit()
            return [row["user_id"] for row in participants]

    async def archive(self, company_id: int, limit: int = 20):
        async with self.connect() as db:
            return await (await db.execute(
                """SELECT a.*,i.title FROM activities a JOIN ideas i ON i.id=a.idea_id
                WHERE a.company_id=? AND a.status='completed'
                ORDER BY a.scheduled_at DESC LIMIT ?""",
                (company_id, limit),
            )).fetchall()

    async def confirm(self, activity_id: int, user_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE activity_participants SET confirmed=1 WHERE activity_id=? AND user_id=?",
                (activity_id, user_id),
            )
            await db.commit()

    async def add_photo(self, activity_id: int, file_id: str) -> None:
        async with self.connect() as db:
            await db.execute("UPDATE activities SET photo_file_id=? WHERE id=?", (file_id, activity_id))
            await db.commit()

    async def completion(self, activity_id: int) -> tuple[int, int, bool, bool]:
        async with self.connect() as db:
            counts = await (await db.execute(
                "SELECT COUNT(*) total,SUM(confirmed) confirmed FROM activity_participants WHERE activity_id=?",
                (activity_id,),
            )).fetchone()
            activity = await (await db.execute(
                """SELECT a.photo_file_id,COUNT(p.id) uploaded_photos
                FROM activities a LEFT JOIN activity_photos p ON p.activity_id=a.id
                WHERE a.id=? GROUP BY a.id""",
                (activity_id,),
            )).fetchone()
            total, confirmed = int(counts["total"]), int(counts["confirmed"] or 0)
            has_photo = bool(activity["photo_file_id"] or activity["uploaded_photos"])
            completed = total > 0 and confirmed == total and has_photo
            if completed:
                await db.execute("UPDATE activities SET status='completed' WHERE id=?", (activity_id,))
                await db.commit()
            return confirmed, total, has_photo, completed

    async def due_reminders(self, now: datetime):
        """Return participant reminders due in the next polling tick."""
        async with self.connect() as db:
            activities = await (await db.execute(
                """SELECT a.*,i.title FROM activities a JOIN ideas i ON i.id=a.idea_id
                WHERE a.status!='completed'"""
            )).fetchall()
            due: list[tuple[int, str, str, datetime]] = []
            for activity in activities:
                scheduled = datetime.fromisoformat(activity["scheduled_at"])
                delta = (scheduled - now).total_seconds()
                kind = None
                if 24 * 3600 < delta <= 7 * 24 * 3600 and not activity["reminder_week_sent"]:
                    kind = "week"
                elif 3 * 3600 < delta <= 24 * 3600 and not activity["reminder_day_sent"]:
                    kind = "day"
                elif 60 < delta <= 3 * 3600 and not activity["reminder_hours_sent"]:
                    kind = "hours"
                elif -60 <= delta <= 60 and not activity["reminder_event_sent"]:
                    kind = "event"
                elif -3 * 3600 <= delta < -60 and not activity["reminder_followup_sent"]:
                    kind = "followup"
                if not kind:
                    continue
                participants = await (await db.execute(
                    f"""SELECT ap.user_id FROM activity_participants ap
                    LEFT JOIN user_settings s ON s.user_id=ap.user_id
                    WHERE ap.activity_id=? AND COALESCE(s.reminder_{kind},1)=1""",
                    (activity["id"],),
                )).fetchall()
                for participant in participants:
                    due.append((participant["user_id"], kind, activity["title"], scheduled))
                await db.execute(f"UPDATE activities SET reminder_{kind}_sent=1 WHERE id=?", (activity["id"],))
            await db.commit()
            return due
