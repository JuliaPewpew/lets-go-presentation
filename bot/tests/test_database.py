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

    async def test_invalid_invite_does_not_change_company(self):
        result = await self.db.join_company(2, "not-a-real-code")
        self.assertIsNone(result)
        company = await self.db.active_company(2)
        self.assertEqual(company["id"], self.company_id)

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


if __name__ == "__main__":
    unittest.main()
