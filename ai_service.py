"""Gửi dữ liệu thời tiết tới Gemini để tạo bản tin buổi sáng."""

from __future__ import annotations

import json
import logging
import time

from google import genai
from google.genai import errors, types

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
- Chỉ dùng Markdown cơ bản của Telegram: *in đậm* (một dấu sao), _in nghiêng_; gạch đầu dòng bằng "•". \
Không dùng tiêu đề "#", bảng, "**", liên kết hay code block.
- Tối đa khoảng 1500 ký tự.
- Chỉ dựa vào dữ liệu được cung cấp, không bịa số liệu. Trường "spikes" là các điểm đột biến đã tính sẵn; \
"alerts" là cảnh báo chính thức (nếu có, phải nêu rõ).
- Không cần ghi tên địa điểm ở đầu bản tin (đã có sẵn).
"""


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
                return text
            last_error = AIError(f"{model} trả về nội dung rỗng")
            break

    raise AIError(f"Tất cả model Gemini đều lỗi: {last_error}")


def fallback_briefing(weather: dict) -> str:
    """Bản tóm tắt thô khi không dùng được AI."""
    s = weather["summary"]
    lines = [
        "🌤️ *Bản tin thời tiết 24h tới*",
        f"🌡️ Nhiệt độ: {s['temp_min_c']:.0f}–{s['temp_max_c']:.0f}°C (cảm giác tới {s['feelslike_max_c']:.0f}°C)",
        f"🌧️ Khả năng mưa cao nhất: {s['max_chance_of_rain']}% (tổng {s['total_precip_mm']} mm)",
        f"🕶️ UV cao nhất: {s['max_uv']:.0f}",
    ]
    if weather["spikes"]:
        lines.append("")
        lines.append("⚡ *Điểm đáng chú ý:*")
        lines.extend(f"• {spike}" for spike in weather["spikes"])
    for alert in weather["alerts"]:
        lines.append(f"🚨 {alert['headline'] or alert['event']}")
    return "\n".join(lines)
