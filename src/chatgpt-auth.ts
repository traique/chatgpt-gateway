import { decryptSecret, encryptSecret } from "./crypto";
import { GatewayAuthError } from "./errors";
import type { ChatGptToken, DeviceLoginSession, Env, StoredAccount } from "./types";

const TOKEN_REFRESH_WINDOW_MS = 5 * 60 * 1000;
const DEVICE_LOGIN_TTL_MS = 15 * 60 * 1000;
const REFRESH_LEASE_MS = 30 * 1000;
const OAUTH_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback";

export async function startDeviceLogin(env: Env): Promise<DeviceLoginSession> {
  const response = await fetch(`${trimBaseUrl(env.CHATGPT_AUTH_BASE_URL)}/api/accounts/deviceauth/usercode`, {
    method: "POST",
    headers: { "content-type": "application/json", "user-agent": "Codex/ChatGPT-Gateway" },
    body: JSON.stringify({ client_id: env.CHATGPT_OAUTH_CLIENT_ID }),
  });
  if (!response.ok) throw new GatewayAuthError(`Device login initialization failed: HTTP ${response.status}.`);

  const payload: unknown = await response.json();
  const deviceAuthId = readString(payload, "device_auth_id");
  const userCode = readString(payload, "user_code") ?? readString(payload, "usercode");
  const intervalSeconds = readNumber(payload, "interval") ?? 5;
  if (!deviceAuthId || !userCode) throw new GatewayAuthError("Device login returned an invalid payload.");

  const now = Date.now();
  const session: DeviceLoginSession = {
    id: crypto.randomUUID(),
    deviceAuthId,
    userCode,
    intervalSeconds,
    expiresAt: now + DEVICE_LOGIN_TTL_MS,
    status: "pending",
  };

  await env.DB.prepare(
    "INSERT INTO login_sessions (id, device_auth_id, user_code, interval_seconds, expires_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
  ).bind(session.id, session.deviceAuthId, session.userCode, session.intervalSeconds, session.expiresAt, now, now).run();

  return session;
}

export async function pollDeviceLogin(env: Env, sessionId: string, label: string): Promise<DeviceLoginSession> {
  const session = await getSession(env, sessionId);
  if (!session) throw new GatewayAuthError("Login session not found.");
  if (session.status !== "pending") return session;
  if (Date.now() >= session.expiresAt) return updateSessionStatus(env, session, "expired");

  const response = await fetch(`${trimBaseUrl(env.CHATGPT_AUTH_BASE_URL)}/api/accounts/deviceauth/token`, {
    method: "POST",
    headers: { "content-type": "application/json", "user-agent": "Codex/ChatGPT-Gateway" },
    body: JSON.stringify({ device_auth_id: session.deviceAuthId, user_code: session.userCode }),
  });

  if (response.status === 403 || response.status === 404) return session;
  if (!response.ok) {
    await updateSessionStatus(env, session, "failed");
    throw new GatewayAuthError(`Device login failed: HTTP ${response.status}.`);
  }

  const payload: unknown = await response.json();
  const authorizationCode = readString(payload, "authorization_code");
  const codeVerifier = readString(payload, "code_verifier");
  if (!authorizationCode || !codeVerifier) throw new GatewayAuthError("Device login returned an invalid authorization payload.");

  const tokens = await exchangeAuthorizationCode(env, authorizationCode, codeVerifier);
  const accountId = extractAccountId(tokens.idToken) ?? extractAccountId(tokens.accessToken);
  if (!accountId) throw new GatewayAuthError("ChatGPT token response did not contain an account ID.");

  const now = Date.now();
  const accountRecord = {
    id: crypto.randomUUID(),
    label: label.trim() || `ChatGPT ${new Date(now).toISOString()}`,
    accountId,
    accessTokenEncrypted: await encryptSecret(tokens.accessToken, env.CHATGPT_TOKEN_ENCRYPTION_KEY),
    refreshTokenEncrypted: await encryptSecret(tokens.refreshToken, env.CHATGPT_TOKEN_ENCRYPTION_KEY),
    idTokenEncrypted: tokens.idToken ? await encryptSecret(tokens.idToken, env.CHATGPT_TOKEN_ENCRYPTION_KEY) : null,
    expiresAt: now + tokens.expiresIn * 1000,
  };

  await env.DB.prepare(
    "INSERT INTO accounts (id, label, account_id, access_token_enc, refresh_token_enc, id_token_enc, expires_at, status, cooldown_until, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)",
  ).bind(accountRecord.id, accountRecord.label, accountRecord.accountId, accountRecord.accessTokenEncrypted, accountRecord.refreshTokenEncrypted, accountRecord.idTokenEncrypted, accountRecord.expiresAt, now, now).run();

  return updateSessionStatus(env, session, "completed");
}

