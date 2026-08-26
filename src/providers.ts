import { UpstreamError } from "./errors";
import type { ChatGptToken, ChatCompletionRequest, Env, ImageEditRequest, ImageGenerationRequest } from "./types";
import { toResponsesInput } from "./validation";

export async function createResponsesResponse(
  env: Env,
  token: ChatGptToken,
  request: ChatCompletionRequest,
): Promise<Response> {
  const body: Record<string, unknown> = {
    model: normalizeChatModel(request.model),
    input: toResponsesInput(request.messages),
    stream: request.stream,
  };

  if (request.webSearch) body.tools = [{ type: "web_search" }];
  if (request.maxTokens !== undefined) body.max_output_tokens = request.maxTokens;

  return fetchCodex(env.CHATGPT_CODEX_ENDPOINT, token, body, request.stream);
}

export async function createChatCompletionResponse(
  env: Env,
  token: ChatGptToken,
  request: ChatCompletionRequest,
): Promise<Response> {
  const upstream = await createResponsesResponse(env, token, request);
  if (!request.stream) return mapResponseToChatCompletion(upstream, request.model);
  return mapStreamToChatCompletion(upstream, request.model);
}

export async function createImageResponse(
  env: Env,
  token: ChatGptToken,
  request: ImageGenerationRequest,
): Promise<Response> {
  const body: Record<string, unknown> = {
    model: "gpt-image-2",
    prompt: request.prompt,
    n: request.n ?? 1,
    size: request.size ?? "auto",
    quality: request.quality ?? "auto",
  };
  if (request.background) body.background = request.background;
  return fetchCodex(`${env.CHATGPT_CODEX_IMAGES_ENDPOINT}/generations`, token, body, false);
}

export async function createImageEditResponse(
  env: Env,
  token: ChatGptToken,
  request: ImageEditRequest,
): Promise<Response> {
  const body: Record<string, unknown> = {
    model: "gpt-image-2",
    prompt: request.prompt,
    images: Array.isArray(request.image) ? request.image : [request.image],
    n: 1,
    size: "auto",
    quality: "auto",
  };
  return fetchCodex(`${env.CHATGPT_CODEX_IMAGES_ENDPOINT}/edits`, token, body, false);
}

function normalizeChatModel(model: string): string {
  return model.startsWith("chatgpt-") ? model : `chatgpt-${model}`;
}

async function fetchCodex(
  endpoint: string,
  token: ChatGptToken,
  body: Record<string, unknown>,
  stream: boolean,
): Promise<Response> {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token.accessToken}`,
      "chatgpt-account-id": token.accountId,
      "content-type": "application/json",
      Accept: stream ? "text/event-stream" : "application/json",
    },
    body: JSON.stringify(body),
  });

  if (response.ok) return response;
  const message = await readUpstreamError(response);
  throw new UpstreamError(message, response.status);
}

async function readUpstreamError(response: Response): Promise<string> {
  const body = await response.text();
  if (!body) return `Upstream returned HTTP ${response.status}.`;
  try {
    const payload: unknown = JSON.parse(body);
    if (isRecord(payload) && isRecord(payload.error) && typeof payload.error.message === "string") {
      return payload.error.message;
    }
  } catch {
    // Preserve a short upstream diagnostic when it is not JSON.
  }
  return body.slice(0, 1_000);
}

async function mapResponseToChatCompletion(response: Response, model: string): Promise<Response> {
  const payload: unknown = await response.json();
  const text = extractOutputText(payload);
  const created = Math.floor(Date.now() / 1000);
  return jsonResponse({
    id: `chatcmpl-${crypto.randomUUID()}`,
    object: "chat.completion",
    created,
    model,
    choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }],
  });
}

function mapStreamToChatCompletion(response: Response, model: string): Response {
  if (!response.body) return new Response(null, { status: 502 });
  const stream = new TransformStream<Uint8Array, Uint8Array>({
    start(controller) {
      this.encoder = new TextEncoder();
      this.decoder = new TextDecoder();
      this.buffer = "";
      this.id = `chatcmpl-${crypto.randomUUID()}`;
      this.model = model;
      this.created = Math.floor(Date.now() / 1000);
      this.controller = controller;
    },
    transform: async function (chunk) {
      this.buffer += this.decoder.decode(chunk, { stream: true });
      const lines = this.buffer.split("\n");
      this.buffer = lines.pop() ?? "";
      for (const line of lines) emitDelta(this, line);
    },
    flush: function () {
      if (this.buffer) emitDelta(this, this.buffer);
      this.controller.enqueue(this.encoder.encode("data: [DONE]\n\n"));
      this.controller.terminate();
    },
  } as TransformStreamDefaultController<Uint8Array> & Record<string, unknown>);

  response.body.pipeTo(stream.writable);
  return new Response(stream.readable, {
    status: response.status,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
  });
}

function emitDelta(state: Record<string, unknown>, line: string): void {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) return;
  const data = trimmed.slice(5).trim();
  if (!data || data === "[DONE]") return;

  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return;
  }
  if (!isRecord(payload)) return;
  const eventType = typeof payload.type === "string" ? payload.type : "";
  if (eventType !== "response.output_text.delta") return;
  const delta = typeof payload.delta === "string" ? payload.delta : "";
  if (!delta) return;

  const encoder = state.encoder as TextEncoder;
  const controller = state.controller as TransformStreamDefaultController<Uint8Array>;
  const chunk = {
    id: state.id,
    object: "chat.completion.chunk",
    created: state.created,
    model: state.model,
    choices: [{ index: 0, delta: { content: delta }, finish_reason: null }],
  };
  controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
}

function extractOutputText(payload: unknown): string {
  if (!isRecord(payload)) return "";
  if (typeof payload.output_text === "string") return payload.output_text;
  const output = payload.output;
  if (!Array.isArray(output)) return "";
  const parts: string[] = [];
  for (const item of output) {
    if (!isRecord(item) || item.type !== "message" || !Array.isArray(item.content)) continue;
    for (const content of item.content) {
      if (isRecord(content) && content.type === "output_text" && typeof content.text === "string") parts.push(content.text);
    }
  }
  return parts.join("");
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
