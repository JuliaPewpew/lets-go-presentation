from __future__ import annotations

import asyncio
from datetime import datetime
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.client.default import DefaultBotProperties

from .config import load_config
from .database import Database


router = Router()
db: Database


class CompanyForm(StatesGroup):
    name = State()


class IdeaForm(StatesGroup):
    title = State()
    difficulty = State()
    budget = State()
    duration = State()
    anonymous = State()


class PlanForm(StatesGroup):
    date = State()


def menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Что делаем?"), KeyboardButton(text="➕ Добавить идею")],
            [KeyboardButton(text="📋 Наш список"), KeyboardButton(text="🏆 Активность")],
            [KeyboardButton(text="👥 Компания")],
        ],
        resize_keyboard=True,
    )


def scale_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(n), callback_data=f"{prefix}:{n}") for n in range(1, 6)
    ]])


async def require_company(message: Message):
    company = await db.active_company(message.from_user.id)
    if not company:
        await message.answer("Сначала создайте компанию или перейдите по ссылке-приглашению.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Создать компанию", callback_data="company:create")
        ]]))
    return company


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    await db.upsert_user(user.id, user.username, user.full_name)
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) == 2 and payload[1].startswith("join_"):
        company_name = await db.join_company(user.id, payload[1][5:])
        if company_name:
            await message.answer(f"Вы в компании <b>{escape(company_name)}</b>. Пора придумать первое приключение!", reply_markup=menu())
            return
        await message.answer("Ссылка-приглашение устарела или содержит ошибку.")
    company = await db.active_company(user.id)
    if company:
        await message.answer(f"С возвращением в <b>{escape(company['name'])}</b>!", reply_markup=menu())
    else:
        await message.answer(
            "<b>let’s go!</b> превращает «когда-нибудь надо» в общие воспоминания.\n\nСоздадим компанию?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Создать компанию", callback_data="company:create")
            ]]),
        )


@router.callback_query(F.data == "company:create")
async def create_company_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompanyForm.name)
    await callback.message.answer("Как назовём вашу компанию?")
    await callback.answer()


@router.message(CompanyForm.name)
async def create_company_finish(message: Message, state: FSMContext, bot: Bot):
    name = (message.text or "").strip()[:60]
    if len(name) < 2:
        await message.answer("Название слишком короткое. Попробуйте ещё раз.")
        return
    _, code = await db.create_company(message.from_user.id, name)
    me = await bot.get_me()
    invite = f"https://t.me/{me.username}?start=join_{code}"
    await state.clear()
    await message.answer(
        f"Компания <b>{escape(name)}</b> создана!\n\nСсылка для друзей:\n<code>{invite}</code>",
        reply_markup=menu(),
    )


@router.message(F.text == "👥 Компания")
async def company_info(message: Message, bot: Bot):
    company = await require_company(message)
    if not company:
        return
    me = await bot.get_me()
    invite = f"https://t.me/{me.username}?start=join_{company['invite_code']}"
    await message.answer(f"<b>{escape(company['name'])}</b>\n\nПригласить друзей:\n<code>{invite}</code>")


@router.message(F.text == "➕ Добавить идею")
async def idea_start(message: Message, state: FSMContext):
    if not await require_company(message):
        return
    await state.set_state(IdeaForm.title)
    await message.answer("Что вы хотите сделать вместе? Одно короткое предложение.")


@router.message(IdeaForm.title)
async def idea_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()[:180]
    if len(title) < 4:
        await message.answer("Опишите идею чуть подробнее.")
        return
    await state.update_data(title=title)
    await state.set_state(IdeaForm.difficulty)
    await message.answer("Насколько это сложно?\n1 — почти без подготовки, 5 — настоящий челлендж.", reply_markup=scale_keyboard("difficulty"))


