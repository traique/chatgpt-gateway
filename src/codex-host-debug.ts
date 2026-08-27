export interface CodexHostProbeResult {
  readonly host: string;
  readonly status: number;
  readonly ok: boolean;
  readonly contentType: string | null;
  readonly cfRay: string | null;
  readonly server: string | null;
  readonly location: string | null;
  readonly bodyPrefix: string;
}

const CANDIDATE_HOSTS = ["api.chatgpt.com", "api.chatgpt-staging.com", "www.chatgpt.com", "www.chatgpt-staging.com"] as const;

export async function probeCodexHosts(): Promise<readonly CodexHostProbeResult[]> {
  return Promise.all(CANDIDATE_HOSTS.map(probeHost));
}

async function probeHost(host: string): Promise<CodexHostProbeResult> {
  const response = await fetch(`https://${host}/backend-api/codex/models`, {
    method: "GET",
    redirect: "manual",
    cf: { cacheTtl: 0, cacheEverything: false },
    headers: { Accept: "application/json, text/plain, */*", "User-Agent": "9Router/3 Codex-Compatible" },
  });
  const body = await response.text();
  return { host, status: response.status, ok: response.ok, contentType: response.headers.get("content-type"), cfRay: response.headers.get("cf-ray"), server: response.headers.get("server"), location: response.headers.get("location"), bodyPrefix: body.slice(0, 160).replace(/\s+/gu, " ") };
}
