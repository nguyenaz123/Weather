# Python Weather AI Assistant (GitHub Actions + Telegram) — Thiết kế cấu trúc

Công cụ chạy **100% trên GitHub Actions** (không phụ thuộc máy Mac): lấy dự báo 24h → Gemini phân tích điểm đột biến & lời khuyên sức khỏe → gửi Telegram. Tin mong muốn đến lúc **08:30** sáng (giờ Việt Nam); workflow được lên lịch **08:00** để chừa thời gian trễ của GitHub.

Bạn có thể **đổi địa điểm bằng cách nhắn cho bot** (ghim vị trí Telegram hoặc lệnh `/location`); bot đọc tin nhắn vào mỗi lần chạy buổi sáng.

**Quyết định đã chốt:** Nền tảng = GitHub Actions (repo **private**) · Weather API = WeatherAPI.com · AI = Google Gemini · Telegram `parse_mode` = HTML (có fallback) · Múi giờ = Asia/Ho_Chi_Minh · Địa điểm mặc định = Hà Nội (`Hanoi`) · Model AI = `gemini-3.8-flash` (free tier, dự phòng `gemini-3.6-flash` → `gemini-2.5-flash`) · Đổi địa điểm = đọc tin nhắn lúc chạy (`getUpdates`), lưu vào `location.json` rồi commit ngược vào repo.

---

## 1. Cây thư mục

```
Weather/                       # = gốc của repo GitHub
├── .github/
│   └── workflows/
│       └── weather.yml        # Lịch chạy 08:00 VN + chạy tay + commit location.json
├── main.py                    # Điều phối: Location -> Fetch -> AI -> Notify
├── location_service.py        # Đọc tin nhắn Telegram, kiểm tra & lưu địa điểm
├── weather_service.py         # Gọi WeatherAPI.com, chuẩn hoá dữ liệu 24h
├── ai_service.py              # Gửi prompt tới Gemini, nhận bản tin
├── telegram_service.py        # Gửi/nhận tin Telegram (sendMessage, getUpdates)
├── config.py                  # Đọc + kiểm tra biến môi trường
├── location.json              # Địa điểm hiện tại (workflow tự cập nhật + commit)
├── .env.example               # Mẫu biến môi trường (chỉ dùng khi chạy thử trên máy)
├── .gitignore                 # Bỏ .env, venv/, __pycache__/
├── requirements.txt           # requests, python-dotenv, google-genai
└── README.md                  # Hướng dẫn: tạo repo, Secrets, bot, chạy thử, đổi địa điểm
```

Đã **bỏ** so với phiên bản macOS: `com.user.weatherbot.plist`, `cleanup.py`, log trên máy, chống gửi trùng bằng file. Lý do: mỗi lần chạy là một máy ảo mới, xong là bị huỷ.

---

## 2. Biến môi trường & GitHub Secrets

Trên GitHub: *Settings → Secrets and variables → Actions*. Khi chạy thử trên máy: đặt trong `.env`.

| Biến | Loại trên GitHub | Bắt buộc | Mô tả | Ví dụ |
|---|---|---|---|---|
| `WEATHER_API_KEY` | **Secret** | ✅ | Key WeatherAPI.com | `abc123...` |
| `AI_API_KEY` | **Secret** | ✅ | Key Google AI Studio (Gemini) | `AIza...` |
| `TELEGRAM_BOT_TOKEN` | **Secret** | ✅ | Token từ @BotFather | `123456:ABC...` |
| `TELEGRAM_CHAT_ID` | **Secret** | ✅ | ID từ @userinfobot; **cũng là danh tính duy nhất được phép đổi địa điểm** | `987654321` |
| `LOCATION` | Variable | ✅ | Địa điểm **mặc định / dự phòng** (dùng khi chưa có `location.json`) | `Hanoi` |
| `TIMEZONE` | Variable | ❌ | Múi giờ IANA (mặc định `Asia/Ho_Chi_Minh`) | `Asia/Ho_Chi_Minh` |
| `AI_MODEL` | Variable | ❌ | Model Gemini chính (mặc định `gemini-3.8-flash`) | `gemini-3.8-flash` |
| `LANGUAGE` | Variable | ❌ | Ngôn ngữ bản tin (mặc định `vi`) | `vi` |

