"""Đọc và kiểm tra biến môi trường (GitHub Secrets/Variables hoặc file .env khi chạy thử)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
LOCATION_FILE = BASE_DIR / "location.json"

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
DEFAULT_AI_MODEL = "gemini-3.8-flash"
DEFAULT_LANGUAGE = "vi"
# Thử lần lượt khi model chính lỗi (không tồn tại / hết quota).
AI_FALLBACK_MODELS = ("gemini-3.6-flash", "gemini-2.5-flash")

REQUIRED_VARS = (
    "WEATHER_API_KEY",
    "AI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "LOCATION",
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    weather_api_key: str
    ai_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    location: str
    timezone: str
    ai_model: str
    language: str

    @property
    def ai_models(self) -> tuple[str, ...]:
        return (self.ai_model,) + tuple(m for m in AI_FALLBACK_MODELS if m != self.ai_model)


def _env(name: str, default: str = "") -> str:
    # Variable chưa tạo trên GitHub được truyền vào dưới dạng chuỗi rỗng -> coi như chưa đặt.
    value = os.getenv(name, "").strip()
    return value or default


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env")  # không có file .env (trên GitHub) thì bỏ qua

    missing = [name for name in REQUIRED_VARS if not _env(name)]
    if missing:
        raise ConfigError("Thiếu biến môi trường: " + ", ".join(missing))

    timezone = _env("TIMEZONE", DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"TIMEZONE không hợp lệ: {timezone}") from None

    return Config(
        weather_api_key=_env("WEATHER_API_KEY"),
        ai_api_key=_env("AI_API_KEY"),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        location=_env("LOCATION"),
        timezone=timezone,
        ai_model=_env("AI_MODEL", DEFAULT_AI_MODEL),
        language=_env("LANGUAGE", DEFAULT_LANGUAGE),
    )
