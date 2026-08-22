import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from urllib.parse import urlencode

from aiohttp import FormData
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

    async def get_file(self, file_id):
        return type("TelegramFile", (), {"file_path": "photos/test.jpg"})()

    async def download_file(self, file_path, destination):
        destination.write(b"fake-jpeg-content")


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
        poll = await self.request_json("GET", "/api/bootstrap")
        self.assertEqual(poll["date_poll"]["title"], chosen["title"])
        future = (datetime.now() + timedelta(days=10)).replace(microsecond=0).isoformat()
        option = await self.request_json("POST", "/api/date/options", {
            "round_id": vote["id"], "scheduled_at": future,
        })
        await self.request_json("POST", "/api/date/vote", {"option_id": option["id"]})
        planned = await self.request_json("POST", "/api/date/confirm", {"option_id": option["id"]})
        final = await self.request_json("GET", "/api/bootstrap")
        self.assertEqual(final["activity"]["title"], chosen["title"])
        await self.db.confirm(planned["id"], 101)
        await self.db.add_photo(planned["id"], "telegram-photo-id")
        await self.db.completion(planned["id"])
        archive = await self.request_json("GET", "/api/bootstrap")
        self.assertEqual(archive["archive"][0]["photo_file_id"], "telegram-photo-id")
        photo = await self.client.get(
            f"/api/archive/photo/legacy-{planned['id']}",
            headers={"X-Telegram-Init-Data": init_data()},
        )
        self.assertEqual(photo.status, 200)
        self.assertEqual(await photo.read(), b"fake-jpeg-content")

    async def test_social_company_settings_and_photo_upload(self):
        first = await self.request_json("POST", "/api/company", {"name": "Первая"})
        await self.request_json("POST", "/api/company", {"name": "Вторая"})
        dashboard = await self.request_json("GET", "/api/bootstrap")
        first_id = next(x["id"] for x in dashboard["companies"] if x["name"] == "Первая")
        await self.request_json("POST", "/api/company/switch", {"company_id": first_id})
        idea = await self.request_json("POST", "/api/ideas", {
            "title": "Поехать за город", "description": "С пледом", "difficulty": 2,
            "budget": 2, "duration": 3, "anonymous": False,
        })
        await self.request_json("POST", f"/api/ideas/{idea['id']}/comments", {"text": "Я за!"})
        await self.request_json("POST", f"/api/ideas/{idea['id']}/reactions", {"emoji": "❤️"})
        await self.request_json("PUT", f"/api/ideas/{idea['id']}", {
            "title": "Поехать за город вместе", "description": "С пледом", "difficulty": 2,
            "budget": 2, "duration": 3, "anonymous": False,
        })
        await self.request_json("POST", "/api/settings", {
            "reminder_week": False, "reminder_day": True, "reminder_hours": True,
            "reminder_event": False, "reminder_followup": True,
        })
        state = await self.request_json("GET", "/api/bootstrap")
        self.assertEqual(state["ideas"][0]["comments"][0]["text"], "Я за!")
        self.assertEqual(state["ideas"][0]["reactions"][0]["count"], 1)
        self.assertEqual(state["settings"]["reminder_week"], 0)
        self.assertEqual(first["id"], first_id)

        activity_id = await self.db.create_activity(
            first_id, idea["id"], datetime.now() + timedelta(days=2), 101
        )
        await self.request_json("POST", f"/api/activity/{activity_id}/confirm", {})
        form = FormData()
        form.add_field("photo", b"small-png", filename="memory.png", content_type="image/png")
        response = await self.client.post(
            f"/api/activity/{activity_id}/photo", data=form,
            headers={"X-Telegram-Init-Data": init_data()},
        )
        self.assertEqual(response.status, 200, await response.text())
        archived = await self.request_json("GET", "/api/bootstrap")
        photo_id = archived["archive"][0]["photos"][0]["id"]
        photo = await self.client.get(
            f"/api/archive/photo/{photo_id}",
            headers={"X-Telegram-Init-Data": init_data()},
        )
        self.assertEqual(await photo.read(), b"small-png")


if __name__ == "__main__":
    unittest.main()
