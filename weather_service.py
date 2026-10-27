"""Gọi WeatherAPI.com và chuẩn hoá dữ liệu dự báo 24 giờ tới."""

from __future__ import annotations

import logging
import time

import requests

from config import Config

log = logging.getLogger(__name__)

BASE_URL = "https://api.weatherapi.com/v1"
TIMEOUT = 15
RETRIES = 3
LOCATION_NOT_FOUND = 1006  # mã lỗi WeatherAPI: không tìm thấy địa điểm

# Ngưỡng phát hiện điểm đột biến (gợi ý sẵn cho AI).
TEMP_JUMP_C = 4  # chênh nhiệt trong 2 giờ
RAIN_CHANCE_HIGH = 60  # %
UV_HIGH = 8


class WeatherError(Exception):
    pass


class LocationNotFound(WeatherError):
    pass


def _get(endpoint: str, api_key: str, params: dict) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    params = {"key": api_key, **params}
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            # Thông báo lỗi của requests có thể chứa URL kèm API key.
            error = WeatherError(f"Lỗi mạng khi gọi WeatherAPI: {str(exc).replace(api_key, '***')}")
        else:
            if resp.status_code < 400:
                return resp.json()
            try:
                detail = resp.json().get("error", {})
            except ValueError:
                detail = {}
            if detail.get("code") == LOCATION_NOT_FOUND:
                raise LocationNotFound(detail.get("message", "Không tìm thấy địa điểm"))
            error = WeatherError(f"WeatherAPI trả lỗi {resp.status_code}: {detail.get('message', resp.reason)}")
            if resp.status_code < 500:
                raise error  # lỗi 4xx (key sai, hết quota...) thì thử lại cũng vô ích
        if attempt < RETRIES:
            log.warning("%s (lần %d/%d), thử lại...", error, attempt, RETRIES)
            time.sleep(2 ** attempt)
    raise error


def lookup_location(config: Config, query: str) -> dict:
    """Trả về thông tin địa điểm WeatherAPI nhận ra; raise LocationNotFound nếu không có."""
    data = _get("current.json", config.weather_api_key, {"q": query, "lang": config.language})
    return data["location"]


def format_location_name(location: dict) -> str:
    return ", ".join(part for part in (location.get("name"), location.get("country")) if part)


def fetch_forecast(config: Config, query: str) -> dict:
    # days=2 để luôn đủ 24 giờ tới khi đã qua nửa ngày.
    return _get(
        "forecast.json",
        config.weather_api_key,
        {"q": query, "days": 2, "alerts": "yes", "aqi": "no", "lang": config.language},
    )


def _clock(hour: dict) -> str:
    return hour["time"][-5:]  # "2026-10-27 14:00" -> "14:00"


def _detect_spikes(hours: list[dict]) -> list[str]:
    spikes = []

    # Nhiệt độ tăng/giảm mạnh trong 2 giờ; bỏ qua các khung chồng lấn.
    last_end = -1
    for i in range(len(hours) - 2):
        if i < last_end:
            continue
        delta = hours[i + 2]["temp_c"] - hours[i]["temp_c"]
        if abs(delta) >= TEMP_JUMP_C:
            trend = "tăng" if delta > 0 else "giảm"
            spikes.append(
                f"Nhiệt độ {trend} {abs(delta):.0f}°C từ {_clock(hours[i])} đến {_clock(hours[i + 2])}"
                f" ({hours[i]['temp_c']:.0f}°C → {hours[i + 2]['temp_c']:.0f}°C)"
            )
            last_end = i + 2

    # Các khung giờ liên tiếp có khả năng mưa cao.
    run: list[dict] = []
    for hour in hours + [None]:
        if hour is not None and hour["chance_of_rain"] >= RAIN_CHANCE_HIGH:
            run.append(hour)
            continue
        if run:
            peak = max(run, key=lambda h: h["chance_of_rain"])
            window = _clock(run[0]) if len(run) == 1 else f"{_clock(run[0])}–{_clock(run[-1])}"
            spikes.append(
                f"Khả năng mưa cao lúc {window} (tối đa {peak['chance_of_rain']}% lúc {_clock(peak)},"
                f" tổng {sum(h['precip_mm'] for h in run):.1f} mm)"
            )
            run = []

    uv_peak = max(hours, key=lambda h: h["uv"])
    if uv_peak["uv"] >= UV_HIGH:
        spikes.append(f"Chỉ số UV đạt đỉnh {uv_peak['uv']:.0f} lúc {_clock(uv_peak)}")

    return spikes


def normalize_next_24h(raw: dict) -> dict:
    """Lọc 24 giờ tới (tính từ đầu giờ hiện tại, theo giờ địa phương của địa điểm)."""
    location = raw["location"]
    now = location["localtime_epoch"]
    start = now - now % 3600

    hours = [
        {
            "time": hour["time"],
            "temp_c": hour["temp_c"],
            "feelslike_c": hour["feelslike_c"],
            "chance_of_rain": hour["chance_of_rain"],
            "precip_mm": hour["precip_mm"],
            "uv": hour["uv"],
            "humidity": hour["humidity"],
            "wind_kph": hour["wind_kph"],
            "condition": hour["condition"]["text"],
            "condition_code": hour["condition"]["code"],
            "is_day": hour["is_day"],
        }
        for day in raw["forecast"]["forecastday"]
        for hour in day["hour"]
        if start <= hour["time_epoch"] < start + 24 * 3600
    ]
    if not hours:
        raise WeatherError("WeatherAPI không trả về dữ liệu theo giờ")

    alerts = [
        {
            "headline": alert.get("headline"),
            "event": alert.get("event"),
            "severity": alert.get("severity"),
            "effective": alert.get("effective"),
            "expires": alert.get("expires"),
            "desc": (alert.get("desc") or "")[:300],
        }
        for alert in raw.get("alerts", {}).get("alert", [])
    ]

    return {
        "location": {
            "name": format_location_name(location),
            "tz_id": location["tz_id"],
            "localtime": location["localtime"],
        },
        "summary": {
            "temp_min_c": min(h["temp_c"] for h in hours),
            "temp_max_c": max(h["temp_c"] for h in hours),
            "feelslike_max_c": max(h["feelslike_c"] for h in hours),
            "max_chance_of_rain": max(h["chance_of_rain"] for h in hours),
            "total_precip_mm": round(sum(h["precip_mm"] for h in hours), 1),
            "max_uv": max(h["uv"] for h in hours),
        },
        "spikes": _detect_spikes(hours),
        "alerts": alerts,
        "hourly": hours,
    }
