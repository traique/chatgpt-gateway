const AES_ALGORITHM = "AES-GCM";
const IV_LENGTH = 12;

export async function encryptSecret(secret: string, keyMaterial: string): Promise<string> {
  const key = await importKey(keyMaterial);
  const iv = crypto.getRandomValues(new Uint8Array(IV_LENGTH));
  const ciphertext = await crypto.subtle.encrypt({ name: AES_ALGORITHM, iv }, key, new TextEncoder().encode(secret));
  return `${toBase64Url(iv)}.${toBase64Url(new Uint8Array(ciphertext))}`;
}

export async function decryptSecret(payload: string, keyMaterial: string): Promise<string> {
  const [ivEncoded, ciphertextEncoded] = payload.split(".");
  if (!ivEncoded || !ciphertextEncoded) throw new Error("Invalid encrypted secret.");
  const key = await importKey(keyMaterial);
  const plaintext = await crypto.subtle.decrypt(
    { name: AES_ALGORITHM, iv: fromBase64Url(ivEncoded) },
    key,
    fromBase64Url(ciphertextEncoded),
  );
  return new TextDecoder().decode(plaintext);
}

async function importKey(keyMaterial: string): Promise<CryptoKey> {
  const bytes = fromHex(keyMaterial);
  if (bytes.byteLength !== 32) throw new Error("CHATGPT_TOKEN_ENCRYPTION_KEY must be 64 hex characters.");
  return crypto.subtle.importKey("raw", bytes, { name: AES_ALGORITHM }, false, ["encrypt", "decrypt"]);
}

function fromHex(value: string): Uint8Array {
  if (!/^[0-9a-f]{64}$/iu.test(value)) throw new Error("Invalid encryption key format.");
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) bytes[index] = Number.parseInt(value.slice(index * 2, index * 2 + 2), 16);
  return bytes;
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/u, "");
}

function fromBase64Url(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(normalized);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}
