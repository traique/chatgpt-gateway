# ChatGPT Gateway


FastAPI gateway chạy trên **Faable**, kết nối ChatGPT/Codex upstream bằng `curl-cffi` và lưu account/session data trên **Supabase PostgreSQL**.

> ChatGPT/Codex authentication và backend endpoint là private/internal interfaces và có thể thay đổi. Gateway không phải OpenAI Public API.

### v0.5.4 · Admin secret reveal + Notion account health

- Client key list không còn giải mã secret; full key chỉ được decrypt khi admin bấm **Xem/Copy** qua endpoint riêng có `Cache-Control: no-store`.
- Notion accounts có health `Khỏe / Lỗi / Đã tắt`, nút kiểm tra session, bật/tắt và xóa hẳn account stale/disabled.
- Provider health của Notion kiểm tra session thực với `getAvailableModels` và ghi lại lỗi gần nhất.

### v0.5.3 · ChatGPT routing + SSE overload recovery

- Cô lập model ChatGPT khỏi model của custom/generic provider khi global route và client-key route khác nhau.
- `/v1/chat/completions` giờ build Codex payload bằng **model đã resolve**, không dùng lại model hard-code từ request của bot.
- `/v1/responses` áp cùng model resolver trước khi gọi ChatGPT/Codex.
- Khi ChatGPT trả `server_is_overloaded` bên trong SSE trước khi có output, gateway retry tối đa **1 lần** và không phát response lỗi đầu tiên cho client.
- Retry chỉ áp dụng cho lỗi transient trước output; lỗi auth/model và lỗi sau khi đã stream output vẫn được trả nguyên trạng để tránh request lặp ngoài ý muốn.

### v0.5.2 · Admin UI stability

- Rebuilt the admin layout with a single mobile breakpoint stack (no overlapping mobile CSS rules).
- Removed `content-visibility` from dashboard cards to prevent blank/oversized tiles on mobile browsers.
- Mobile navigation is now sticky below the top bar instead of fixed over content.
- Dynamic provider editor and client-key creation are collapsed until needed.
- Built-in connectors use lightweight accordions, reducing visual clutter and initial paint work.
- Liquid-glass effects remain lightweight on mobile: no backdrop blur, no external assets, no frontend build step.


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
GENERIC_BASE_URL      # Base URL OpenAI-compatible, VD https://example.com/v1
GENERIC_API_KEY       # API key của upstream OpenAI-compatible
GENERIC_MODEL         # Model mặc định của upstream, VD vendor/model-1