Thứ tự ưu tiên địa điểm: **`location.json`** (nếu có) > biến `LOCATION`.

---

## 3. Luồng chạy

```
GitHub cron (01:00 UTC = 08:00 VN)  ──hoặc──  bấm "Run workflow" (chạy tay)
        │
        ▼
  weather.yml: checkout → setup-python (cache pip) → pip install → python main.py
        │
        ▼
    main.py ──► config.load_config()           # fail-fast nếu thiếu biến
        │
        ├─► location_service.resolve_location()
        │        ├─ getUpdates: đọc tin chưa xử lý, CHỈ lấy từ TELEGRAM_CHAT_ID
        │        ├─ tìm tin mới nhất là ghim vị trí hoặc /location <...>
        │        ├─ kiểm tra hợp lệ với WeatherAPI -> ghi location.json
        │        └─ xác nhận đã đọc (getUpdates offset) để không xử lý lại
        │
        ├─► weather_service.fetch_forecast()   # JSON thô WeatherAPI theo địa điểm hiện tại
        │        └─► normalize_next_24h()      # list 24 bản ghi theo giờ + alerts
        │
        ├─► ai_service.generate_briefing()     # prompt + data -> HTML (đã lọc thẻ)
        │
        └─► telegram_service.send_message()    # đầu tin: 📍 địa điểm + dòng tóm tắt; cuối tin: bảng theo giờ thu gọn
        │
        ▼
  weather.yml (bước cuối, chạy cả khi main lỗi): nếu location.json đổi -> git commit + push
```

- Lỗi bất kỳ bước nào: ghi ra log của job và thoát mã ≠ 0 → GitHub gửi email "workflow failed" cho bạn.
- Nếu AI lỗi: gửi bản tóm tắt thô (nhiệt độ max/min, % mưa, UV) để vẫn có thông báo.
- Nếu đọc tin nhắn (`getUpdates`) lỗi: **không làm hỏng bản tin**, dùng địa điểm đã lưu và ghi cảnh báo trong log.

---

## 4. Workflow `.github/workflows/weather.yml` (dự kiến)

```yaml
name: Weather Briefing

on:
  schedule:
    - cron: "0 1 * * *"      # 01:00 UTC = 08:00 giờ Việt Nam (GitHub dùng UTC)
  workflow_dispatch: {}       # cho phép bấm chạy tay để thử / áp dụng địa điểm mới ngay

permissions:
  contents: write             # chỉ để commit location.json

concurrency:
  group: weather-briefing
  cancel-in-progress: false

jobs:
  send:
    runs-on: ubuntu-latest
    timeout-minutes: 5        # chống treo, tiết kiệm phút miễn phí
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python main.py
        env:
          WEATHER_API_KEY: ${{ secrets.WEATHER_API_KEY }}
          AI_API_KEY: ${{ secrets.AI_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          LOCATION: ${{ vars.LOCATION }}
          TIMEZONE: ${{ vars.TIMEZONE }}
          AI_MODEL: ${{ vars.AI_MODEL }}
          LANGUAGE: ${{ vars.LANGUAGE }}
      - name: Commit location.json nếu có thay đổi
        if: always()
        run: |
          if [ -n "$(git status --porcelain location.json)" ]; then
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add location.json
            git commit -m "chore: update location"
            git push
          fi
```

Dùng `actions/checkout@v7`, `actions/setup-python@v7` (bản major mới nhất, đã kiểm tra 10/2026). Có thể ghim bằng commit SHA. `LOCATION` mặc định `Hanoi` nếu chưa tạo Variable.

