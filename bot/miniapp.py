from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import time
from io import BytesIO
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from .domain import IdeaInput, REACTIONS, REMINDER_KEYS, ValidationError, future_datetime
from .miniapp_dashboard import DashboardLoader
from .miniapp_routes import register_miniapp_routes
from .photo_storage import PhotoStorage

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


class MiniApp:
    def __init__(self, db, bot, token: str):
        self.db, self.bot, self.token = db, bot, token
        self.photos = PhotoStorage(db.path)
        self.dashboard = DashboardLoader(db)

    @staticmethod
    def bad_request(error: ValidationError):
        raise web.HTTPBadRequest(text=str(error))

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

    async def asset(self, request):
        assets = {
            "miniapp.css": ("miniapp.css", "text/css"),
            "miniapp.js": ("miniapp.js", "application/javascript"),
        }
        asset = assets.get(request.match_info["name"])
        if not asset:
            raise web.HTTPNotFound()
        return web.FileResponse(
            Path(__file__).with_name(asset[0]),
            headers={"Content-Type": f"{asset[1]}; charset=utf-8", "Cache-Control": "public, max-age=300"},
        )

    async def bootstrap(self, request):
        user = self.user(request)
        await self.db.upsert_user(user["id"], user.get("username"), " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "Друг")
        company = await self.db.active_company(user["id"])
        if not company:
            return web.json_response({"user": user, "company": None})
        return web.json_response(await self.dashboard.load(user, company))

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
        try:
            new_owner = await self.db.leave_company(user["id"], company["id"])
        except (LookupError, ValueError) as error:
            raise web.HTTPBadRequest(text=str(error)) from error
        return web.json_response({"ok": True, "new_owner": new_owner})

    async def add_idea(self, request):
        user = self.user(request); body = await request.json(); company = await self.db.active_company(user["id"])
        if not company: raise web.HTTPForbidden()
        try: values = IdeaInput.from_mapping(body)
        except ValidationError as error: self.bad_request(error)
        idea_id = await self.db.add_idea(
            company["id"], user["id"], values.title, values.difficulty, values.budget,
            values.duration, values.anonymous, values.description,
        )
        return web.json_response({"id": idea_id})

    async def update_idea(self, request):
        user = self.user(request); body = await request.json(); idea_id = int(request.match_info["idea_id"])
        _, idea = await self.idea_access(user["id"], idea_id)
        if user["id"] not in (idea["author_id"], idea["owner_id"]): raise web.HTTPForbidden(text="Редактировать может автор или владелец")
        try: values = IdeaInput.from_mapping(body)
        except ValidationError as error: self.bad_request(error)
        async with self.db.connect() as conn:
            await conn.execute("""UPDATE ideas SET title=?,description=?,difficulty=?,budget=?,duration=?,anonymous=? WHERE id=?""",
                (values.title, values.description, values.difficulty, values.budget, values.duration, int(values.anonymous), idea_id))
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
        if emoji not in REACTIONS: raise web.HTTPBadRequest()
        async with self.db.connect() as conn:
            exists = await (await conn.execute("SELECT 1 FROM idea_reactions WHERE idea_id=? AND user_id=? AND emoji=?", (idea_id,user["id"],emoji))).fetchone()
            if exists: await conn.execute("DELETE FROM idea_reactions WHERE idea_id=? AND user_id=? AND emoji=?", (idea_id,user["id"],emoji))
            else: await conn.execute("INSERT INTO idea_reactions VALUES(?,?,?)", (idea_id,user["id"],emoji))
            await conn.commit()
        return web.json_response({"ok": True})

    async def start_vote(self, request):
        user = self.user(request); company = await self.db.active_company(user["id"])
        if not company: raise web.HTTPForbidden()
        if await self.db.current_activity(company["id"]):
            raise web.HTTPBadRequest(
                text="Сначала завершите текущую активность: подтвердите участие и добавьте фото"
            )
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
        try: scheduled = future_datetime(body.get("scheduled_at"))
        except ValidationError as error: self.bad_request(error)
        activity_id = await self.db.create_activity(company["id"], int(body["idea_id"]), scheduled, user["id"])
        return web.json_response({"id": activity_id})

    async def add_date_option(self, request):
        user = self.user(request); body = await request.json(); round_id = int(body["round_id"])
        voting_round, _ = await self.db.voting_status(round_id)
        if not voting_round or user["id"] not in (voting_round["created_by"], voting_round["owner_id"]): raise web.HTTPForbidden()
        try: scheduled = future_datetime(body.get("scheduled_at"))
        except ValidationError as error: self.bad_request(error)
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

    async def reschedule_activity(self, request):
        user = self.user(request)
        company = await self.company_for(user["id"])
        activity_id = int(request.match_info["activity_id"])
        body = await request.json()
        try:
            scheduled = future_datetime(body.get("scheduled_at"))
            participant_ids = await self.db.reschedule_activity(
                company["id"], activity_id, user["id"], scheduled
            )
        except ValidationError as error:
            self.bad_request(error)
        except LookupError as error:
            raise web.HTTPNotFound(text=str(error)) from error
        except PermissionError as error:
            raise web.HTTPForbidden(text=str(error)) from error
        message = f"Дата мероприятия изменена: <b>{scheduled:%d.%m.%Y в %H:%M}</b> 📅"
        for participant_id in participant_ids:
            if participant_id == user["id"]:
                continue
            try:
                await self.bot.send_message(participant_id, message)
            except Exception:
                continue
        return web.json_response({"scheduled_at": scheduled.isoformat()})

    async def upload_activity_photo(self, request):
        user = self.user(request); company = await self.company_for(user["id"]); activity_id = int(request.match_info["activity_id"])
        async with self.db.connect() as conn:
            activity = await (await conn.execute("SELECT 1 FROM activities WHERE id=? AND company_id=?", (activity_id,company["id"]))).fetchone()
        if not activity: raise web.HTTPNotFound()
        reader = await request.multipart(); field = await reader.next()
        if not field or field.name != "photo": raise web.HTTPBadRequest(text="Нужно изображение JPG, PNG или WebP")
        content = await field.read(decode=False)
        try: path = self.photos.save(content, field.headers.get("Content-Type", ""))
        except ValidationError as error: self.bad_request(error)
        async with self.db.connect() as conn:
            cursor = await conn.execute("INSERT INTO activity_photos(activity_id,uploaded_by,storage_path,created_at) VALUES(?,?,?,?)", (activity_id,user["id"],str(path),datetime.now().isoformat()))
            await conn.commit()
        await self.db.completion(activity_id)
        return web.json_response({"id":cursor.lastrowid})

    async def update_settings(self, request):
        user = self.user(request); body = await request.json()
        values=[int(bool(body.get(key))) for key in REMINDER_KEYS]
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
    register_miniapp_routes(app, api)
    return app


async def start_miniapp(db, bot, token: str):
    app = create_miniapp(db, bot, token)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 8088).start()
    return runner
