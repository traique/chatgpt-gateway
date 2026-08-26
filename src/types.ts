export interface Env {
  GATEWAY_API_KEY: string;
  ADMIN_USERNAME: string;
  ADMIN_PASSWORD: string;
  CHATGPT_CODEX_ENDPOINT: string;
  CHATGPT_CODEX_IMAGES_ENDPOINT: string;
  CHATGPT_AUTH_BASE_URL: string;
  CHATGPT_OAUTH_CLIENT_ID: string;
  CHATGPT_TOKEN_ENCRYPTION_KEY: string;
  DB: D1Database;
}

export interface ChatGptToken {
  accessToken: string;
  accountId: string;
}

export type ChatRole = "developer" | "system" | "user" | "assistant";

export interface ChatCompletionMessage {
  role: ChatRole;
  content: string;
}

export interface ChatCompletionRequest {
  model: string;
  messages: ChatCompletionMessage[];
  stream: boolean;
  maxTokens?: number;
  webSearch: boolean;
}

export interface ResponsesRequest {
  model: string;
  input: string | ResponsesInputItem[];
  instructions?: string;
  stream: boolean;
  maxOutputTokens?: number;
  webSearch: boolean;
}

export interface ResponsesInputItem {
  role: "developer" | "system" | "user" | "assistant";
  content: string | ResponsesContentItem[];
}

export interface ResponsesContentItem {
  type: "input_text" | "output_text";
  text: string;
}

export interface ImageGenerationRequest {
  model: string;
  prompt: string;
  n?: number;
  size?: string;
  quality?: string;
  background?: string;
}

export interface ImageEditRequest {
  model: string;
  prompt: string;
  image: string | string[];
}

export interface StoredAccount {
  id: string;
  label: string;
  accountId: string;
  accessTokenEncrypted: string;
  refreshTokenEncrypted: string;
  idTokenEncrypted?: string;
  expiresAt: number;
  status: "active" | "expired" | "disabled";
  cooldownUntil: number;
}

export interface DeviceLoginSession {
  id: string;
  deviceAuthId: string;
  userCode: string;
  intervalSeconds: number;
  expiresAt: number;
  status: "pending" | "completed" | "failed" | "expired";
}