**Về commit tự động:**
- Commit/push **thẳng lên nhánh chính** bằng `GITHUB_TOKEN`; **không có PR, không có merge**. Người commit hiển thị là `github-actions[bot]`.
- Chỉ commit khi `location.json` thực sự đổi (đa số ngày là không có commit).
- Commit do `GITHUB_TOKEN` tạo ra **không kích hoạt thêm workflow**, nên không bị lặp vô hạn.
- Nếu bật branch protection bắt buộc PR cho nhánh chính thì push sẽ bị chặn → với repo cá nhân đừng bật. Nếu push lỗi, bản tin vẫn đã gửi; địa điểm sẽ được đọc lại từ Telegram ở lần chạy sau (nếu tin còn trong 24h).
- Cần kiểm tra *Settings → Actions → General → Workflow permissions* cho phép ghi (nếu tài khoản/tổ chức giới hạn).

**Về giờ chạy:**
- 08:00 VN = 01:00 UTC (Việt Nam UTC+7, không có giờ mùa hè).
- GitHub không đảm bảo đúng phút: thường trễ vài phút, giờ cao điểm có thể 15–30 phút. Cộng thêm ~20–30 giây chạy script → tin dự kiến đến khoảng **08:05–08:30**.
- Nếu thực tế hay trễ quá 08:30, chỉnh cron sớm hơn (vd `30 0 * * *` = 07:30 VN). Không nên đặt đúng 08:30 vì sẽ trễ thành ~08:45.
- Phút `:00` rất đông của GitHub; có thể đổi sang `7 1 * * *` (08:07) để giảm trễ.

---

## 5. Chi tiết từng module

### 5.1 `config.py`
- `load_dotenv()` chỉ để chạy thử trên máy; trên GitHub biến lấy trực tiếp từ môi trường (`.env` không tồn tại, không lỗi).
- `dataclass Config(frozen=True)` + `load_config() -> Config`: kiểm tra biến bắt buộc, gom danh sách biến thiếu vào một `ConfigError`.
- Biến rỗng (Variable chưa tạo trên GitHub trả về chuỗi rỗng) được coi như chưa đặt và dùng giá trị mặc định.
- Không bao giờ in giá trị key/token ra log.

### 5.2 `location_service.py` — Đổi địa điểm qua Telegram

**Cách bạn đổi địa điểm (nhắn cho bot):**

| Cách | Thao tác | Ghi chú |
|---|---|---|
| **Ghim vị trí (khuyên dùng)** | Telegram: 📎 → *Location* → gửi vị trí | Telegram gửi sẵn lat/lon, chính xác, không lo gõ sai hay trùng tên |
| **Lệnh kèm tên** | `/location Da Nang` | Gõ không dấu hoặc có dấu đều được, WeatherAPI tự nhận |
| **Lệnh kèm tọa độ** | `/location 16.05,108.20` | Dạng `lat,lon` |
| Menu gợi ý lệnh | Cài `/setcommands` ở @BotFather: `location - Đổi địa điểm thời tiết` | Chỉ gợi ý tên lệnh; phần địa điểm vẫn tự gõ |

**Thời điểm có hiệu lực:** bot chỉ đọc tin khi workflow chạy. Nhắn **trước 08:00** → áp dụng ngay sáng đó; nhắn sau đó → áp dụng sáng hôm sau. Muốn áp dụng ngay: tab *Actions → Run workflow* (sẽ gửi thêm 1 bản tin, chủ ý).

**Logic `resolve_location(config) -> Location`:**
1. Đọc `location.json` (nếu có); nếu không có thì dùng `config.location` (biến `LOCATION`).
2. Gọi `getUpdates` (timeout ngắn, không long-poll) lấy các tin chưa xử lý.
3. **Lọc bảo mật:** chỉ giữ tin có `message.chat.id == TELEGRAM_CHAT_ID` **và** `message.from.id == TELEGRAM_CHAT_ID`; bỏ qua mọi tin khác (kể cả từ nhóm hay người lạ).
4. Lấy tin **mới nhất** là một trong:
   - `message.location` → `query = "lat,lon"`
   - text bắt đầu bằng `/location <nội dung>` → `query = nội dung`
