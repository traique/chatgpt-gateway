import { UpstreamError } from "./errors";
import type { ChatGptToken, ChatCompletionRequest, Env, ImageEditRequest, ImageGenerationRequest, ResponsesRequest } from "./types";
import { toResponsesInput } from "./validation";

const MAX_UPSTREAM_ATTEMPTS = 3;
const RETRYABLE_STATUS_CODES = new Set([429, 502, 503, 504]);
const DEFAULT_CODEX_CLIENT_VERSION = "0.148.0";
const CODEX_ORIGINATOR = "codex_cli_rs";
const CODEX_RESPONSES_BETA = "responses=experimental";

export async function createResponsesResponse(env: Env, token: ChatGptToken, request: ResponsesRequest): Promise<Response> {
  const clientVersion = resolveCodexClientVersion(env);
  const body: Record<string, unknown> = {
    model: normalizeChatModel(request.model),
    input: request.input,
    stream: request.stream,
    store: false,
    reasoning: { effort: "medium", summary: "auto" },
    include: ["reasoning.encrypted_content"],
  };
  if (request.instructions) body.instructions = request.instructions;
  if (request.webSearch) body.tools = [{ type: "web_search" }];
  if (request.maxOutputTokens !== undefined) body.max_output_tokens = request.maxOutputTokens;
  return fetchCodex(env.CHATGPT_CODEX_ENDPOINT, token, body, request.stream, request.webSearch, clientVersion);
}

export async function createChatCompletionResponse(env: Env, token: ChatGptToken, request: ChatCompletionRequest): Promise<Response> {
  const upstream = await createResponsesResponse(env, token, {
    model: request.model,
    input: toResponsesInput(request.messages),
    stream: request.stream,
    maxOutputTokens: request.maxTokens,
    webSearch: request.webSearch,
  });
  if (!request.stream) return mapResponseToChatCompletion(upstream, request.model);
  return mapStreamToChatCompletion(upstream, request.model);
}

export async function createImageResponse(env: Env, token: ChatGptToken, request: ImageGenerationRequest): Promise<Response> {
  const body: Record<string, unknown> = { model: "gpt-image-2", prompt: request.prompt, n: request.n ?? 1, size: request.size ?? "auto", quality: request.quality ?? "auto" };
  if (request.background) body.background = request.background;
  return fetchCodex(`${env.CHATGPT_CODEX_IMAGES_ENDPOINT}/generations`, token, body, false, false, resolveCodexClientVersion(env));
}

export async function createImageEditResponse(env: Env, token: ChatGptToken, request: ImageEditRequest): Promise<Response> {
  const body: Record<string, unknown> = { model: "gpt-image-2", prompt: request.prompt, images: Array.isArray(request.image) ? request.image : [request.image], n: 1, size: "auto", quality: "auto" };
  return fetchCodex(`${env.CHATGPT_CODEX_IMAGES_ENDPOINT}/edits`, token, body, false, false, resolveCodexClientVersion(env));
}

function normalizeChatModel(model: string): string {
  return model.startsWith("chatgpt-") ? model.slice("chatgpt-".length) : model;
}

function resolveCodexClientVersion(env: Env): string {
  const configuredVersion = env.CHATGPT_CODEX_CLIENT_VERSION?.trim();
  return configuredVersion || DEFAULT_CODEX_CLIENT_VERSION;
}

async function fetchCodex(
  endpoint: string,
  token: ChatGptToken,
  body: Record<string, unknown>,
  stream: boolean,
  webSearch: boolean,
  clientVersion: string,
): Promise<Response> {
  let lastResponse: Response | null = null;
  for (let attempt = 1; attempt <= MAX_UPSTREAM_ATTEMPTS; attempt += 1) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: createCodexHeaders(token, stream, webSearch, clientVersion),
      body: JSON.stringify(body),
    });
    if (response.ok) return response;
    lastResponse = response;
    if (!RETRYABLE_STATUS_CODES.has(response.status) || attempt === MAX_UPSTREAM_ATTEMPTS) break;
    const retryAfter = readRetryAfter(response.headers.get("retry-after"));
    await sleep(retryAfter ?? 250 * 2 ** (attempt - 1));
  }
  if (!lastResponse) throw new UpstreamError("No response from upstream.", 502);
  throw new UpstreamError(await readUpstreamError(lastResponse), lastResponse.status);
}

