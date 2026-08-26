# ChatGPT Gateway

Cloudflare Worker gateway that exposes a small OpenAI-compatible API surface for ChatGPT/Codex upstreams.

## Capabilities

- Chat + Responses
- SSE streaming
- Web Search through the Responses `web_search` tool
- GPT Image generation and editing
- Device-code authentication boundary
- Encrypted credential persistence in D1
- Automatic access-token refresh
- Per-client rate limiting
- Usage and latency metrics
- Upstream retry/backoff for transient 429/502/503/504 responses

## Architecture

```text
Admin
  │
  ├── /auth/device/start
  ├── ChatGPT device login
  └── /auth/device/poll
          │
          ▼
      OAuth credential store
          │
          ▼
      Cloudflare D1

Client ── API key ──► Worker
                         │
                         ├── validation
                         ├── rate limit
                         ├── request metrics
                         └── provider adapter
                                  │
                                  ├── Chat / Responses
                                  ├── Web Search
                                  └── GPT Image
```

## Endpoints

### Health

`GET /health`

### API

- `GET /v1/models`
- `GET /v1/usage`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/images/generations`
- `POST /v1/images/edits`

API authentication:

```http
Authorization: Bearer $GATEWAY_API_KEY
```

### Admin

- `POST /auth/device/start`
- `POST /auth/device/poll`
- `GET /auth/accounts`
- `DELETE /auth/accounts/:id`

Admin authentication:

```http
Authorization: Bearer $GATEWAY_ADMIN_KEY
```

## Login flow

1. Deploy the Worker and D1 schema.
2. Start a device login:

```bash
curl -X POST https://YOUR_GATEWAY/auth/device/start \
  -H "Authorization: Bearer $GATEWAY_ADMIN_KEY"
```

3. Open the returned `verification_url` and enter `user_code`.
4. Poll the login session:

```bash
curl -X POST https://YOUR_GATEWAY/auth/device/poll \
  -H "Authorization: Bearer $GATEWAY_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"login_id":"LOGIN_ID","label":"primary"}'
```

5. Continue polling until `status` is `completed`.

The gateway keeps credential material server-side and never exposes it through the account-management endpoints.

## Cloudflare setup

Create D1:

```bash
npx wrangler d1 create chatgpt-gateway
```

Set the returned `database_id` in `wrangler.toml` and apply migrations:

```bash
npx wrangler d1 migrations apply chatgpt-gateway --remote
```

For an existing deployment that already applied `0001_auth.sql`, the observability tables must also be applied once. The definitions are included in `0001_auth.sql` for fresh databases; for an already migrated database, run the equivalent `usage_events` and `rate_limits` table definitions manually before enabling strict rate limiting.

Secrets:

```bash
npx wrangler secret put GATEWAY_API_KEY
npx wrangler secret put GATEWAY_ADMIN_KEY
npx wrangler secret put CHATGPT_TOKEN_ENCRYPTION_KEY
```

Generate the encryption key:

```bash
openssl rand -hex 32
```

## Chat

```bash
curl https://YOUR_GATEWAY/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt-gpt-5.6",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

## Web Search

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [
    {"role": "user", "content": "What are the latest technology news today?"}
  ],
  "web_search": true,
  "stream": true
}
```

The gateway maps `web_search: true` to the upstream Responses `web_search` tool.

## Image generation

```bash
curl https://YOUR_GATEWAY/v1/images/generations \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt-gpt-image-2",
    "prompt": "A cinematic Vietnamese street at golden hour"
  }'
```

## Usage

```bash
curl https://YOUR_GATEWAY/v1/usage \
  -H "Authorization: Bearer $GATEWAY_API_KEY"
```

The summary covers the last seven days and reports request count, success count, failure count, and average latency. No prompts or response bodies are stored.

## Reliability

Transient upstream statuses `429`, `502`, `503`, and `504` are retried up to three attempts with exponential backoff and `Retry-After` support. Streaming requests are only retried before a successful upstream response is established.

## Security

- API and admin credentials are separate.
- Stored credential material is encrypted at rest with AES-256-GCM.
- Account listings never return access or refresh tokens.
- Device login sessions expire.
- Rate-limit keys are SHA-256 derived; raw API credentials are not written to metrics.
- Usage telemetry stores route/model/status/latency only.
- CORS is permissive by default; restrict it before exposing browser clients.

## Important limitation

The ChatGPT/Codex upstream endpoints used by this project are private service endpoints rather than the public OpenAI API. They can change without notice. Upstream protocol code is isolated in `src/providers.ts`, while authentication is isolated in `src/chatgpt-auth.ts`.

## Local checks

```bash
npm install
npm test
npm run typecheck
npm run dev
```
