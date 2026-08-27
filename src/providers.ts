import { UpstreamError } from "./errors";
import type { ChatGptToken, ChatCompletionRequest, Env, ImageEditRequest, ImageGenerationRequest, ResponsesRequest } from "./types";
import { toResponsesInput } from "./validation";

const MAX_UPSTREAM_ATTEMPTS = 3;
const RETRYABLE_STATUS_CODES = new Set([429, 502, 503, 504]);
const DEFAULT_CODEX_CLIENT_VERSION = "0.144.1";
const CODEX_ORIGINATOR = "codex_cli_rs";
const CODEX_USER_AGENT = "9Router/3 Codex-Compatible";
const CODEX_ORIGIN = "https://chatgpt.com";
const CODEX_REFERER = "https://chatgpt.com/";
const ALTERNATE_UPSTREAM_HOSTS = ["chatgpt.com", "chat.openai.com"];

export async function createResponsesResponse(env: Env, token: ChatGptToken, request: ResponsesRequest): Promise<Response> {
  const clientVersion = resolveCodexClientVersion(env);
  const body: Record<string, unknown> = { model: normalizeChatModel(request.model), input: request.input, stream: true, store: false };
  if (request.instructions) body.instructions = request.instructions;
  if (request.webSearch) body.tools = [{ type: "web_search" }];
  if (request.maxOutputTokens !== undefined) body.max_output_tokens = request.maxOutputTokens;
  const upstream = await fetchCodex(env.CHATGPT_CODEX_ENDPOINT, token, body, request.webSearch, clientVersion);
  if (request.stream) return upstream;
  return aggregateResponsesStream(upstream);
}

export async function createChatCompletionResponse(env: Env, token: ChatGptToken, request: ChatCompletionRequest): Promise<Response> {
  const upstream = await createResponsesResponse(env, token, { model: request.model, input: toResponsesInput(request.messages), stream: request.stream, maxOutputTokens: request.maxTokens, webSearch: request.webSearch });
  if (!request.stream) return mapResponseToChatCompletion(upstream, request.model);
  return mapStreamToChatCompletion(upstream, request.model);
}

export async function createImageResponse(env: Env, token: ChatGptToken, request: ImageGenerationRequest): Promise<Response> {
  const body: Record<string, unknown> = { model: "gpt-image-2", prompt: request.prompt, n: request.n ?? 1, size: request.size ?? "auto", quality: request.quality ?? "auto" };
  if (request.background) body.background = request.background;
  return fetchCodex(`${env.CHATGPT_CODEX_IMAGES_ENDPOINT}/generations`, token, body, false, resolveCodexClientVersion(env), false);
}

export async function createImageEditResponse(env: Env, token: ChatGptToken, request: ImageEditRequest): Promise<Response> {
  const body: Record<string, unknown> = { model: "gpt-image-2", prompt: request.prompt, images: Array.isArray(request.image) ? request.image : [request.image], n: 1, size: "auto", quality: "auto" };
  return fetchCodex(`${env.CHATGPT_CODEX_IMAGES_ENDPOINT}/edits`, token, body, false, resolveCodexClientVersion(env), false);
}

export async function diagnoseCodexUpstream(env: Env, token: ChatGptToken): Promise<Record<string, unknown>> {
  const configuredEndpoint = new URL(env.CHATGPT_CODEX_ENDPOINT);
  const hosts = Array.from(new Set([configuredEndpoint.hostname, ...ALTERNATE_UPSTREAM_HOSTS]));
  const checks = await Promise.all(hosts.flatMap((hostname) => [
    probeUpstream(`https://${hostname}/robots.txt`, token, false),
    probeUpstream(`https://${hostname}/backend-api/codex/models`, token, true),
    probeUpstream(`https://${hostname}/backend-api/codex/responses`, token, true),
    probeRedirect(`https://${hostname}/`, token),
  ]));
  return { generated_at: new Date().toISOString(), runtime: "cloudflare-worker", checks };
}

