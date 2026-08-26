# ChatGPT Gateway

Cloudflare Worker gateway cho API tương thích OpenAI, kết nối tới ChatGPT/Codex upstream.

> **Lưu ý:** upstream ChatGPT/Codex sử dụng endpoint dịch vụ riêng, không phải OpenAI Public API. Endpoint có thể thay đổi bất kỳ lúc nào.

## Chức năng

- Chat
- Responses API
- SSE streaming
- Web Search
- GPT Image generation
- GPT Image editing
- Đăng nhập ChatGPT bằng giao diện web trên điện thoại
- Lưu credential phía server trong Cloudflare D1, mã hóa AES-256-GCM
- Tự refresh access token
- Rate limit theo client
- Usage/latency metrics
- Retry/backoff cho lỗi tạm thời

## Kiến trúc

```text
Điện thoại
   │
   ▼
Web Admin UI
   │
   ├── Đăng nhập ChatGPT
   ├── Quản lý account
   └── Kiểm tra trạng thái
          │
          ▼
Cloudflare Worker
   │
   ├── Authentication
   ├── Validation
   ├── Rate limit
   ├── Metrics
   └── Provider adapter
          │
          ├── Chat / Responses
          ├── Web Search
          └── GPT Image
```

## 1. Chuẩn bị

Bạn chỉ cần điện thoại + trình duyệt. Có thể thao tác phần Cloudflare trực tiếp trên Cloudflare Dashboard.

Tạo/clone repository:

```text
https://github.com/traique/chatgpt-gateway
```

Nếu dùng GitHub Codespaces hoặc một máy có Node.js:

```bash
npm install
npm test
npm run typecheck
```

## 2. Tạo Cloudflare Worker

Mở:

https://dash.cloudflare.com/

Chọn:

```text
Workers & Pages
→ Create
→ Import a repository
→ GitHub
→ traique/chatgpt-gateway
```

Chọn branch:

```text
main
```

Build command:

```text
npm run deploy
```

> Nếu Cloudflare Dashboard không cho dùng `wrangler deploy` trong build configuration của bạn, hãy dùng GitHub Actions hoặc deploy bằng Wrangler từ Codespaces/Termux.

## 3. Tạo D1 Database

Trong Cloudflare Dashboard:

```text
Workers & Pages
→ D1 SQL Database
→ Create database
```

Tên:

```text
chatgpt-gateway
```

Sau khi tạo, lấy `database_id`.

Mở `wrangler.toml` và thay:

```toml
database_id = "REPLACE_WITH_D1_DATABASE_ID"
```

bằng ID thật.

Nếu deploy bằng Wrangler:

```bash
npx wrangler d1 migrations apply chatgpt-gateway --remote
```

## 4. Tạo Secrets

Không lưu các secret trong GitHub hoặc `wrangler.toml`.

Tạo:

```text
GATEWAY_API_KEY
GATEWAY_ADMIN_KEY
CHATGPT_TOKEN_ENCRYPTION_KEY
```

Nếu dùng Wrangler:

```bash
npx wrangler secret put GATEWAY_API_KEY
npx wrangler secret put GATEWAY_ADMIN_KEY
npx wrangler secret put CHATGPT_TOKEN_ENCRYPTION_KEY
```

Tạo encryption key:

```bash
openssl rand -hex 32
```

Nếu chỉ dùng điện thoại, có thể tạo secret ngẫu nhiên bằng một password manager đáng tin cậy. Không dùng lại mật khẩu ChatGPT.

## 5. Deploy

Sau khi cấu hình repository + D1 + secrets:

```bash
npm install
npm run typecheck
npm test
npm run deploy
```

Worker sẽ có địa chỉ dạng:

```text
https://chatgpt-gateway.<subdomain>.workers.dev
```

Kiểm tra:

```text
GET /health
```

Ví dụ:

```text
https://chatgpt-gateway.<subdomain>.workers.dev/health
```

## 6. Giao diện đăng nhập trên điện thoại

Không cần dùng `curl` để đăng nhập.

Mở trên điện thoại:

```text
https://YOUR_GATEWAY/auth
```

Giao diện cần thực hiện flow:

```text
Đăng nhập ChatGPT
      ↓
Bấm "Bắt đầu đăng nhập"
      ↓
Worker tạo device session
      ↓
Hiển thị verification URL + user code
      ↓
Bấm "Mở trang đăng nhập"
      ↓
Đăng nhập ChatGPT
      ↓
Quay lại trang Gateway
      ↓
Gateway tự poll trạng thái
      ↓
Hiển thị "Đã kết nối"
```

### Lưu ý về thiết kế login

- Không yêu cầu nhập email/password ChatGPT vào Gateway.
- Không đưa access token/refresh token vào trình duyệt.
- Trình duyệt chỉ nhận `login_id`, trạng thái và thông tin hướng dẫn.
- Credential được xử lý phía Worker.
- Endpoint quản trị phải được bảo vệ bằng `GATEWAY_ADMIN_KEY` hoặc một session admin riêng.

## 7. Quản lý tài khoản

Sau khi đăng nhập, giao diện quản trị nên hiển thị:

