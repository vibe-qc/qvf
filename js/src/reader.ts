/**
 * `QvfReader`: open a `.qvf` archive held in memory, expose its manifest, and
 * decode members with checksum verification (spec § 2, § 4, § 8.2).
 *
 * The reader throws `QvfError` when the container cannot be read (not a ZIP,
 * duplicate entry names, no or unparsable `manifest.json`, a cap exceeded, a
 * `byte_order` other than `"little"`) and when a member cannot be decoded
 * (checksum mismatch, malformed spec, wrong size, a declared `size` that
 * disagrees with the ZIP entry). Several `manifest.json` entries are an archive
 * updated in place: the last one is the manifest (spec § 2.3). Everything that is merely wrong with the contents is a finding of the
 * validator (`validate`), never an exception.
 */

import { declaredSizeProblem, decodeBinary, expectedByteLength, isDType, isShape } from "./binary.js";
import { QvfError } from "./errors.js";
import { jsonDepth, parseJsonBytes } from "./json.js";
import { resolveLimits, type Limits } from "./limits.js";
import { DTYPE_ITEMSIZE, type BinaryArray, type Manifest, type MemberSpec, type Section } from "./model.js";
import { READABLE_VERSIONS } from "./kinds.js";
import { sha256Hex } from "./sha256.js";
import { pathProblem, ratioExceeded, ZipArchive, type ZipEntry } from "./zip.js";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isWellFormedSection(value: unknown): value is Section {
  return (
    isObject(value) &&
    typeof value.id === "string" &&
    typeof value.kind === "string" &&
    isObject(value.members)
  );
}

export class QvfReader {
  /** The resource caps in force (the defaults of spec § 6.1 unless overridden). */
  readonly limits: Limits;
  /** The parsed `manifest.json`, exactly as stored. */
  readonly manifest: Manifest;

  private readonly zip: ZipArchive;
  private readonly wellFormed: Section[];

  private constructor(zip: ZipArchive, limits: Limits, manifest: Manifest) {
    this.zip = zip;
    this.limits = limits;
    this.manifest = manifest;
    const raw: unknown = (manifest as unknown as Record<string, unknown>).sections;
    this.wellFormed = Array.isArray(raw) ? raw.filter(isWellFormedSection) : [];
  }

  /**
   * Open an archive from its bytes.
   *
   * Throws `QvfError` when the container is unreadable: `E_ZIP_UNREADABLE`,
   * `E_ZIP_DUPLICATE_ENTRY` (a duplicated name other than `manifest.json`),
   * `E_MANIFEST_MISSING`, `E_MANIFEST_JSON`, `E_JSON_TOO_LARGE`,
   * `E_JSON_TOO_DEEP`, `E_MEMBER_TOO_LARGE` or `E_COMPRESSION_RATIO` (for
   * `manifest.json`), and `E_SCHEMA` for a `byte_order` other than `"little"`.
   * A `TypeError` reports an invalid `limits` argument.
   */
  static fromBytes(bytes: Uint8Array | ArrayBuffer, limits?: Partial<Limits>): QvfReader {
    const lim = resolveLimits(limits);
    const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    const zip = ZipArchive.open(data);
    // Superseded manifest.json copies of an archive updated in place are not
    // ambiguous: find() resolves to the last one, the manifest (spec § 2.3).
    const duplicates = zip.duplicates.filter((name) => name !== "manifest.json");
    if (duplicates.length > 0) {
      throw new QvfError(
        "E_ZIP_DUPLICATE_ENTRY",
        `duplicate ZIP entry name(s) ${JSON.stringify(duplicates)}; refusing an ambiguous archive`,
      );
    }
    const entry = zip.find("manifest.json");
    if (!entry) throw new QvfError("E_MANIFEST_MISSING", "missing manifest.json");
    if (entry.size > lim.max_json_bytes) {
      throw new QvfError(
        "E_JSON_TOO_LARGE",
        `manifest.json is ${entry.size} bytes, over the ${lim.max_json_bytes}-byte JSON cap`,
      );
    }
    checkEntryCaps(entry, lim);
    const raw = zip.read(entry, { maxBytes: lim.max_member_bytes });
    if (jsonDepth(raw, lim.max_json_depth) > lim.max_json_depth) {
      throw new QvfError("E_JSON_TOO_DEEP", `manifest.json nests deeper than ${lim.max_json_depth} levels`);
    }
    let manifest: unknown;
    try {
      manifest = parseJsonBytes(raw);
    } catch (err) {
      throw new QvfError("E_MANIFEST_JSON", `manifest.json is not valid JSON: ${errorText(err)}`);
    }
    if (!isObject(manifest)) {
      throw new QvfError("E_MANIFEST_JSON", "manifest.json must be a JSON object");
    }
    if (Object.hasOwn(manifest, "byte_order") && manifest.byte_order !== "little") {
      // "little" is the only v1 byte order; refuse rather than guess (spec § 2.2).
      throw new QvfError(
        "E_SCHEMA",
        `byte_order ${JSON.stringify(manifest.byte_order)} is not "little", the only byte order of QVF v1`,
      );
    }
    return new QvfReader(zip, lim, manifest as unknown as Manifest);
  }

