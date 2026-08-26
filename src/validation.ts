import { GatewayRequestError } from "./errors";
import type { ChatCompletionMessage, ChatCompletionRequest, ImageEditRequest, ImageGenerationRequest } from "./types";

const DEFAULT_CHAT_MODEL = "chatgpt-gpt-5.6";
const DEFAULT_IMAGE_MODEL = "chatgpt-gpt-image-2";
const MAX_MESSAGES = 100;
const MAX_PROMPT_LENGTH = 100_000;

export function validateChatRequest(input: unknown): ChatCompletionRequest {
  if (!isRecord(input)) throw new GatewayRequestError("Request body must be a JSON object.");

  const messages = input.messages;
  if (!Array.isArray(messages) || messages.length === 0) {
    throw new GatewayRequestError("messages is required.");
  }
  if (messages.length > MAX_MESSAGES) {
    throw new GatewayRequestError(`messages cannot contain more than ${MAX_MESSAGES} items.`);
  }

  const normalizedMessages = messages.map(normalizeMessage);
  const model = readString(input.model) ?? DEFAULT_CHAT_MODEL;
  const maxTokens = readPositiveInteger(input.max_tokens);

  if (input.temperature !== undefined) {
    throw new GatewayRequestError("temperature is not supported by the Responses gateway.");
  }

  return {
    model,
    messages: normalizedMessages,
    stream: input.stream === true,
    maxTokens,
    webSearch: input.web_search === true,
  };
}

export function validateImageGenerationRequest(input: unknown): ImageGenerationRequest {
  if (!isRecord(input)) throw new GatewayRequestError("Request body must be a JSON object.");

  const prompt = readString(input.prompt);
  if (!prompt) throw new GatewayRequestError("prompt is required.");
  validatePromptLength(prompt);

  const count = readPositiveInteger(input.n);
  if (count !== undefined && count > 4) {
    throw new GatewayRequestError("n cannot be greater than 4.");
  }

  return {
    model: readString(input.model) ?? DEFAULT_IMAGE_MODEL,
    prompt,
    n: count,
    size: readString(input.size),
    quality: readString(input.quality),
    background: readString(input.background),
  };
}

export function validateImageEditRequest(input: unknown): ImageEditRequest {
  if (!isRecord(input)) throw new GatewayRequestError("Request body must be a JSON object.");

  const prompt = readString(input.prompt);
  const image = input.image;
  if (!prompt) throw new GatewayRequestError("prompt is required.");
  validatePromptLength(prompt);
  if (!isImageInput(image)) {
    throw new GatewayRequestError("image must be a base64/data URL string or an array of strings.");
  }

  return { model: readString(input.model) ?? DEFAULT_IMAGE_MODEL, prompt, image };
}

export function toResponsesInput(messages: readonly ChatCompletionMessage[]): string {
  return messages.map(({ role, content }) => `${role}: ${content}`).join("\n\n");
}

function normalizeMessage(input: unknown): ChatCompletionMessage {
  if (!isRecord(input)) throw new GatewayRequestError("Every message must be an object.");

  const role = input.role;
  const content = readString(input.content);
  if (!isChatRole(role) || !content) {
    throw new GatewayRequestError("Every message needs a valid role and content.");
  }
  return { role, content };
}

function isChatRole(value: unknown): value is ChatCompletionMessage["role"] {
  return value === "developer" || value === "system" || value === "user" || value === "assistant";
}

function isImageInput(value: unknown): value is string | string[] {
  return typeof value === "string" || (Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "string"));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function readPositiveInteger(value: unknown): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
    throw new GatewayRequestError("Expected a positive integer.");
  }
  return value;
}

function validatePromptLength(prompt: string): void {
  if (prompt.length > MAX_PROMPT_LENGTH) {
    throw new GatewayRequestError(`prompt cannot exceed ${MAX_PROMPT_LENGTH} characters.`);
  }
}