function createCodexHeaders(token: ChatGptToken, stream: boolean, webSearch: boolean, clientVersion: string): Record<string, string> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token.accessToken}`,
    "ChatGPT-Account-Id": token.accountId,
    "Content-Type": "application/json",
    Accept: stream ? "text/event-stream" : "application/json",
    "User-Agent": `codex_cli_rs/${clientVersion}`,
    originator: CODEX_ORIGINATOR,
    Version: clientVersion,
    "OpenAI-Beta": CODEX_RESPONSES_BETA,
    session_id: crypto.randomUUID(),
  };
  if (webSearch) headers["x-oai-web-search-eligible"] = "true";
  return headers;
}

function readRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 10_000);
  const timestamp = Date.parse(value);
  if (!Number.isNaN(timestamp)) return Math.min(Math.max(0, timestamp - Date.now()), 10_000);
  return undefined;
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function readUpstreamError(response: Response): Promise<string> {
  const body = await response.text();
  if (!body) return `Upstream returned HTTP ${response.status}.`;
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (contentType.includes("text/html") || looksLikeHtml(body)) {
    return `ChatGPT upstream returned an HTML block page (HTTP ${response.status}).`;
  }
  try {
    const payload: unknown = JSON.parse(body);
    if (isRecord(payload) && isRecord(payload.error) && typeof payload.error.message === "string") return payload.error.message;
  } catch {
    // Preserve a short diagnostic when the upstream body is not JSON.
  }
  return body.slice(0, 1_000);
}

function looksLikeHtml(body: string): boolean {
  return /^\s*<!doctype\s+html[\s>]/iu.test(body) || /^\s*<html[\s>]/iu.test(body);
}

async function mapResponseToChatCompletion(response: Response, model: string): Promise<Response> {
  const payload: unknown = await response.json();
  return jsonResponse({ id: `chatcmpl-${crypto.randomUUID()}`, object: "chat.completion", created: Math.floor(Date.now() / 1000), model, choices: [{ index: 0, message: { role: "assistant", content: extractOutputText(payload) }, finish_reason: "stop" }] });
}

function mapStreamToChatCompletion(response: Response, model: string): Response {
  if (!response.body) return new Response(null, { status: 502 });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const id = `chatcmpl-${crypto.randomUUID()}`;
  const created = Math.floor(Date.now() / 1000);
  let buffer = "";
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      const result = await reader.read();
      if (result.done) {
        buffer += decoder.decode();
        emitStreamLines(buffer, controller, encoder, id, created, model);
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
        return;
      }
      buffer += decoder.decode(result.value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      emitStreamLines(lines.join("\n"), controller, encoder, id, created, model);
    },
    cancel() { void reader.cancel(); },
  });
  return new Response(stream, { headers: { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache", connection: "keep-alive" } });
}

function emitStreamLines(text: string, controller: ReadableStreamDefaultController<Uint8Array>, encoder: TextEncoder, id: string, created: number, model: string): void {
  for (const line of text.split("\n")) {
    const data = line.trim().startsWith("data:") ? line.trim().slice(5).trim() : "";
    if (!data || data === "[DONE]") continue;
    let payload: unknown;
    try { payload = JSON.parse(data); } catch { continue; }
    if (!isRecord(payload) || payload.type !== "response.output_text.delta" || typeof payload.delta !== "string") continue;
    controller.enqueue(encoder.encode(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model, choices: [{ index: 0, delta: { content: payload.delta }, finish_reason: null }] })}\n\n`));
  }
}

function extractOutputText(payload: unknown): string {
  if (!isRecord(payload)) return "";
  if (typeof payload.output_text === "string") return payload.output_text;
  if (!Array.isArray(payload.output)) return "";
  const parts: string[] = [];
  for (const item of payload.output) {
    if (!isRecord(item) || item.type !== "message" || !Array.isArray(item.content)) continue;
    for (const content of item.content) if (isRecord(content) && content.type === "output_text" && typeof content.text === "string") parts.push(content.text);
  }
  return parts.join("");
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json", "cache-control": "no-store" } });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