async function probeUpstream(url: string, token: ChatGptToken, authenticated: boolean): Promise<Record<string, unknown>> {
  const headers = authenticated ? createCodexHeaders(token, false, DEFAULT_CODEX_CLIENT_VERSION, true) : { Accept: "text/plain", "User-Agent": CODEX_USER_AGENT };
  const method = url.endsWith("/responses") ? "POST" : "GET";
  const init: RequestInit = { method, headers, redirect: "manual", cf: { cacheTtl: 0, cacheEverything: false } };
  if (method === "POST") init.body = JSON.stringify({ model: "gpt-5.4", input: [{ role: "user", content: [{ type: "input_text", text: "ping" }] }], stream: true, store: false });
  const response = await fetch(url, init);
  const body = await response.text();
  return { url, method, status: response.status, ok: response.ok, content_type: response.headers.get("content-type"), cf_mitigated: response.headers.get("cf-mitigated"), cf_ray: response.headers.get("cf-ray"), server: response.headers.get("server"), location: response.headers.get("location"), body_prefix: body.slice(0, 160).replace(/\s+/gu, " ") };
}

async function probeRedirect(url: string, token: ChatGptToken): Promise<Record<string, unknown>> {
  const response = await fetch(url, { method: "GET", headers: createCodexHeaders(token, false, DEFAULT_CODEX_CLIENT_VERSION, true), redirect: "manual", cf: { cacheTtl: 0, cacheEverything: false } });
  return { url, method: "GET", status: response.status, location: response.headers.get("location"), content_type: response.headers.get("content-type"), cf_ray: response.headers.get("cf-ray"), server: response.headers.get("server") };
}

function normalizeChatModel(model: string): string { return model.startsWith("chatgpt-") ? model.slice("chatgpt-".length) : model; }
function resolveCodexClientVersion(env: Env): string { return env.CHATGPT_CODEX_CLIENT_VERSION?.trim() || DEFAULT_CODEX_CLIENT_VERSION; }

async function fetchCodex(endpoint: string, token: ChatGptToken, body: Record<string, unknown>, webSearch: boolean, clientVersion: string, stream = true): Promise<Response> {
  let lastResponse: Response | null = null;
  for (let attempt = 1; attempt <= MAX_UPSTREAM_ATTEMPTS; attempt += 1) {
    const response = await fetch(endpoint, { method: "POST", headers: createCodexHeaders(token, webSearch, clientVersion, stream), body: JSON.stringify(body), redirect: "manual", cf: { cacheTtl: 0, cacheEverything: false } });
    if (response.ok) return response;
    lastResponse = response;
    if (!RETRYABLE_STATUS_CODES.has(response.status) || attempt === MAX_UPSTREAM_ATTEMPTS) break;
    const retryAfter = readRetryAfter(response.headers.get("retry-after"));
    await sleep(retryAfter ?? 250 * 2 ** (attempt - 1));
  }
  if (!lastResponse) throw new UpstreamError("No response from upstream.", 502);
  throw new UpstreamError(await readUpstreamError(lastResponse), lastResponse.status);
}

