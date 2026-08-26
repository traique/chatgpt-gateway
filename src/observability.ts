import type { Env } from "./types";

const USAGE_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const RATE_WINDOW_MS = 60_000;
const DEFAULT_RATE_LIMIT = 60;

export interface RequestContext {
  requestId: string;
  startedAt: number;
}

export interface RateLimitResult {
  allowed: boolean;
  remaining: number;
  resetAt: number;
}

export function createRequestContext(): RequestContext {
  return { requestId: crypto.randomUUID(), startedAt: Date.now() };
}

export async function enforceRateLimit(env: Env, key: string, limit = DEFAULT_RATE_LIMIT): Promise<RateLimitResult> {
  const now = Date.now();
  const windowStart = Math.floor(now / RATE_WINDOW_MS) * RATE_WINDOW_MS;
  const bucket = `${key}:${windowStart}`;
  const row = await env.DB.prepare("SELECT request_count FROM rate_limits WHERE bucket = ?").bind(bucket).first<{ request_count: number }>();
  const requestCount = Number(row?.request_count ?? 0);
  if (requestCount >= limit) return { allowed: false, remaining: 0, resetAt: windowStart + RATE_WINDOW_MS };

  await env.DB.prepare(
    "INSERT INTO rate_limits (bucket, window_start, request_count) VALUES (?, ?, 1) ON CONFLICT(bucket) DO UPDATE SET request_count = request_count + 1",
  ).bind(bucket, windowStart).run();

  return { allowed: true, remaining: Math.max(0, limit - requestCount - 1), resetAt: windowStart + RATE_WINDOW_MS };
}

export async function recordUsage(env: Env, route: string, model: string, status: number, latencyMs: number, accountId?: string, clientHash?: string): Promise<void> {
  const now = Date.now();
  await env.DB.prepare(
    "INSERT INTO usage_events (id, created_at, route, model, status, latency_ms, account_id, client_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
  ).bind(crypto.randomUUID(), now, route, model, status, latencyMs, accountId ?? null, clientHash ?? null).run();
  await env.DB.prepare("DELETE FROM usage_events WHERE created_at < ?").bind(now - USAGE_RETENTION_MS).run();
  await env.DB.prepare("DELETE FROM rate_limits WHERE window_start < ?").bind(now - RATE_WINDOW_MS * 2).run();
}

export async function getUsageSummary(env: Env): Promise<UsageSummary> {
  const since = Date.now() - USAGE_RETENTION_MS;
  const result = await env.DB.prepare(
    "SELECT COUNT(*) AS total, SUM(CASE WHEN status >= 200 AND status < 400 THEN 1 ELSE 0 END) AS successful, AVG(latency_ms) AS avg_latency_ms FROM usage_events WHERE created_at >= ?",
  ).bind(since).first<{ total: number; successful: number; avg_latency_ms: number }>();
  return {
    windowMs: USAGE_RETENTION_MS,
    totalRequests: Number(result?.total ?? 0),
    successfulRequests: Number(result?.successful ?? 0),
    failedRequests: Math.max(0, Number(result?.total ?? 0) - Number(result?.successful ?? 0)),
    averageLatencyMs: Math.round(Number(result?.avg_latency_ms ?? 0)),
  };
}

export interface UsageSummary {
  windowMs: number;
  totalRequests: number;
  successfulRequests: number;
  failedRequests: number;
  averageLatencyMs: number;
}