  /**
   * The well-formed sections, in manifest order. A section that is not an
   * object with a string `id`, a string `kind` and a `members` object is
   * skipped (the validator reports it as `E_SECTION_MALFORMED`);
   * `manifest.sections` is the raw array.
   */
  get sections(): readonly Section[] {
    return this.wellFormed;
  }

  /** The sections of one kind, in manifest order. */
  sectionsOf(kind: string): Section[] {
    return this.wellFormed.filter((s) => s.kind === kind);
  }

  /** The first section with this id, or `undefined`. */
  section(id: string): Section | undefined {
    return this.wellFormed.find((s) => s.id === id);
  }

  /**
   * Whether `qvf_version` is one this consumer opens (spec § 3.1: `1`, and the
   * withdrawn `2`, which is treated as `1`). A consumer that supports only v1
   * must refuse an archive for which this is `false`.
   */
  get versionReadable(): boolean {
    const version: unknown = this.manifest.qvf_version;
    return typeof version === "number" && READABLE_VERSIONS.includes(version);
  }

  /** The spec of a member, looked up by section id and role. Throws `RangeError` if absent. */
  memberSpec(sectionId: string, role: string): MemberSpec {
    const section = this.section(sectionId);
    if (!section) throw new RangeError(`section id not found: ${sectionId}`);
    if (!Object.hasOwn(section.members, role)) {
      throw new RangeError(`section ${JSON.stringify(sectionId)} has no member ${JSON.stringify(role)}`);
    }
    return section.members[role]!;
  }

  /**
   * The stored bytes of a member (an opaque member, or the raw bytes of any
   * member). The result is a fresh buffer. With `verify` (the default) the
   * member's `sha256` is checked first and a mismatch throws
   * `E_SHA256_MISMATCH`.
   */
  async readBytes(sectionId: string, role: string, verify = true): Promise<Uint8Array> {
    return (await this.load(sectionId, role, verify, false)).bytes;
  }

  /**
   * Decode a JSON member. Throws `E_JSON_TOO_LARGE`, `E_JSON_TOO_DEEP` or
   * `E_JSON_INVALID` for a member over the caps or not UTF-8 JSON, besides the
   * errors of `readBytes`. Nothing about the payload is validated: the result
   * is `unknown` unless you pass the expected type.
   */
  async readJson<T = unknown>(sectionId: string, role: string, verify = true): Promise<T> {
    const { spec, bytes } = await this.load(sectionId, role, verify, true);
    if (jsonDepth(bytes, this.limits.max_json_depth) > this.limits.max_json_depth) {
      throw new QvfError(
        "E_JSON_TOO_DEEP",
        `member ${JSON.stringify(spec.path)} nests deeper than ${this.limits.max_json_depth} levels`,
      );
    }
    try {
      return parseJsonBytes(bytes) as T;
    } catch (err) {
      throw new QvfError("E_JSON_INVALID", `member ${JSON.stringify(spec.path)} is not valid JSON (${errorText(err)})`);
    }
  }

