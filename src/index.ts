import { disableAccount, getChatGptToken, listAccounts, pollDeviceLogin, startDeviceLogin } from "./auth";
import { GatewayRequestError, UpstreamError } from "./errors";
import { createChatCompletionResponse, createImageEditResponse, createImageResponse, createResponsesResponse } from "./providers";
import { validateChatRequest, validateImageEditRequest, validateImageGenerationRequest } from "./validation";
import type { Env } from "./types";

const DEFAULT_CHAT_MODEL = "chatgpt-gpt-5.6";
const IMAGE_MODEL = "chatgpt-gpt-image-2";
const DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders() });

    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return json({ ok: true });
    if (request.method === "GET" && url.pathname === "/v1/models") return authorizedApi(request, env) ? modelsResponse() : errorResponse("authentication_error", "Invalid API key.", 401);

    if (url.pathname.startsWith("/auth/")) return handleAuthRoute(request, env, url);
    if (!isAuthorized(request, env)) return errorResponse("authentication_error", "Invalid API key.", 401);
    if (request.method !== "POST") return errorResponse("invalid_request_error", "Method not allowed.", 405);

    try {
      const payload: unknown = await request.json();
      const token = await getChatGptToken(env);

      if (url.pathname === "/v1/chat/completions") return proxyResponse(await createChatCompletionResponse(env, token, validateChatRequest(payload)));
      if (url.pathname === "/v1/responses") return proxyResponse(await createResponsesResponse(env, token, validateChatRequest(payload)));
      if (url.pathname === "/v1/images/generations") return proxyResponse(await createImageResponse(env, token, validateImageGenerationRequest(payload)));
      if (url.pathname === "/v1/images/edits") return proxyResponse(await createImageEditResponse(env, token, validateImageEditRequest(payload)));
      return errorResponse("invalid_request_error", "Unknown endpoint.", 404);
    } catch (error) {
      return mapError(error);
    }
  },
} satisfies ExportedHandler<Env>;

async function handleAuthRoute(request: Request, env: Env, url: URL): Promise<Response> {
  if (!isAdminAuthorized(request, env)) return errorResponse("authentication_error", "Invalid admin API key.", 401);
  if (request.method === "POST" && url.pathname === "/auth/device/start") return startDeviceAuth(env);
  if (request.method === "POST" && url.pathname === "/auth/device/poll") return pollDeviceAuth(request, env);
  if (request.method === "GET" && url.pathname === "/auth/accounts") return json({ data: await listAccounts(env) });
  if (request.method === "DELETE" && url.pathname.startsWith("/auth/accounts/")) {
    const accountId = url.pathname.split("/").pop();
    if (!accountId) return errorResponse("invalid_request_error", "Account ID is required.", 400);
    await disableAccount(env, accountId);
    return json({ ok: true });
  }
  return errorResponse("invalid_request_error", "Unknown authentication endpoint.", 404);
}

async function startDeviceAuth(env: Env): Promise<Response> {
  try {
    const session = await startDeviceLogin(env);
    return json({
      login_id: session.id,
      verification_url: DEVICE_VERIFICATION_URL,
      user_code: session.userCode,
      interval_seconds: session.intervalSeconds,
      expires_at: session.expiresAt,
    });
  } catch (error) {
    return mapError(error);
  }
}

async function pollDeviceAuth(request: Request, env: Env): Promise<Response> {
  try {
    const payload: unknown = await request.json();
    if (!isRecord(payload) || typeof payload.login_id !== "string") return errorResponse("invalid_request_error", "login_id is required.", 400);
    const label = typeof payload.label === "string" ? payload.label : "";
    const session = await pollDeviceLogin(env, payload.login_id, label);
    return json({ login_id: session.id, status: session.status });
  } catch (error) {
    return mapError(error);
  }
}

function isAuthorized(request: Request, env: Env): boolean {
  const authorization = request.headers.get("authorization") ?? "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();
  const apiKey = bearer ?? request.headers.get("x-api-key")?.trim();
  return Boolean(apiKey && apiKey === env.GATEWAY_API_KEY);
}

function authorizedApi(request: Request, env: Env): boolean {
  return isAuthorized(request, env);
}

function isAdminAuthorized(request: Request, env: Env): boolean {
  const authorization = request.headers.get("authorization") ?? "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();
  const adminKey = bearer ?? request.headers.get("x-admin-key")?.trim();
  return Boolean(adminKey && adminKey === env.GATEWAY_ADMIN_KEY);
}

async function proxyResponse(response: Response): Promise<Response> {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(corsHeaders())) headers.set(key, value);
  headers.delete("content-length");
  return new Response(response.body, { status: response.status, headers });
}

function modelsResponse(): Response {
  const created = Math.floor(Date.now() / 1000);
  return json({ object: "list", data: [
    { id: DEFAULT_CHAT_MODEL, object: "model", created, owned_by: "openai-chatgpt" },
    { id: IMAGE_MODEL, object: "model", created, owned_by: "openai-chatgpt" },
  ] });
}

function mapError(error: unknown): Response {
  if (error instanceof GatewayRequestError) return errorResponse(error.type, error.message, error.status);
  if (error instanceof UpstreamError) return errorResponse(error.type, error.message, error.status);
  if (error instanceof SyntaxError) return errorResponse("invalid_request_error", "Request body must be valid JSON.", 400);
  const message = error instanceof Error ? error.message : "Unexpected gateway error.";
  return errorResponse("server_error", message, 500);
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...corsHeaders() },
  });
}

function errorResponse(type: string, message: string, status: number): Response {
  return json({ error: { type, message } }, status);
}

function corsHeaders(): Record<string, string> {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "authorization, content-type, x-api-key, x-admin-key",
    "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