5. Làm sạch đầu vào: cắt tối đa 100 ký tự, bỏ ký tự điều khiển; tọa độ phải đúng khoảng (`lat ∈ [-90, 90]`, `lon ∈ [-180, 180]`).
6. **Kiểm tra hợp lệ** bằng WeatherAPI (`search.json?q=<query>` cho tên, hoặc một lần gọi forecast cho tọa độ). Không tìm thấy → **giữ địa điểm cũ**, ghi nhận lỗi để báo trong bản tin sáng.
7. Hợp lệ → ghi `location.json`:
   ```json
   {
     "query": "16.05,108.20",
     "display_name": "Da Nang, Vietnam",
     "source": "telegram_pin",
     "updated_at": "2026-01-01T07:55:00+07:00"
   }
   ```
   Tọa độ từ ghim vị trí được **làm tròn 2 chữ số thập phân (~1 km)** trước khi lưu, để không ghi vị trí chính xác của nhà vào repo.
8. Gọi `getUpdates` lại với `offset = update_id cuối + 1` để xác nhận đã đọc (không xử lý lại).
9. Trả về `Location(query, display_name, changed: bool, error: str | None)`.

**Hiển thị:** đầu mỗi bản tin luôn có dòng `📍 <display_name>`; nếu vừa đổi thì thêm `✅ Đã đổi địa điểm sang ...`; nếu thất bại thì thêm `⚠️ Không nhận ra "<...>", giữ nguyên <địa điểm cũ>`. Các dòng này do **code** thêm vào, không nhờ AI. Vì địa điểm luôn hiện ở đầu tin nên không cần lệnh `/where`.

**Giới hạn:**
- Telegram chỉ giữ tin chưa đọc khoảng **24 giờ**; nếu workflow lỗi liên tiếp 2 ngày, lệnh có thể mất → nhắn lại.
- `getUpdates` không dùng được nếu bot đang đặt webhook (ta không đặt webhook).
- Chưa có phản hồi tức thì khi bạn nhắn (cần dịch vụ luôn bật như Cloudflare Workers; **ngoài phạm vi hiện tại**, có thể nâng cấp sau).
- Chỉ nhận vị trí tĩnh; vị trí trực tiếp (live location) và nút bấm chọn thành phố chưa hỗ trợ.

### 5.3 `weather_service.py`
- Endpoint: `GET https://api.weatherapi.com/v1/forecast.json`
  - params: `key`, `q=<location.query>`, `days=2`, `alerts=yes`, `aqi=no`, `lang=vi`.
  - `days=2` để đủ 24h tiếp theo khi qua nửa đêm.
- `fetch_forecast(config, location) -> dict`: `requests.get` với `timeout=15`, retry 3 lần (backoff) cho lỗi mạng/5xx.
- `normalize_next_24h(raw, tz) -> dict`: gộp `forecastday[0].hour + forecastday[1].hour`, lọc từ giờ hiện tại đến +24h theo `TIMEZONE` (máy chủ GitHub chạy UTC nên **phải** quy đổi múi giờ rõ ràng). Khi người dùng ở nơi khác múi giờ, ưu tiên `tz_id` WeatherAPI trả về cho địa điểm đó.
- Trường mỗi giờ:

| Trường chuẩn hoá | Nguồn WeatherAPI |
|---|---|
| `time` | `time` |
| `temp_c`, `feelslike_c` | `temp_c`, `feelslike_c` |
| `chance_of_rain`, `precip_mm` | `chance_of_rain`, `precip_mm` |
| `uv` | `uv` |
| `humidity`, `wind_kph` | `humidity`, `wind_kph` |
| `condition` | `condition.text` |

- Kèm theo: `location`, `summary` (min/max temp, max chance_of_rain, max UV), `alerts` (từ `alerts.alert[]`, rỗng nếu không có).
- Tuỳ chọn: tính sẵn "spike" (chênh nhiệt ≥ 4°C/2h, rain ≥ 60%, UV ≥ 8) để gợi ý cho AI, giảm sai sót tính toán của LLM.

