// Test-only helpers: build ZIP and QVF archives in memory.
//
// @qvf/core has no writer; these helpers hand-assemble archives, including
// deliberately broken ones, so the tests do not depend on any other
// implementation or on committed binary fixtures.

import { createHash } from "node:crypto";

import { deflateSync } from "fflate";

import { crc32 } from "../dist/index.js";

const encoder = new TextEncoder();

/** @param {string | Uint8Array} x */
export function toBytes(x) {
  return typeof x === "string" ? encoder.encode(x) : x;
}

/** @param {Uint8Array} data */
export function sha256(data) {
  return createHash("sha256").update(data).digest("hex");
}

/** @param {Uint8Array[]} parts */
export function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

/** @param {number} n */
const u16 = (n) => Uint8Array.of(n & 0xff, (n >>> 8) & 0xff);
/** @param {number} n */
const u32 = (n) => Uint8Array.of(n & 0xff, (n >>> 8) & 0xff, (n >>> 16) & 0xff, (n >>> 24) & 0xff);
/** @param {number} n */
const u64 = (n) => concat([u32(n % 2 ** 32), u32(Math.floor(n / 2 ** 32))]);

/**
 * @typedef {object} ZipEntrySpec
 * @property {string} name
 * @property {string | Uint8Array} [data]       uncompressed content
 * @property {number} [method]                  0 = STORE, 8 = DEFLATE (default 8)
 * @property {Uint8Array} [stored]              override the stored (compressed) bytes
 * @property {number} [crc]                     override the CRC-32 recorded
 * @property {number} [usize]                   override the uncompressed size recorded
 * @property {number} [csize]                   override the compressed size recorded
 * @property {number} [flags]                   general-purpose flags (default 0x800)
 * @property {Uint8Array} [rawName]             override the central-directory name bytes
 * @property {Uint8Array} [localName]           override the local-header name bytes
 * @property {boolean} [zip64]                  saturate the central sizes and use a ZIP64 extra field
 * @property {number} [zip64Size]               ZIP64 uncompressed size to record (implies zip64)
 * @property {number} [zip64CompressedSize]     ZIP64 compressed size to record
 * @property {number} [zip64Offset]             ZIP64 local-header offset to record
 */

/**
 * Assemble a ZIP archive.
 * @param {ZipEntrySpec[]} entries
 * @param {{ zip64Eocd?: boolean, comment?: Uint8Array }} [options]
 */
export function buildZip(entries, options = {}) {
  /** @type {Uint8Array[]} */
  const parts = [];
  let offset = 0;
  /** @param {Uint8Array} u8 */
  const push = (u8) => {
    parts.push(u8);
    offset += u8.length;
  };
  /** @type {Uint8Array[]} */
  const central = [];

  for (const e of entries) {
    const nameBytes = e.rawName ?? encoder.encode(e.name);
    const data = toBytes(e.data ?? new Uint8Array(0));
    const method = e.method ?? 8;
    const stored = e.stored ?? (method === 0 ? data : deflateSync(data));
    const crc = e.crc ?? crc32(data);
    const usize = e.usize ?? data.length;
    const csize = e.csize ?? stored.length;
    const flags = e.flags ?? 0x800;
    const localOffset = offset;
    const localName = e.localName ?? nameBytes;

    push(
      concat([
        u32(0x04034b50),
        u16(20),
        u16(flags),
        u16(method),
        u16(0),
        u16(0x21),
        u32(crc),
        u32(csize),
        u32(usize),
        u16(localName.length),
        u16(0),
        localName,
      ]),
    );
    push(stored);

    const zip64 = e.zip64 || e.zip64Size !== undefined || e.zip64CompressedSize !== undefined || e.zip64Offset !== undefined;
    const extra = zip64
      ? concat([
          u16(0x0001),
          u16(24),
          u64(e.zip64Size ?? usize),
          u64(e.zip64CompressedSize ?? csize),
          u64(e.zip64Offset ?? localOffset),
        ])
      : new Uint8Array(0);
    central.push(
      concat([
        u32(0x02014b50),
        u16(45),
        u16(zip64 ? 45 : 20),
        u16(flags),
        u16(method),
        u16(0),
        u16(0x21),
        u32(crc),
        u32(zip64 ? 0xffffffff : csize),
        u32(zip64 ? 0xffffffff : usize),
        u16(nameBytes.length),
        u16(extra.length),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(zip64 ? 0xffffffff : localOffset),
        nameBytes,
        extra,
      ]),
    );
  }

  const directoryOffset = offset;
  const directory = concat(central);
  push(directory);

  const comment = options.comment ?? new Uint8Array(0);
  const big = options.zip64Eocd === true || entries.length >= 0xffff;
  if (big) {
    const recordOffset = offset;
    push(
      concat([
        u32(0x06064b50),
        u64(44),
        u16(45),
        u16(45),
        u32(0),
        u32(0),
        u64(entries.length),
        u64(entries.length),
        u64(directory.length),
        u64(directoryOffset),
      ]),
    );
    push(concat([u32(0x07064b50), u32(0), u64(recordOffset), u32(1)]));
  }
  push(
    concat([
      u32(0x06054b50),
      u16(0),
      u16(0),
      u16(big ? 0xffff : entries.length),
      u16(big ? 0xffff : entries.length),
      u32(big ? 0xffffffff : directory.length),
      u32(big ? 0xffffffff : directoryOffset),
      u16(comment.length),
      comment,
    ]),
  );
  return concat(parts);
}