@router.callback_query(IdeaForm.difficulty, F.data.startswith("difficulty:"))
async def idea_difficulty(callback: CallbackQuery, state: FSMContext):
    await state.update_data(difficulty=int(callback.data.split(":")[1]))
    await state.set_state(IdeaForm.budget)
    await callback.message.answer("Какой бюджет?\n1 — бесплатно или символически, 5 — существенные расходы.", reply_markup=scale_keyboard("budget"))
    await callback.answer()


@router.callback_query(IdeaForm.budget, F.data.startswith("budget:"))
async def idea_budget(callback: CallbackQuery, state: FSMContext):
    await state.update_data(budget=int(callback.data.split(":")[1]))
    await state.set_state(IdeaForm.duration)
    await callback.message.answer("Сколько времени понадобится?\n1 — до часа, 5 — несколько дней.", reply_markup=scale_keyboard("duration"))
    await callback.answer()


@router.callback_query(IdeaForm.duration, F.data.startswith("duration:"))
async def idea_duration(callback: CallbackQuery, state: FSMContext):
    await state.update_data(duration=int(callback.data.split(":")[1]))
    await state.set_state(IdeaForm.anonymous)
    await callback.message.answer("Показывать автора идеи?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Показывать", callback_data="anonymous:0"),
        InlineKeyboardButton(text="Скрыть", callback_data="anonymous:1"),
    ]]))
    await callback.answer()


@router.callback_query(IdeaForm.anonymous, F.data.startswith("anonymous:"))
async def idea_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    company = await db.active_company(callback.from_user.id)
    await db.add_idea(company["id"], callback.from_user.id, data["title"], data["difficulty"], data["budget"], data["duration"], callback.data.endswith("1"))
    await state.clear()
    await callback.message.answer("Идея добавлена в общий список ✨", reply_markup=menu())
    await callback.answer()


@router.message(F.text == "📋 Наш список")
async def ideas_list(message: Message):
    company = await require_company(message)
    if not company:
        return
    rows = await db.ideas(company["id"])
    if not rows:
        await message.answer("Список пока пуст. Добавьте первую идею!")
        return
    text = [f"<b>Идеи компании «{escape(company['name'])}»</b>"]
    for idea in rows[:20]:
        author = "анонимно" if idea["anonymous"] else escape(idea["author"])
        text.append(f"\n<b>{escape(idea['title'])}</b>\nСложность {idea['difficulty']}/5 · Бюджет {idea['budget']}/5 · Длительность {idea['duration']}/5\n<i>{author}</i>")
    await message.answer("\n".join(text))


@router.message(F.text == "🎲 Что делаем?")
async def vote_start(message: Message):
    company = await require_company(message)
    if not company:
        return
    ideas = await db.ideas(company["id"])
    if len(ideas) < 2:
        await message.answer("Для голосования нужно хотя бы две идеи.")
        return
    round_id = await db.create_round(company["id"], message.from_user.id)
    buttons = [[InlineKeyboardButton(text=idea["title"][:45], callback_data=f"vote:{round_id}:{idea['id']}")] for idea in ideas[:10]]
    buttons.append([InlineKeyboardButton(text="Завершить голосование", callback_data=f"vote_close:{round_id}")])
    await message.answer("<b>Что делаем следующим?</b>\nКаждый может выбрать один вариант и изменить голос до закрытия.", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("vote:"))
async def vote_cast(callback: CallbackQuery):
    _, round_id, idea_id = callback.data.split(":")
    await db.vote(int(round_id), callback.from_user.id, int(idea_id))
    await callback.answer("Голос принят!")


@router.callback_query(F.data.startswith("vote_close:"))
async def vote_close(callback: CallbackQuery, state: FSMContext):
    round_id = int(callback.data.split(":")[1])
    winner = await db.close_round(round_id)
    if not winner:
        await callback.answer("Пока никто не проголосовал.", show_alert=True)
        return
    await state.update_data(winner_id=winner["id"], winner_title=winner["title"])
    await state.set_state(PlanForm.date)
    await callback.message.answer(f"Победила идея <b>{escape(winner['title'])}</b> 🎉\n\nКогда встречаемся? Напишите дату и время в формате <code>24.08.2026 18:00</code>.")
    await callback.answer()


