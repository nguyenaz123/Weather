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


def build_header(weather: dict, location: location_service.Location) -> str:
    # Các dòng này do code thêm (không qua AI); bỏ ký tự Markdown khỏi phần người dùng gõ.
    lines = [f"📍 {telegram_service.strip_markdown(weather['location']['name'])}"]
    if location.changed:
        lines.append("✅ Đã đổi địa điểm theo tin nhắn của bạn")
    if location.error:
        lines.append(f"⚠️ Không đổi được địa điểm: {telegram_service.strip_markdown(location.error)}. Giữ nguyên địa điểm cũ")
    return "\n".join(lines)


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

        message = f"{build_header(weather, location)}\n\n{body}"
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