// --- QVF archives -------------------------------------------------------------

export const WATER = {
  atoms: [
    { symbol: "O", position: [0.0, 0.0, 0.1173], atomic_number: 8 },
    { symbol: "H", position: [0.0, 0.7572, -0.4692], atomic_number: 1 },
    { symbol: "H", position: [0.0, -0.7572, -0.4692], atomic_number: 1 },
  ],
  pbc: [false, false, false],
  lattice_vectors: null,
};

/** @param {unknown} value */
export const jsonBytes = (value) => encoder.encode(JSON.stringify(value, null, 1));

/**
 * @param {string} path
 * @param {Uint8Array} data
 */
export const jsonMember = (path, data) => ({ path, format: "json", sha256: sha256(data) });

/**
 * @param {string} path
 * @param {Uint8Array} data
 * @param {string} dtype
 * @param {number[]} shape
 */
export const binaryMember = (path, data, dtype, shape) => ({ path, format: "binary", dtype, shape, sha256: sha256(data) });

/**
 * @param {string} path
 * @param {Uint8Array} data
 */
export const opaqueMember = (path, data) => ({ path, format: "binary", sha256: sha256(data) });

/**
 * A valid one-section archive (a water structure) as a mutable description:
 * `manifest` (the object that becomes manifest.json) and `entries` (the ZIP
 * entries other than the manifest).
 * @returns {{ manifest: any, entries: ZipEntrySpec[], manifestBytes?: Uint8Array, omitManifest?: boolean }}
 */
export function baseArchive() {
  const data = jsonBytes(WATER);
  return {
    manifest: {
      qvf_version: 1,
      source: { program: "qvf-test", version: "0.0.1", calculation: "base" },
      sections: [
        {
          id: "structure",
          kind: "structure",
          members: { structure: jsonMember("structure/structure.json", data) },
        },
      ],
    },
    entries: [{ name: "structure/structure.json", data }],
  };
}

/**
 * Add a section and its entries to a description from {@link baseArchive}.
 * @param {ReturnType<typeof baseArchive>} archive
 * @param {any} section
 * @param {Record<string, Uint8Array>} files
 */
export function addSection(archive, section, files) {
  archive.manifest.sections.push(section);
  for (const [name, data] of Object.entries(files)) archive.entries.push({ name, data });
  return section;
}

/**
 * Pack a description into archive bytes (manifest stored last, uncompressed).
 * @param {ReturnType<typeof baseArchive>} archive
 */
export function pack(archive) {
  const entries = [...archive.entries];
  if (!archive.omitManifest) {
    entries.push({
      name: "manifest.json",
      method: 0,
      data: archive.manifestBytes ?? jsonBytes(archive.manifest),
    });
  }
  return buildZip(entries);
}

/** Little-endian bytes of float64 values. @param {number[]} values */
export function float64Bytes(values) {
  const out = new Uint8Array(values.length * 8);
  const view = new DataView(out.buffer);
  values.forEach((v, i) => view.setFloat64(i * 8, v, true));
  return out;
}