function createCodexHeaders(token: ChatGptToken, webSearch: boolean, clientVersion: string, stream: boolean): Record<string, string> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token.accessToken}`, "ChatGPT-Account-Id": token.accountId, "Content-Type": "application/json", Accept: stream ? "text/event-stream" : "application/json", "User-Agent": CODEX_USER_AGENT, originator: CODEX_ORIGINATOR, Version: clientVersion, Origin: CODEX_ORIGIN, Referer: CODEX_REFERER };
  if (webSearch) headers["x-oai-web-search-eligible"] = "true";
  return headers;
}

function readRetryAfter(value: string | null): number | undefined { if (!value) return undefined; const seconds = Number(value); if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 10_000); const timestamp = Date.parse(value); return Number.isNaN(timestamp) ? undefined : Math.min(Math.max(0, timestamp - Date.now()), 10_000); }
function sleep(milliseconds: number): Promise<void> { return new Promise((resolve) => setTimeout(resolve, milliseconds)); }
async function readUpstreamError(response: Response): Promise<string> { const body = await response.text(); if (!body) return `Upstream returned HTTP ${response.status}.`; const contentType = response.headers.get("content-type")?.toLowerCase() ?? ""; if (contentType.includes("text/html") || looksLikeHtml(body)) return `ChatGPT upstream returned an HTML block page (HTTP ${response.status}).`; try { const payload: unknown = JSON.parse(body); if (isRecord(payload) && isRecord(payload.error) && typeof payload.error.message === "string") return payload.error.message; } catch { /* Non-JSON upstream response. */ } return body.slice(0, 1_000); }
function looksLikeHtml(body: string): boolean { return /^\s*<!doctype\s+html[\s>]/iu.test(body) || /^\s*<html[\s>]/iu.test(body); }
async function aggregateResponsesStream(response: Response): Promise<Response> { const text = await response.text(); const outputText = extractStreamText(text); if (!outputText) throw new UpstreamError("ChatGPT Responses stream completed without assistant text.", 502); return jsonResponse({ object: "response", output_text: outputText, output: [{ type: "message", role: "assistant", content: [{ type: "output_text", text: outputText }] }] }); }
function extractStreamText(text: string): string { const parts: string[] = []; for (const line of text.split(/\r?\n/u)) { const data = line.trim().startsWith("data:") ? line.trim().slice(5).trim() : ""; if (!data || data === "[DONE]") continue; try { const payload: unknown = JSON.parse(data); if (isRecord(payload) && payload.type === "response.output_text.delta" && typeof payload.delta === "string") parts.push(payload.delta); } catch { /* Ignore malformed SSE frames. */ } } return parts.join(""); }
async function mapResponseToChatCompletion(response: Response, model: string): Promise<Response> { const payload: unknown = await response.json(); return jsonResponse({ id: `chatcmpl-${crypto.randomUUID()}`, object: "chat.completion", created: Math.floor(Date.now() / 1000), model, choices: [{ index: 0, message: { role: "assistant", content: extractOutputText(payload) }, finish_reason: "stop" }] }); }
function mapStreamToChatCompletion(response: Response, model: string): Response { if (!response.body) return new Response(null, { status: 502 }); const reader = response.body.getReader(); const decoder = new TextDecoder(); const encoder = new TextEncoder(); const id = `chatcmpl-${crypto.randomUUID()}`; const created = Math.floor(Date.now() / 1000); let buffer = ""; const stream = new ReadableStream<Uint8Array>({ async pull(controller) { const result = await reader.read(); if (result.done) { buffer += decoder.decode(); emitStreamLines(buffer, controller, encoder, id, created, model); controller.enqueue(encoder.encode("data: [DONE]\n\n")); controller.close(); return; } buffer += decoder.decode(result.value, { stream: true }); const lines = buffer.split("\n"); buffer = lines.pop() ?? ""; emitStreamLines(lines.join("\n"), controller, encoder, id, created, model); }, cancel() { void reader.cancel(); } }); return new Response(stream, { headers: { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache", connection: "keep-alive" } }); }
function emitStreamLines(text: string, controller: ReadableStreamDefaultController<Uint8Array>, encoder: TextEncoder, id: string, created: number, model: string): void { for (const line of text.split("\n")) { const data = line.trim().startsWith("data:") ? line.trim().slice(5).trim() : ""; if (!data || data === "[DONE]") continue; try { const payload: unknown = JSON.parse(data); if (!isRecord(payload) || payload.type !== "response.output_text.delta" || typeof payload.delta !== "string") continue; controller.enqueue(encoder.encode(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model, choices: [{ index: 0, delta: { content: payload.delta }, finish_reason: null }] })}\n\n`)); } catch { /* Ignore malformed SSE frames. */ } } }
function extractOutputText(payload: unknown): string { if (!isRecord(payload)) return ""; if (typeof payload.output_text === "string") return payload.output_text; if (!Array.isArray(payload.output)) return ""; const parts: string[] = []; for (const item of payload.output) { if (!isRecord(item) || item.type !== "message" || !Array.isArray(item.content)) continue; for (const content of item.content) if (isRecord(content) && content.type === "output_text" && typeof content.text === "string") parts.push(content.text); } return parts.join(""); }
function jsonResponse(value: unknown): Response { return new Response(JSON.stringify(value), { headers: { "content-type": "application/json", "cache-control": "no-store" } }); }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
