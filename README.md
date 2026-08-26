# ChatGPT Gateway

Cloudflare Worker gateway cho ChatGPT/Codex upstream, cung cấp API tương thích OpenAI và giao diện quản trị mobile-first.

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
  ├── ChatGPT login
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

Sau khi deploy code mới, cần chạy toàn bộ migrations. Đặc biệt migration `0002_admin_sessions.sql` tạo session admin.

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

Ví dụ:

```text
admin
```

### Admin password

```text
ADMIN_PASSWORD
```

Dùng một mật khẩu mạnh, riêng biệt. Đây là Cloudflare Secret, không commit vào GitHub.

### Encryption key

```text
CHATGPT_TOKEN_ENCRYPTION_KEY
```

Giá trị phải là 64 ký tự hex = 32 bytes.

Không còn sử dụng `GATEWAY_ADMIN_KEY` cho giao diện quản trị.

## 4. Deploy migration

Nếu dùng Wrangler:

```bash
npx wrangler d1 migrations apply chatgpt-gateway --remote
```

Nếu chỉ dùng điện thoại, mở Cloudflare Dashboard → D1 → `chatgpt-gateway` và chạy migration bằng D1 Console nếu Dashboard hỗ trợ thao tác SQL của database.

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
Device login
  ↓
Mở trang đăng nhập ChatGPT
  ↓
Nhập user code
  ↓
Xác nhận tài khoản
  ↓
Gateway tự polling
  ↓
Account Active
```

Không nhập email/password ChatGPT vào Gateway.

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

## 18. Sau khi đổi sang Admin Login

Xóa Secret cũ nếu còn:

```text
GATEWAY_ADMIN_KEY
```

Không cần dùng nó nữa.

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
4. Tạo session thành công
5. Đăng nhập ChatGPT
6. Account Active
7. Chat
8. Streaming
9. Web Search
10. Image
11. Image Edit
12. /v1/usage
```

## 20. License

MIT
