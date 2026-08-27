import { afterEach, describe, expect, it, vi } from "vitest";
import { createResponsesResponse } from "./providers";
import type { ChatGptToken, Env } from "./types";

const TEST_TOKEN: ChatGptToken = {
  accessToken: "access-token",
  accountId: "account-id",
};

const TEST_ENV = {
  CHATGPT_CODEX_ENDPOINT: "https://chatgpt.example.test/backend-api/codex/responses",
  CHATGPT_CODEX_CLIENT_VERSION: "0.144.1",
} as Env;

describe("Worker Codex compatibility", () => {
  afterEach(() => vi.restoreAllMocks());

  it("matches the known-working Render ChatGPT request identity", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ output_text: "OK" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await createResponsesResponse(TEST_ENV, TEST_TOKEN, {
      model: "gpt-5.4",
      input: [{ role: "user", content: [{ type: "input_text", text: "Hello" }] }],
      stream: false,
      webSearch: false,
    });

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;

    expect(headers.get("user-agent")).toBe("9Router/3 Codex-Compatible");
    expect(headers.get("originator")).toBe("codex_cli_rs");
    expect(headers.get("version")).toBe("0.144.1");
    expect(headers.get("origin")).toBe("https://chatgpt.com");
    expect(headers.get("referer")).toBe("https://chatgpt.com/");
    expect(headers.get("chatgpt-account-id")).toBe("account-id");
    expect(headers.get("openai-beta")).toBeNull();
    expect(headers.get("session_id")).toBeNull();
    expect(body.stream).toBe(true);
  });
});
