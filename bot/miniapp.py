from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web


def validate_init_data(raw: str, token: str) -> dict:
    values = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise web.HTTPUnauthorized(text="Telegram authorization required")
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise web.HTTPUnauthorized(text="Invalid Telegram signature")
    if abs(time.time() - int(values.get("auth_date", "0"))) > 86400:
        raise web.HTTPUnauthorized(text="Telegram authorization expired")
    return json.loads(values["user"])


def json_row(row):
    return dict(row) if row else None


class MiniApp:
    def __init__(self, db, bot, token: str):
        self.db, self.bot, self.token = db, bot, token

    def user(self, request: web.Request) -> dict:
        return validate_init_data(request.headers.get("X-Telegram-Init-Data", ""), self.token)

    async def index(self, request):
        return web.FileResponse(Path(__file__).with_name("miniapp.html"))

    async def bootstrap(self, request):
        user = self.user(request)
        await self.db.upsert_user(user["id"], user.get("username"), " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "Друг")
        company = await self.db.active_company(user["id"])
        if not company:
            return web.json_response({"user": user, "company": None})
        ideas = [dict(x) for x in await self.db.ideas(company["id"])]
        activity = json_row(await self.db.current_activity(company["id"]))
        archive = [dict(x) for x in await self.db.archive(company["id"])]
        async with self.db.connect() as conn:
            members = [dict(x) for x in await (await conn.execute(
                "SELECT u.id,u.display_name FROM members m JOIN users u ON u.id=m.user_id WHERE m.company_id=? ORDER BY u.display_name", (company["id"],)
            )).fetchall()]
            voting = await (await conn.execute(
                "SELECT id FROM voting_rounds WHERE company_id=? AND status='open' ORDER BY id DESC LIMIT 1", (company["id"],)
            )).fetchone()
        vote = None
        if voting:
            voting_round, status = await self.db.voting_status(voting["id"])
            vote = {"id": voting["id"], "organizer": voting_round["organizer"], "members": [dict(x) for x in status]}
        return web.json_response({"user": user, "company": dict(company), "members": members, "ideas": ideas, "activity": activity, "archive": archive, "vote": vote})

    async def create_company(self, request):
        user = self.user(request); body = await request.json()
        await self.db.upsert_user(user["id"], user.get("username"), user.get("first_name", "Друг"))
        company_id, code = await self.db.create_company(user["id"], str(body.get("name", ""))[:60])
        me = await self.bot.get_me()
        return web.json_response({"id": company_id, "invite": f"https://t.me/{me.username}?start=join_{code}"})

    async def add_idea(self, request):
        user = self.user(request); body = await request.json(); company = await self.db.active_company(user["id"])
        if not company: raise web.HTTPForbidden()
        title = str(body.get("title", "")).strip()[:180]
        if len(title) < 4: raise web.HTTPBadRequest(text="Название слишком короткое")
        ratings = [int(body.get(key, 0)) for key in ("difficulty", "budget", "duration")]
        if any(x not in range(1, 6) for x in ratings): raise web.HTTPBadRequest(text="Оценки должны быть от 1 до 5")
        idea_id = await self.db.add_idea(company["id"], user["id"], title, *ratings, bool(body.get("anonymous")), str(body.get("description", "")).strip()[:1000] or None)
        return web.json_response({"id": idea_id})

    async def start_vote(self, request):
        user = self.user(request); company = await self.db.active_company(user["id"])
        if not company: raise web.HTTPForbidden()
        if len(await self.db.ideas(company["id"])) < 2: raise web.HTTPBadRequest(text="Нужно хотя бы две идеи")
        return web.json_response({"id": await self.db.create_round(company["id"], user["id"])})

    async def cast_vote(self, request):
        user = self.user(request); body = await request.json()
        await self.db.vote(int(body["round_id"]), user["id"], int(body["idea_id"]))
        return web.json_response({"ok": True})

    async def close_vote(self, request):
        user = self.user(request); body = await request.json(); round_id = int(body["round_id"])
        if not await self.db.can_close_round(round_id, user["id"]): raise web.HTTPForbidden(text="Только организатор может завершить голосование")
        _, members = await self.db.voting_status(round_id); winner = await self.db.close_round(round_id)
        if not winner: raise web.HTTPBadRequest(text="Пока никто не проголосовал")
        for member in members:
            try: await self.bot.send_message(member["id"], f"Голосование завершено! Победила идея <b>{winner['title']}</b> 🎉")
            except Exception: pass
        return web.json_response({"winner": dict(winner)})

    async def plan(self, request):
        user = self.user(request); body = await request.json(); company = await self.db.active_company(user["id"])
        scheduled = datetime.fromisoformat(body["scheduled_at"])
        if scheduled <= datetime.now(): raise web.HTTPBadRequest(text="Выберите будущую дату")
        activity_id = await self.db.create_activity(company["id"], int(body["idea_id"]), scheduled, user["id"])
        return web.json_response({"id": activity_id})


def create_miniapp(db, bot, token: str) -> web.Application:
    api = MiniApp(db, bot, token)
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app.add_routes([
        web.get("/", api.index), web.get("/api/bootstrap", api.bootstrap),
        web.post("/api/company", api.create_company), web.post("/api/ideas", api.add_idea),
        web.post("/api/vote/start", api.start_vote), web.post("/api/vote/cast", api.cast_vote),
        web.post("/api/vote/close", api.close_vote), web.post("/api/plan", api.plan),
    ])
    return app


async def start_miniapp(db, bot, token: str):
    app = create_miniapp(db, bot, token)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 8088).start()
    return runner
