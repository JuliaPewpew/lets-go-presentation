import os
import tempfile
import unittest
from datetime import datetime, timedelta

import aiosqlite

from bot.database import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = Database(self.path)
        await self.db.init()
        await self.db.upsert_user(1, "julia", "Юлия")
        await self.db.upsert_user(2, "friend", "Друг")
        self.company_id, self.code = await self.db.create_company(1, "Свои")
        await self.db.join_company(2, self.code)

    async def asyncTearDown(self):
        os.unlink(self.path)

    async def test_idea_ratings_and_vote(self):
        first = await self.db.add_idea(self.company_id, 1, "Ночной пикник", 2, 2, 3, False)
        second = await self.db.add_idea(self.company_id, 2, "Случайный город", 4, 4, 5, True)
        round_id = await self.db.create_round(self.company_id, 1)
        await self.db.vote(round_id, 1, second)
        await self.db.vote(round_id, 2, second)
        winner = await self.db.close_round(round_id)
        self.assertEqual(winner["id"], second)
        self.assertNotEqual(first, second)

    async def test_schema_migrations_are_versioned_and_idempotent(self):
        await self.db.init()
        async with self.db.connect() as connection:
            migrations = await (
                await connection.execute("SELECT version,name FROM schema_migrations ORDER BY version")
            ).fetchall()
            journal_mode = (await (await connection.execute("PRAGMA journal_mode")).fetchone())[0]
        self.assertEqual([row["version"] for row in migrations], [1, 2])
        self.assertEqual(journal_mode, "wal")

    async def test_idea_description_is_optional(self):
        await self.db.add_idea(self.company_id, 1, "Пикник", 1, 2, 2, False, "Взять пледы и чай")
        await self.db.add_idea(self.company_id, 2, "Прогулка", 1, 1, 2, False)
        ideas = await self.db.ideas(self.company_id)
        by_title = {idea["title"]: idea for idea in ideas}
        self.assertEqual(by_title["Пикник"]["description"], "Взять пледы и чай")
        self.assertIsNone(by_title["Прогулка"]["description"])

    async def test_voter_can_replace_vote(self):
        first = await self.db.add_idea(self.company_id, 1, "Пикник", 1, 2, 2, False)
        second = await self.db.add_idea(self.company_id, 2, "Поездка", 4, 4, 5, False)
        round_id = await self.db.create_round(self.company_id, 1)
        await self.db.vote(round_id, 1, first)
        await self.db.vote(round_id, 1, second)
        await self.db.vote(round_id, 2, second)
        winner = await self.db.close_round(round_id)
        self.assertEqual(winner["id"], second)
        self.assertEqual(winner["vote_count"], 2)

    async def test_open_round_is_reused(self):
        first = await self.db.create_round(self.company_id, 1)
        second = await self.db.create_round(self.company_id, 2)
        self.assertEqual(first, second)

    async def test_only_organizer_or_owner_can_close_vote(self):
        await self.db.upsert_user(3, "guest", "Гость")
        await self.db.join_company(3, self.code)
        round_id = await self.db.create_round(self.company_id, 2)
        self.assertTrue(await self.db.can_close_round(round_id, 2))
        self.assertTrue(await self.db.can_close_round(round_id, 1))
        self.assertFalse(await self.db.can_close_round(round_id, 3))

    async def test_voting_status_lists_voted_and_waiting_members(self):
        idea_id = await self.db.add_idea(self.company_id, 1, "Пикник", 1, 1, 2, False)
        round_id = await self.db.create_round(self.company_id, 1)
        await self.db.vote(round_id, 1, idea_id)
        voting_round, members = await self.db.voting_status(round_id)
        self.assertEqual(voting_round["organizer"], "Юлия")
        by_id = {member["id"]: member for member in members}
        self.assertEqual(by_id[1]["idea_title"], "Пикник")
        self.assertIsNone(by_id[2]["idea_title"])

    async def test_invalid_invite_does_not_change_company(self):
        result = await self.db.join_company(2, "not-a-real-code")
        self.assertIsNone(result)
        company = await self.db.active_company(2)
        self.assertEqual(company["id"], self.company_id)

    async def test_user_can_create_and_switch_between_companies(self):
        second_id, _ = await self.db.create_company(1, "Коллеги")
        companies = await self.db.user_companies(1)
        self.assertEqual({row["id"] for row in companies}, {self.company_id, second_id})
        self.assertEqual(next(row["id"] for row in companies if row["active"]), second_id)
        self.assertEqual(await self.db.switch_company(1, self.company_id), "Свои")
        self.assertEqual((await self.db.active_company(1))["id"], self.company_id)

    async def test_user_cannot_switch_to_foreign_company(self):
        await self.db.upsert_user(3, "stranger", "Чужой")
        foreign_id, _ = await self.db.create_company(3, "Чужая компания")
        self.assertIsNone(await self.db.switch_company(1, foreign_id))
        self.assertEqual((await self.db.active_company(1))["id"], self.company_id)

    async def test_owner_can_leave_and_transfers_company(self):
        new_owner = await self.db.leave_company(1, self.company_id)
        self.assertEqual(new_owner, "Друг")
        company = await self.db.active_company(2)
        self.assertEqual(company["owner_id"], 2)
        self.assertIsNone(await self.db.active_company(1))

    async def test_only_member_cannot_leave_owned_company(self):
        second_id, _ = await self.db.create_company(1, "Личная")
        with self.assertRaisesRegex(ValueError, "единственный участник"):
            await self.db.leave_company(1, second_id)

    async def test_rating_must_be_between_one_and_five(self):
        with self.assertRaises(aiosqlite.IntegrityError):
            await self.db.add_idea(self.company_id, 1, "Невозможная оценка", 6, 1, 1, False)

    async def test_achievement_requires_every_confirmation_and_photo(self):
        idea_id = await self.db.add_idea(self.company_id, 1, "Ужин вслепую", 3, 3, 2, False)
        activity_id = await self.db.create_activity(self.company_id, idea_id, datetime.now() + timedelta(days=1), 1)
        await self.db.confirm(activity_id, 1)
        self.assertEqual(await self.db.completion(activity_id), (1, 2, False, False))
        await self.db.add_photo(activity_id, "telegram-file-id")
        self.assertEqual(await self.db.completion(activity_id), (1, 2, True, False))
        await self.db.confirm(activity_id, 2)
        self.assertEqual(await self.db.completion(activity_id), (2, 2, True, True))

    async def test_planning_hides_idea_and_adds_every_member(self):
        idea_id = await self.db.add_idea(self.company_id, 1, "Квест", 3, 2, 2, False)
        activity_id = await self.db.create_activity(self.company_id, idea_id, datetime.now() + timedelta(days=2), 1)
        self.assertEqual(await self.db.ideas(self.company_id), [])
        self.assertEqual(await self.db.completion(activity_id), (0, 2, False, False))

    async def test_organizer_or_owner_can_reschedule_and_reminders_reset(self):
        idea_id = await self.db.add_idea(self.company_id, 2, "Пикник", 1, 1, 2, False)
        activity_id = await self.db.create_activity(
            self.company_id, idea_id, datetime.now() + timedelta(days=2), 2
        )
        async with self.db.connect() as connection:
            await connection.execute(
                """UPDATE activities SET reminder_week_sent=1,reminder_day_sent=1,
                reminder_hours_sent=1,reminder_event_sent=1,reminder_followup_sent=1
                WHERE id=?""",
                (activity_id,),
            )
            await connection.commit()
        changed = datetime.now() + timedelta(days=4)
        participants = await self.db.reschedule_activity(
            self.company_id, activity_id, 1, changed
        )
        self.assertEqual(set(participants), {1, 2})
        async with self.db.connect() as connection:
            activity = await (
                await connection.execute("SELECT * FROM activities WHERE id=?", (activity_id,))
            ).fetchone()
        self.assertEqual(activity["scheduled_at"], changed.isoformat())
        self.assertEqual(activity["reminder_week_sent"], 0)
        self.assertEqual(activity["reminder_followup_sent"], 0)

    async def test_regular_member_cannot_reschedule_activity(self):
        await self.db.upsert_user(3, "third", "Третий")
        await self.db.join_company(3, self.code)
        idea_id = await self.db.add_idea(self.company_id, 2, "Пикник", 1, 1, 2, False)
        activity_id = await self.db.create_activity(
            self.company_id, idea_id, datetime.now() + timedelta(days=2), 2
        )
        with self.assertRaises(PermissionError):
            await self.db.reschedule_activity(
                self.company_id, activity_id, 3, datetime.now() + timedelta(days=3)
            )

    async def test_day_reminder_is_sent_once_to_every_participant(self):
        idea_id = await self.db.add_idea(self.company_id, 1, "Завтрашний план", 2, 2, 2, False)
        now = datetime.now()
        await self.db.create_activity(self.company_id, idea_id, now + timedelta(hours=23), 1)
        reminders = await self.db.due_reminders(now)
        self.assertEqual(len(reminders), 2)
        self.assertEqual({row[0] for row in reminders}, {1, 2})
        self.assertTrue(all(row[1] == "day" for row in reminders))
        self.assertEqual(await self.db.due_reminders(now), [])

    async def test_followup_reminder_after_activity(self):
        idea_id = await self.db.add_idea(self.company_id, 1, "Вечеринка", 2, 3, 3, False)
        now = datetime.now()
        await self.db.create_activity(self.company_id, idea_id, now - timedelta(hours=2), 1)
        reminders = await self.db.due_reminders(now)
        self.assertEqual(len(reminders), 2)
        self.assertTrue(all(row[1] == "followup" for row in reminders))

    async def test_completed_activity_appears_in_archive(self):
        idea_id = await self.db.add_idea(self.company_id, 1, "Поход", 4, 2, 5, False)
        activity_id = await self.db.create_activity(self.company_id, idea_id, datetime.now(), 1)
        await self.db.confirm(activity_id, 1)
        await self.db.confirm(activity_id, 2)
        await self.db.add_photo(activity_id, "archive-photo")
        await self.db.completion(activity_id)
        archive = await self.db.archive(self.company_id)
        self.assertEqual(len(archive), 1)
        self.assertEqual(archive[0]["title"], "Поход")
        self.assertEqual(archive[0]["photo_file_id"], "archive-photo")


if __name__ == "__main__":
    unittest.main()
