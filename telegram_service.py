"""Gửi và nhận tin nhắn qua Telegram Bot API."""

from __future__ import annotations

import html
import logging
import re
import time

import requests

from config import Config

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 15
RETRIES = 3
MAX_LENGTH = 4096
SPLIT_LENGTH = MAX_LENGTH - 200  # chừa chỗ cho thẻ đóng/mở lại khi tách tin
HTML_TAG = re.compile(r"<(/?)([a-z][a-z-]*)[^>]*>")


class TelegramError(Exception):
    pass


def _call(config: Config, method: str, payload: dict) -> dict:
    """Gọi Bot API; trả về JSON (kể cả khi lỗi) để người gọi tự xử lý."""
    token = config.telegram_bot_token
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.post(API_URL.format(token=token, method=method), json=payload, timeout=TIMEOUT)
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            # URL chứa token -> che trước khi đưa vào thông báo lỗi.
            message = f"Lỗi kết nối Telegram ({method}): {str(exc).replace(token, '***')}"
        if attempt < RETRIES:
            log.warning("%s (lần %d/%d), thử lại...", message, attempt, RETRIES)
            time.sleep(3)
    raise TelegramError(message)


def escape(text: str) -> str:
    """Escape văn bản thường trước khi chèn vào tin HTML."""
    return html.escape(text, quote=False)


def to_plain_text(text: str) -> str:
    return html.unescape(HTML_TAG.sub("", text))


def _split_lines(text: str) -> list[str]:
    """Tách tin dài thành nhiều phần, ưu tiên cắt theo dòng."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > SPLIT_LENGTH:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:SPLIT_LENGTH])
            line = line[SPLIT_LENGTH:]
        if len(current) + len(line) > SPLIT_LENGTH:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


def _split(text: str) -> list[str]:
    """Như _split_lines, nhưng thẻ đang mở ở cuối một phần được đóng lại và mở lại ở phần sau."""
    result, carry = [], ""
    for chunk in _split_lines(text):
        chunk = carry + chunk
        open_tags: list[tuple[str, str]] = []
        for match in HTML_TAG.finditer(chunk):
            name = match.group(2)
            if not match.group(1):
                open_tags.append((name, match.group(0)))
            elif open_tags and open_tags[-1][0] == name:
                open_tags.pop()
        result.append(chunk + "".join(f"</{name}>" for name, _ in reversed(open_tags)))
        carry = "".join(tag for _, tag in open_tags)
    return result


def _send_one(config: Config, text: str) -> None:
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    result = _call(config, "sendMessage", payload)
    if result.get("ok"):
        return

    description = result.get("description", "")
    if result.get("error_code") == 400 and "can't parse entities" in description:
        log.warning("HTML không hợp lệ (%s), gửi lại dạng văn bản thường", description)
        del payload["parse_mode"]
        payload["text"] = to_plain_text(text)
        result = _call(config, "sendMessage", payload)
        if result.get("ok"):
            return
        description = result.get("description", "")

    raise TelegramError(f"Telegram trả lỗi {result.get('error_code')}: {description}")


def send_message(config: Config, text: str) -> None:
    """Gửi tin định dạng HTML (chỉ các thẻ Telegram hỗ trợ: b, i, code, blockquote...)."""
    for chunk in _split(text):
        _send_one(config, chunk)


def get_updates(config: Config, offset: int | None = None) -> list[dict]:
    payload: dict = {"timeout": 0, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    result = _call(config, "getUpdates", payload)
    if not result.get("ok"):
        raise TelegramError(f"getUpdates lỗi {result.get('error_code')}: {result.get('description', '')}")
    return result["result"]


def confirm_updates(config: Config, last_update_id: int) -> None:
    """Báo Telegram đã xử lý xong tới last_update_id để không nhận lại các tin này."""
    result = _call(config, "getUpdates", {"offset": last_update_id + 1, "limit": 1, "timeout": 0})
    if not result.get("ok"):
        raise TelegramError(f"Xác nhận getUpdates lỗi: {result.get('description', '')}")