# Tùy chọn tối ưu free tier (giá trị dưới đây cũng là mặc định)
GATEWAY_SETTINGS_CACHE_TTL=30
GATEWAY_CLIENT_CACHE_TTL=60
GATEWAY_CLIENT_CACHE_MAX=256
GATEWAY_PROVIDER_CACHE_TTL=120
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
public.gateway_api_keys
public.gateway_dynamic_providers
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
uvicorn app:app --host 0.0.0.0 --port $PORT --no-access-log
```
### Procfile

```text
web: uvicorn app:app --host 0.0.0.0 --port $PORT --no-access-log
```

`--no-access-log` chỉ tắt access log cho từng request; error log của Uvicorn vẫn còn. Với Free tier nên giữ **1 worker** (mặc định của lệnh trên) để tránh nhân đôi RAM và cache in-process.

> Docker/container deployment yêu cầu **Hobby hoặc Pro** theo giới hạn plan của Faable. Bản Free dùng managed Python buildpack.

### Tối ưu Free tier đã bật sẵn

- Không preload catalog model từ upstream khi admin vừa mở trang.
- Không tải các panel admin nằm dưới viewport cho tới khi người dùng cuộn tới.
- Cold start preload toàn bộ `gateway_settings` bằng một query, thay vì mỗi provider mở một connection riêng.
- Cache `active_provider` / `active_model` mặc định 30 giây để tránh query DB trên từng request.
- Cache policy của client key hợp lệ mặc định 60 giây; CRUD client key sẽ xóa cache ngay.
- Cache config custom provider mặc định 120 giây; CRUD provider cập nhật cache ngay.
- Polling device login dừng khi tab admin bị ẩn và tiếp tục khi quay lại.
- Procfile tắt per-request access log và giữ một Uvicorn worker.

Nếu database được thay đổi **trực tiếp bên ngoài gateway** (SQL Editor/instance khác), cache in-process có thể giữ giá trị cũ tối đa bằng TTL tương ứng. Muốn đồng bộ nhanh hơn có thể hạ TTL; không nên đặt TTL quá thấp trên Free tier vì sẽ tăng số connection/query.

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

Trang admin dùng giao diện mobile-first Liquid Glass + Bento Grid, palette trà đào / cam / sả. UI không cần CDN hay frontend build step; toàn bộ CSS/JS nằm trong `faable/admin_ui.py`. Trên màn hình nhỏ có bottom dock để nhảy nhanh giữa Route / Provider / Keys / Kết nối, input dùng cỡ chữ 16px để iOS không auto-zoom, có safe-area cho Dynamic Island/Home Indicator và touch target lớn.

Để nhẹ trên điện thoại, mobile tự tắt `backdrop-filter`/orb blur nặng, giảm shadow, dùng `content-visibility` cho card bên dưới viewport và giữ màu glass bằng nền bán trong suốt. Trang admin cũng lazy-load theo vùng nhìn thấy: Client Keys, ChatGPT Accounts, Notion và các built-in status chỉ gọi API khi card sắp xuất hiện. Catalog model upstream không tự fetch khi mở dashboard; nó chỉ được tải khi admin focus ô Model override.

Ở backend, active provider/model và client-key policy có cache ngắn trong process để giảm PostgreSQL round-trip. Thay đổi từ admin sẽ cập nhật/invalidate cache ngay trên instance hiện tại. Custom provider cũng có cache riêng. Các TTL có thể chỉnh bằng các biến `GATEWAY_*_CACHE_*` ở phần Environment variables.

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
| `generic` | Base URL tùy chỉnh (OpenAI-compatible) | Base URL + API key + model trong admin hoặc env | Adapter dùng chung cho upstream chuẩn OpenAI; không cần thêm file Python riêng cho từng hãng |

### Dynamic provider registry

Ngoài các provider tích hợp sẵn ở trên, admin có thể tạo **không giới hạn custom provider OpenAI-compatible** ngay trong `/admin`. Mỗi provider chỉ cần:

```text
Name
Base URL
API key
Model
```

Mỗi custom provider được cấp một ID ổn định dạng `custom-...`, có thể chọn làm routing mặc định hoặc gán riêng cho từng Client Key. Sửa tên/Base URL/API key/model không làm thay đổi ID nên các client đang gán vẫn giữ nguyên routing. API key được mã hóa Fernet trước khi lưu trong `gateway_dynamic_providers`.

Custom provider dùng cùng **một adapter** trong `faable/generic_provider.py`; thêm provider mới không tạo file Python mới. Gateway tự route:

```text
/v1/chat/completions -> {BASE_URL}/chat/completions
/v1/responses        -> {BASE_URL}/responses
/v1/messages         -> bridge Anthropic -> {BASE_URL}/chat/completions
/v1/models           -> expose model đã cấu hình
```

Để tránh route bị gãy, admin không cho xóa custom provider khi provider đó đang được chọn global hoặc còn được Client Key tham chiếu.

API quản trị custom provider:

```text
GET    /auth/custom-providers
POST   /auth/custom-providers
POST   /auth/custom-providers/{provider_id}
DELETE /auth/custom-providers/{provider_id}
```

Payload tạo mới:

```json
{
  "name": "My Provider",
  "base_url": "https://api.example.com/v1",
  "api_key": "sk-...",
  "model": "model-id"
}
```

Khi update, có thể gửi `api_key` rỗng để giữ nguyên secret đang lưu. Các alias `/admin-api/*` tương ứng cũng được tạo tự động.

Cấu hình OpenAI Compatible / OpenRouter / TokenRouter / Notion / NIM ngay trên trang admin:

- **OpenAI Compatible**: nhập `Base URL` (ví dụ `https://example.com/v1`), `API key` và `Model`. Gateway dùng một adapter `generic` duy nhất, tự nối `/chat/completions` hoặc `/responses` vào Base URL. `/v1/messages` được bridge sang Chat Completions như OpenRouter/NIM. API key được mã hóa khi có database.
- **OpenRouter**: dán API key (`sk-or-v1-…`) vào thẻ *OpenRouter*. Danh sách model lấy từ OpenRouter và lọc chỉ giữ model free (`:free`); đặt `OPENROUTER_MODELS_FILTER_MODE=all` để xem toàn bộ catalog.
- **TokenRouter**: dán key (`tr_…`) vào thẻ *TokenRouter*. Gateway dùng base mặc định `https://api.tokenrouter.io/v1`; có thể đổi bằng `TOKENROUTER_BASE_URL`. Catalog model lấy động từ `/v1/models` và cache 5 phút.
- **Notion AI**: có 2 cách đăng nhập. **Browser-assisted** mở một Chrome/Edge tạm trên **chính máy đang chạy gateway**, bạn đăng nhập Notion bình thường và gateway tự lấy session tối thiểu qua Chrome DevTools (`token_v2`, `notion_user_id`, `notion_users`, cùng browser/device id nếu Notion cấp), rồi đóng profile tạm. Cách này được ưu tiên vì Notion có thể trả 401 khi session identity không khớp. **Session thủ công** cho phép nhập `token_v2` (bắt buộc), `notion_user_id` và `notion_users` từ cùng một phiên browser; gateway dùng `notion_user_id` làm active-user header và giữ nguyên `notion_users` nếu được cung cấp. Nếu `notion_users` bỏ trống nhưng có `notion_user_id`, gateway chỉ dựng giá trị fallback để giữ tương thích. Mật khẩu không được thu thập, dữ liệu session được mã hóa trước khi lưu.
- **NVIDIA NIM**: dán key (`nvapi-…`) vào thẻ *NVIDIA NIM*. Catalog lấy trực tiếp từ NVIDIA (cache 5 phút) và lọc bỏ model embedding/rerank/OCR…; `NIM_MODELS_FILTER_MODE=all` để tắt lọc, `NIM_FREE_EXCLUDE=từ-khóa` để loại thêm.

Với B.AI / OpenRouter / TokenRouter / Notion / NIM / OpenAI Compatible, model do client gửi được đối chiếu với catalog của provider đang hoạt động: khớp thì giữ nguyên; nếu client hardcode một model không tồn tại (VD ZCode luôn gửi `glm-5.3-flash`), gateway tự thay bằng model admin đã chọn cho provider đó, hoặc model đầu tiên trong catalog — client không cần đổi cấu hình khi đổi provider. Model hợp lệ luôn được chuyển nguyên bản.

Provider secrets được mã hóa Fernet khi lưu DB. OpenRouter/TokenRouter/NIM dùng `gateway_settings`; custom provider dùng `gateway_dynamic_providers`; Notion lưu session tối thiểu đã mã hóa trong `notion_accounts`. API admin liên quan:

```text
POST /auth/generic/config      # {"base_url": "https://example.com/v1", "api_key": "sk-…", "model": "vendor/model"}
GET  /auth/generic/config      # trạng thái + base_url + model; không trả API key
POST /auth/openrouter/key      # {"api_key": "sk-or-v1-…"}
GET  /auth/openrouter/key      # {"configured": true}
POST /auth/tokenrouter/key     # {"api_key": "tr_…"}
GET  /auth/tokenrouter/key     # {"configured": true, "base_url": "..."}
POST /auth/nim/key             # {"api_key": "nvapi-…"}
GET  /auth/nim/key             # {"configured": true}; catalog model tải lazy
POST /auth/notion/login          # {"token_v2": "...", "notion_user_id": "...", "notion_users": "..."}
POST /auth/notion/browser/start  # mở Chrome/Edge local và bắt đầu chờ login
POST /auth/notion/browser/poll   # {"login_id": "..."}
GET    /auth/notion/accounts               # danh sách + health tài khoản Notion
POST   /auth/notion/accounts/{id}              # {"status":"active"|"disabled"}
POST   /auth/notion/accounts/{id}/health       # kiểm tra session ngay
DELETE /auth/notion/accounts/{id}              # xóa hẳn; account khỏe đang active phải tắt trước
```

OpenRouter, TokenRouter, NIM và `generic` nói chuẩn OpenAI nên `/v1/chat/completions` được passthrough nguyên bản (stream + non-stream, kể cả tool calling). `generic` cũng passthrough `/v1/responses` tới `${GENERIC_BASE_URL}/responses`; upstream nào không hỗ trợ Responses sẽ trả lỗi upstream bình thường. TokenRouter được passthrough native cho `/v1/responses` và `/v1/messages`; OpenRouter và NIM hiện vẫn trả 503 ở endpoint Responses. Với `/v1/messages`, `generic` dùng bridge Anthropic → OpenAI Chat Completions. Notion không có tool calling native — các message được gộp thành một prompt duy nhất và văn bản trả về được chuyển thành `chat.completion` chuẩn (stream qua bộ parse NDJSON của Notion).

API admin:

```text
GET  /auth/providers                    # bootstrap nhanh, không gọi upstream model
GET  /auth/providers/{provider}/models  # tải catalog động của một provider khi cần
POST /auth/providers/select             # {"provider": "chatgpt"|"bai"|"openrouter"|"tokenrouter"|"notion"|"nim"|"generic", "model": "..."}

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
GET    /auth/clients                    # chỉ metadata + mask; không decrypt secret
POST   /auth/clients                    # {"label", "provider", "model", "key?"} — bỏ trống key để tự sinh (gwc-…)
GET    /auth/clients/{id}/secret        # decrypt on-demand khi admin bấm Xem/Copy; no-store
POST   /auth/clients/{id}               # {"provider"?, "model"?, "label"?, "status"?}
DELETE /auth/clients/{id}               # xóa vĩnh viễn
```

Client keys được mã hóa Fernet trong bảng `gateway_api_keys` (kèm SHA-256 hash để tra cứu). Danh sách client không giải mã key; full key chỉ được trả lúc tạo hoặc khi admin chủ động bấm **Xem/Copy**. Client key không model (để trống) sẽ dùng model chung của gateway.

## Account management

Các endpoint admin:

```text
POST   /auth/device/start
POST   /auth/device/poll
GET    /auth/accounts
POST   /auth/accounts/{account_id}      # {"status":"active"|"disabled"}
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


