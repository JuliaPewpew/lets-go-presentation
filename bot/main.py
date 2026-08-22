from __future__ import annotations

import asyncio
from datetime import datetime
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, MenuButtonWebApp, Message, ReplyKeyboardMarkup, WebAppInfo
from aiogram.client.default import DefaultBotProperties

from .config import load_config
from .database import Database
from .miniapp import start_miniapp


router = Router()
db: Database

MENU_ACTIONS = {
    "🗳 Голосование", "🎲 Что делаем?",
    "➕ Новая идея", "➕ Добавить идею",
    "💡 Все идеи", "📋 Наш список",
    "📍 Текущая активность", "🏆 Активность",
    "🖼 Архив",
    "👥 Компания и друзья", "👥 Компания",
}


class CompanyForm(StatesGroup):
    name = State()


class IdeaForm(StatesGroup):
    title = State()
    description = State()
    difficulty = State()
    budget = State()
    duration = State()
    anonymous = State()


class PlanForm(StatesGroup):
    date = State()


def menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗳 Голосование"), KeyboardButton(text="➕ Новая идея")],
            [KeyboardButton(text="💡 Все идеи"), KeyboardButton(text="📍 Текущая активность")],
            [KeyboardButton(text="🖼 Архив"), KeyboardButton(text="👥 Компания и друзья")],
        ],
        resize_keyboard=True,
    )


def scale_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(n), callback_data=f"{prefix}:{n}") for n in range(1, 6)
    ]])


def invite_keyboard(invite: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Вступить в компанию 🚀", url=invite)
    ]])


async def voting_view(round_id: int, viewer_id: int):
    voting_round, members = await db.voting_status(round_id)
    if not voting_round:
        return "Голосование не найдено.", None
    voted = [escape(member["display_name"]) for member in members if member["idea_title"]]
    waiting = [escape(member["display_name"]) for member in members if not member["idea_title"]]
    viewer = next((member for member in members if member["id"] == viewer_id), None)
    choice = escape(viewer["idea_title"]) if viewer and viewer["idea_title"] else "ещё не выбран"
    ideas = await db.ideas(voting_round["company_id"])
    buttons = [[InlineKeyboardButton(text=idea["title"][:45], callback_data=f"vote:{round_id}:{idea['id']}")] for idea in ideas[:10]]
    buttons.append([InlineKeyboardButton(text="🔄 Обновить статус", callback_data=f"vote_refresh:{round_id}")])
    buttons.append([InlineKeyboardButton(text="🔒 Завершить — организатор", callback_data=f"vote_close:{round_id}")])
    text = (
        "<b>Голосование: что делаем следующим?</b>\n"
        f"Организатор: {escape(voting_round['organizer'])}\n\n"
        f"Ваш выбор: <b>{choice}</b>\n"
        "Можно голосовать один раз и менять выбор до завершения.\n\n"
        f"✅ Проголосовали: {', '.join(voted) if voted else 'пока никто'}\n"
        f"⏳ Ещё не проголосовали: {', '.join(waiting) if waiting else 'все проголосовали'}\n\n"
        "Завершить голосование может его организатор или владелец компании."
    )
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


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
        f"Компания <b>{escape(name)}</b> создана!\n\n"
        f"Отправьте друзьям эту ссылку:\n<a href=\"{invite}\">{invite}</a>",
        reply_markup=invite_keyboard(invite),
    )
    await message.answer("Главное меню", reply_markup=menu())


@router.message(F.text.in_({"👥 Компания и друзья", "👥 Компания"}))
async def company_info(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    company = await require_company(message)
    if not company:
        return
    me = await bot.get_me()
    invite = f"https://t.me/{me.username}?start=join_{company['invite_code']}"
    await message.answer(
        f"<b>{escape(company['name'])}</b>\n\n"
        f"Пригласить друзей:\n<a href=\"{invite}\">{invite}</a>",
        reply_markup=invite_keyboard(invite),
    )


@router.message(F.text.in_({"➕ Новая идея", "➕ Добавить идею"}))
async def idea_start(message: Message, state: FSMContext):
    await state.clear()
    if not await require_company(message):
        return
    await state.set_state(IdeaForm.title)
    await message.answer("Что вы хотите сделать вместе? Одно короткое предложение.")


@router.message(IdeaForm.title, ~F.text.in_(MENU_ACTIONS))
async def idea_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()[:180]
    if len(title) < 4:
        await message.answer("Опишите идею чуть подробнее.")
        return
    await state.update_data(title=title)
    await state.set_state(IdeaForm.description)
    await message.answer(
        "Хотите добавить описание? Напишите детали, которые пригодятся друзьям.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Пропустить", callback_data="description:skip")
        ]]),
    )


async def ask_idea_difficulty(message: Message, state: FSMContext):
    await state.set_state(IdeaForm.difficulty)
    await message.answer("Насколько это сложно?\n1 — не требуется подготовки, 5 — настоящий челлендж.", reply_markup=scale_keyboard("difficulty"))


@router.message(IdeaForm.description, ~F.text.in_(MENU_ACTIONS))
async def idea_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()[:1000]
    if not description:
        await message.answer("Напишите описание или нажмите «Пропустить».")
        return
    await state.update_data(description=description)
    await ask_idea_difficulty(message, state)


