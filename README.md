# ChatGPT Gateway

FastAPI gateway chạy trên Faable, kết nối ChatGPT/Codex upstream và lưu account/session data trên Supabase PostgreSQL.

> ChatGPT/Codex authentication và backend endpoint được thiết kế cho Codex và có thể thay đổi. Gateway không phải OpenAI Public API.

## Chức năng

- Chat / Responses API / SSE streaming
- Web Search
- GPT Image generation / editing
- Admin login bằng username + password
- HttpOnly session cookie
- ChatGPT device login
- Credential ChatGPT mã hóa phía server
- Supabase PostgreSQL cho account/session data
- Rate limit

## Kiến trúc

```text
Client
  ↓
Faable / FastAPI
  ├── /auth
  ├── /v1/chat/completions
  ├── /v1/responses
  ├── /v1/images/generations
  └── /v1/images/edits
          ↓
     ChatGPT/Codex
          
Faable / FastAPI
          ↓
Supabase PostgreSQL
```

## Environment variables

```text
GATEWAY_API_KEY
ADMIN_USERNAME
ADMIN_PASSWORD
SESSION_SECRET
CHATGPT_TOKEN_ENCRYPTION_KEY
DATABASE_URL
CHATGPT_AUTH_BASE_URL
CHATGPT_CODEX_ENDPOINT
CHATGPT_OAUTH_CLIENT_ID
CHATGPT_CODEX_CLIENT_VERSION
```

`DATABASE_URL` dùng connection string PostgreSQL của Supabase.

`CHATGPT_TOKEN_ENCRYPTION_KEY` phải là Fernet key hợp lệ. Không commit secrets vào GitHub.

## Deploy Faable

Faable chạy ứng dụng FastAPI bằng Uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
```

Docker image hiện tại sử dụng `faable/app.py` làm application entrypoint.

## Supabase

Gateway tự kiểm tra kết nối database khi khởi động và tạo các bảng cần thiết nếu chưa tồn tại:

```text
chatgpt_accounts
device_login_sessions
```

Có thể kiểm tra bằng:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

## Admin login

Mở:

```text
/auth
```

Đăng nhập bằng:

```text
ADMIN_USERNAME
ADMIN_PASSWORD
```

Session được lưu bằng HttpOnly cookie và có TTL 12 giờ.

## ChatGPT device login

```text
/auth
  ↓
/auth/device/start
  ↓
https://auth.openai.com/codex/device
  ↓
Nhập user code
  ↓
/auth/device/poll
  ↓
OAuth token exchange
  ↓
Credential mã hóa trong Supabase
```

Gateway không yêu cầu email/password ChatGPT.

## API authentication

```http
Authorization: Bearer YOUR_GATEWAY_API_KEY
```

## Chat

```text
POST /v1/chat/completions
```

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [
    {"role": "user", "content": "Xin chào"}
  ],
  "stream": true
}
```

## Web Search

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [
    {"role": "user", "content": "Tìm tin tức mới nhất về AI."}
  ],
  "web_search": true
}
```

## Image

```text
POST /v1/images/generations
```

```json
{
  "model": "chatgpt-gpt-image-2",
  "prompt": "A cinematic photorealistic portrait in Saigon at golden hour"
}
```

## Image Edit

```text
POST /v1/images/edits
```

## Responses API

```text
POST /v1/responses
```

## Models

```text
GET /v1/models
```

## Usage

```text
GET /v1/usage
```
