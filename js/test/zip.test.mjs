import assert from "node:assert/strict";
import { test } from "node:test";

import { deflateSync } from "fflate";

import { QvfError, ZipArchive, crc32, pathProblem } from "../dist/index.js";
import { jsonDepth } from "../dist/json.js";
import { buildZip } from "./helpers.mjs";

const text = (/** @type {Uint8Array} */ u8) => new TextDecoder().decode(u8);

/** @param {() => unknown} fn @param {string} code */
function assertQvfError(fn, code) {
  assert.throws(fn, (err) => err instanceof QvfError && err.code === code, `expected ${code}`);
}

test("crc32 matches the standard check value", () => {
  assert.equal(crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
  assert.equal(crc32(new Uint8Array(0)), 0);
});

test("STORE and DEFLATE entries round-trip", () => {
  const big = new Uint8Array(100_000).map((_, i) => (i * 7) & 0xff);
  const zip = ZipArchive.open(
    buildZip([
      { name: "a.txt", data: "hello", method: 0 },
      { name: "dir/b.bin", data: big, method: 8 },
      { name: "empty", data: "", method: 0 },
      { name: "empty-deflated", data: "", method: 8 },
    ]),
  );
  assert.deepEqual(zip.names(), ["a.txt", "dir/b.bin", "empty", "empty-deflated"]);
  assert.equal(text(zip.read("a.txt")), "hello");
  assert.deepEqual(zip.read("dir/b.bin"), big);
  assert.equal(zip.read("empty").length, 0);
  assert.equal(zip.read("empty-deflated").length, 0);
  assert.equal(zip.totalSize, 5 + big.length);
  assert.equal(zip.read("a.txt").byteOffset, 0, "a read returns a fresh buffer");
});

test("an entry name is decoded as UTF-8", () => {
  const zip = ZipArchive.open(buildZip([{ name: "grid/\u00e5ngstr\u00f6m.json", data: "{}" }]));
  assert.ok(zip.has("grid/\u00e5ngstr\u00f6m.json"));
});

test("an archive comment is skipped when locating the directory", () => {
  const zip = ZipArchive.open(
    buildZip([{ name: "a", data: "x" }], { comment: new TextEncoder().encode("a comment") }),
  );
  assert.equal(text(zip.read("a")), "x");
});

test("duplicate entry names are recorded and the last one wins", () => {
  const zip = ZipArchive.open(
    buildZip([
      { name: "a", data: "first" },
      { name: "b", data: "b" },
      { name: "a", data: "second" },
    ]),
  );
  assert.deepEqual(zip.duplicates, ["a"]);
  assert.equal(zip.entries.length, 3);
  assert.equal(text(zip.read("a")), "second");
});

test("ZIP64: extra field sizes and offset, and a ZIP64 end record", () => {
  const zip = ZipArchive.open(
    buildZip(
      [
        { name: "small.txt", data: "zip64 extra", zip64: true, method: 0 },
        { name: "plain.txt", data: "plain" },
      ],
      { zip64Eocd: true },
    ),
  );
  assert.equal(text(zip.read("small.txt")), "zip64 extra");
  assert.equal(text(zip.read("plain.txt")), "plain");
});

test("ZIP64: more than 65535 entries", () => {
  const n = 70_000;
  const entries = Array.from({ length: n }, (_, i) => ({ name: `e/${i}`, data: String(i), method: 0 }));
  const zip = ZipArchive.open(buildZip(entries));
  assert.equal(zip.entries.length, n);
  assert.equal(zip.duplicates.length, 0);
  assert.equal(text(zip.read("e/0")), "0");
  assert.equal(text(zip.read("e/65535")), "65535");
  assert.equal(text(zip.read(`e/${n - 1}`)), String(n - 1));
});

test("ZIP64: sizes and offsets beyond 4 GiB parse without reading data", () => {
  const six = 6 * 2 ** 30;
  const zip = ZipArchive.open(
    buildZip([
      { name: "huge", data: "x", zip64Size: six, zip64CompressedSize: 100 },
      { name: "far", data: "y", zip64Offset: 5 * 2 ** 32 + 7 },
    ]),
  );
  const huge = zip.find("huge");
  assert.equal(huge?.size, six);
  assert.equal(huge?.compressedSize, 100);
  assert.equal(zip.find("far")?.localOffset, 5 * 2 ** 32 + 7);
  assert.equal(zip.totalSize, six + 1);
  // A declared size over the cap is refused before anything is decompressed.
  assertQvfError(() => zip.read("huge", { maxBytes: 2 ** 30 }), "E_MEMBER_TOO_LARGE");
  // An offset past the end of the buffer is a truncated entry, not a crash.
  assertQvfError(() => zip.read("far"), "E_ZIP_UNREADABLE");
});

test("ZIP64: a saturated field without an extra field is unreadable", () => {
  const bytes = buildZip([{ name: "a", data: "x", zip64: true }]);
  // Rename the extra field id (0x0001) so that it is no longer the ZIP64 field.
  const at = bytes.findIndex((b, i) => b === 0x01 && bytes[i + 1] === 0x00 && bytes[i + 2] === 24 && bytes[i + 3] === 0);
  assert.ok(at > 0);
  bytes[at] = 0x7f;
  assertQvfError(() => ZipArchive.open(bytes), "E_ZIP_UNREADABLE");
});

test("garbage is E_ZIP_UNREADABLE, never another error", () => {
  assertQvfError(() => ZipArchive.open(new Uint8Array(0)), "E_ZIP_UNREADABLE");
  assertQvfError(() => ZipArchive.open(new Uint8Array(21)), "E_ZIP_UNREADABLE");
  assertQvfError(() => ZipArchive.open(new TextEncoder().encode("not a zip archive at all, just text")), "E_ZIP_UNREADABLE");
  const good = buildZip([{ name: "a", data: "hello" }]);
  for (let cut = 0; cut < good.length; cut++) {
    assertQvfError(() => ZipArchive.open(good.subarray(0, cut)), "E_ZIP_UNREADABLE");
  }
});

test("a central directory that lies about its size or count is rejected", () => {
  const good = buildZip([{ name: "a", data: "hello" }]);
  const eocd = good.length - 22;
  const view = new DataView(good.buffer, good.byteOffset, good.byteLength);
  const counted = good.slice();
  new DataView(counted.buffer).setUint16(eocd + 10, 5000, true); // far more entries than fit
  assertQvfError(() => ZipArchive.open(counted), "E_ZIP_UNREADABLE");
  const moved = good.slice();
  new DataView(moved.buffer).setUint32(eocd + 16, view.getUint32(eocd + 16, true) + 3, true);
  assertQvfError(() => ZipArchive.open(moved), "E_ZIP_UNREADABLE");
});

test("a CRC-32 mismatch is E_ZIP_UNREADABLE", () => {
  const zip = ZipArchive.open(buildZip([{ name: "a", data: "hello", crc: 1234 }]));
  assertQvfError(() => zip.read("a"), "E_ZIP_UNREADABLE");
});

test("an unsupported method, encryption and a mismatched local name are refused", () => {
  const method = ZipArchive.open(buildZip([{ name: "a", data: "x", method: 9, stored: new Uint8Array([1]) }]));
  assertQvfError(() => method.read("a"), "E_ZIP_UNREADABLE");
  const encrypted = ZipArchive.open(buildZip([{ name: "a", data: "x", method: 0, flags: 0x801 }]));
  assertQvfError(() => encrypted.read("a"), "E_ZIP_UNREADABLE");
  const renamed = ZipArchive.open(buildZip([{ name: "a", data: "x", localName: new TextEncoder().encode("b") }]));
  assertQvfError(() => renamed.read("a"), "E_ZIP_UNREADABLE");
});

test("a STORE entry whose compressed size differs from its size is refused", () => {
  const zip = ZipArchive.open(buildZip([{ name: "a", data: "hello", method: 0, usize: 4 }]));
  assertQvfError(() => zip.read("a"), "E_ZIP_UNREADABLE");
});

test("an entry is never inflated past its declared size", () => {
  const data = new Uint8Array(8192).fill(0x41);
  // Declares 1 KiB, inflates to 8 KiB.
  const understated = ZipArchive.open(buildZip([{ name: "a", data, usize: 1024 }]));
  assertQvfError(() => understated.read("a"), "E_ZIP_UNREADABLE");
  // Declares 16 KiB, inflates to 8 KiB.
  const overstated = ZipArchive.open(buildZip([{ name: "a", data, usize: 16384 }]));
  assertQvfError(() => overstated.read("a"), "E_ZIP_UNREADABLE");
  // A stream with a real bomb in it: 16 MiB of zeros declared as 1 KiB stops early.
  const bomb = deflateSync(new Uint8Array(16 * 1024 * 1024));
  const bombed = ZipArchive.open(buildZip([{ name: "a", data: "", stored: bomb, usize: 1024, crc: 0 }]));
  assertQvfError(() => bombed.read("a"), "E_ZIP_UNREADABLE");
});

test("corrupt DEFLATE data and truncated streams are E_ZIP_UNREADABLE", () => {
  const data = new Uint8Array(5000).map((_, i) => (i * 31) & 0xff);
  const packed = deflateSync(data);
  const truncated = ZipArchive.open(buildZip([{ name: "a", data, stored: packed.subarray(0, packed.length >> 1) }]));
  assertQvfError(() => truncated.read("a"), "E_ZIP_UNREADABLE");
  const junk = ZipArchive.open(buildZip([{ name: "a", data, stored: new Uint8Array(50).fill(0xff) }]));
  assertQvfError(() => junk.read("a"), "E_ZIP_UNREADABLE");
});

test("reading an unknown name is E_MEMBER_MISSING", () => {
  const zip = ZipArchive.open(buildZip([{ name: "a", data: "x" }]));
  assertQvfError(() => zip.read("nope"), "E_MEMBER_MISSING");
});

test("pathProblem applies the rules of spec 2.1", () => {
  const cases = /** @type {[string, string | null][]} */ ([
    ["manifest.json", null],
    ["structure/structure.json", null],
    ["a/b/c.dat", null],
    ["dir/", null],
    ["a..b/c", null],
    ["a/..b", null],
    ["/abs", "begins with '/'"],
    ["C:/x", "begins with a drive letter"],
    ["z:x", "begins with a drive letter"],
    ["a\\b", "contains a backslash"],
    ["a\0b", "contains a NUL character"],
    ["../x", "contains a '..' segment"],
    ["a/../b", "contains a '..' segment"],
    ["a/..", "contains a '..' segment"],
  ]);
  for (const [path, want] of cases) assert.equal(pathProblem(path), want, JSON.stringify(path));
});

test("jsonDepth counts nesting of arrays and objects", () => {
  const enc = (/** @type {string} */ s) => new TextEncoder().encode(s);
  assert.equal(jsonDepth(enc("1"), 64), 0);
  assert.equal(jsonDepth(enc("[]"), 64), 1);
  assert.equal(jsonDepth(enc('{"a":[1,{"b":[]}]}'), 64), 4);
  assert.equal(jsonDepth(enc('["[[[[", "\\"[[[", "]]"]'), 64), 1, "brackets inside strings do not count");
  assert.equal(jsonDepth(enc("[".repeat(100) + "]".repeat(100)), 64), 65, "stops at limit + 1");
});
