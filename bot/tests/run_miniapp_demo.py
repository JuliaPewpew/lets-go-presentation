"""Local-only Mini App demo server for browser UI testing."""
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
from urllib.parse import urlencode

from aiohttp import web

from bot.database import Database
from bot.miniapp import create_miniapp


TOKEN = "local-ui-test-token"
USER_ID = 909001


class FakeBot:
    async def get_me(self):
        return type("BotUser", (), {"username": "lets_go_friends_bot"})()

    async def send_message(self, *args, **kwargs):
        return None


def signed_init_data():
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "local-browser-test",
        "user": json.dumps({"id": USER_ID, "first_name": "Тестировщик"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


async def main():
    path = os.path.join(tempfile.gettempdir(), "lets_go_ui_test.db")
    if os.path.exists(path):
        os.unlink(path)
    db = Database(path)
    await db.init()
    await db.upsert_user(USER_ID, "tester", "Тестировщик")
    company_id, _ = await db.create_company(USER_ID, "Тестовая компания")
    await db.add_idea(company_id, USER_ID, "Ночной пикник", 2, 2, 3, False, "Пледы, чай и звёзды")
    await db.add_idea(company_id, USER_ID, "Сходить в музей", 1, 2, 2, False)
    app = create_miniapp(db, FakeBot(), TOKEN)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 8099).start()
    print("http://127.0.0.1:8099/?" + urlencode({"test_init_data": signed_init_data()}), flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