export async function getChatGptToken(env: Env): Promise<ChatGptToken> {
  const account = await selectAccount(env);
  if (!account) throw new GatewayAuthError("No active ChatGPT account is configured. Start a device login first.");
  if (account.expiresAt > Date.now() + TOKEN_REFRESH_WINDOW_MS) {
    return { accessToken: await decryptSecret(account.accessTokenEncrypted, env.CHATGPT_TOKEN_ENCRYPTION_KEY), accountId: account.accountId };
  }
  return refreshAccount(env, account);
}

export async function listAccounts(env: Env): Promise<Array<{ id: string; label: string; accountId: string; status: string; expiresAt: number }>> {
  const result = await env.DB.prepare("SELECT id, label, account_id, status, expires_at FROM accounts ORDER BY created_at DESC").all();
  return result.results.map((row) => ({
    id: String(row.id),
    label: String(row.label),
    accountId: String(row.account_id),
    status: String(row.status),
    expiresAt: Number(row.expires_at),
  }));
}

export async function disableAccount(env: Env, accountId: string): Promise<void> {
  await env.DB.prepare("UPDATE accounts SET status = 'disabled', updated_at = ? WHERE id = ?").bind(Date.now(), accountId).run();
}

async function refreshAccount(env: Env, account: StoredAccount): Promise<ChatGptToken> {
  const leaseUntil = Date.now() + REFRESH_LEASE_MS;
  const lease = await env.DB.prepare(
    "UPDATE accounts SET cooldown_until = ?, updated_at = ? WHERE id = ? AND status = 'active' AND cooldown_until < ?",
  ).bind(leaseUntil, Date.now(), account.id, Date.now()).run();

  if (lease.meta.changes === 0) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const latest = await selectAccount(env);
    if (!latest) throw new GatewayAuthError("No active ChatGPT account is available.");
    const accessToken = await decryptSecret(latest.accessTokenEncrypted, env.CHATGPT_TOKEN_ENCRYPTION_KEY);
    return { accessToken, accountId: latest.accountId };
  }

  try {
    const refreshToken = await decryptSecret(account.refreshTokenEncrypted, env.CHATGPT_TOKEN_ENCRYPTION_KEY);
    const tokens = await exchangeRefreshToken(env, refreshToken);
    const now = Date.now();
    const encryptedAccessToken = await encryptSecret(tokens.accessToken, env.CHATGPT_TOKEN_ENCRYPTION_KEY);
    const encryptedRefreshToken = await encryptSecret(tokens.refreshToken, env.CHATGPT_TOKEN_ENCRYPTION_KEY);
    const encryptedIdToken = tokens.idToken ? await encryptSecret(tokens.idToken, env.CHATGPT_TOKEN_ENCRYPTION_KEY) : account.idTokenEncrypted;
    await env.DB.prepare(
      "UPDATE accounts SET access_token_enc = ?, refresh_token_enc = ?, id_token_enc = ?, expires_at = ?, cooldown_until = 0, last_error = NULL, updated_at = ? WHERE id = ?",
    ).bind(encryptedAccessToken, encryptedRefreshToken, encryptedIdToken ?? null, now + tokens.expiresIn * 1000, now, account.id).run();
    return { accessToken: tokens.accessToken, accountId: account.accountId };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Token refresh failed.";
    await env.DB.prepare("UPDATE accounts SET cooldown_until = 0, last_error = ?, updated_at = ? WHERE id = ?").bind(message.slice(0, 500), Date.now(), account.id).run();
    throw error;
  }
}

async function selectAccount(env: Env): Promise<StoredAccount | null> {
  const row = await env.DB.prepare(
    "SELECT id, label, account_id, access_token_enc, refresh_token_enc, id_token_enc, expires_at, status, cooldown_until FROM accounts WHERE status = 'active' AND cooldown_until < ? ORDER BY expires_at DESC LIMIT 1",
  ).bind(Date.now()).first();
  if (!row) return null;
  return {
    id: String(row.id),
    label: String(row.label),
    accountId: String(row.account_id),
    accessTokenEncrypted: String(row.access_token_enc),
    refreshTokenEncrypted: String(row.refresh_token_enc),
    idTokenEncrypted: row.id_token_enc ? String(row.id_token_enc) : undefined,
    expiresAt: Number(row.expires_at),
    status: String(row.status) as StoredAccount["status"],
    cooldownUntil: Number(row.cooldown_until),
  };
}