```text
ChatGPT Accounts

● primary       Active
● backup        Active
○ old-account   Disabled
```

Không hiển thị:

```text
access_token
refresh_token
id_token
```

Có thể cho phép:

```text
+ Thêm tài khoản
⟳ Refresh trạng thái
✕ Disable tài khoản
🗑 Xóa tài khoản
```

## 8. API Key cho ứng dụng

Các ứng dụng Telegram/Open WebUI/app của bạn chỉ cần:

```http
Authorization: Bearer YOUR_GATEWAY_API_KEY
```

Không cần biết credential ChatGPT.

## 9. Chat

```bash
curl -X POST https://YOUR_GATEWAY/v1/chat/completions \
  -H "Authorization: Bearer YOUR_GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt-gpt-5.6",
    "messages": [
      {"role": "user", "content": "Xin chào"}
    ],
    "stream": true
  }'
```

## 10. Web Search

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [
    {
      "role": "user",
      "content": "Tin tức mới nhất về AI hôm nay?"
    }
  ],
  "web_search": true,
  "stream": true
}
```

Gateway map `web_search: true` thành upstream Responses `web_search` tool.

## 11. Tạo ảnh

```bash
curl -X POST https://YOUR_GATEWAY/v1/images/generations \
  -H "Authorization: Bearer YOUR_GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt-gpt-image-2",
    "prompt": "A cinematic Vietnamese woman walking in Saigon at golden hour, photorealistic"
  }'
```

## 12. Chỉnh sửa ảnh

```bash
curl -X POST https://YOUR_GATEWAY/v1/images/edits \
  -H "Authorization: Bearer YOUR_GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt-gpt-image-2",
    "prompt": "Change the background to a modern Saigon street at sunset",
    "image": "BASE64_OR_SUPPORTED_IMAGE_REFERENCE"
  }'
```

## 13. Responses API

```json
{
  "model": "chatgpt-gpt-5.6",
  "input": "Tìm thông tin mới nhất về Cloudflare Workers",
  "web_search": true,
  "stream": true
}
```

Endpoint:

```text
POST /v1/responses
```

## 14. Usage

```text
GET /v1/usage
```

Yêu cầu:

```http
Authorization: Bearer YOUR_GATEWAY_API_KEY
```

Metrics chỉ lưu metadata:

```text
route
model
status
latency
account reference
created_at
```

Không lưu prompt hoặc response.

## 15. Rate Limit

Gateway giới hạn request theo client/API key.

Response có các header:

```text
X-RateLimit-Remaining
X-RateLimit-Reset
```

## 16. Retry

Các lỗi tạm thời được retry có giới hạn:

```text
429
502
503
504
```

Có hỗ trợ `Retry-After` và exponential backoff.

Không retry vô hạn.

## 17. Domain riêng

Trong Cloudflare:

```text
Workers & Pages
→ chatgpt-gateway
→ Settings
→ Domains & Routes
→ Add Custom Domain
```

Ví dụ:

```text
api.example.com
```

Sau đó API sẽ là:

```text
https://api.example.com/v1/chat/completions
```

## 18. Kiểm tra deployment

Theo thứ tự:

```text
1. /health
2. /v1/models
3. /auth
4. Đăng nhập ChatGPT
5. Kiểm tra account Active
6. Chat non-stream
7. Chat stream
8. Web Search
9. Image generation
10. Image edit
11. /v1/usage
```

## 19. Bảo mật

- Không commit API key.
- Không commit encryption key.
- Không nhập mật khẩu ChatGPT vào Gateway.
- Không hiển thị OAuth token trên UI.
- Không ghi prompt/response vào logs.
- Dùng HTTPS.
- Đổi `GATEWAY_API_KEY` định kỳ.
- Không dùng `GATEWAY_ADMIN_KEY` làm API key cho Telegram.
- Nếu mở API cho Internet, nên giới hạn CORS và thêm rate limit chặt hơn.

## 20. Cấu trúc project

```text
chatgpt-gateway/
├── src/
│   ├── index.ts
│   ├── types.ts
│   ├── validation.ts
│   ├── errors.ts
│   ├── crypto.ts
│   ├── chatgpt-auth.ts
│   └── providers.ts
├── migrations/
│   └── 0001_auth.sql
├── test/
├── wrangler.toml
├── package.json
└── README.md
```

## 21. Giới hạn hiện tại

ChatGPT/Codex upstream là service endpoint riêng và có thể thay đổi. Vì vậy:

```text
src/chatgpt-auth.ts
```

chịu trách nhiệm authentication, còn:

```text
src/providers.ts
```

chịu trách nhiệm upstream protocol.

Tách hai phần này giúp thay đổi backend mà không phải viết lại toàn bộ API gateway.

## 22. Local development

```bash
npm install
npm test
npm run typecheck
npm run dev
```

## 23. Deploy nhanh

```text
GitHub
  ↓
Cloudflare Workers
  ↓
Connect repository
  ↓
Set database_id
  ↓
Apply D1 migration
  ↓
Set 3 secrets
  ↓
Deploy
  ↓
Mở /auth trên điện thoại
  ↓
Login ChatGPT
  ↓
Dùng /v1/chat/completions
```

## License

MIT