@router.callback_query(IdeaForm.description, F.data == "description:skip")
async def idea_description_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await ask_idea_difficulty(callback.message, state)
    await callback.answer()


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
    await db.add_idea(
        company["id"], callback.from_user.id, data["title"], data["difficulty"],
        data["budget"], data["duration"], callback.data.endswith("1"), data.get("description"),
    )
    await state.clear()
    await callback.message.answer("Идея добавлена в общий список ✨", reply_markup=menu())
    await callback.answer()


@router.message(F.text.in_({"💡 Все идеи", "📋 Наш список"}))
async def ideas_list(message: Message, state: FSMContext):
    await state.clear()
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
        description = f"\n{escape(idea['description'])}" if idea["description"] else ""
        text.append(f"\n<b>{escape(idea['title'])}</b>{description}\nСложность {idea['difficulty']}/5 · Бюджет {idea['budget']}/5 · Длительность {idea['duration']}/5\n<i>{author}</i>")
    await message.answer("\n".join(text))


@router.message(F.text.in_({"🗳 Голосование", "🎲 Что делаем?"}))
async def vote_start(message: Message, state: FSMContext):
    await state.clear()
    company = await require_company(message)
    if not company:
        return
    ideas = await db.ideas(company["id"])
    if len(ideas) < 2:
        await message.answer("Для голосования нужно хотя бы две идеи.")
        return
    round_id = await db.create_round(company["id"], message.from_user.id)
    text, keyboard = await voting_view(round_id, message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("vote:"))
async def vote_cast(callback: CallbackQuery):
    _, round_id, idea_id = callback.data.split(":")
    await db.vote(int(round_id), callback.from_user.id, int(idea_id))
    text, keyboard = await voting_view(int(round_id), callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Голос сохранён. Его можно изменить до завершения.", show_alert=True)


@router.callback_query(F.data.startswith("vote_refresh:"))
async def vote_refresh(callback: CallbackQuery):
    round_id = int(callback.data.split(":")[1])
    text, keyboard = await voting_view(round_id, callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise
    await callback.answer("Статус обновлён")


@router.callback_query(F.data.startswith("vote_close:"))
async def vote_close(callback: CallbackQuery, state: FSMContext, bot: Bot):
    round_id = int(callback.data.split(":")[1])
    if not await db.can_close_round(round_id, callback.from_user.id):
        await callback.answer("Завершить голосование может только организатор или владелец компании.", show_alert=True)
        return
    _, members = await db.voting_status(round_id)
    winner = await db.close_round(round_id)
    if not winner:
        await callback.answer("Пока никто не проголосовал.", show_alert=True)
        return
    await callback.answer("Голосование завершено")
    await state.update_data(winner_id=winner["id"], winner_title=winner["title"])
    await state.set_state(PlanForm.date)
    result_text = f"Голосование завершено! Победила идея <b>{escape(winner['title'])}</b> 🎉"
    await callback.message.answer(result_text, reply_markup=menu())
    for member in members:
        if member["id"] == callback.from_user.id:
            continue
        try:
            await bot.send_message(member["id"], result_text, reply_markup=menu())
        except Exception:
            pass
    await callback.message.answer("Когда встречаемся? Напишите дату и время в формате <code>24.08.2026 18:00</code>.")


@router.message(PlanForm.date, ~F.text.in_(MENU_ACTIONS))
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


@router.message(F.text.in_({"📍 Текущая активность", "🏆 Активность"}))
async def activity_show(message: Message, state: FSMContext):
    await state.clear()
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


@router.message(F.text == "🖼 Архив")
async def archive_show(message: Message, state: FSMContext):
    await state.clear()
    company = await require_company(message)
    if not company:
        return
    activities = await db.archive(company["id"])
    if not activities:
        await message.answer(
            "Архив пока пуст. Сюда попадут активности, которые подтвердили все участники и для которых добавлено фото."
        )
        return
    await message.answer(f"<b>Архив компании «{escape(company['name'])}»</b>\nВыполнено: {len(activities)}")
    for activity in activities:
        scheduled = datetime.fromisoformat(activity["scheduled_at"])
        caption = f"🏆 <b>{escape(activity['title'])}</b>\n{scheduled:%d.%m.%Y}"
        await message.answer_photo(activity["photo_file_id"], caption=caption)


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
    web_runner = await start_miniapp(db, bot, config.bot_token)
    if config.webapp_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=config.webapp_url)))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    reminder_task = asyncio.create_task(reminder_loop(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        reminder_task.cancel()
        await web_runner.cleanup()


async def reminder_loop(bot: Bot) -> None:
    while True:
        for user_id, kind, title, scheduled in await db.due_reminders(datetime.now()):
            if kind == "day":
                text = f"Уже завтра: <b>{escape(title)}</b>\n{scheduled:%d.%m.%Y в %H:%M}. Вы с нами?"
            elif kind == "event":
                text = f"Пора! Сегодня вы планировали <b>{escape(title)}</b> 🚀"
            else:
                text = f"Ну как прошло <b>{escape(title)}</b>? Откройте «📍 Текущая активность», подтвердите участие и добавьте фото."
            try:
                await bot.send_message(user_id, text)
            except Exception:
                pass
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
