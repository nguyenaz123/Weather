"""Đổi địa điểm qua tin nhắn Telegram (ghim vị trí hoặc /location) và lưu vào location.json."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

import telegram_service
import weather_service
from config import LOCATION_FILE, Config

log = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 100
COMMAND_RE = re.compile(r"^/location(?:@\w+)?(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
COORD_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$")


@dataclass(frozen=True)
class Location:
    query: str
    changed: bool = False
    error: str | None = None  # mô tả yêu cầu đổi địa điểm bị từ chối (để báo trong bản tin)


class _Request(NamedTuple):
    query: str | None
    source: str
    error: str | None = None


def _coords(lat: float, lon: float) -> str:
    # Làm tròn ~1 km để không lưu vị trí chính xác vào repo.
    return f"{lat:.2f},{lon:.2f}"


def _clean(text: str) -> str:
    text = "".join(ch for ch in text if ch.isprintable())
    return " ".join(text.split())[:MAX_QUERY_LENGTH]


def _parse(message: dict) -> _Request | None:
    """Trả về yêu cầu đổi địa điểm trong tin nhắn, hoặc None nếu không phải lệnh đổi."""
    if "location" in message:
        pin = message["location"]
        return _Request(_coords(pin["latitude"], pin["longitude"]), "telegram_pin")

    match = COMMAND_RE.match((message.get("text") or "").strip())
    if not match:
        return None
    arg = _clean(match.group(1) or "")
    if not arg:
        return _Request(None, "command", "thiếu địa điểm sau /location")

    coord = COORD_RE.match(arg)
    if coord:
        lat, lon = float(coord.group(1)), float(coord.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return _Request(None, "command", f'tọa độ "{arg}" không hợp lệ')
        return _Request(_coords(lat, lon), "command")
    return _Request(arg, "command")


def _is_authorized(message: dict, chat_id: str) -> bool:
    return (
        str(message.get("chat", {}).get("id")) == chat_id
        and str(message.get("from", {}).get("id")) == chat_id
    )


def _load_saved() -> dict | None:
    if not LOCATION_FILE.exists():
        return None
    try:
        data = json.loads(LOCATION_FILE.read_text(encoding="utf-8"))
        return data if data.get("query") else None
    except (ValueError, OSError, AttributeError) as exc:
        log.warning("Không đọc được %s (%s), dùng địa điểm mặc định", LOCATION_FILE.name, exc)
        return None


def _save(config: Config, query: str, display_name: str, source: str) -> None:
    data = {
        "query": query,
        "display_name": display_name,
        "source": source,
        "updated_at": datetime.now(ZoneInfo(config.timezone)).isoformat(timespec="seconds"),
    }
    LOCATION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_location(config: Config, dry_run: bool = False) -> Location:
    """Xác định địa điểm cho lần chạy này; lỗi khi đọc tin nhắn không làm hỏng bản tin."""
    saved = _load_saved()
    current = Location(saved["query"] if saved else config.location)

    try:
        updates = telegram_service.get_updates(config)
    except telegram_service.TelegramError as exc:
        log.warning("Không đọc được tin nhắn Telegram, giữ địa điểm hiện tại: %s", exc)
        return current
    if not updates:
        return current

    last_update_id = updates[-1]["update_id"]
    messages = [u["message"] for u in updates if "message" in u]
    authorized = [m for m in messages if _is_authorized(m, config.telegram_chat_id)]
    if len(authorized) < len(messages):
        log.warning("Bỏ qua %d tin nhắn từ người/nhóm không được phép", len(messages) - len(authorized))

    changes = [r for r in map(_parse, authorized) if r is not None]
    result = current
    if changes:
        request = changes[-1]  # tin mới nhất thắng
        if request.error:
            result = Location(current.query, error=request.error)
        else:
            try:
                found = weather_service.lookup_location(config, request.query)
            except weather_service.LocationNotFound:
                result = Location(current.query, error=f'không tìm thấy "{request.query}"')
            except weather_service.WeatherError as exc:
                # Lỗi mạng/API: không xác nhận tin để lần chạy sau thử lại.
                log.warning("Không kiểm tra được địa điểm mới, sẽ thử lại lần sau: %s", exc)
                return current
            else:
                query = _coords(found["lat"], found["lon"])
                display_name = weather_service.format_location_name(found)
                log.info("Đổi địa điểm: %s -> %s (%s)", current.query, query, display_name)
                if not dry_run:
                    _save(config, query, display_name, request.source)
                result = Location(query, changed=True)

    if not dry_run:
        try:
            telegram_service.confirm_updates(config, last_update_id)
        except telegram_service.TelegramError as exc:
            log.warning("%s", exc)
    return result
