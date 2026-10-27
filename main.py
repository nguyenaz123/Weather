"""Điều phối: Location -> Fetch -> AI -> Notify."""

from __future__ import annotations

import argparse
import logging
import sys

import ai_service
import location_service
import telegram_service
import weather_service
from config import ConfigError, load_config

log = logging.getLogger("weatherbot")

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_API = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bản tin thời tiết buổi sáng qua Telegram")
    parser.add_argument("--dry-run", action="store_true",
                        help="in bản tin ra terminal; không gửi Telegram, không ghi location.json")
    parser.add_argument("--no-ai", action="store_true", help="bỏ qua AI, dùng bản tóm tắt thô")
    parser.add_argument("--location", help='ép địa điểm khi chạy thử, vd "Da Nang" hoặc "16.05,108.20"')
    return parser.parse_args()


HOURLY_STEP = 3  # bảng theo giờ: mỗi dòng cách nhau 3 giờ

# Mã điều kiện thời tiết của WeatherAPI (https://www.weatherapi.com/docs/weather_conditions.json).
CLOUDY = {1006, 1009}
FOG = {1030, 1135, 1147}
DRIZZLE = {1063, 1150, 1153, 1180, 1183, 1240}
RAIN = {1186, 1189, 1192, 1195, 1243, 1246}
THUNDER = {1087, 1273, 1276}


def condition_emoji(code: int, is_day: int) -> str:
    if code == 1000:
        return "☀️" if is_day else "🌙"
    if code == 1003:
        return "⛅" if is_day else "☁️"
    if code in CLOUDY:
        return "☁️"
    if code in FOG:
        return "🌫️"
    if code in DRIZZLE:
        return "🌦️"
    if code in RAIN:
        return "🌧️"
    if code in THUNDER:
        return "⛈️"
    return "❄️"  # các mã còn lại đều là tuyết/mưa đá/băng


def build_header(weather: dict, location: location_service.Location) -> str:
    # Các dòng này do code thêm (không qua AI); escape phần đến từ người dùng/API.
    s = weather["summary"]
    lines = [
        f"📍 <b>{telegram_service.escape(weather['location']['name'])}</b>",
        f"🌡️ {s['temp_min_c']:.0f}–{s['temp_max_c']:.0f}°C · ☂️ {s['max_chance_of_rain']}% · 🕶️ UV {s['max_uv']:.0f}",
    ]
    if location.changed:
        lines.append("✅ <i>Đã đổi địa điểm theo tin nhắn của bạn</i>")
    if location.error:
        lines.append(f"⚠️ <i>Không đổi được địa điểm: {telegram_service.escape(location.error)}. Giữ nguyên địa điểm cũ</i>")
    return "\n".join(lines)


def build_hourly(weather: dict) -> str:
    """Bảng dự báo theo giờ, thu gọn (bấm để mở) để không làm dài bản tin."""
    rows = [
        f"<code>{h['time'][11:13]}h {h['temp_c']:>3.0f}° {h['chance_of_rain']:>3}%</code> "
        f"{condition_emoji(h['condition_code'], h['is_day'])}"
        for h in weather["hourly"][::HOURLY_STEP]
    ]
    return "<blockquote expandable>🕒 <b>Theo giờ</b> · nhiệt độ · khả năng mưa\n" + "\n".join(rows) + "</blockquote>"


def run(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG

    try:
        if args.location:
            location = location_service.Location(args.location)
        else:
            location = location_service.resolve_location(config, dry_run=args.dry_run)

        weather = weather_service.normalize_next_24h(weather_service.fetch_forecast(config, location.query))
        log.info("Đã lấy dự báo cho %s (%d giờ)", weather["location"]["name"], len(weather["hourly"]))

        if args.no_ai:
            body = ai_service.fallback_briefing(weather)
        else:
            try:
                body = ai_service.generate_briefing(config, weather)
            except ai_service.AIError as exc:
                log.error("AI lỗi, gửi bản tóm tắt thô: %s", exc)
                body = ai_service.fallback_briefing(weather)

        message = f"{build_header(weather, location)}\n\n{body}\n\n{build_hourly(weather)}"
        if args.dry_run:
            print("\n" + "=" * 40 + "\n" + message + "\n" + "=" * 40)
            return EXIT_OK

        telegram_service.send_message(config, message)
        log.info("Đã gửi bản tin qua Telegram")
        return EXIT_OK
    except (weather_service.WeatherError, telegram_service.TelegramError) as exc:
        log.error("%s", exc)
        return EXIT_API


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # tránh log URL request của SDK
    logging.getLogger("google_genai").setLevel(logging.ERROR)  # bỏ log nhiễu "AFC is enabled", "thought_signature"
    sys.exit(run(parse_args()))


if __name__ == "__main__":
    main()