async function getSession(env: Env, sessionId: string): Promise<DeviceLoginSession | null> {
  const row = await env.DB.prepare("SELECT id, device_auth_id, user_code, interval_seconds, expires_at, status FROM login_sessions WHERE id = ?").bind(sessionId).first();
  if (!row) return null;
  return {
    id: String(row.id),
    deviceAuthId: String(row.device_auth_id),
    userCode: String(row.user_code),
    intervalSeconds: Number(row.interval_seconds),
    expiresAt: Number(row.expires_at),
    status: String(row.status) as DeviceLoginSession["status"],
  };
}

async function updateSessionStatus(env: Env, session: DeviceLoginSession, status: DeviceLoginSession["status"]): Promise<DeviceLoginSession> {
  await env.DB.prepare("UPDATE login_sessions SET status = ?, updated_at = ? WHERE id = ?").bind(status, Date.now(), session.id).run();
  return { ...session, status };
}

async function exchangeAuthorizationCode(env: Env, code: string, codeVerifier: string): Promise<OAuthTokenResponse> {
  return exchangeOAuth(env, {
    grant_type: "authorization_code",
    code,
    redirect_uri: OAUTH_REDIRECT_URI,
    client_id: env.CHATGPT_OAUTH_CLIENT_ID,
    code_verifier: codeVerifier,
  });
}

async function exchangeRefreshToken(env: Env, refreshToken: string): Promise<OAuthTokenResponse> {
  return exchangeOAuth(env, {
    grant_type: "refresh_token",
    refresh_token: refreshToken,
    client_id: env.CHATGPT_OAUTH_CLIENT_ID,
  });
}

async function exchangeOAuth(env: Env, parameters: Record<string, string>): Promise<OAuthTokenResponse> {
  const response = await fetch(`${trimBaseUrl(env.CHATGPT_AUTH_BASE_URL)}/oauth/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", "user-agent": "Codex/ChatGPT-Gateway" },
    body: new URLSearchParams(parameters),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new GatewayAuthError(`OAuth token exchange failed: HTTP ${response.status}${body ? `: ${body.slice(0, 300)}` : ""}`);
  }
  const payload: unknown = await response.json();
  const accessToken = readString(payload, "access_token");
  const refreshToken = readString(payload, "refresh_token");
  const idToken = readString(payload, "id_token");
  const expiresIn = readNumber(payload, "expires_in") ?? 3600;
  if (!accessToken || !refreshToken) throw new GatewayAuthError("OAuth token response is missing required tokens.");
  return { accessToken, refreshToken, idToken, expiresIn };
}

function extractAccountId(token: string | undefined): string | undefined {
  if (!token) return undefined;
  const parts = token.split(".");
  if (parts.length < 2) return undefined;
  try {
    const payload = JSON.parse(new TextDecoder().decode(fromBase64Url(parts[1]))) as Record<string, unknown>;
    if (typeof payload.chatgpt_account_id === "string") return payload.chatgpt_account_id;
    const auth = payload["https://api.openai.com/auth"];
    if (isRecord(auth) && typeof auth.chatgpt_account_id === "string") return auth.chatgpt_account_id;
    if (Array.isArray(payload.organizations) && isRecord(payload.organizations[0]) && typeof payload.organizations[0].id === "string") return payload.organizations[0].id;
  } catch {
    return undefined;
  }
  return undefined;
}

interface OAuthTokenResponse {
  accessToken: string;
  refreshToken: string;
  idToken?: string;
  expiresIn: number;
}

function readString(payload: unknown, key: string): string | undefined {
  return isRecord(payload) && typeof payload[key] === "string" && payload[key] ? payload[key] : undefined;
}

function readNumber(payload: unknown, key: string): number | undefined {
  if (!isRecord(payload)) return undefined;
  const value = payload[key];
  const numberValue = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(numberValue) ? numberValue : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fromBase64Url(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(normalized);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function trimBaseUrl(value: string): string {
  return value.replace(/\/$/u, "");
}