### 5.4 `ai_service.py`
- SDK `google-genai`: `genai.Client(api_key=...)`, `client.models.generate_content(model, contents, config=system_instruction)`.
- `build_prompt(weather: dict) -> str`: nhúng JSON đã chuẩn hoá (compact) + giờ hiện tại (theo múi giờ của địa điểm) + tên địa điểm **do WeatherAPI trả về** (không đưa chuỗi gõ tay của người dùng thẳng vào prompt).
- `generate_briefing(config, weather) -> str`: gọi model, retry khi lỗi tạm thời (429/5xx), `temperature≈0.4`.
- **Chọn model (free tier):** mặc định `gemini-3.8-flash` (Flash mới nhất, miễn phí, bản stable). Nếu model chính lỗi (404 model không tồn tại/đã ngừng, hoặc 429 hết quota) thì tự thử lần lượt `gemini-3.6-flash` → `gemini-2.5-flash` rồi mới dùng bản tóm tắt thô. Danh sách dự phòng nằm trong `config.py`, đổi được mà không sửa logic.
- Không dùng `gemini-4-argon` và `gemini-3.1-pro-preview`: **không có free tier**. `gemini-2.5-pro` có free tier nhưng là model suy luận nặng, không cần cho bản tin ngắn mỗi ngày một lần. Mỗi ngày chỉ 1 request nên chắc chắn nằm trong hạn mức miễn phí (hạn mức cụ thể xem tại Google AI Studio; có thể thay đổi).
- **System instruction** (giữ nguyên yêu cầu gốc):
  > Bạn là một trợ lý thời tiết cá nhân thông minh và chu đáo. Hãy phân tích dữ liệu thời tiết 24h tới và tạo một bản tin buổi sáng ngắn gọn, trực quan, dễ đọc trên điện thoại:
  > 1. **Tổng quan ngắn:** thời tiết chủ đạo, nhiệt độ cao nhất/thấp nhất, khả năng mưa.
  > 2. **Điểm đột biến (Spikes/Alerts):** nêu chính xác khung giờ thay đổi đột ngột (nhiệt độ, mưa, UV).
  > 3. **Cảnh báo sức khỏe & vật dụng cần mang:** gợi ý cụ thể dựa trên các điểm đột biến (ô/áo mưa, áo chống nắng, kính râm, khẩu trang, uống nước).
  > 4. **Định dạng:** HTML của Telegram + emoji (☀️ 🌧️ ☂️ 🕶️ 🏍️).
- Ràng buộc bổ sung: chỉ dùng thẻ `<b>`, `<i>` và tối đa một `<blockquote>` (gạch đầu dòng `•`), không Markdown/bảng/liên kết; output được escape lại, chỉ giữ các thẻ cho phép (`to_telegram_html`); tối đa ~1500 ký tự; chỉ dựa vào dữ liệu được cung cấp, không bịa số.

### 5.5 `telegram_service.py`
- **Gửi:** `POST https://api.telegram.org/bot<TOKEN>/sendMessage` với `chat_id`, `text`, `parse_mode="HTML"`, `disable_web_page_preview=true`.
- `send_message(config, text) -> None`:
  1. Thử gửi HTML.
  2. Nếu API trả `400` với mô tả chứa `can't parse entities` → gửi lại **plain text** (bỏ `parse_mode`) sau khi bỏ thẻ HTML và giải mã `&amp;`, `&lt;`...
  3. Lỗi khác (401 token sai, 403 bot bị chặn, 429) → raise `TelegramError` kèm mô tả.
- Tin dài hơn 4096 ký tự: tách theo dòng thành nhiều tin; thẻ đang mở ở chỗ cắt được đóng lại và mở lại ở tin sau.
- **Nhận:** `get_updates(config, offset=None) -> list[dict]` (`GET .../getUpdates`, `timeout=0`, `allowed_updates=["message"]`) và hàm xác nhận offset; dùng bởi `location_service.py`.
- Che token trong mọi thông báo lỗi (URL chứa token). GitHub tự che Secrets trong log nhưng không dựa hoàn toàn vào đó.

