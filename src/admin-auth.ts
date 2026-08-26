const SESSION_TTL_SECONDS = 60 * 60 * 12;
const SESSION_TOKEN_BYTES = 32;

export const ADMIN_SESSION_COOKIE = "cg_admin_session";

export async function authenticateAdmin(env: Env, username: string, password: string): Promise<string | null> {
  if (!username || !password || username !== env.ADMIN_USERNAME || password !== env.ADMIN_PASSWORD) return null;

  const sessionToken = randomHex(SESSION_TOKEN_BYTES);
  const tokenHash = await sha256(sessionToken);
  const now = Math.floor(Date.now() / 1000);
  const expiresAt = now + SESSION_TTL_SECONDS;

  await env.DB.prepare(
    "INSERT INTO admin_sessions (id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
  ).bind(crypto.randomUUID(), tokenHash, expiresAt, now).run();

  return sessionToken;
}

export async function isAdminSessionValid(env: Env, token: string | null): Promise<boolean> {
  if (!token) return false;
  const tokenHash = await sha256(token);
  const row = await env.DB.prepare(
    "SELECT id FROM admin_sessions WHERE token_hash = ? AND expires_at > ?",
  ).bind(tokenHash, Math.floor(Date.now() / 1000)).first<{ id: string }>();
  return Boolean(row);
}

export async function revokeAdminSession(env: Env, token: string | null): Promise<void> {
  if (!token) return;
  const tokenHash = await sha256(token);
  await env.DB.prepare("DELETE FROM admin_sessions WHERE token_hash = ?").bind(tokenHash).run();
}

export async function cleanupAdminSessions(env: Env): Promise<void> {
  await env.DB.prepare("DELETE FROM admin_sessions WHERE expires_at <= ?").bind(Math.floor(Date.now() / 1000)).run();
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function randomHex(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

interface Env {
  DB: D1Database;
  ADMIN_USERNAME: string;
  ADMIN_PASSWORD: string;
}
