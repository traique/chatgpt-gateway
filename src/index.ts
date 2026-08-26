import { getChatGptToken } from "./auth";
import { GatewayRequestError, UpstreamError } from "./errors";
import { createChatCompletionResponse, createImageEditResponse, createImageResponse, createResponsesResponse } from "./providers";
import { validateChatRequest, validateImageEditRequest, validateImageGenerationRequest } from "./validation";
import type { Env } from "./types";

const DEFAULT_CHAT_MODEL = "chatgpt-gpt-5.6";
const IMAGE_MODEL = "chatgpt-gpt-image-2";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders() });
    if (!isAuthorized(request, env)) return errorResponse("authentication_error", "Invalid API key.", 401);

    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return json({ ok: true });
    if (request.method === "GET" && url.pathname === "/v1/models") return modelsResponse();
    if (request.method !== "POST") return errorResponse("invalid_request_error", "Method not allowed.", 405);

    try {
      const payload: unknown = await request.json();
      const token = await getChatGptToken(env);

      if (url.pathname === "/v1/chat/completions") {
        return proxyResponse(await createChatCompletionResponse(env, token, validateChatRequest(payload)));
      }
      if (url.pathname === "/v1/responses") {
        return proxyResponse(await createResponsesResponse(env, token, validateChatRequest(payload)));
      }
      if (url.pathname === "/v1/images/generations") {
        return proxyResponse(await createImageResponse(env, token, validateImageGenerationRequest(payload)));
      }
      if (url.pathname === "/v1/images/edits") {
        return proxyResponse(await createImageEditResponse(env, token, validateImageEditRequest(payload)));
      }
      return errorResponse("invalid_request_error", "Unknown endpoint.", 404);
    } catch (error) {
      return mapError(error);
    }
  },
} satisfies ExportedHandler<Env>;

function isAuthorized(request: Request, env: Env): boolean {
  const authorization = request.headers.get("authorization") ?? "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();
  const apiKey = bearer ?? request.headers.get("x-api-key")?.trim();
  return Boolean(apiKey && apiKey === env.GATEWAY_API_KEY);
}

async function proxyResponse(response: Response): Promise<Response> {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(corsHeaders())) headers.set(key, value);
  headers.delete("content-length");
  return new Response(response.body, { status: response.status, headers });
}

function modelsResponse(): Response {
  const created = Math.floor(Date.now() / 1000);
  return json({
    object: "list",
    data: [
      { id: DEFAULT_CHAT_MODEL, object: "model", created, owned_by: "openai-chatgpt" },
      { id: IMAGE_MODEL, object: "model", created, owned_by: "openai-chatgpt" },
    ],
  });
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
    "access-control-allow-headers": "authorization, content-type, x-api-key",
    "access-control-allow-methods": "GET, POST, OPTIONS",
  };
}