### 5.6 `main.py`
- `main()`: cấu hình `logging` ra stdout (không cần ghi file) → `load_config` → `resolve_location` → fetch → AI → ghép đầu tin (📍 + thông báo đổi/lỗi) → send.
- Tham số CLI:
  - `--dry-run`: chạy toàn bộ nhưng **in kết quả ra terminal, không gửi Telegram, không ghi `location.json`, không xác nhận offset**.
  - `--no-ai`: bỏ qua AI, gửi bản tóm tắt thô (kiểm tra weather + telegram).
  - `--location "<tên hoặc lat,lon>"`: ép địa điểm khi chạy thử (không ghi file).
- Exit code: `0` thành công, `1` lỗi cấu hình, `2` lỗi mạng/API.
- Không cần chống gửi trùng: mỗi lịch chỉ kích hoạt một lần. Bấm chạy tay trong ngày sẽ nhận thêm một tin (chủ ý).

### 5.7 `requirements.txt`
```
requests>=2.32,<3
python-dotenv>=1.0,<2
google-genai>=1.40,<3
```
GitHub dùng Python 3.12 nên cài bản mới nhất (`google-genai` 2.x). Trên Mac dùng Python 3.9 có sẵn; pip tự chọn `google-genai` 1.x tương thích (API dùng trong code giống nhau).

---

## 6. Nội dung `README.md` (dự kiến)

1. **Tổng quan:** tool chạy trên GitHub Actions, không cài gì lên máy.
2. **Tạo bot Telegram:** chat `@BotFather` → `/newbot` → lấy token; **nhắn một tin bất kỳ cho bot của bạn** (bắt buộc); chat `@userinfobot` để lấy `Chat ID`. Tuỳ chọn: `/setcommands` → `location - Đổi địa điểm thời tiết`.
3. **Lấy API key:**
   - WeatherAPI.com: đăng ký tại weatherapi.com → Dashboard → API Key (có gói free).
   - Gemini: aistudio.google.com → *Get API key* (có free tier).
4. **Tạo repo GitHub:** chọn **Private**; đẩy mã nguồn lên (kiểm tra `.env` không bị commit). Đừng bật branch protection bắt buộc PR cho nhánh chính.
5. **Cấu hình:** *Settings → Secrets and variables → Actions* → thêm 4 Secrets và các Variables ở mục 2; kiểm tra *Settings → Actions → General → Workflow permissions* cho phép ghi.
6. **Chạy thử:** tab *Actions* → *Weather Briefing* → *Run workflow*; kiểm tra tin Telegram và log.
7. **Đổi địa điểm:** nhắn bot ghim vị trí, hoặc `/location Da Nang`; có hiệu lực ở lần chạy kế tiếp (nhắn trước 08:00 để áp dụng sáng đó, hoặc bấm *Run workflow*).
8. **Chạy thử trên máy (tuỳ chọn):** `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cp .env.example .env` → `python main.py --dry-run`.
9. **Xử lý sự cố:** lỗi Telegram 401/403/400, hết quota Gemini, workflow bị tắt, tin đến trễ, push `location.json` bị chặn, lệnh `/location` không có hiệu lực (tin quá 24h hoặc gửi sai tài khoản).
10. **Tạm dừng / gỡ:** *Actions → Weather Briefing → ⋯ → Disable workflow*, hoặc xoá repo; đổi/huỷ key nếu nghi bị lộ.

---

## 7. Chi phí & giới hạn của GitHub Actions
- Mỗi lần chạy ~20–60 giây (tính tròn lên 1 phút) → ~30 phút/tháng, rất nhỏ so với hạn mức miễn phí của repo private. **Hạn mức có thể thay đổi, hãy kiểm tra trên trang GitHub.**
- **Repo public:** GitHub tự tắt workflow theo lịch sau 60 ngày không có hoạt động; dùng **repo private** để tránh (nếu bị tắt, vào tab Actions bật lại). Mỗi lần đổi địa điểm có commit cũng được tính là hoạt động.
- Lịch có thể trễ hoặc hiếm khi bị bỏ qua khi GitHub quá tải; cần chính xác tuyệt đối thì phải dùng dịch vụ có SLA (ngoài phạm vi miễn phí).
- Nếu tài khoản GitHub bị khoá hoặc hết hạn mức, bản tin dừng; email "workflow failed" là tín hiệu để phát hiện.