@router.message(PlanForm.date)
async def plan_date(message: Message, state: FSMContext):
    try:
        scheduled = datetime.strptime((message.text or "").strip(), "%d.%m.%Y %H:%M")
        if scheduled <= datetime.now():
            raise ValueError
    except ValueError:
        await message.answer("Нужна будущая дата в формате <code>24.08.2026 18:00</code>.")
        return
    data = await state.get_data()
    company = await db.active_company(message.from_user.id)
    await db.create_activity(company["id"], data["winner_id"], scheduled, message.from_user.id)
    await state.clear()
    await message.answer(f"Запланировано: <b>{escape(data['winner_title'])}</b>\n{scheduled:%d.%m.%Y в %H:%M}\n\nЯ напомню компании ближе к делу.", reply_markup=menu())


@router.message(F.text == "🏆 Активность")
async def activity_show(message: Message):
    company = await require_company(message)
    if not company:
        return
    activity = await db.current_activity(company["id"])
    if not activity:
        await message.answer("Сейчас нет незавершённой активности.")
        return
    confirmed, total, has_photo, _ = await db.completion(activity["id"])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтверждаю участие", callback_data=f"confirm:{activity['id']}")],
        [InlineKeyboardButton(text="📷 Добавить фото", callback_data=f"photo:{activity['id']}")],
    ])
    await message.answer(
        f"<b>{escape(activity['title'])}</b>\n{datetime.fromisoformat(activity['scheduled_at']):%d.%m.%Y в %H:%M}\n\nПодтверждения: {confirmed} из {total}\nФото: {'есть ✅' if has_photo else 'ждём'}",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("confirm:"))
async def activity_confirm(callback: CallbackQuery):
    activity_id = int(callback.data.split(":")[1])
    await db.confirm(activity_id, callback.from_user.id)
    confirmed, total, has_photo, completed = await db.completion(activity_id)
    text = "🏆 <b>Ачивка получена!</b> Активность отправлена в архив." if completed else f"Подтверждено: {confirmed} из {total}. Фото: {'есть' if has_photo else 'ещё нет'}."
    await callback.message.answer(text)
    await callback.answer("Спасибо!")


@router.callback_query(F.data.startswith("photo:"))
async def activity_photo_request(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_activity_id=int(callback.data.split(":")[1]))
    await callback.message.answer("Пришлите одну фотографию с мероприятия.")
    await callback.answer()


@router.message(F.photo)
async def activity_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    activity_id = data.get("photo_activity_id")
    if not activity_id:
        return
    await db.add_photo(activity_id, message.photo[-1].file_id)
    confirmed, total, _, completed = await db.completion(activity_id)
    await state.update_data(photo_activity_id=None)
    if completed:
        await message.answer("🏆 <b>Ачивка получена!</b> Все подтвердили выполнение, а фото сохранено в архив.")
    else:
        await message.answer(f"Фото добавлено ✅ Осталось подтверждений: {total - confirmed}.")


async def main() -> None:
    global db
    config = load_config()
    db = Database(config.database_path)
    await db.init()
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    reminder_task = asyncio.create_task(reminder_loop(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        reminder_task.cancel()


async def reminder_loop(bot: Bot) -> None:
    while True:
        for user_id, kind, title, scheduled in await db.due_reminders(datetime.now()):
            if kind == "day":
                text = f"Уже завтра: <b>{escape(title)}</b>\n{scheduled:%d.%m.%Y в %H:%M}. Вы с нами?"
            elif kind == "event":
                text = f"Пора! Сегодня вы планировали <b>{escape(title)}</b> 🚀"
            else:
                text = f"Ну как прошло <b>{escape(title)}</b>? Откройте «🏆 Активность», подтвердите участие и добавьте фото."
            try:
                await bot.send_message(user_id, text)
            except Exception:
                pass
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
