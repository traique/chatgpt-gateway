# ChatGPT Gateway

Cloudflare Worker gateway cho ChatGPT/Codex upstream, cung cấp API tương thích OpenAI và giao diện quản trị mobile-first.

> **Lưu ý:** ChatGPT/Codex authentication và backend endpoint được thiết kế cho Codex và có thể thay đổi. Gateway không phải OpenAI Public API.

## Chức năng

- Chat / Responses API / SSE streaming
- Web Search
- GPT Image generation / editing
- Đăng nhập quản trị bằng username + password
- Session admin `HttpOnly + Secure + SameSite=Lax`, TTL 12 giờ
- Đăng nhập ChatGPT bằng giao diện web trên điện thoại
- Credential ChatGPT xử lý phía server
- D1 cho account/session/usage
- Rate limit
- Usage/latency metrics
- Retry/backoff

## Kiến trúc

```text
Điện thoại
  ↓
/auth
  ↓
Admin username + password
  ↓
HttpOnly session cookie
  ↓
Cloudflare Worker
  ├── ChatGPT device login
  ├── Account management
  ├── Chat / Responses
  ├── Web Search
  └── Image
```

## 1. Cloudflare Worker

Kết nối GitHub repository:

```text
https://github.com/traique/chatgpt-gateway
```

Branch:

```text
main
```

## 2. D1

Tạo D1 database tên:

```text
chatgpt-gateway
```

`wrangler.toml` phải chứa đúng `database_id` của database.

Schema gồm:

```text
accounts
login_sessions
admin_sessions
usage_events
rate_limits
```

## 3. Secrets

### API key cho ứng dụng

```text
GATEWAY_API_KEY
```

Dùng cho Telegram, Open WebUI hoặc client API.

### Admin username

```text
ADMIN_USERNAME
```

### Admin password

```text
ADMIN_PASSWORD
```

Dùng mật khẩu mạnh, riêng biệt. Đây là Cloudflare Secret, không commit vào GitHub.

### Encryption key

```text
CHATGPT_TOKEN_ENCRYPTION_KEY
```

Giá trị phải là 64 ký tự hex = 32 bytes.

Không còn sử dụng `GATEWAY_ADMIN_KEY` cho giao diện quản trị.

## 4. Migration D1

Repository có các migration:

```text
migrations/0001_auth.sql
migrations/0002_admin_sessions.sql
migrations/0003_schema_repair.sql
```

`0003_schema_repair.sql` là migration idempotent để sửa các database đã deploy nhưng thiếu một hoặc nhiều bảng. Có thể chạy lại an toàn nhờ `CREATE TABLE IF NOT EXISTS` và `CREATE INDEX IF NOT EXISTS`.

### Nếu dùng Wrangler

```bash
npx wrangler d1 migrations apply chatgpt-gateway --remote
```

### Nếu chỉ dùng điện thoại

Cloudflare Dashboard → **D1 → `chatgpt-gateway` → Console**.

Nếu database đang thiếu schema, chạy SQL trong `migrations/0003_schema_repair.sql`.

Kiểm tra:

```sql
SELECT name
FROM sqlite_master
WHERE type = 'table'
ORDER BY name;
```

Phải có:

```text
accounts
admin_sessions
login_sessions
rate_limits
usage_events
```

## 5. Deploy Worker

Cloudflare → Workers & Pages → `chatgpt-gateway` → Deployments → deploy commit mới nhất.

Kiểm tra:

```text
https://YOUR-WORKER.workers.dev/health
```

Kết quả:

```json
{"ok":true,"service":"chatgpt-gateway"}
```

## 6. Đăng nhập Admin trên điện thoại

Mở:

```text
https://YOUR-WORKER.workers.dev/auth
```

Nhập:

```text
Tên đăng nhập: ADMIN_USERNAME
Mật khẩu: ADMIN_PASSWORD
```

Bấm **Đăng nhập**.

Gateway tạo session server-side và trả cookie:

```text
cg_admin_session
```

Cookie có:

```text
HttpOnly
Secure
SameSite=Lax
Max-Age=43200
```

Trình duyệt không cần lưu admin password hay admin token trong `sessionStorage`.

## 7. Đăng nhập ChatGPT

Sau khi đăng nhập Admin:

```text
/auth
  ↓
Bắt đầu đăng nhập
  ↓
Gateway tạo device code
  ↓
Mở https://auth.openai.com/codex/device
  ↓
Nhập user code
  ↓
OpenAI xác nhận thiết bị
  ↓
Gateway polling trạng thái
  ↓
OAuth token exchange
  ↓
Credential mã hóa trong D1
  ↓
Account Active
```

Gateway không yêu cầu email/password ChatGPT.

Device login sử dụng các endpoint mà Codex hiện dùng cho device authorization và token exchange. Đây là giao thức dịch vụ Codex, không phải API authentication contract công khai của OpenAI. Các endpoint có thể thay đổi.

## 8. Quản lý ChatGPT account

UI hiển thị trạng thái account:

```text
primary       Active
backup        Active
old-account   Disabled
```

Không hiển thị:

```text
access_token
refresh_token
id_token
```

## 9. API authentication

API client dùng riêng:

```http
Authorization: Bearer YOUR_GATEWAY_API_KEY
```

Không dùng username/password Admin cho API.

## 10. Chat

```text
POST /v1/chat/completions
```

Ví dụ body:

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [
    {"role": "user", "content": "Xin chào"}
  ],
  "stream": true
}
```

## 11. Web Search

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [
    {"role": "user", "content": "Tìm tin tức mới nhất về AI."}
  ],
  "web_search": true
}
```

## 12. Image

```text
POST /v1/images/generations
```

```json
{
  "model": "chatgpt-gpt-image-2",
  "prompt": "A cinematic photorealistic portrait in Saigon at golden hour"
}
```

## 13. Image Edit

```text
POST /v1/images/edits
```

## 14. Responses API

```text
POST /v1/responses
```

Hỗ trợ input, instructions, streaming và web search theo adapter hiện tại.

## 15. Models

```text
GET /v1/models
```

## 16. Usage

```text
GET /v1/usage
```

Dùng `GATEWAY_API_KEY`.

Metrics chỉ lưu metadata như route, model, status, latency và account reference; không lưu prompt/response.

## 17. Bảo mật

- Admin authentication dùng username/password + server-side session.
- Không lưu admin password trong browser storage.
- Không trả OAuth credential về browser.
- Không commit secrets vào GitHub.
- Không log access token/refresh token.
- Không log prompt/response.
- API key và Admin login là hai lớp credential độc lập.
- Dùng HTTPS.

## 18. Secrets sau khi đổi sang Admin Login

Xóa Secret cũ nếu còn:

```text
GATEWAY_ADMIN_KEY
```

Giữ:

```text
GATEWAY_API_KEY
ADMIN_USERNAME
ADMIN_PASSWORD
CHATGPT_TOKEN_ENCRYPTION_KEY
```

## 19. Kiểm tra deployment

```text
1. /health
2. /auth
3. Đăng nhập Admin
4. Kiểm tra admin session
5. Bắt đầu ChatGPT device login
6. Xác nhận device code
7. Account Active
8. Chat
9. Streaming
10. Web Search
11. Image
12. Image Edit
13. /v1/usage
```

## License

MIT
