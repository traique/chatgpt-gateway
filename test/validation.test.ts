import { describe, expect, it } from "vitest";
import { GatewayRequestError } from "../src/errors";
import { toResponsesInput, validateChatRequest, validateImageEditRequest, validateImageGenerationRequest } from "../src/validation";

describe("request validation", () => {
  it("normalizes chat defaults", () => {
    const result = validateChatRequest({ messages: [{ role: "user", content: "Hello" }] });
    expect(result.model).toBe("chatgpt-gpt-5.6");
    expect(result.stream).toBe(false);
    expect(result.webSearch).toBe(false);
  });

  it("maps web search to an explicit flag", () => {
    const result = validateChatRequest({ model: "gpt-5.6", messages: [{ role: "user", content: "Latest news" }], web_search: true });
    expect(result.webSearch).toBe(true);
  });

  it("rejects empty messages", () => {
    expect(() => validateChatRequest({ messages: [] })).toThrow("messages is required");
  });

  it("rejects unsupported temperature", () => {
    expect(() => validateChatRequest({ messages: [{ role: "user", content: "Hello" }], temperature: 0.2 })).toThrow(GatewayRequestError);
  });

  it("rejects invalid max tokens", () => {
    expect(() => validateChatRequest({ messages: [{ role: "user", content: "Hello" }], max_tokens: 0 })).toThrow(GatewayRequestError);
  });

  it("accepts image generation defaults", () => {
    const result = validateImageGenerationRequest({ prompt: "A mountain" });
    expect(result.model).toBe("chatgpt-gpt-image-2");
  });

  it("accepts image edits", () => {
    const result = validateImageEditRequest({ prompt: "Remove the logo", image: "data:image/png;base64,AAA" });
    expect(result.image).toContain("data:image/png");
  });

  it("creates deterministic Responses input", () => {
    expect(toResponsesInput([
      { role: "system", content: "Be concise." },
      { role: "user", content: "Hello" },
    ])).toBe("system: Be concise.\n\nuser: Hello");
  });
});
