/**
 * SHA-256 through WebCrypto (`globalThis.crypto.subtle`), which Node (19 and
 * later) and browsers provide. Browsers expose `subtle` only in secure
 * contexts (HTTPS, `localhost`, `file:`).
 */

const HEX: string[] = Array.from({ length: 256 }, (_, i) => i.toString(16).padStart(2, "0"));

/** Lowercase hexadecimal SHA-256 of `bytes`. */
export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error(
      "WebCrypto is not available (globalThis.crypto.subtle); " +
        "use Node 19 or later, or serve the page from a secure context",
    );
  }
  const digest = new Uint8Array(await subtle.digest("SHA-256", bytes as Uint8Array<ArrayBuffer>));
  let hex = "";
  for (let i = 0; i < digest.length; i++) hex += HEX[digest[i]!];
  return hex;
}