---

## 8. Bảo mật
- Repo **private**; không commit `.env` (có trong `.gitignore`).
- Key/token chỉ nằm trong **GitHub Secrets**, truyền vào bước chạy qua `env`; không `echo`, không in ra log.
- **Chỉ nhận lệnh từ đúng `TELEGRAM_CHAT_ID`** (kiểm tra cả `chat.id` và `from.id`); tin từ người lạ bị bỏ qua. Nếu không có bước này, bất kỳ ai tìm ra tên bot đều đổi được địa điểm của bạn.
- Đầu vào địa điểm được làm sạch và giới hạn độ dài; tên đưa vào prompt AI là tên do WeatherAPI trả về, giảm rủi ro prompt injection từ tin nhắn.
- `permissions: contents: write` chỉ để commit `location.json`; bước commit chỉ `git add location.json`, không thêm file khác.
- `location.json` chứa địa điểm (tọa độ làm tròn ~1 km); repo private nên chỉ bạn thấy. Nếu muốn che hoàn toàn, dùng tên thành phố/quận thay vì ghim vị trí.
- Không bật chạy workflow cho pull request từ fork; workflow chỉ kích hoạt bằng `schedule` và `workflow_dispatch`.
- Chỉ dùng action chính chủ của GitHub (`actions/checkout`, `actions/setup-python`).
- Dữ liệu gửi cho bên thứ ba: địa điểm + dữ liệu thời tiết (WeatherAPI, Gemini) và bản tin (Telegram). Telegram bot không mã hoá đầu cuối, đừng đưa thông tin nhạy cảm vào bản tin.
- Nếu nghi lộ key: revoke/đổi key ở nhà cung cấp (Telegram: `/revoke` trong @BotFather), cập nhật lại Secret.

---

## 9. Tác động tới máy Mac
Không có gì được cài hoặc chạy nền trên Mac.

| Hoạt động | Tác động lên Mac |
|---|---|
| Bản tin hằng ngày, đọc tin nhắn, commit `location.json` | **Không** (tất cả chạy trên máy chủ GitHub) |
| Đẩy mã nguồn lên GitHub | Dùng `git`, chỉ đọc thư mục dự án; nhớ `git pull` để lấy `location.json` mới nếu làm việc trên máy |
| Chạy thử `--dry-run` (tuỳ chọn) | Tạo `venv/` trong thư mục dự án, gọi mạng; xoá `venv/` là sạch |
| `launchd`, `~/Library/*`, cài đặt hệ thống | **Không đụng tới** |

Nguyên tắc cho code: không dùng `shell=True`, `os.system`, `sudo`; không ghi file ngoài thư mục dự án; không in secrets.

---

## 10. Thứ tự triển khai đề xuất
1. `config.py`, `.env.example`, `requirements.txt`, `.gitignore`
2. `weather_service.py` (+ in thử JSON đã chuẩn hoá)
3. `telegram_service.py` (gửi + nhận) (+ `--no-ai`)
4. `location_service.py` (+ test lọc `chat_id`, phân tích ghim vị trí và `/location`, địa điểm không hợp lệ)
5. `ai_service.py` (+ `--dry-run`)
6. `main.py` hoàn chỉnh (exit code, múi giờ, ghép đầu tin)
7. `.github/workflows/weather.yml` + `README.md`
8. Bạn tạo repo private + Secrets/Variables → bấm *Run workflow* để thử
9. Thử đổi địa điểm bằng ghim vị trí và `/location`, bấm *Run workflow* kiểm tra commit `location.json`
10. Quan sát 2–3 sáng đầu để chỉnh giờ cron cho tin đến sát 08:30
11. Quét mã nguồn kiểm tra không lộ secrets và không có lệnh hệ thống nguy hiểm
