from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime

import aiosqlite


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT,
  display_name TEXT NOT NULL,
  active_company_id INTEGER
);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  invite_code TEXT NOT NULL UNIQUE,
  owner_id INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
  company_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  joined_at TEXT NOT NULL,
  PRIMARY KEY (company_id, user_id),
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  author_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
  budget INTEGER NOT NULL CHECK(budget BETWEEN 1 AND 5),
  duration INTEGER NOT NULL CHECK(duration BETWEEN 1 AND 5),
  anonymous INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS voting_rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
  round_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  idea_id INTEGER NOT NULL,
  PRIMARY KEY (round_id, user_id),
  FOREIGN KEY (round_id) REFERENCES voting_rounds(id) ON DELETE CASCADE,
  FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  idea_id INTEGER NOT NULL,
  scheduled_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned',
  photo_file_id TEXT,
  reminder_day_sent INTEGER NOT NULL DEFAULT 0,
  reminder_event_sent INTEGER NOT NULL DEFAULT 0,
  reminder_followup_sent INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (idea_id) REFERENCES ideas(id)
);
CREATE TABLE IF NOT EXISTS activity_participants (
  activity_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  confirmed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (activity_id, user_id),
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
        finally:
            await db.close()

    async def init(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        async with self.connect() as db:
            await db.executescript(SCHEMA)
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

    async def add_idea(self, company_id: int, author_id: int, title: str, difficulty: int, budget: int, duration: int, anonymous: bool) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """INSERT INTO ideas(company_id,author_id,title,difficulty,budget,duration,anonymous,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (company_id, author_id, title, difficulty, budget, duration, int(anonymous), datetime.now().isoformat()),
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
            activity = await (await db.execute("SELECT photo_file_id FROM activities WHERE id=?", (activity_id,))).fetchone()
            total, confirmed = int(counts["total"]), int(counts["confirmed"] or 0)
            has_photo = bool(activity["photo_file_id"])
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
                if 0 < delta <= 24 * 3600 and not activity["reminder_day_sent"]:
                    kind = "day"
                if -60 <= delta <= 60 and not activity["reminder_event_sent"]:
                    kind = "event"
                if -3 * 3600 <= delta < -60 and not activity["reminder_followup_sent"]:
                    kind = "followup"
                if not kind:
                    continue
                participants = await (await db.execute(
                    "SELECT user_id FROM activity_participants WHERE activity_id=?",
                    (activity["id"],),
                )).fetchall()
                for participant in participants:
                    due.append((participant["user_id"], kind, activity["title"], scheduled))
                await db.execute(f"UPDATE activities SET reminder_{kind}_sent=1 WHERE id=?", (activity["id"],))
            await db.commit()
            return due
