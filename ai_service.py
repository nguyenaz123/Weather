"""Gửi dữ liệu thời tiết tới Gemini để tạo bản tin buổi sáng."""

from __future__ import annotations

import json
import logging
import re
import time

from google import genai
from google.genai import errors, types

import telegram_service
from config import Config

log = logging.getLogger(__name__)

TIMEOUT_MS = 60_000
SERVER_RETRIES = 2

SYSTEM_INSTRUCTION = """\
Bạn là một trợ lý thời tiết cá nhân thông minh và chu đáo. Hãy phân tích dữ liệu thời tiết 24h tới \
và tạo một bản tin buổi sáng ngắn gọn, trực quan, dễ đọc trên điện thoại theo các yêu cầu sau:
1. Tổng quan ngắn: thời tiết chủ đạo trong ngày (nhiệt độ cao nhất/thấp nhất, khả năng mưa).
2. Điểm đột biến quan trọng (Spikes/Alerts): chỉ ra chính xác khung giờ có sự thay đổi đột ngột \
(ví dụ: "Nhiệt độ tăng mạnh từ 11h-14h", "Dự báo mưa rào lúc 16h50 đúng giờ tan tầm", \
"Chỉ số UV đạt đỉnh mức 9 vào lúc 12h").
3. Cảnh báo sức khỏe & vật dụng cần mang theo: dựa trên các điểm đột biến, gợi ý cụ thể vật dụng nên mang \
(ví dụ: ô/áo mưa, áo khoác chống nắng, kính râm, khẩu trang chống bụi/lạnh, uống nhiều nước).
4. Định dạng: thêm các icon emoji phù hợp (☀️, 🌧️, ☂️, 🕶️, 🏍️) để tạo cảm giác thân thiện.

Quy tắc bắt buộc:
- Định dạng bằng thẻ HTML của Telegram, chỉ dùng: <b>in đậm</b> cho tiêu đề từng phần, <i>in nghiêng</i>, \
và tối đa một khối <blockquote>...</blockquote> cho cảnh báo quan trọng nhất. Gạch đầu dòng bằng "•". \
Không dùng Markdown (*, **, _, #), bảng, liên kết hay thẻ nào khác; không viết ký tự <, >, & đứng riêng.
- Tối đa khoảng 1500 ký tự.
- Chỉ dựa vào dữ liệu được cung cấp, không bịa số liệu. Trường "spikes" là các điểm đột biến đã tính sẵn; \
"alerts" là cảnh báo chính thức (nếu có, phải nêu rõ).
- Đầu tin đã có sẵn tên địa điểm và dòng nhiệt độ/mưa/UV; cuối tin đã có bảng dự báo theo giờ. \
Không ghi lại tên địa điểm và không liệt kê dự báo từng giờ.
"""

ALLOWED_TAG = re.compile(r"&lt;(/?)(b|i|u|s|blockquote)&gt;")
MARKDOWN_BOLD = re.compile(r"\*\*?(\S[^*\n]*?)\*\*?")


def to_telegram_html(text: str) -> str:
    """Escape output của AI, chỉ giữ lại các thẻ được phép; đổi Markdown đậm (nếu model lỡ dùng) sang <b>."""
    text = ALLOWED_TAG.sub(r"<\1\2>", telegram_service.escape(text))
    return MARKDOWN_BOLD.sub(r"<b>\1</b>", text)


class AIError(Exception):
    pass


def build_prompt(config: Config, weather: dict) -> str:
    location = weather["location"]
    lines = [
        f"Địa điểm: {location['name']}",
        f"Thời điểm hiện tại (giờ địa phương): {location['localtime']}",
    ]
    if config.language != "vi":
        lines.append(f"Viết bản tin bằng ngôn ngữ có mã: {config.language}")
    lines.append("Dữ liệu (JSON):")
    lines.append(json.dumps(weather, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)


def generate_briefing(config: Config, weather: dict) -> str:
    """Thử lần lượt các model; model lỗi 404/429 thì chuyển sang model dự phòng."""
    client = genai.Client(api_key=config.ai_api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    request_config = types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.4)
    prompt = build_prompt(config, weather)

    last_error: Exception | None = None
    for model in config.ai_models:
        for attempt in range(1, SERVER_RETRIES + 1):
            try:
                response = client.models.generate_content(model=model, contents=prompt, config=request_config)
            except errors.ServerError as exc:
                last_error = exc
                log.warning("Gemini %s lỗi máy chủ (lần %d/%d): %s", model, attempt, SERVER_RETRIES, exc.code)
                if attempt < SERVER_RETRIES:
                    time.sleep(5)
                continue
            except errors.ClientError as exc:
                if exc.code not in (404, 429):
                    raise AIError(f"Gemini từ chối yêu cầu ({exc.code} {exc.status})") from None
                last_error = exc
                log.warning("Gemini %s không dùng được (%s), thử model dự phòng", model, exc.code)
                break
            except Exception as exc:  # lỗi mạng/timeout từ httpx
                last_error = exc
                log.warning("Gemini %s lỗi kết nối: %s", model, type(exc).__name__)
                break

            text = (response.text or "").strip()
            if text:
                log.info("Đã tạo bản tin bằng %s", model)
                return to_telegram_html(text)
            last_error = AIError(f"{model} trả về nội dung rỗng")
            break

    raise AIError(f"Tất cả model Gemini đều lỗi: {last_error}")


def fallback_briefing(weather: dict) -> str:
    """Bản tóm tắt thô (HTML) khi không dùng được AI."""
    s = weather["summary"]
    lines = [
        "🌤️ <b>Bản tin thời tiết 24h tới</b>",
        f"🥵 Cảm giác nóng nhất: {s['feelslike_max_c']:.0f}°C",
        f"💧 Tổng lượng mưa: {s['total_precip_mm']} mm",
    ]
    if weather["spikes"]:
        lines.append("")
        lines.append("⚡ <b>Điểm đáng chú ý:</b>")
        lines.extend(f"• {telegram_service.escape(spike)}" for spike in weather["spikes"])
    if weather["alerts"]:
        alerts = "\n".join(f"🚨 {telegram_service.escape(a['headline'] or a['event'] or '')}" for a in weather["alerts"])
        lines.append(f"\n<blockquote>{alerts}</blockquote>")
    return "\n".join(lines)
