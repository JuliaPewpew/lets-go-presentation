from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_path: str
    timezone: str


def load_config() -> Config:
    load_dotenv(Path(__file__).with_name(".env"))
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and add the token.")
    return Config(
        bot_token=token,
        database_path=os.getenv("DATABASE_PATH", "./data/lets_go.db"),
        timezone=os.getenv("BOT_TIMEZONE", "Europe/Moscow"),
    )
