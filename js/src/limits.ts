/**
 * Resource caps applied to untrusted archives (spec § 6.1).
 *
 * Field names and default values are those of the Python `Limits` dataclass
 * and the C++ `Limits` struct, so the `limits` objects of the conformance
 * corpus apply to every implementation unchanged. Sizes are bytes.
 */
export interface Limits {
  /** Per ZIP entry, uncompressed bytes (1 gigavoxel of float64). */
  max_member_bytes: number;
  /** Sum over all ZIP entries, uncompressed bytes. */
  max_total_bytes: number;
  /** Optional application ratio policy; 0 disables it (the default). */
  max_ratio: number;
  /** Entries smaller than this (uncompressed) are exempt from the ratio check. */
  ratio_exempt_bytes: number;
  /** Largest allowed `manifest.json` or JSON member, uncompressed bytes. */
  max_json_bytes: number;
  /** Deepest allowed nesting of JSON arrays and objects. */
  max_json_depth: number;
}

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;

/** The reference values of spec § 6.1. */
export const DEFAULT_LIMITS: Readonly<Limits> = Object.freeze({
  max_member_bytes: 8 * GIB,
  max_total_bytes: 64 * GIB,
  max_ratio: 0,
  ratio_exempt_bytes: MIB,
  max_json_bytes: 256 * MIB,
  max_json_depth: 64,
});

/**
 * The default limits with `overrides` applied.
 *
 * Throws a `TypeError` for a key that is not a limit or a value that is not a
 * non-negative number (`Infinity` disables a cap). This is API misuse, not a
 * property of an archive, so it is the one place the package throws on input
 * that is not an archive.
 */
export function resolveLimits(overrides?: Partial<Limits> | null): Limits {
  const out: Limits = { ...DEFAULT_LIMITS };
  if (!overrides) return out;
  for (const [key, value] of Object.entries(overrides)) {
    if (!Object.hasOwn(DEFAULT_LIMITS, key)) {
      throw new TypeError(`unknown limit ${JSON.stringify(key)}`);
    }
    if (value === undefined) continue;
    if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
      throw new TypeError(`limit ${key} must be a non-negative number, got ${String(value)}`);
    }
    out[key as keyof Limits] = value;
  }
  return out;
}
