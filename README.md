# ChatGPT Gateway

OpenAI-compatible Cloudflare Worker gateway for a ChatGPT/Codex upstream, with a separate token provider.

## Endpoints

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/images/generations`
- `POST /v1/images/edits`

## Architecture

```text
Client
  │  OpenAI-compatible API
  ▼
Cloudflare Worker
  ├── API-key authentication
  ├── request validation
  ├── Chat Completions → Responses adapter
  ├── Responses passthrough
  └── Images
       │
       ▼
Token Provider
       │
       ▼
ChatGPT/Codex backend
```

The gateway never stores refresh tokens. The token provider owns OAuth refresh, account selection and token persistence.

## Environment

Set these as Wrangler secrets:

```bash
wrangler secret put GATEWAY_API_KEY
wrangler secret put CHATGPT_AUTH_TOKEN_PROVIDER_URL
wrangler secret put CHATGPT_AUTH_TOKEN_PROVIDER_API_KEY
```

The Codex endpoints are configured in `wrangler.toml`.

## Client example

```bash
curl https://YOUR_GATEWAY/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.6",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Web search:

```json
{
  "model": "gpt-5.6",
  "messages": [{"role": "user", "content": "What happened in Vietnam today?"}],
  "web_search": true
}
```

## Local checks

```bash
npm install
npm test
npm run typecheck
npm run dev
```

## Production checklist

1. Keep `GATEWAY_API_KEY` private and rotate it periodically.
2. Restrict CORS if the gateway is called from a browser.
3. Put rate limiting in front of the Worker for public deployments.
4. Monitor upstream HTTP 401/403/429/5xx separately.
5. Keep OAuth refresh logic in the token provider, not this gateway.
