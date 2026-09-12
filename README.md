# ChatGPT Gateway

FastAPI gateway chạy trên **Faable**, kết nối ChatGPT/Codex upstream bằng `curl-cffi` và lưu account/session data trên **Supabase PostgreSQL**.

> ChatGPT/Codex authentication và backend endpoint là private/internal interfaces và có thể thay đổi. Gateway không phải OpenAI Public API.

## Kiến trúc

```text
Client
  ↓
Faable / FastAPI
  ├── /admin  (khuyến nghị; /auth vẫn tương thích)
  ├── /v1/models
  ├── /v1/debug/transport
  ├── /v1/chat/completions  (OpenAI-compatible, hỗ trợ tool calling)
  ├── /v1/responses         (OpenAI Responses, passthrough stream)
  └── /v1/messages          (Anthropic Messages-compatible)
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

Tùy chọn cho các provider khác (có thể dán key trực tiếp trong admin thay vì env):

```text
BAI_API_KEY          # API key của B.AI (https://api.b.ai)
BAI_BASE_URL         # mặc định https://api.b.ai/v1
OPENROUTER_API_KEY   # API key OpenRouter (https://openrouter.ai)
TOKENROUTER_API_KEY  # API key TokenRouter (tr_...)
TOKENROUTER_BASE_URL # mặc định https://api.tokenrouter.io/v1
NIM_API_KEY          # API key NVIDIA NIM (https://build.nvidia.com)
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
public.gateway_settings
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

Mở trang quản trị bằng đường dẫn khuyến nghị:

```text
/admin
```

`/auth` vẫn được giữ để tương thích. Khi mở `/admin`, frontend dùng các alias `/admin-api/*` thay cho `/auth/*`; chức năng và quyền truy cập giống nhau.

Trang admin ưu tiên hiển thị nhanh: endpoint provider ban đầu chỉ đọc trạng thái local/DB và catalog fallback/cache, không chờ API model của provider. Catalog động của **provider đang chọn** mới được tải nền sau khi UI đã hiện; timeout discovery được giới hạn để upstream chậm không làm dashboard treo.

Đăng nhập bằng:

```text
ADMIN_USERNAME
ADMIN_PASSWORD
```

Session admin có TTL 12 giờ và sử dụng HttpOnly cookie.

### FortiGuard / enterprise web filter

Nếu `/auth` bị FortiGuard chặn nhưng domain là hợp lệ, thử truy cập `/admin` trước để loại trừ false-positive theo URL path. Gateway cũng trả `Cache-Control: no-store`, CSP, anti-clickjacking và referrer/security headers cho trang quản trị.

Nếu **cả domain** vẫn bị chặn, đây không phải vấn đề có thể sửa chắc chắn bằng code ứng dụng. Kiểm tra rating của hostname trên FortiGuard Web Filter và gửi yêu cầu phân loại lại nếu bị `Not Rated/Unrated` hoặc phân loại sai. Trong mạng doanh nghiệp, quản trị FortiGate có thể tạo exception cho đúng hostname theo policy nội bộ; không nên tắt toàn bộ IPS/Web Filter chỉ để chạy gateway.

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

## Anthropic Messages API

```text
POST /v1/messages
```

Endpoint tương thích Anthropic Messages API (cho Claude Code và các tool nói chuẩn Anthropic):
system/messages/tool_use/tool_result được dịch sang Responses upstream; streaming trả
`message_start` / `content_block_start` / `content_block_delta` / `message_delta` / `message_stop`;
lỗi trả về dạng `{"type": "error", "error": {"type", "message"}}`.

## Tool calling

`/v1/chat/completions` hỗ trợ đầy đủ agent loop:
- `tools` trong request được convert sang Responses tools.
- Upstream `function_call` được trả về client dưới dạng `delta.tool_calls` (stream) hoặc
  `message.tool_calls` (non-stream) với `finish_reason: "tool_calls"`.
- Lịch sử `assistant.tool_calls` và `role: "tool"` được convert thành
  `function_call` / `function_call_output` items.
- `usage` (prompt/completion/total tokens) được trả về từ upstream khi có.

## Transport debug

```text
GET /v1/debug/transport
```

