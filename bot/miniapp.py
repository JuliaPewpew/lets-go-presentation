from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import time
from io import BytesIO
from datetime import datetime
from pathlib import Path
from uuid import uuid4
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

    async def company_for(self, user_id: int):
        company = await self.db.active_company(user_id)
        if not company:
            raise web.HTTPForbidden(text="Сначала выберите компанию")
        return company

    async def idea_access(self, user_id: int, idea_id: int):
        company = await self.company_for(user_id)
        async with self.db.connect() as conn:
            idea = await (await conn.execute(
                """SELECT i.*,c.owner_id FROM ideas i JOIN companies c ON c.id=i.company_id
                WHERE i.id=? AND i.company_id=?""", (idea_id, company["id"])
            )).fetchone()
        if not idea:
            raise web.HTTPNotFound()
        return company, idea

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
            companies = [dict(x) for x in await self.db.user_companies(user["id"])]
            members = [dict(x) for x in await (await conn.execute(
                "SELECT u.id,u.display_name FROM members m JOIN users u ON u.id=m.user_id WHERE m.company_id=? ORDER BY u.display_name", (company["id"],)
            )).fetchall()]
            comments = [dict(x) for x in await (await conn.execute(
                """SELECT c.id,c.idea_id,c.user_id,c.text,c.created_at,u.display_name
                FROM idea_comments c JOIN ideas i ON i.id=c.idea_id JOIN users u ON u.id=c.user_id
                WHERE i.company_id=? ORDER BY c.id""", (company["id"],)
            )).fetchall()]
            reactions = [dict(x) for x in await (await conn.execute(
                """SELECT r.idea_id,r.emoji,COUNT(*) count,
                MAX(CASE WHEN r.user_id=? THEN 1 ELSE 0 END) mine
                FROM idea_reactions r JOIN ideas i ON i.id=r.idea_id
                WHERE i.company_id=? GROUP BY r.idea_id,r.emoji""", (user["id"], company["id"])
            )).fetchall()]
            voting = await (await conn.execute(
                "SELECT id FROM voting_rounds WHERE company_id=? AND status='open' ORDER BY id DESC LIMIT 1", (company["id"],)
            )).fetchone()
            await conn.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES(?)", (user["id"],))
            settings = dict(await (await conn.execute("SELECT * FROM user_settings WHERE user_id=?", (user["id"],))).fetchone())
            stats = dict(await (await conn.execute(
                """SELECT
                (SELECT COUNT(*) FROM activities WHERE company_id=? AND status='completed') completed,
                (SELECT COUNT(*) FROM ideas WHERE company_id=? AND author_id=?) ideas_created,
                (SELECT COUNT(*) FROM votes v JOIN voting_rounds r ON r.id=v.round_id WHERE r.company_id=? AND v.user_id=?) votes_cast""",
                (company["id"], company["id"], user["id"], company["id"], user["id"]),
            )).fetchone())
            activity_people = []
            if activity:
                activity_people = [dict(x) for x in await (await conn.execute(
                    """SELECT u.id,u.display_name,ap.confirmed FROM activity_participants ap
                    JOIN users u ON u.id=ap.user_id WHERE ap.activity_id=? ORDER BY u.display_name""", (activity["id"],)
                )).fetchall()]
            for archived in archive:
                archived["photos"] = [dict(x) for x in await (await conn.execute(
                    "SELECT id FROM activity_photos WHERE activity_id=? ORDER BY id", (archived["id"],)
                )).fetchall()]
                if archived["photo_file_id"] and not archived["photos"]:
                    archived["photos"] = [{"id": f"legacy-{archived['id']}"}]
            closed_round = await (await conn.execute(
                """SELECT r.id,r.created_by,i.id idea_id,i.title FROM voting_rounds r
                JOIN votes v ON v.round_id=r.id JOIN ideas i ON i.id=v.idea_id
                LEFT JOIN activities a ON a.idea_id=i.id
                WHERE r.company_id=? AND r.status='closed' AND a.id IS NULL
                GROUP BY r.id,i.id ORDER BY COUNT(v.user_id) DESC,r.id DESC LIMIT 1""", (company["id"],)
            )).fetchone()
            date_poll = None
            if closed_round:
                options = [dict(x) for x in await (await conn.execute(
                    """SELECT o.id,o.scheduled_at,COUNT(v.user_id) votes,
                    MAX(CASE WHEN v.user_id=? THEN 1 ELSE 0 END) mine
                    FROM date_options o LEFT JOIN date_votes v ON v.option_id=o.id
                    WHERE o.round_id=? GROUP BY o.id ORDER BY o.scheduled_at""", (user["id"], closed_round["id"])
                )).fetchall()]
                date_poll = {**dict(closed_round), "options": options}
            await conn.commit()
        by_idea_comments = {idea["id"]: [] for idea in ideas}
        by_idea_reactions = {idea["id"]: [] for idea in ideas}
        for comment in comments: by_idea_comments.setdefault(comment["idea_id"], []).append(comment)
        for reaction in reactions: by_idea_reactions.setdefault(reaction["idea_id"], []).append(reaction)
        for idea in ideas:
            idea["comments"] = by_idea_comments.get(idea["id"], [])
            idea["reactions"] = by_idea_reactions.get(idea["id"], [])
        vote = None
        if voting:
            voting_round, status = await self.db.voting_status(voting["id"])
            vote = {"id": voting["id"], "organizer": voting_round["organizer"], "members": [dict(x) for x in status]}
        achievements = []
        if stats["completed"] >= 1: achievements.append("🏆 Первое приключение")
        if stats["completed"] >= 5: achievements.append("🔥 Пять приключений")
        if stats["ideas_created"] >= 5: achievements.append("💡 Генератор идей")
        if stats["votes_cast"] >= 5: achievements.append("🗳 Голос компании")
        return web.json_response({"user": user, "company": dict(company), "companies": companies, "members": members,
            "ideas": ideas, "activity": activity, "activity_people": activity_people, "archive": archive,
            "vote": vote, "date_poll": date_poll, "settings": settings, "stats": stats, "achievements": achievements})

    async def create_company(self, request):
        user = self.user(request); body = await request.json()
        await self.db.upsert_user(user["id"], user.get("username"), user.get("first_name", "Друг"))
        name = str(body.get("name", "")).strip()[:60]
        if len(name) < 2: raise web.HTTPBadRequest(text="Название слишком короткое")
        company_id, code = await self.db.create_company(user["id"], name)
        me = await self.bot.get_me()
        return web.json_response({"id": company_id, "invite": f"https://t.me/{me.username}?start=join_{code}"})

    async def switch_company(self, request):
        user = self.user(request); body = await request.json()
        name = await self.db.switch_company(user["id"], int(body["company_id"]))
        if not name: raise web.HTTPForbidden(text="Компания недоступна")
        return web.json_response({"name": name})

    async def leave_company(self, request):
        user = self.user(request); company = await self.company_for(user["id"])
        if company["owner_id"] == user["id"]: raise web.HTTPBadRequest(text="Владелец не может выйти из компании")
        async with self.db.connect() as conn:
            await conn.execute("DELETE FROM members WHERE company_id=? AND user_id=?", (company["id"], user["id"]))
            fallback = await (await conn.execute("SELECT company_id FROM members WHERE user_id=? LIMIT 1", (user["id"],))).fetchone()
            await conn.execute("UPDATE users SET active_company_id=? WHERE id=?", (fallback["company_id"] if fallback else None, user["id"]))
            await conn.commit()
        return web.json_response({"ok": True})

    async def add_idea(self, request):
        user = self.user(request); body = await request.json(); company = await self.db.active_company(user["id"])
        if not company: raise web.HTTPForbidden()
        title = str(body.get("title", "")).strip()[:180]
        if len(title) < 4: raise web.HTTPBadRequest(text="Название слишком короткое")
        ratings = [int(body.get(key, 0)) for key in ("difficulty", "budget", "duration")]
        if any(x not in range(1, 6) for x in ratings): raise web.HTTPBadRequest(text="Оценки должны быть от 1 до 5")
        idea_id = await self.db.add_idea(company["id"], user["id"], title, *ratings, bool(body.get("anonymous")), str(body.get("description", "")).strip()[:1000] or None)
        return web.json_response({"id": idea_id})

    async def update_idea(self, request):
        user = self.user(request); body = await request.json(); idea_id = int(request.match_info["idea_id"])
        _, idea = await self.idea_access(user["id"], idea_id)
        if user["id"] not in (idea["author_id"], idea["owner_id"]): raise web.HTTPForbidden(text="Редактировать может автор или владелец")
        title = str(body.get("title", "")).strip()[:180]
        ratings = [int(body.get(key, 0)) for key in ("difficulty", "budget", "duration")]
        if len(title) < 4 or any(x not in range(1, 6) for x in ratings): raise web.HTTPBadRequest(text="Проверьте название и оценки")
        async with self.db.connect() as conn:
            await conn.execute("""UPDATE ideas SET title=?,description=?,difficulty=?,budget=?,duration=?,anonymous=? WHERE id=?""",
                (title, str(body.get("description", "")).strip()[:1000] or None, *ratings, int(bool(body.get("anonymous"))), idea_id))
            await conn.commit()
        return web.json_response({"ok": True})

    async def delete_idea(self, request):
        user = self.user(request); idea_id = int(request.match_info["idea_id"]); _, idea = await self.idea_access(user["id"], idea_id)
        if user["id"] not in (idea["author_id"], idea["owner_id"]): raise web.HTTPForbidden(text="Удалить может автор или владелец")
        async with self.db.connect() as conn:
            linked = await (await conn.execute("SELECT 1 FROM activities WHERE idea_id=?", (idea_id,))).fetchone()
            if linked: raise web.HTTPBadRequest(text="Запланированную идею удалить нельзя")
            await conn.execute("DELETE FROM ideas WHERE id=?", (idea_id,)); await conn.commit()
        return web.json_response({"ok": True})

    async def add_comment(self, request):
        user = self.user(request); idea_id = int(request.match_info["idea_id"]); await self.idea_access(user["id"], idea_id)
        text = str((await request.json()).get("text", "")).strip()[:500]
        if not text: raise web.HTTPBadRequest(text="Комментарий пуст")
        async with self.db.connect() as conn:
            await conn.execute("INSERT INTO idea_comments(idea_id,user_id,text,created_at) VALUES(?,?,?,?)", (idea_id,user["id"],text,datetime.now().isoformat()))
            await conn.commit()
        return web.json_response({"ok": True})

    async def react(self, request):
        user = self.user(request); idea_id = int(request.match_info["idea_id"]); await self.idea_access(user["id"], idea_id)
        emoji = str((await request.json()).get("emoji", ""))
        if emoji not in {"👍","❤️","🔥"}: raise web.HTTPBadRequest()
        async with self.db.connect() as conn:
            exists = await (await conn.execute("SELECT 1 FROM idea_reactions WHERE idea_id=? AND user_id=? AND emoji=?", (idea_id,user["id"],emoji))).fetchone()
            if exists: await conn.execute("DELETE FROM idea_reactions WHERE idea_id=? AND user_id=? AND emoji=?", (idea_id,user["id"],emoji))
            else: await conn.execute("INSERT INTO idea_reactions VALUES(?,?,?)", (idea_id,user["id"],emoji))
            await conn.commit()
        return web.json_response({"ok": True})

    async def start_vote(self, request):
        user = self.user(request); company = await self.db.active_company(user["id"])
        if not company: raise web.HTTPForbidden()
        if len(await self.db.ideas(company["id"])) < 2: raise web.HTTPBadRequest(text="Нужно хотя бы две идеи")
        return web.json_response({"id": await self.db.create_round(company["id"], user["id"])})

    async def cast_vote(self, request):
        user = self.user(request); body = await request.json()
        round_id, idea_id = int(body["round_id"]), int(body["idea_id"])
        company = await self.company_for(user["id"])
        async with self.db.connect() as conn:
            allowed = await (await conn.execute(
                """SELECT 1 FROM voting_rounds r JOIN ideas i ON i.company_id=r.company_id
                WHERE r.id=? AND r.status='open' AND i.id=? AND r.company_id=?""",
                (round_id, idea_id, company["id"]),
            )).fetchone()
        if not allowed: raise web.HTTPForbidden(text="Идея недоступна для этого голосования")
        await self.db.vote(round_id, user["id"], idea_id)
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

    async def add_date_option(self, request):
        user = self.user(request); body = await request.json(); round_id = int(body["round_id"])
        voting_round, _ = await self.db.voting_status(round_id)
        if not voting_round or user["id"] not in (voting_round["created_by"], voting_round["owner_id"]): raise web.HTTPForbidden()
        scheduled = datetime.fromisoformat(body["scheduled_at"])
        if scheduled <= datetime.now(): raise web.HTTPBadRequest(text="Выберите будущую дату")
        async with self.db.connect() as conn:
            cursor = await conn.execute("INSERT INTO date_options(round_id,scheduled_at,created_by) VALUES(?,?,?)", (round_id,scheduled.isoformat(),user["id"]))
            await conn.commit()
        return web.json_response({"id": cursor.lastrowid})

    async def vote_date(self, request):
        user = self.user(request); body = await request.json(); option_id = int(body["option_id"])
        company = await self.company_for(user["id"])
        async with self.db.connect() as conn:
            option = await (await conn.execute("""SELECT o.id FROM date_options o JOIN voting_rounds r ON r.id=o.round_id
                WHERE o.id=? AND r.company_id=?""", (option_id,company["id"]))).fetchone()
            if not option: raise web.HTTPNotFound()
            exists = await (await conn.execute("SELECT 1 FROM date_votes WHERE option_id=? AND user_id=?", (option_id,user["id"]))).fetchone()
            if exists: await conn.execute("DELETE FROM date_votes WHERE option_id=? AND user_id=?", (option_id,user["id"]))
            else: await conn.execute("INSERT INTO date_votes VALUES(?,?)", (option_id,user["id"]))
            await conn.commit()
        return web.json_response({"ok": True})

    async def confirm_date(self, request):
        user = self.user(request); body = await request.json(); option_id = int(body["option_id"])
        company = await self.company_for(user["id"])
        async with self.db.connect() as conn:
            option = await (await conn.execute("""SELECT o.*,r.created_by organizer_id,c.owner_id,i.id idea_id FROM date_options o
                JOIN voting_rounds r ON r.id=o.round_id JOIN companies c ON c.id=r.company_id
                JOIN votes v ON v.round_id=r.id JOIN ideas i ON i.id=v.idea_id
                WHERE o.id=? AND r.company_id=? GROUP BY i.id ORDER BY COUNT(v.user_id) DESC,i.id ASC LIMIT 1""", (option_id,company["id"]))).fetchone()
        if not option or user["id"] not in (option["organizer_id"],option["owner_id"]): raise web.HTTPForbidden()
        activity_id = await self.db.create_activity(company["id"], option["idea_id"], datetime.fromisoformat(option["scheduled_at"]), user["id"])
        return web.json_response({"id": activity_id})

    async def confirm_activity(self, request):
        user = self.user(request); company = await self.company_for(user["id"]); activity_id = int(request.match_info["activity_id"])
        async with self.db.connect() as conn:
            allowed = await (await conn.execute("SELECT 1 FROM activities a JOIN activity_participants p ON p.activity_id=a.id WHERE a.id=? AND a.company_id=? AND p.user_id=?", (activity_id,company["id"],user["id"]))).fetchone()
        if not allowed: raise web.HTTPForbidden()
        await self.db.confirm(activity_id,user["id"]); confirmed,total,has_photo,completed = await self.db.completion(activity_id)
        return web.json_response({"confirmed":confirmed,"total":total,"has_photo":has_photo,"completed":completed})

    async def upload_activity_photo(self, request):
        user = self.user(request); company = await self.company_for(user["id"]); activity_id = int(request.match_info["activity_id"])
        async with self.db.connect() as conn:
            activity = await (await conn.execute("SELECT 1 FROM activities WHERE id=? AND company_id=?", (activity_id,company["id"]))).fetchone()
        if not activity: raise web.HTTPNotFound()
        reader = await request.multipart(); field = await reader.next()
        if not field or field.name != "photo" or field.headers.get("Content-Type","") not in {"image/jpeg","image/png","image/webp"}: raise web.HTTPBadRequest(text="Нужно изображение JPG, PNG или WebP")
        content = await field.read(decode=False)
        if not content or len(content) > 10*1024*1024: raise web.HTTPBadRequest(text="Фото должно быть не больше 10 МБ")
        extension = {"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}[field.headers["Content-Type"]]
        photo_dir = Path(os.path.dirname(os.path.abspath(self.db.path))) / "photos"; photo_dir.mkdir(parents=True,exist_ok=True)
        path = photo_dir / f"{uuid4().hex}.{extension}"; path.write_bytes(content)
        async with self.db.connect() as conn:
            cursor = await conn.execute("INSERT INTO activity_photos(activity_id,uploaded_by,storage_path,created_at) VALUES(?,?,?,?)", (activity_id,user["id"],str(path),datetime.now().isoformat()))
            await conn.commit()
        await self.db.completion(activity_id)
        return web.json_response({"id":cursor.lastrowid})

    async def update_settings(self, request):
        user = self.user(request); body = await request.json(); keys=("reminder_week","reminder_day","reminder_hours","reminder_event","reminder_followup")
        values=[int(bool(body.get(key))) for key in keys]
        async with self.db.connect() as conn:
            await conn.execute("""INSERT INTO user_settings(user_id,reminder_week,reminder_day,reminder_hours,reminder_event,reminder_followup)
                VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET reminder_week=excluded.reminder_week,reminder_day=excluded.reminder_day,
                reminder_hours=excluded.reminder_hours,reminder_event=excluded.reminder_event,reminder_followup=excluded.reminder_followup""", (user["id"],*values))
            await conn.commit()
        return web.json_response({"ok":True})

    async def archive_photo(self, request):
        user = self.user(request)
        company = await self.db.active_company(user["id"])
        if not company:
            raise web.HTTPForbidden()
        photo_key = request.match_info["photo_id"]
        async with self.db.connect() as conn:
            if photo_key.startswith("legacy-"):
                activity_id = int(photo_key.split("-",1)[1])
                photo = await (await conn.execute("SELECT photo_file_id telegram_file_id,NULL storage_path FROM activities WHERE id=? AND company_id=? AND status='completed'", (activity_id,company["id"]))).fetchone()
            else:
                photo = await (await conn.execute("""SELECT p.telegram_file_id,p.storage_path FROM activity_photos p JOIN activities a ON a.id=p.activity_id
                    WHERE p.id=? AND a.company_id=? AND a.status='completed'""", (int(photo_key),company["id"]))).fetchone()
        if not photo:
            raise web.HTTPNotFound()
        if photo["storage_path"]:
            path = Path(photo["storage_path"])
            if not path.is_file(): raise web.HTTPNotFound()
            return web.FileResponse(path,headers={"Cache-Control":"private, max-age=3600"})
        telegram_file = await self.bot.get_file(photo["telegram_file_id"])
        content = BytesIO()
        await self.bot.download_file(telegram_file.file_path, destination=content)
        mime_type = mimetypes.guess_type(telegram_file.file_path or "")[0] or "image/jpeg"
        return web.Response(body=content.getvalue(), content_type=mime_type, headers={"Cache-Control": "private, max-age=3600"})


def create_miniapp(db, bot, token: str) -> web.Application:
    api = MiniApp(db, bot, token)
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app.add_routes([
        web.get("/", api.index), web.get("/api/bootstrap", api.bootstrap),
        web.post("/api/company", api.create_company), web.post("/api/company/switch", api.switch_company), web.post("/api/company/leave", api.leave_company),
        web.post("/api/ideas", api.add_idea), web.put("/api/ideas/{idea_id}", api.update_idea), web.delete("/api/ideas/{idea_id}", api.delete_idea),
        web.post("/api/ideas/{idea_id}/comments", api.add_comment), web.post("/api/ideas/{idea_id}/reactions", api.react),
        web.post("/api/vote/start", api.start_vote), web.post("/api/vote/cast", api.cast_vote),
        web.post("/api/vote/close", api.close_vote), web.post("/api/plan", api.plan),
        web.post("/api/date/options", api.add_date_option), web.post("/api/date/vote", api.vote_date), web.post("/api/date/confirm", api.confirm_date),
        web.post("/api/activity/{activity_id}/confirm", api.confirm_activity), web.post("/api/activity/{activity_id}/photo", api.upload_activity_photo),
        web.post("/api/settings", api.update_settings), web.get("/api/archive/photo/{photo_id}", api.archive_photo),
    ])
    return app


async def start_miniapp(db, bot, token: str):
    app = create_miniapp(db, bot, token)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 8088).start()
    return runner
