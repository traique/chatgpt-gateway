# ChatGPT Gateway

OpenAI-compatible Cloudflare Worker gateway for ChatGPT/Codex subscription access.

## Capabilities

- Chat via ChatGPT/Codex Responses
- SSE streaming
- Web Search tool
- GPT Image generation
- GPT Image editing
- ChatGPT device-code login
- Encrypted OAuth credential storage in Cloudflare D1
- Automatic access-token refresh
- Account rotation foundation

The authentication flow follows the current Codex device login: request a device code, send the user to `https://auth.openai.com/codex/device`, poll for an authorization code, then exchange it at `https://auth.openai.com/oauth/token`. Codex itself documents the same device-code sequence and persists/refreshed ChatGPT OAuth credentials. citeturn2view0turn1search7

## Architecture

```text
Admin
  │
  ├── POST /auth/device/start
  │       ↓
  │   OpenAI device code
  │       ↓
  │   https://auth.openai.com/codex/device
  │       ↓
  └── POST /auth/device/poll
          ↓
       OAuth tokens
          ↓
       AES-256-GCM
          ↓
      Cloudflare D1
          │
          ▼
Client ── API key ──► Cloudflare Worker
                         │
                         ├── Chat
                         ├── Web Search
                         ├── Image
                         └── Image Edit
                         │
                         ▼
                  ChatGPT/Codex backend
```

OAuth refresh tokens are encrypted before persistence. The encryption key is a Wrangler secret and never enters D1.

## Endpoints

### Public health

`GET /health`

### API

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/images/generations`
- `POST /v1/images/edits`

API authentication:

```http
Authorization: Bearer $GATEWAY_API_KEY
```

### Admin authentication

- `POST /auth/device/start`
- `POST /auth/device/poll`
- `GET /auth/accounts`
- `DELETE /auth/accounts/:id`

Admin authentication:

```http
Authorization: Bearer $GATEWAY_ADMIN_KEY
```

## ChatGPT login

1. Deploy the Worker and run the D1 migration.
2. Call:

```bash
curl -X POST https://YOUR_GATEWAY/auth/device/start \
  -H "Authorization: Bearer $GATEWAY_ADMIN_KEY"
```

3. Open the returned `verification_url`.
4. Enter the returned `user_code`.
5. Poll until `status` becomes `completed`:

```bash
curl -X POST https://YOUR_GATEWAY/auth/device/poll \
  -H "Authorization: Bearer $GATEWAY_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"login_id":"LOGIN_ID","label":"primary"}'
```

After completion, the Worker owns the ChatGPT OAuth credentials. You do **not** copy `auth.json`, access tokens, or refresh tokens into Worker variables.

## Cloudflare setup

Create the D1 database:

```bash
npx wrangler d1 create chatgpt-gateway
```

Put the returned database ID into `wrangler.toml`, then run:

```bash
npx wrangler d1 migrations apply chatgpt-gateway --remote
```

Create secrets:

```bash
npx wrangler secret put GATEWAY_API_KEY
npx wrangler secret put GATEWAY_ADMIN_KEY
npx wrangler secret put CHATGPT_TOKEN_ENCRYPTION_KEY
```

Generate the encryption key with:

```bash
openssl rand -hex 32
```

`CHATGPT_OAUTH_CLIENT_ID` is configured as a non-secret public OAuth client identifier. The current Codex implementation uses `app_EMoamEEZ73f0CkXaXp7hrann`. citeturn3search4turn3search2

## API example

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

Web Search:

```json
{
  "model": "chatgpt-gpt-5.6",
  "messages": [{"role": "user", "content": "What happened in Vietnam today?"}],
  "web_search": true,
  "stream": true
}
```

Image generation:

```bash
curl https://YOUR_GATEWAY/v1/images/generations \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chatgpt-gpt-image-2",
    "prompt": "A cinematic Vietnamese street at golden hour"
  }'
```

## Security model

- API key and admin key are separate credentials.
- Refresh/access/id tokens are encrypted with AES-256-GCM at rest.
- Tokens are never returned by `/auth/accounts`.
- OAuth device sessions expire after 15 minutes.
- Access tokens are refreshed inside the Worker when they approach expiry.
- Refresh-token rotation is persisted after successful refresh.

## Important limitation

ChatGPT/Codex endpoints are private, undocumented service endpoints rather than the public OpenAI API. They can change without notice. The gateway therefore keeps the upstream protocol isolated in `src/providers.ts` and authentication isolated in `src/chatgpt-auth.ts`.

## Local checks

```bash
npm install
npm test
npm run typecheck
npm run dev
```
