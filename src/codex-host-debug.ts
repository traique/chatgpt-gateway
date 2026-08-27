export interface CodexHostProbeResult {
  readonly host: string;
  readonly path: string;
  readonly status: number;
  readonly ok: boolean;
  readonly contentType: string | null;
  readonly cfRay: string | null;
  readonly server: string | null;
  readonly location: string | null;
  readonly allow: string | null;
  readonly bodyPrefix: string;
}

const CODEX_HOST = "chatgpt.com";
const CODEX_RESPONSES_PATH = "/backend-api/codex/responses";
const CODEX_MODELS_PATH = "/backend-api/codex/models";
const CODEX_ORIGIN = "https://chatgpt.com";
const CODEX_REFERER = "https://chatgpt.com/";
const CODEX_ORIGINATOR = "codex_cli_rs";
const CODEX_VERSION = "0.144.1";
const CODEX_USER_AGENT = "9Router/3 Codex-Compatible";

export async function probeCodexRequestParity(accessToken?: string, accountId?: string): Promise<readonly CodexHostProbeResult[]> {
  const headers = createParityHeaders(accessToken, accountId);
  return Promise.all([
    probe("baseline-models", CODEX_MODELS_PATH, "GET", headers),
    probe("parity-models", CODEX_MODELS_PATH, "GET", headers),
    probe("parity-responses", CODEX_RESPONSES_PATH, "POST", headers),
  ]);
}

async function probe(variant: string, path: string, method: "GET" | "POST", headers: Headers): Promise<CodexHostProbeResult> {
  const requestHeaders = new Headers(headers);
  if (variant === "baseline-models") {
    requestHeaders.delete("originator");
    requestHeaders.delete("Version");
    requestHeaders.delete("Origin");
    requestHeaders.delete("Referer");
    requestHeaders.delete("User-Agent");
  }
  const response = await fetch(`https://${CODEX_HOST}${path}`, {
    method,
    redirect: "manual",
    headers: requestHeaders,
    cf: { cacheTtl: 0, cacheEverything: false },
    body: method === "POST" ? JSON.stringify({ model: "gpt-5.4", input: [{ role: "user", content: [{ type: "input_text", text: "ping" }] }], stream: true, store: false }) : undefined,
  });
  const body = await response.text();
  return {
    host: CODEX_HOST,
    path,
    status: response.status,
    ok: response.ok,
    contentType: response.headers.get("content-type"),
    cfRay: response.headers.get("cf-ray"),
    server: response.headers.get("server"),
    location: response.headers.get("location"),
    allow: response.headers.get("allow"),
    bodyPrefix: body.slice(0, 300).replace(/\s+/gu, " "),
  };
}

function createParityHeaders(accessToken?: string, accountId?: string): Headers {
  const headers = new Headers({
    Accept: "application/json, text/event-stream, */*",
    "Content-Type": "application/json",
    "User-Agent": CODEX_USER_AGENT,
    originator: CODEX_ORIGINATOR,
    Version: CODEX_VERSION,
    Origin: CODEX_ORIGIN,
    Referer: CODEX_REFERER,
  });
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (accountId) headers.set("ChatGPT-Account-Id", accountId);
  return headers;
}
