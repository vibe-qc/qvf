/**
 * JSON helpers shared by the reader and the validator: the nesting-depth scan
 * that guards the parser (spec § 6.1), strict UTF-8 decoding, and parsing.
 */

const strictUtf8 = new TextDecoder("utf-8", { fatal: true });

/**
 * Nesting depth of the JSON arrays and objects in `raw`, capped at `limit + 1`.
 *
 * A top-level `[]` or `{}` has depth 1 and a scalar depth 0. The scan is
 * linear and never recurses: it looks only at brackets, quotes and
 * backslashes, skips string contents (with escapes), and stops as soon as the
 * limit is exceeded. Malformed JSON is left to the parser to report.
 */
export function jsonDepth(raw: Uint8Array, limit: number): number {
  let depth = 0;
  let deepest = 0;
  let inString = false;
  let escaped = false;
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i]!;
    if (inString) {
      if (escaped) escaped = false;
      else if (c === 0x5c) escaped = true; // backslash escapes the next byte
      else if (c === 0x22) inString = false; // closing quote
      continue;
    }
    if (c === 0x22) {
      inString = true;
    } else if (c === 0x5b || c === 0x7b) {
      // [ {
      depth++;
      if (depth > deepest) {
        deepest = depth;
        if (deepest > limit) return deepest;
      }
    } else if (c === 0x5d || c === 0x7d) {
      depth--; // ] }
    }
  }
  return deepest;
}

/**
 * Decode `raw` as strict UTF-8. Throws a `TypeError` for an invalid sequence
 * (overlong form, surrogate, truncated). A leading byte order mark is skipped,
 * as the Python reference reader does.
 */
export function decodeUtf8(raw: Uint8Array): string {
  return strictUtf8.decode(raw);
}

/** Whether `raw` is valid UTF-8. */
export function isValidUtf8(raw: Uint8Array): boolean {
  try {
    strictUtf8.decode(raw);
    return true;
  } catch {
    return false;
  }
}

/** Parse UTF-8 JSON bytes. Throws for invalid UTF-8 or invalid JSON. */
export function parseJsonBytes(raw: Uint8Array): unknown {
  return JSON.parse(decodeUtf8(raw));
}
