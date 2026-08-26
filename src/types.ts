export interface Env {
  GATEWAY_API_KEY: string;
  CHATGPT_AUTH_TOKEN_PROVIDER_URL: string;
  CHATGPT_AUTH_TOKEN_PROVIDER_API_KEY: string;
  CHATGPT_CODEX_ENDPOINT: string;
  CHATGPT_CODEX_IMAGES_ENDPOINT: string;
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
