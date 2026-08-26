import { disableAccount, getChatGptToken, listAccounts, pollDeviceLogin, startDeviceLogin } from "./auth";
import { GatewayRequestError, UpstreamError } from "./errors";
import { createChatCompletionResponse, createImageEditResponse, createImageResponse, createResponsesResponse } from "./providers";
import { createRequestContext, enforceRateLimit, getUsageSummary, recordUsage } from "./observability";
import { validateChatRequest, validateImageEditRequest, validateImageGenerationRequest, validateResponsesRequest } from "./validation";
import type { Env } from "./types";

const DEFAULT_CHAT_MODEL = "chatgpt-gpt-5.6";
const IMAGE_MODEL = "chatgpt-gpt-image-2";
const DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device";
const API_RATE_LIMIT = 60;

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders() });
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return json({ ok: true, service: "chatgpt-gateway" });
    if (url.pathname.startsWith("/auth/")) return handleAuthRoute(request, env, url);
    if (!isAuthorized(request, env)) return errorResponse("authentication_error", "Invalid API key.", 401);
    if (request.method === "GET" && url.pathname === "/v1/models") return modelsResponse();
    if (request.method === "GET" && url.pathname === "/v1/usage") return json(await getUsageSummary(env));
    if (request.method !== "POST") return errorResponse("invalid_request_error", "Method not allowed.", 405);
    return handleApiRequest(request, env, url);
  },
} satisfies ExportedHandler<Env>;

async function handleApiRequest(request: Request, env: Env, url: URL): Promise<Response> {
  const context = createRequestContext();
  const rateLimit = await enforceRateLimit(env, await hashClientKey(request), API_RATE_LIMIT);
  if (!rateLimit.allowed) return rateLimitResponse(rateLimit.resetAt);
  try {
    const payload: unknown = await request.json();
    const token = await getChatGptToken(env);
    const response = await routeApiRequest(url.pathname, env, token, payload);
    await recordUsage(env, url.pathname, readModel(payload), response.status, Date.now() - context.startedAt, token.accountId);
    return withRateLimitHeaders(response, rateLimit.remaining, rateLimit.resetAt);
  } catch (error) {
    const response = mapError(error);
    await recordUsage(env, url.pathname, "unknown", response.status, Date.now() - context.startedAt);
    return withRateLimitHeaders(response, rateLimit.remaining, rateLimit.resetAt);
  }
}

async function routeApiRequest(pathname: string, env: Env, token: Awaited<ReturnType<typeof getChatGptToken>>, payload: unknown): Promise<Response> {
  if (pathname === "/v1/chat/completions") return proxyResponse(await createChatCompletionResponse(env, token, validateChatRequest(payload)));
  if (pathname === "/v1/responses") return proxyResponse(await createResponsesResponse(env, token, validateResponsesRequest(payload)));
  if (pathname === "/v1/images/generations") return proxyResponse(await createImageResponse(env, token, validateImageGenerationRequest(payload)));
  if (pathname === "/v1/images/edits") return proxyResponse(await createImageEditResponse(env, token, validateImageEditRequest(payload)));
  throw new GatewayRequestError("Unknown endpoint.");
}

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
    return json({ login_id: session.id, verification_url: DEVICE_VERIFICATION_URL, user_code: session.userCode, interval_seconds: session.intervalSeconds, expires_at: session.expiresAt });
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
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...corsHeaders() } });
}

function errorResponse(type: string, message: string, status: number): Response {
  return json({ error: { type, message } }, status);
}

function rateLimitResponse(resetAt: number): Response {
  return withRateLimitHeaders(errorResponse("rate_limit_error", "Rate limit exceeded.", 429), 0, resetAt);
}

function withRateLimitHeaders(response: Response, remaining: number, resetAt: number): Response {
  const headers = new Headers(response.headers);
  headers.set("x-ratelimit-remaining", String(remaining));
  headers.set("x-ratelimit-reset", String(Math.ceil(resetAt / 1000)));
  return new Response(response.body, { status: response.status, headers });
}

async function hashClientKey(request: Request): Promise<string> {
  const identity = request.headers.get("x-api-key") ?? request.headers.get("authorization") ?? request.headers.get("cf-connecting-ip") ?? "anonymous";
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

function readModel(payload: unknown): string {
  return isRecord(payload) && typeof payload.model === "string" ? payload.model : "unknown";
}

function corsHeaders(): Record<string, string> {
  return { "access-control-allow-origin": "*", "access-control-allow-headers": "authorization, content-type, x-api-key, x-admin-key", "access-control-allow-methods": "GET, POST, DELETE, OPTIONS" };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
