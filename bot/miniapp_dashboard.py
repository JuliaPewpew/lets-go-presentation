from __future__ import annotations


def _group_by(rows: list[dict], key: str) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(row)
    return grouped


def _achievements(stats: dict) -> list[str]:
    rules = (
        ("completed", 1, "🏆 Первое приключение"),
        ("completed", 5, "🔥 Пять приключений"),
        ("ideas_created", 5, "💡 Генератор идей"),
        ("votes_cast", 5, "🗳 Голос компании"),
    )
    return [label for metric, threshold, label in rules if stats[metric] >= threshold]


class DashboardLoader:
    """Builds the Mini App read model without depending on HTTP."""

    def __init__(self, db):
        self.db = db

    async def load(self, user: dict, company) -> dict:
        company_id, user_id = company["id"], user["id"]
        ideas = [dict(row) for row in await self.db.ideas(company_id)]
        activity_row = await self.db.current_activity(company_id)
        activity = dict(activity_row) if activity_row else None
        archive = [dict(row) for row in await self.db.archive(company_id)]

        async with self.db.connect() as connection:
            companies = await self._companies(connection, user_id)
            members = await self._members(connection, company_id)
            comments = await self._comments(connection, company_id)
            reactions = await self._reactions(connection, company_id, user_id)
            voting = await (
                await connection.execute(
                    "SELECT id FROM voting_rounds WHERE company_id=? AND status='open' ORDER BY id DESC LIMIT 1",
                    (company_id,),
                )
            ).fetchone()
            await connection.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (user_id,))
            settings = dict(
                await (
                    await connection.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,))
                ).fetchone()
            )
            stats = await self._stats(connection, company_id, user_id)
            activity_people = await self._activity_people(connection, activity)
            await self._attach_archive_photos(connection, archive)
            date_poll = await self._date_poll(connection, company_id, user_id)
            await connection.commit()

        comments_by_idea = _group_by(comments, "idea_id")
        reactions_by_idea = _group_by(reactions, "idea_id")
        for idea in ideas:
            idea["comments"] = comments_by_idea.get(idea["id"], [])
            idea["reactions"] = reactions_by_idea.get(idea["id"], [])

        vote = None
        if voting:
            voting_round, status = await self.db.voting_status(voting["id"])
            vote = {
                "id": voting["id"],
                "organizer": voting_round["organizer"],
                "organizer_id": voting_round["created_by"],
                "members": [dict(row) for row in status],
            }
        return {
            "user": user,
            "company": dict(company),
            "companies": companies,
            "members": members,
            "ideas": ideas,
            "activity": activity,
            "activity_people": activity_people,
            "archive": archive,
            "vote": vote,
            "date_poll": date_poll,
            "settings": settings,
            "stats": stats,
            "achievements": _achievements(stats),
        }

    @staticmethod
    async def _companies(connection, user_id: int) -> list[dict]:
        rows = await (
            await connection.execute(
                """SELECT c.*,c.id=u.active_company_id active
                FROM members m JOIN companies c ON c.id=m.company_id
                JOIN users u ON u.id=m.user_id
                WHERE m.user_id=? ORDER BY active DESC,c.name""",
                (user_id,),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def _members(connection, company_id: int) -> list[dict]:
        rows = await (
            await connection.execute(
                """SELECT u.id,u.display_name FROM members m JOIN users u ON u.id=m.user_id
                WHERE m.company_id=? ORDER BY u.display_name""",
                (company_id,),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def _comments(connection, company_id: int) -> list[dict]:
        rows = await (
            await connection.execute(
                """SELECT c.id,c.idea_id,c.user_id,c.text,c.created_at,u.display_name
                FROM idea_comments c JOIN ideas i ON i.id=c.idea_id JOIN users u ON u.id=c.user_id
                WHERE i.company_id=? ORDER BY c.id""",
                (company_id,),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def _reactions(connection, company_id: int, user_id: int) -> list[dict]:
        rows = await (
            await connection.execute(
                """SELECT r.idea_id,r.emoji,COUNT(*) count,
                MAX(CASE WHEN r.user_id=? THEN 1 ELSE 0 END) mine
                FROM idea_reactions r JOIN ideas i ON i.id=r.idea_id
                WHERE i.company_id=? GROUP BY r.idea_id,r.emoji""",
                (user_id, company_id),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def _stats(connection, company_id: int, user_id: int) -> dict:
        row = await (
            await connection.execute(
                """SELECT
                (SELECT COUNT(*) FROM activities WHERE company_id=? AND status='completed') completed,
                (SELECT COUNT(*) FROM ideas WHERE company_id=? AND author_id=?) ideas_created,
                (SELECT COUNT(*) FROM votes v JOIN voting_rounds r ON r.id=v.round_id
                    WHERE r.company_id=? AND v.user_id=?) votes_cast""",
                (company_id, company_id, user_id, company_id, user_id),
            )
        ).fetchone()
        return dict(row)

    @staticmethod
    async def _activity_people(connection, activity: dict | None) -> list[dict]:
        if not activity:
            return []
        rows = await (
            await connection.execute(
                """SELECT u.id,u.display_name,ap.confirmed FROM activity_participants ap
                JOIN users u ON u.id=ap.user_id WHERE ap.activity_id=? ORDER BY u.display_name""",
                (activity["id"],),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def _attach_archive_photos(connection, archive: list[dict]) -> None:
        if not archive:
            return
        activity_ids = [item["id"] for item in archive]
        placeholders = ",".join("?" for _ in activity_ids)
        rows = await (
            await connection.execute(
                f"SELECT id,activity_id FROM activity_photos WHERE activity_id IN ({placeholders}) ORDER BY id",
                activity_ids,
            )
        ).fetchall()
        photos_by_activity = _group_by([dict(row) for row in rows], "activity_id")
        for item in archive:
            item["photos"] = [{"id": photo["id"]} for photo in photos_by_activity.get(item["id"], [])]
            if item["photo_file_id"] and not item["photos"]:
                item["photos"] = [{"id": f"legacy-{item['id']}"}]

    @staticmethod
    async def _date_poll(connection, company_id: int, user_id: int) -> dict | None:
        closed_round = await (
            await connection.execute(
                """SELECT r.id,r.created_by,i.id idea_id,i.title FROM voting_rounds r
                JOIN votes v ON v.round_id=r.id JOIN ideas i ON i.id=v.idea_id
                LEFT JOIN activities a ON a.idea_id=i.id
                WHERE r.company_id=? AND r.status='closed' AND a.id IS NULL
                GROUP BY r.id,i.id ORDER BY COUNT(v.user_id) DESC,r.id DESC LIMIT 1""",
                (company_id,),
            )
        ).fetchone()
        if not closed_round:
            return None
        rows = await (
            await connection.execute(
                """SELECT o.id,o.scheduled_at,COUNT(v.user_id) votes,
                MAX(CASE WHEN v.user_id=? THEN 1 ELSE 0 END) mine
                FROM date_options o LEFT JOIN date_votes v ON v.option_id=o.id
                WHERE o.round_id=? GROUP BY o.id ORDER BY o.scheduled_at""",
                (user_id, closed_round["id"]),
            )
        ).fetchall()
        return {**dict(closed_round), "options": [dict(row) for row in rows]}
