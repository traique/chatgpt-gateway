# ChatGPT Gateway

FastAPI gateway chạy trên **Faable**, kết nối ChatGPT/Codex upstream bằng `curl-cffi` và lưu account/session data trên **Supabase PostgreSQL**.

> ChatGPT/Codex authentication và backend endpoint là private/internal interfaces và có thể thay đổi. Gateway không phải OpenAI Public API.

## Kiến trúc

```text
Client
  ↓
Faable / FastAPI
  ├── /auth
  ├── /v1/models
  ├── /v1/debug/transport
  ├── /v1/chat/completions
  └── /v1/responses
          ↓
     ChatGPT/Codex upstream
          ↓
     Supabase PostgreSQL
```

Không còn Cloudflare Workers, D1, Wrangler hoặc SQLite/Turso runtime.

## Runtime

- Python 3.11+
- FastAPI + Uvicorn
- `curl-cffi` với browser impersonation
- PostgreSQL qua `psycopg`
- Supabase PostgreSQL làm persistent storage
- Fernet để mã hóa access/refresh token trước khi lưu DB
- HttpOnly admin session cookie

## Environment variables

Bắt buộc cho gateway API:

```text
GATEWAY_API_KEY
```

Bắt buộc cho Supabase/device login:

```text
DATABASE_URL
SESSION_SECRET
CHATGPT_TOKEN_ENCRYPTION_KEY
ADMIN_USERNAME
ADMIN_PASSWORD
```

Các biến upstream có default:

```text
CHATGPT_AUTH_BASE_URL
CHATGPT_CODEX_ENDPOINT
CHATGPT_OAUTH_CLIENT_ID
CHATGPT_CODEX_CLIENT_VERSION
```

`DATABASE_URL` là PostgreSQL connection string của Supabase. Với production nên dùng connection string/pooler phù hợp với giới hạn connection của project.

`CHATGPT_TOKEN_ENCRYPTION_KEY` phải là Fernet key hợp lệ. Không commit secrets vào GitHub.

## Supabase setup

Schema chuẩn nằm tại:

```text
supabase/schema.sql
```

Chạy **toàn bộ nội dung `supabase/schema.sql` trong Supabase SQL Editor** trước khi sử dụng device login.

Các bảng chính:

```text
public.chatgpt_accounts
public.device_login_sessions
```

Kiểm tra:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('chatgpt_accounts', 'device_login_sessions')
ORDER BY table_name;
```

Backend dùng PostgreSQL trực tiếp; Supabase Auth không được dùng để lưu session admin của gateway.

## Deploy Faable Free

Repo được bố trí để Faable Free tự nhận **managed Python buildpack** từ root repository. Không cần `rootDir`, `faable.json` hoặc Docker.

### Install command

```bash
pip install -r requirements.txt
```

### Start command

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

### Procfile

```text
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

> Docker/container deployment yêu cầu **Hobby hoặc Pro** theo giới hạn plan của Faable. Bản Free dùng managed Python buildpack.

## Health check

```text
GET /health
```

Endpoint này trả trạng thái cấu hình runtime, transport và database configuration.

## Admin

Mở:

```text
/auth
```

Đăng nhập bằng:

```text
ADMIN_USERNAME
ADMIN_PASSWORD
```

Session admin có TTL 12 giờ và sử dụng HttpOnly cookie.

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
Credential mã hóa bằng Fernet
  ↓
Supabase PostgreSQL
```

Gateway không yêu cầu lưu email/password ChatGPT.

## API authentication

Sử dụng một trong hai dạng:

```http
Authorization: Bearer YOUR_GATEWAY_API_KEY
```

hoặc:

```http
X-API-Key: YOUR_GATEWAY_API_KEY
```

## Models

```text
GET /v1/models
```

Model hiện được expose:

```text
chatgpt-gpt-5.6
```

## Chat Completions

```text
POST /v1/chat/completions
```

Ví dụ:

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [
    {"role": "user", "content": "Xin chào"}
  ],
  "stream": true
}
```

Gateway chuyển request sang ChatGPT/Codex Responses endpoint và trả SSE stream.

## Responses API

```text
POST /v1/responses
```

Gateway ép `store=false` và streaming để phù hợp với gateway runtime hiện tại.

## Transport debug

```text
GET /v1/debug/transport
```

Endpoint này kiểm tra khả năng kết nối HTTPS từ Faable tới `chatgpt.com` bằng `curl-cffi`.

Nó chỉ kiểm tra transport/network; HTTP 200 từ `robots.txt` không có nghĩa ChatGPT backend API đã xác thực thành công.

## Account management

Các endpoint admin:

```text
POST   /auth/device/start
POST   /auth/device/poll
GET    /auth/accounts
DELETE /auth/accounts/{account_id}
```

Access token và refresh token không được lưu plaintext trong Supabase.

## Development

Cài dependency:

```bash
pip install -r requirements.txt
```

Chạy test:

```bash
PYTHONPATH=. pytest -q
```

CI hiện chạy cùng command và phải pass trước khi deploy.

## Scope hiện tại

Runtime hiện tại tập trung vào:

1. Faable/FastAPI runtime.
2. curl-cffi transport tới ChatGPT/Codex.
3. Device Login + OAuth token storage.
4. Supabase PostgreSQL persistence.
5. `/v1/chat/completions` và `/v1/responses` streaming.
6. Admin/account management.

Image API, Web Search API riêng và Usage/Rate-limit API chưa được expose trong runtime hiện tại; không nên coi các endpoint đó là supported cho tới khi được implement và có regression tests.
