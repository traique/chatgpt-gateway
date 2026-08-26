import { GatewayAuthError } from "./errors";
import type { ChatGptToken, Env } from "./types";

export async function getChatGptToken(env: Env): Promise<ChatGptToken> {
  const endpoint = `${env.CHATGPT_AUTH_TOKEN_PROVIDER_URL.replace(/\/$/u, "")}/v1/token`;
  const response = await fetch(endpoint, {
    headers: {
      Authorization: `Bearer ${env.CHATGPT_AUTH_TOKEN_PROVIDER_API_KEY}`,
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new GatewayAuthError(`Token provider returned HTTP ${response.status}.`);
  }

  const payload: unknown = await response.json();
  if (!isRecord(payload)) throw new GatewayAuthError("Token provider returned an invalid payload.");

  const accessToken = readString(payload.access_token) ?? readString(payload.accessToken);
  const accountId = readString(payload.account_id) ?? readString(payload.accountId);
  if (!accessToken || !accountId) {
    throw new GatewayAuthError("Token provider returned an invalid token payload.");
  }

  return { accessToken, accountId };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
