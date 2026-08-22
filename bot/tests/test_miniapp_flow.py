import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from urllib.parse import urlencode

from aiohttp.test_utils import AioHTTPTestCase

from bot.database import Database
from bot.miniapp import create_miniapp


TOKEN = "test-token"


def init_data(user_id=101):
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "integration-test",
        "user": json.dumps({"id": user_id, "first_name": "Тестировщик"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class FakeBot:
    async def get_me(self):
        return type("BotUser", (), {"username": "lets_go_friends_bot"})()

    async def send_message(self, *args, **kwargs):
        return None


class MiniAppFlowTests(AioHTTPTestCase):
    async def get_application(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = Database(self.path)
        await self.db.init()
        return create_miniapp(self.db, FakeBot(), TOKEN)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        os.unlink(self.path)

    async def request_json(self, method, path, body=None):
        response = await self.client.request(
            method, path, json=body, headers={"X-Telegram-Init-Data": init_data()}
        )
        text = await response.text()
        self.assertLess(response.status, 400, text)
        return json.loads(text)

    async def test_complete_company_to_activity_flow(self):
        created = await self.request_json("POST", "/api/company", {"name": "Тестовая компания"})
        self.assertIn("start=join_", created["invite"])

        for title in ("Ночной пикник", "Поход в музей"):
            await self.request_json("POST", "/api/ideas", {
                "title": title, "description": "Описание", "difficulty": 2,
                "budget": 3, "duration": 2, "anonymous": False,
            })

        vote = await self.request_json("POST", "/api/vote/start", {})
        dashboard = await self.request_json("GET", "/api/bootstrap")
        chosen = dashboard["ideas"][0]
        await self.request_json("POST", "/api/vote/cast", {"round_id": vote["id"], "idea_id": chosen["id"]})
        after_vote = await self.request_json("GET", "/api/bootstrap")
        member = next(x for x in after_vote["vote"]["members"] if x["id"] == 101)
        self.assertEqual(member["idea_title"], chosen["title"])

        result = await self.request_json("POST", "/api/vote/close", {"round_id": vote["id"]})
        self.assertEqual(result["winner"]["id"], chosen["id"])
        await self.request_json("POST", "/api/plan", {"idea_id": chosen["id"], "scheduled_at": "2030-08-24T18:00"})
        final = await self.request_json("GET", "/api/bootstrap")
        self.assertEqual(final["activity"]["title"], chosen["title"])


if __name__ == "__main__":
    unittest.main()
