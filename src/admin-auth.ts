const SESSION_TTL_SECONDS = 60 * 60 * 12;
const PASSWORD_HASH_ITERATIONS = 120_000;
const PASSWORD_HASH_BYTES = 32;
const SESSION_TOKEN_BYTES = 32;

interface AdminSession {
  id: string;
  tokenHash: string;
  expiresAt: number;
}

export async function authenticateAdmin(env: Env, username: string, password: string): Promise<string | null> {
  if (username !== env.ADMIN_USERNAME || !password) return null;
  const valid = await verifyPassword(password, env.ADMIN_PASSWORD_HASH);
  if (!valid) return null;

  const sessionToken = randomHex(SESSION_TOKEN_BYTES);
  const sessionId = crypto.randomUUID();
  const tokenHash = await sha256(sessionToken);
  const expiresAt = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;

  await env.DB.prepare(
    "INSERT INTO admin_sessions (id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
  ).bind(sessionId, tokenHash, expiresAt, Math.floor(Date.now() / 1000)).run();

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

async function verifyPassword(password: string, encodedHash: string): Promise<boolean> {
  const parts = encodedHash.split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2-sha256") return false;

  const iterations = Number(parts[1]);
  if (!Number.isSafeInteger(iterations) || iterations < 100_000) return false;

  const salt = hexToBytes(parts[2]);
  const expected = hexToBytes(parts[3]);
  if (salt.length < 16 || expected.length !== PASSWORD_HASH_BYTES) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const derived = new Uint8Array(await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    key,
    PASSWORD_HASH_BYTES * 8,
  ));
  return constantTimeEqual(derived, expected);
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return bytesToHex(new Uint8Array(digest));
}

function randomHex(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return bytesToHex(bytes);
}

function hexToBytes(value: string): Uint8Array {
  if (!/^[0-9a-f]+$/i.test(value) || value.length % 2 !== 0) return new Uint8Array();
  const bytes = new Uint8Array(value.length / 2);
  for (let index = 0; index < bytes.length; index += 1) bytes[index] = Number.parseInt(value.slice(index * 2, index * 2 + 2), 16);
  return bytes;
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

interface Env {
  DB: D1Database;
  ADMIN_USERNAME: string;
  ADMIN_PASSWORD_HASH: string;
}

export const ADMIN_SESSION_COOKIE = "cg_admin_session";
export const ADMIN_SESSION_TTL_SECONDS = SESSION_TTL_SECONDS;
