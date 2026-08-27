export interface TransportProbeResult {
  readonly variant: string;
  readonly status: number;
  readonly ok: boolean;
  readonly contentType: string | null;
  readonly cfRay: string | null;
  readonly server: string | null;
  readonly location: string | null;
  readonly cfMitigated: string | null;
  readonly bodyPrefix: string;
}

const PROBE_URL = "https://chatgpt.com/robots.txt";
const PROBE_USER_AGENT = "9Router/3 Codex-Compatible";

export async function probeWorkerTransports(): Promise<readonly TransportProbeResult[]> {
  const probes: Array<Promise<TransportProbeResult>> = [
    runProbe("native-fetch", () => fetch(PROBE_URL, { method: "GET", redirect: "manual" })),
    runProbe("request-fetch", () => fetch(new Request(PROBE_URL, { method: "GET", redirect: "manual" }))),
    runProbe("request-headers", () => fetch(new Request(PROBE_URL, { method: "GET", redirect: "manual", headers: { Accept: "text/plain", "User-Agent": PROBE_USER_AGENT } }))),
    runProbe("cache-disabled", () => fetch(PROBE_URL, { method: "GET", redirect: "manual", cf: { cacheTtl: 0, cacheEverything: false } })),
    runProbe("cache-key", () => fetch(PROBE_URL, { method: "GET", redirect: "manual", cf: { cacheKey: `transport-probe-${crypto.randomUUID()}`, cacheTtl: 0, cacheEverything: false } })),
  ];
  return Promise.all(probes);
}

async function runProbe(variant: string, request: () => Promise<Response>): Promise<TransportProbeResult> {
  const response = await request();
  const body = await response.text();
  return { variant, status: response.status, ok: response.ok, contentType: response.headers.get("content-type"), cfRay: response.headers.get("cf-ray"), server: response.headers.get("server"), location: response.headers.get("location"), cfMitigated: response.headers.get("cf-mitigated"), bodyPrefix: body.slice(0, 160).replace(/\s+/gu, " ") };
}