Endpoint này kiểm tra khả năng kết nối HTTPS từ Faable tới `chatgpt.com` bằng `curl-cffi`.

Nó chỉ kiểm tra transport/network; HTTP 200 từ `robots.txt` không có nghĩa ChatGPT backend API đã xác thực thành công.

## Providers

Gateway hỗ trợ nhiều provider upstream, chọn trong trang admin (`/admin`, hoặc `/auth` tương thích) tại thẻ **Provider & Model**:

| Provider | Endpoint | Xác thực | Ghi chú |
| --- | --- | --- | --- |
| `chatgpt` | ChatGPT/Codex backend (mặc định) | Device login | Đầy đủ tool calling, usage |
| `bai` | `https://api.b.ai/v1` (OpenAI/Anthropic/Responses compatible) | `BAI_API_KEY` | Passthrough native cả 3 protocol |
| `openrouter` | `https://openrouter.ai/api/v1` (OpenAI-compatible) | Key dán trong admin (hoặc `OPENROUTER_API_KEY`) | Model list động, lọc sẵn model free (đuôi `:free`) |
| `tokenrouter` | `https://api.tokenrouter.io/v1` (OpenAI-compatible) | Key dán trong admin (hoặc `TOKENROUTER_API_KEY`) | Model list động; hỗ trợ Chat Completions, Responses và Anthropic Messages |
| `notion` | `https://app.notion.com/api/v3` (runInferenceTranscript) | Browser-assisted hoặc `token_v2` | Model list động từ `getAvailableModels` theo workspace |
| `nim` | `https://integrate.api.nvidia.com/v1` (OpenAI-compatible) | Key dán trong admin (hoặc `NIM_API_KEY`) | Model list động, lọc model không chat-capable (NIM là free tier) |

Cấu hình OpenRouter / TokenRouter / Notion / NIM ngay trên trang admin:

- **OpenRouter**: dán API key (`sk-or-v1-…`) vào thẻ *OpenRouter*. Danh sách model lấy từ OpenRouter và lọc chỉ giữ model free (`:free`); đặt `OPENROUTER_MODELS_FILTER_MODE=all` để xem toàn bộ catalog.
- **TokenRouter**: dán key (`tr_…`) vào thẻ *TokenRouter*. Gateway dùng base mặc định `https://api.tokenrouter.io/v1`; có thể đổi bằng `TOKENROUTER_BASE_URL`. Catalog model lấy động từ `/v1/models` và cache 5 phút.
- **Notion AI**: có 2 cách đăng nhập. **Browser-assisted** mở một Chrome/Edge tạm trên **chính máy đang chạy gateway**, bạn đăng nhập Notion bình thường và gateway tự lấy session tối thiểu qua Chrome DevTools (`token_v2`, `notion_user_id`, `notion_users`, cùng browser/device id nếu Notion cấp), rồi đóng profile tạm. Cách này được ưu tiên vì Notion có thể trả 401 khi session identity không khớp. **Session thủ công** cho phép nhập `token_v2` (bắt buộc), `notion_user_id` và `notion_users` từ cùng một phiên browser; gateway dùng `notion_user_id` làm active-user header và giữ nguyên `notion_users` nếu được cung cấp. Nếu `notion_users` bỏ trống nhưng có `notion_user_id`, gateway chỉ dựng giá trị fallback để giữ tương thích. Mật khẩu không được thu thập, dữ liệu session được mã hóa trước khi lưu.
- **NVIDIA NIM**: dán key (`nvapi-…`) vào thẻ *NVIDIA NIM*. Catalog lấy trực tiếp từ NVIDIA (cache 5 phút) và lọc bỏ model embedding/rerank/OCR…; `NIM_MODELS_FILTER_MODE=all` để tắt lọc, `NIM_FREE_EXCLUDE=từ-khóa` để loại thêm.

Với B.AI / OpenRouter / TokenRouter / Notion / NIM, model do client gửi được đối chiếu với catalog của provider đang hoạt động: khớp thì giữ nguyên; nếu client hardcode một model không tồn tại (VD ZCode luôn gửi `glm-5.3-flash`), gateway tự thay bằng model admin đã chọn cho provider đó, hoặc model đầu tiên trong catalog — client không cần đổi cấu hình khi đổi provider. Model hợp lệ luôn được chuyển nguyên bản.

