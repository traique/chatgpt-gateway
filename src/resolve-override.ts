const RESOLVE_OVERRIDE_HOSTS = ["chat.openai.com", "chatgpt.com", "chatgpt-staging.com"] as const;

export interface ResolveOverrideProbe {
  readonly targetHost: string;
  readonly resolveHost: string;
  readonly status: number;
  readonly ok: boolean;
  readonly contentType: string | null;
  readonly location: string | null;
  readonly cfRay: string | null;
  readonly server: string | null;
  readonly bodyPrefix: string;
}

export async function probeResolveOverrides(targetHost: string): Promise<readonly ResolveOverrideProbe[]> {
  const results: ResolveOverrideProbe[] = [];
  for (const resolveHost of RESOLVE_OVERRIDE_HOSTS) {
    results.push(await probeResolveOverride(targetHost, resolveHost));
  }
  return results;
}

async function probeResolveOverride(targetHost: string, resolveHost: string): Promise<ResolveOverrideProbe> {
  const response = await fetch(`https://${targetHost}/robots.txt`, {
    method: "GET",
    redirect: "manual",
    cf: {
      resolveOverride: resolveHost,
      cacheTtl: 0,
      cacheEverything: false,
    },
    headers: {
      Accept: "text/plain",
      "User-Agent": "9Router/3 Codex-Compatible",
    },
  });
  const body = await response.text();
  return {
    targetHost,
    resolveHost,
    status: response.status,
    ok: response.ok,
    contentType: response.headers.get("content-type"),
    location: response.headers.get("location"),
    cfRay: response.headers.get("cf-ray"),
    server: response.headers.get("server"),
    bodyPrefix: body.slice(0, 160).replace(/\s+/gu, " "),
  };
}