  /**
   * Decode a binary array member into a typed array of its declared dtype
   * with its declared shape. `data` is flat and C-ordered; 64-bit integer
   * dtypes give `BigInt64Array` / `BigUint64Array`. Throws `E_DTYPE`,
   * `E_MEMBER_MALFORMED` or `E_BINARY_SIZE` when the spec or the byte length
   * is wrong, besides the errors of `readBytes`.
   */
  async readBinary(sectionId: string, role: string, verify = true): Promise<BinaryArray> {
    const { spec, bytes } = await this.load(sectionId, role, verify, false);
    const where = JSON.stringify(spec.path);
    const dtype: unknown = (spec as { dtype?: unknown }).dtype;
    if (!isDType(dtype)) throw new QvfError("E_DTYPE", `member ${where}: bad dtype ${JSON.stringify(dtype)}`);
    const rawShape: unknown = (spec as { shape?: unknown }).shape ?? [];
    if (!isShape(rawShape)) {
      throw new QvfError("E_MEMBER_MALFORMED", `member ${where}: shape must be a list of non-negative integers`);
    }
    const want = expectedByteLength(DTYPE_ITEMSIZE[dtype], rawShape);
    if (BigInt(bytes.length) !== want) {
      throw new QvfError(
        "E_BINARY_SIZE",
        `member ${where}: byte length ${bytes.length} != itemsize*prod(shape) ${want}`,
      );
    }
    return decodeBinary(dtype, rawShape, bytes);
  }

  private async load(
    sectionId: string,
    role: string,
    verify: boolean,
    json: boolean,
  ): Promise<{ spec: MemberSpec; bytes: Uint8Array }> {
    const spec = this.memberSpec(sectionId, role);
    const path: unknown = isObject(spec) ? spec.path : undefined;
    if (typeof path !== "string") {
      throw new QvfError("E_MEMBER_MALFORMED", `section ${JSON.stringify(sectionId)} member ${JSON.stringify(role)}: malformed spec`);
    }
    const problem = pathProblem(path);
    if (problem) throw new QvfError("E_MEMBER_PATH", `member ${JSON.stringify(path)}: illegal path (${problem})`);
    const entry = this.zip.find(path);
    if (!entry) throw new QvfError("E_MEMBER_MISSING", `member ${JSON.stringify(path)} declared but not in archive`);
    if (this.zip.totalSize > this.limits.max_total_bytes) {
      throw new QvfError(
        "E_TOTAL_TOO_LARGE",
        `archive expands to ${this.zip.totalSize} bytes, over the ${this.limits.max_total_bytes}-byte total cap`,
      );
    }
    if (json && entry.size > this.limits.max_json_bytes) {
      throw new QvfError(
        "E_JSON_TOO_LARGE",
        `member ${JSON.stringify(path)} is ${entry.size} bytes, over the ${this.limits.max_json_bytes}-byte JSON cap`,
      );
    }
    checkEntryCaps(entry, this.limits);
    const sizeProblem = declaredSizeProblem(spec as unknown as Record<string, unknown>, entry.size, path);
    if (sizeProblem) throw new QvfError(sizeProblem[0], sizeProblem[1]);
    const bytes = this.zip.read(entry, { maxBytes: this.limits.max_member_bytes });
    const declared: unknown = spec.sha256;
    if (verify && declared !== undefined && declared !== (await sha256Hex(bytes))) {
      throw new QvfError("E_SHA256_MISMATCH", `sha256 mismatch for ${path}`);
    }
    return { spec, bytes };
  }
}

/** The per-member and ratio caps of spec § 6.1, checked before decompressing. */
function checkEntryCaps(entry: ZipEntry, limits: Limits): void {
  if (entry.size > limits.max_member_bytes) {
    throw new QvfError(
      "E_MEMBER_TOO_LARGE",
      `ZIP entry ${JSON.stringify(entry.name)} exceeds the per-member size cap (${entry.size} > ${limits.max_member_bytes} bytes uncompressed)`,
    );
  }
  if (ratioExceeded(entry, limits)) {
    throw new QvfError(
      "E_COMPRESSION_RATIO",
      `ZIP entry ${JSON.stringify(entry.name)} expands ${entry.size} bytes from ${entry.compressedSize}, over the ratio cap ${limits.max_ratio}`,
    );
  }
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
