# Weather AI Assistant (GitHub Actions + Telegram)

Mỗi sáng khoảng **08:00–08:30** (giờ Việt Nam), GitHub Actions sẽ:
1. Lấy dự báo 24 giờ tới từ WeatherAPI.com.
2. Dùng Gemini phân tích các điểm đột biến (nhiệt độ, mưa, UV) và đưa lời khuyên sức khỏe.
3. Gửi bản tin vào Telegram của bạn.

Mọi thứ chạy trên máy chủ GitHub. Bạn **không cần cài gì lên máy Mac**.

Thiết kế chi tiết nằm trong [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

---

## 1. Tạo bot Telegram

1. Mở Telegram, chat với **@BotFather** → gửi `/newbot` → đặt tên → nhận **token** (dạng `123456:ABC...`).
2. Mở chat với bot vừa tạo và **gửi một tin bất kỳ** (bắt buộc, nếu không bot không nhắn cho bạn được).
3. Chat với **@userinfobot** để lấy **Chat ID** (một dãy số).
4. Tuỳ chọn, để Telegram gợi ý lệnh: trong @BotFather gửi `/setcommands`, chọn bot, rồi gửi:
   ```
   location - Đổi địa điểm thời tiết
   ```

## 2. Lấy API key (miễn phí)

- **WeatherAPI.com:** đăng ký tại https://www.weatherapi.com/signup.aspx → đăng nhập → *Dashboard* → copy **API Key**.
- **Gemini:** vào https://aistudio.google.com → *Get API key* → *Create API key*.

## 3. Tạo repo GitHub (Private)

1. Tạo repo mới trên GitHub, chọn **Private**.
2. Đẩy **nội dung thư mục `Weather/`** làm gốc của repo (thư mục `.github/` phải nằm ở gốc repo):
   ```bash
   cd Weather
   git init
   git add .
   git status          # kiểm tra KHÔNG có file .env trong danh sách
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<tài-khoản>/<tên-repo>.git
   git push -u origin main
   ```
3. Đừng bật branch protection bắt buộc pull request cho nhánh `main`, vì workflow cần tự commit `location.json`.

## 4. Cấu hình Secrets và Variables

Trong repo: *Settings → Secrets and variables → Actions*.

**Tab Secrets** → *New repository secret*:

| Tên | Giá trị |
|---|---|
| `WEATHER_API_KEY` | Key WeatherAPI.com |
| `AI_API_KEY` | Key Gemini |
| `TELEGRAM_BOT_TOKEN` | Token từ @BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID từ @userinfobot |

**Tab Variables** → *New repository variable* (đều tuỳ chọn):

| Tên | Mặc định | Ghi chú |
|---|---|---|
| `LOCATION` | `Hanoi` | Địa điểm mặc định khi chưa đổi qua Telegram |
| `TIMEZONE` | `Asia/Ho_Chi_Minh` | |
| `AI_MODEL` | `gemini-3.8-flash` | Lỗi thì tự chuyển sang `gemini-3.6-flash` → `gemini-2.5-flash` |
| `LANGUAGE` | `vi` | |

Kiểm tra thêm *Settings → Actions → General → Workflow permissions*: chọn **Read and write permissions** nếu commit `location.json` bị từ chối.

## 5. Chạy thử

Tab **Actions** → **Weather Briefing** → **Run workflow**. Sau khoảng 1 phút, bạn sẽ nhận được tin trên Telegram. Nếu lỗi, bấm vào lần chạy để xem log.

Từ đó, workflow tự chạy lúc **08:00** mỗi ngày. GitHub có thể trễ vài phút đến khoảng 30 phút. Nếu tin hay đến sau 08:30, sửa dòng `cron` trong [.github/workflows/weather.yml](.github/workflows/weather.yml), ví dụ `"30 0 * * *"` là 07:30.

## 6. Đổi địa điểm qua Telegram

Nhắn cho bot một trong các cách sau:

| Cách | Ví dụ |
|---|---|
| **Ghim vị trí** (khuyên dùng) | 📎 → *Location* → gửi vị trí hiện tại |
| Lệnh kèm tên | `/location Da Nang` |
| Lệnh kèm tọa độ | `/location 16.05,108.20` |

- Bot **chỉ đọc tin khi workflow chạy**. Nhắn trước 08:00 thì có hiệu lực ngay sáng đó. Muốn áp dụng ngay thì bấm *Run workflow* (bạn sẽ nhận thêm một bản tin).
- Đầu bản tin luôn có dòng `📍` cho biết địa điểm đang dùng. Nếu đổi thành công sẽ có dòng `✅`, nếu không nhận ra địa điểm sẽ có dòng `⚠️` và bot giữ địa điểm cũ.
- Bot chỉ chấp nhận tin từ đúng tài khoản có `TELEGRAM_CHAT_ID`.
- Tọa độ được làm tròn khoảng 1 km rồi lưu vào `location.json` trong repo. Workflow tự commit file này với tên `github-actions[bot]`.
- Telegram chỉ giữ tin chưa đọc khoảng 24 giờ. Nếu workflow lỗi nhiều ngày liền thì hãy nhắn lại.

## 7. Chạy thử trên máy (tuỳ chọn)

Dùng được Python 3.9 có sẵn trên macOS (`/usr/bin/python3`); pip tự chọn phiên bản thư viện phù hợp. Cảnh báo `NotOpenSSLWarning` khi chạy là bình thường, không ảnh hưởng kết nối. Nếu không muốn cài gì thêm, hãy bỏ qua bước này và dùng *Run workflow*.

```bash
cd Weather
/usr/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # rồi điền key vào .env
chmod 600 .env

python main.py --dry-run                     # in bản tin ra màn hình, không gửi, không ghi file
python main.py --dry-run --no-ai             # bỏ qua Gemini
python main.py --dry-run --location "Da Nang"
python main.py                               # gửi thật qua Telegram
```

Lưu ý: chạy thật trên máy (không có `--dry-run`) cũng đọc và xác nhận tin nhắn Telegram, nên tin `/location` sẽ được xử lý ở máy thay vì trên GitHub. Sau đó hãy commit `location.json` nếu file thay đổi.

Muốn dọn sạch: xoá thư mục `venv/` và file `.env`.

## 8. Xử lý sự cố

| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| `Thiếu biến môi trường: ...` | Chưa tạo đủ Secrets ở bước 4 |
| Telegram `401` | Token sai hoặc đã bị revoke → cập nhật `TELEGRAM_BOT_TOKEN` |
| Telegram `400 chat not found` / `403` | Chưa nhắn tin cho bot, hoặc đã chặn bot, hoặc sai Chat ID |
| `getUpdates lỗi 409` | Bot đang đặt webhook → mở `https://api.telegram.org/bot<TOKEN>/deleteWebhook` |
| WeatherAPI `401` / `403` | Key sai hoặc hết quota |
| `Tất cả model Gemini đều lỗi` | Key Gemini sai hoặc hết quota; bạn vẫn nhận bản tóm tắt thô |
| Không có commit `location.json` | Kiểm tra Workflow permissions (bước 4) và branch protection |
| Lệnh `/location` không có tác dụng | Tin đã quá 24 giờ, hoặc gửi từ tài khoản khác `TELEGRAM_CHAT_ID` |
| Workflow không tự chạy | Tab Actions → kiểm tra workflow có bị *Disabled* không → bật lại |

Exit code: `0` thành công, `1` lỗi cấu hình, `2` lỗi mạng/API. GitHub sẽ gửi email khi workflow lỗi.

## 9. Tạm dừng / gỡ bỏ

- Tạm dừng: *Actions → Weather Briefing → ⋯ → Disable workflow*.
- Gỡ hẳn: xoá repo trên GitHub.
- Nếu nghi lộ key: đổi key tại WeatherAPI hoặc AI Studio, gửi `/revoke` trong @BotFather, rồi cập nhật lại Secrets.
