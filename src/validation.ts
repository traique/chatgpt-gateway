import { GatewayRequestError } from "./errors";
import type { ChatCompletionMessage, ChatCompletionRequest, ImageEditRequest, ImageGenerationRequest, ResponsesContentItem, ResponsesInputItem, ResponsesRequest } from "./types";

const DEFAULT_CHAT_MODEL = "chatgpt-gpt-5.6";
const DEFAULT_IMAGE_MODEL = "chatgpt-gpt-image-2";
const MAX_MESSAGES = 100;
const MAX_PROMPT_LENGTH = 100_000;

export function validateChatRequest(input: unknown): ChatCompletionRequest {
  if (!isRecord(input)) throw new GatewayRequestError("Request body must be a JSON object.");
  const messages = input.messages;
  if (!Array.isArray(messages) || messages.length === 0) throw new GatewayRequestError("messages is required.");
  if (messages.length > MAX_MESSAGES) throw new GatewayRequestError(`messages cannot contain more than ${MAX_MESSAGES} items.`);
  if (input.temperature !== undefined) throw new GatewayRequestError("temperature is not supported by the Responses gateway.");
  return {
    model: readString(input.model) ?? DEFAULT_CHAT_MODEL,
    messages: messages.map(normalizeMessage),
    stream: input.stream === true,
    maxTokens: readPositiveInteger(input.max_tokens),
    webSearch: input.web_search === true,
  };
}

export function validateResponsesRequest(input: unknown): ResponsesRequest {
  if (!isRecord(input)) throw new GatewayRequestError("Request body must be a JSON object.");
  const rawInput = input.input;
  if (typeof rawInput !== "string" && !Array.isArray(rawInput)) throw new GatewayRequestError("input is required.");
  const normalizedInput = typeof rawInput === "string" ? rawInput : rawInput.map(normalizeResponsesInput);
  if (typeof normalizedInput === "string") validatePromptLength(normalizedInput);
  return {
    model: readString(input.model) ?? DEFAULT_CHAT_MODEL,
    input: normalizedInput,
    instructions: readString(input.instructions),
    stream: input.stream === true,
    maxOutputTokens: readPositiveInteger(input.max_output_tokens),
    webSearch: input.web_search === true || hasWebSearchTool(input.tools),
  };
}

export function validateImageGenerationRequest(input: unknown): ImageGenerationRequest {
  if (!isRecord(input)) throw new GatewayRequestError("Request body must be a JSON object.");
  const prompt = readString(input.prompt);
  if (!prompt) throw new GatewayRequestError("prompt is required.");
  validatePromptLength(prompt);
  const count = readPositiveInteger(input.n);
  if (count !== undefined && count > 4) throw new GatewayRequestError("n cannot be greater than 4.");
  return { model: readString(input.model) ?? DEFAULT_IMAGE_MODEL, prompt, n: count, size: readString(input.size), quality: readString(input.quality), background: readString(input.background) };
}

export function validateImageEditRequest(input: unknown): ImageEditRequest {
  if (!isRecord(input)) throw new GatewayRequestError("Request body must be a JSON object.");
  const prompt = readString(input.prompt);
  if (!prompt) throw new GatewayRequestError("prompt is required.");
  validatePromptLength(prompt);
  if (!isImageInput(input.image)) throw new GatewayRequestError("image must be a base64/data URL string or an array of strings.");
  return { model: readString(input.model) ?? DEFAULT_IMAGE_MODEL, prompt, image: input.image };
}

export function toResponsesInput(messages: readonly ChatCompletionMessage[]): string {
  return messages.map(({ role, content }) => `${role}: ${content}`).join("\n\n");
}

function normalizeMessage(input: unknown): ChatCompletionMessage {
  if (!isRecord(input)) throw new GatewayRequestError("Every message must be an object.");
  const role = input.role;
  const content = readString(input.content);
  if (!isChatRole(role) || !content) throw new GatewayRequestError("Every message needs a valid role and content.");
  return { role, content };
}

function normalizeResponsesInput(input: unknown): ResponsesInputItem {
  if (!isRecord(input) || !isResponsesRole(input.role)) throw new GatewayRequestError("Every Responses input item needs a valid role.");
  if (typeof input.content === "string") {
    validatePromptLength(input.content);
    return { role: input.role, content: input.content };
  }
  if (!Array.isArray(input.content)) throw new GatewayRequestError("Responses content must be a string or array.");
  const content = input.content.map(normalizeResponsesContent);
  return { role: input.role, content };
}

function normalizeResponsesContent(input: unknown): ResponsesContentItem {
  if (!isRecord(input) || (input.type !== "input_text" && input.type !== "output_text") || typeof input.text !== "string") {
    throw new GatewayRequestError("Unsupported Responses content item.");
  }
  validatePromptLength(input.text);
  return { type: input.type, text: input.text };
}

function hasWebSearchTool(value: unknown): boolean {
  return Array.isArray(value) && value.some((tool) => isRecord(tool) && tool.type === "web_search");
}

function isChatRole(value: unknown): value is ChatRole {
  return value === "developer" || value === "system" || value === "user" || value === "assistant";
}

function isResponsesRole(value: unknown): value is ResponsesInputItem["role"] {
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
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) throw new GatewayRequestError("Expected a positive integer.");
  return value;
}

function validatePromptLength(prompt: string): void {
  if (prompt.length > MAX_PROMPT_LENGTH) throw new GatewayRequestError(`prompt cannot exceed ${MAX_PROMPT_LENGTH} characters.`);
}
