export interface CodexHostProbeResult {
  readonly host: string;
  readonly path: string;
  readonly status: number;
  readonly ok: boolean;
  readonly contentType: string | null;
  readonly cfRay: string | null;
  readonly server: string | null;
  readonly location: string | null;
  readonly bodyPrefix: string;
}

const CANDIDATE_HOSTS = ["api.chatgpt.com", "api.chatgpt-staging.com", "www.chatgpt.com", "www.chatgpt-staging.com"] as const;
const CODEX_PATHS = ["/backend-api/codex/models", "/backend-api/codex/responses"] as const;

export async function probeCodexHosts(): Promise<readonly CodexHostProbeResult[]> {
  return Promise.all(CANDIDATE_HOSTS.flatMap((host) => CODEX_PATHS.map((path) => probeHost(host, path))));
}

async function probeHost(host: string, path: string): Promise<CodexHostProbeResult> {
  const isResponses = path.endsWith("/responses");
  const response = await fetch(`https://${host}${path}`, {
    method: isResponses ? "POST" : "GET",
    redirect: "manual",
    cf: { cacheTtl: 0, cacheEverything: false },
    headers: {
      Accept: isResponses ? "text/event-stream" : "application/json, text/plain, */*",
      "Content-Type": "application/json",
      "User-Agent": "9Router/3 Codex-Compatible",
    },
    body: isResponses ? JSON.stringify({ model: "gpt-5.4", input: [{ role: "user", content: [{ type: "input_text", text: "ping" }] }], stream: true, store: false }) : undefined,
  });
  const body = await response.text();
  return { host, path, status: response.status, ok: response.ok, contentType: response.headers.get("content-type"), cfRay: response.headers.get("cf-ray"), server: response.headers.get("server"), location: response.headers.get("location"), bodyPrefix: body.slice(0, 160).replace(/\s+/gu, " ") };
}
