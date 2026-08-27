import { afterEach, describe, expect, it, vi } from "vitest";
import { createResponsesResponse } from "./providers";
import type { ChatGptToken, Env } from "./types";

const TEST_TOKEN: ChatGptToken = {
  accessToken: "access-token",
  accountId: "account-id",
};

const TEST_ENV = {
  CHATGPT_CODEX_ENDPOINT: "https://chatgpt.example.test/backend-api/codex/responses",
  CHATGPT_CODEX_CLIENT_VERSION: "0.148.0",
} as Env;

describe("Codex upstream request", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends the Codex client identity and account headers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ output_text: "OK" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await createResponsesResponse(TEST_ENV, TEST_TOKEN, {
      model: "chatgpt-gpt-5.4",
      input: [{ role: "user", content: [{ type: "input_text", text: "Hello" }] }],
      stream: false,
      webSearch: false,
    });

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;

    expect(headers.get("authorization")).toBe("Bearer access-token");
    expect(headers.get("chatgpt-account-id")).toBe("account-id");
    expect(headers.get("originator")).toBe("codex_cli_rs");
    expect(headers.get("user-agent")).toBe("codex_cli_rs/0.148.0");
    expect(headers.get("version")).toBe("0.148.0");
    expect(headers.get("openai-beta")).toBe("responses=experimental");
    expect(headers.get("session_id")).toMatch(/^[0-9a-f-]{36}$/);
    expect(body.model).toBe("gpt-5.4");
    expect(body.store).toBe(false);
  });

  it("marks web-search requests as eligible", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ output_text: "OK" }), { status: 200 }),
    );

    await createResponsesResponse(TEST_ENV, TEST_TOKEN, {
      model: "gpt-5.4",
      input: [{ role: "user", content: [{ type: "input_text", text: "Search the web" }] }],
      stream: false,
      webSearch: true,
    });

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);

    expect(headers.get("x-oai-web-search-eligible")).toBe("true");
  });

  it("returns a bounded diagnostic instead of leaking an HTML block page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html><body>Cloudflare challenge page</body></html>", {
        status: 403,
        headers: { "content-type": "text/html; charset=UTF-8" },
      }),
    );

    await expect(
      createResponsesResponse(TEST_ENV, TEST_TOKEN, {
        model: "gpt-5.4",
        input: [{ role: "user", content: [{ type: "input_text", text: "Hello" }] }],
        stream: false,
        webSearch: false,
      }),
    ).rejects.toThrow("ChatGPT upstream returned an HTML block page (HTTP 403)");
  });
});
