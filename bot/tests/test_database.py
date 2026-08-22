import os
import tempfile
import unittest
from datetime import datetime, timedelta

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

    async def test_achievement_requires_every_confirmation_and_photo(self):
        idea_id = await self.db.add_idea(self.company_id, 1, "Ужин вслепую", 3, 3, 2, False)
        activity_id = await self.db.create_activity(self.company_id, idea_id, datetime.now() + timedelta(days=1), 1)
        await self.db.confirm(activity_id, 1)
        self.assertEqual(await self.db.completion(activity_id), (1, 2, False, False))
        await self.db.add_photo(activity_id, "telegram-file-id")
        self.assertEqual(await self.db.completion(activity_id), (1, 2, True, False))
        await self.db.confirm(activity_id, 2)
        self.assertEqual(await self.db.completion(activity_id), (2, 2, True, True))


if __name__ == "__main__":
    unittest.main()
