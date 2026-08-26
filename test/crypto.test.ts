import { describe, expect, it } from "vitest";
import { decryptSecret, encryptSecret } from "../src/crypto";

const TEST_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

describe("secret encryption", () => {
  it("round-trips OAuth credentials without storing plaintext", async () => {
    const secret = "refresh-token-example";
    const encrypted = await encryptSecret(secret, TEST_KEY);

    expect(encrypted).not.toContain(secret);
    await expect(decryptSecret(encrypted, TEST_KEY)).resolves.toBe(secret);
  });

  it("rejects invalid encryption keys", async () => {
    await expect(encryptSecret("secret", "bad-key")).rejects.toThrow();
  });
});