Provider secrets được mã hóa Fernet khi lưu DB. OpenRouter/TokenRouter/NIM dùng `gateway_settings`; Notion lưu session tối thiểu đã mã hóa trong `notion_accounts`. API admin liên quan:

```text
POST /auth/openrouter/key      # {"api_key": "sk-or-v1-…"}
GET  /auth/openrouter/key      # {"configured": true}
POST /auth/tokenrouter/key     # {"api_key": "tr_…"}
GET  /auth/tokenrouter/key     # {"configured": true, "base_url": "..."}
POST /auth/nim/key             # {"api_key": "nvapi-…"}
GET  /auth/nim/key             # {"configured": true}; catalog model tải lazy
POST /auth/notion/login          # {"token_v2": "...", "notion_user_id": "...", "notion_users": "..."}
POST /auth/notion/browser/start  # mở Chrome/Edge local và bắt đầu chờ login
POST /auth/notion/browser/poll   # {"login_id": "..."}
GET  /auth/notion/accounts       # danh sách tài khoản Notion
DELETE /auth/notion/accounts/{id}
```

OpenRouter, TokenRouter và NIM nói chuẩn OpenAI nên `/v1/chat/completions` được passthrough nguyên bản (stream + non-stream, kể cả tool calling). TokenRouter cũng được passthrough native cho `/v1/responses` và `/v1/messages`; OpenRouter và NIM hiện vẫn trả 503 ở endpoint Responses. Notion không có tool calling native — các message được gộp thành một prompt duy nhất và văn bản trả về được chuyển thành `chat.completion` chuẩn (stream qua bộ parse NDJSON của Notion).

API admin:

```text
GET  /auth/providers                    # bootstrap nhanh, không gọi upstream model
GET  /auth/providers/{provider}/models  # tải catalog động của một provider khi cần
POST /auth/providers/select             # {"provider": "chatgpt"|"bai"|"openrouter"|"tokenrouter"|"notion"|"nim", "model": "..."}

# Khi dùng /admin, các API trên có alias tương ứng dưới /admin-api/*.
```

Lựa chọn được lưu trong bảng `gateway_settings` (hoặc trong bộ nhớ nếu không có `DATABASE_URL`). Khi client gọi model mặc định (`chatgpt-gpt-5.6` hoặc bỏ trống), gateway dùng model admin đã chọn cho provider đang active; model client ghi rõ thì được truyền nguyên. `/v1/models` trả về danh sách model của provider đang active (B.AI được query trực tiếp từ `GET /v1/models` của B.AI với cache 60 giây).

### Client keys — mỗi client một provider riêng

Thẻ **Client Keys** trên trang admin cho phép tạo API key riêng cho từng client (bot, CLI, app…), mỗi key gắn với một provider + model cụ thể:

| Client key | Provider | Model | Ưu tiên |
| --- | --- | --- | --- |
| Key master (`GATEWAY_API_KEY`) | Provider chọn chung (thẻ Provider & Model) | Model chung | Mặc định |
| Client key | Provider gán cho key đó | Model gán cho key đó | Ghi đè lựa chọn chung |

API admin (yêu cầu đăng nhập admin):

```text
GET    /auth/clients                 # danh sách client keys (key đã mask)
POST   /auth/clients                 # {"label", "provider", "model", "key?"} — bỏ trống key để tự sinh (gwc-…)
POST   /auth/clients/{id}            # {"provider"?, "model"?, "label"?, "status"?}
DELETE /auth/clients/{id}            # xóa vĩnh viễn
```

Client keys được mã hóa Fernet trong bảng `gateway_api_keys` (kèm SHA-256 hash để tra cứu); key đầy đủ chỉ hiển thị một lần lúc tạo. Client key không model (để trống) sẽ dùng model chung của gateway.

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
5. `/v1/chat/completions` (có tool calling), `/v1/responses` và `/v1/messages` streaming.
6. Admin/account management.

Image API, Web Search API riêng và Usage/Rate-limit API chưa được expose trong runtime hiện tại; không nên coi các endpoint đó là supported cho tới khi được implement và có regression tests.


