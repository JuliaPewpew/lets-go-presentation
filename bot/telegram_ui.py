from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


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
        InlineKeyboardButton(text=str(number), callback_data=f"{prefix}:{number}")
        for number in range(1, 6)
    ]])


def invite_keyboard(invite: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Вступить в компанию 🚀", url=invite)
    ]])

