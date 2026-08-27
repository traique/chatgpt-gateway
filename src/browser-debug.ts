import puppeteer from "@cloudflare/puppeteer";
import type { ChatGptToken, Env } from "./types";

const CHATGPT_URL = "https://chatgpt.com/";
const CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses";
const CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models";
const CODEX_ORIGIN = "https://chatgpt.com";
const CODEX_REFERER = "https://chatgpt.com/";
const CODEX_ORIGINATOR = "codex_cli_rs";
const CODEX_VERSION = "0.144.1";

export async function probeBrowserTransport(env: Env, token: ChatGptToken): Promise<Record<string, unknown>> {
  if (!env.BROWSER_RENDERING) return { configured: false, error: "BROWSER_RENDERING binding is not configured." };
  const browser = await puppeteer.launch(env.BROWSER_RENDERING);
  try {
    const page = await browser.newPage();
    const navigation = await page.goto(CHATGPT_URL, { waitUntil: "domcontentloaded", timeout: 20_000 });
    const browserIdentity = await page.evaluate(() => ({ userAgent: navigator.userAgent, platform: navigator.platform, language: navigator.language }));
    const requestFromPage = async (url: string, method: "GET" | "POST") => page.evaluate(async ({ url, method, accessToken, accountId, origin, referer, originator, version }) => {
      const response = await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "ChatGPT-Account-Id": accountId,
          Accept: method === "POST" ? "text/event-stream" : "application/json",
          "Content-Type": "application/json",
          Origin: origin,
          Referer: referer,
          originator,
          Version: version,
        },
        body: method === "POST" ? JSON.stringify({ model: "gpt-5.4", input: [{ role: "user", content: [{ type: "input_text", text: "ping" }] }], stream: true, store: false }) : undefined,
      });
      return { status: response.status, ok: response.ok, contentType: response.headers.get("content-type"), bodyPrefix: (await response.text()).slice(0, 300) };
    }, { url, method, accessToken: token.accessToken, accountId: token.accountId, origin: CODEX_ORIGIN, referer: CODEX_REFERER, originator: CODEX_ORIGINATOR, version: CODEX_VERSION });
    return {
      configured: true,
      navigation: { status: navigation?.status() ?? null, url: page.url(), contentType: navigation?.headers()["content-type"] ?? null },
      browserIdentity,
      models: await requestFromPage(CODEX_MODELS_URL, "GET"),
      responses: await requestFromPage(CODEX_RESPONSES_URL, "POST"),
    };
  } finally {
    await browser.close();
  }
}
