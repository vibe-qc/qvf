import assert from "node:assert/strict";
import { test } from "node:test";

import { DEFAULT_LIMITS, QvfError, QvfReader, ZipArchive, resolveLimits, validate as validateWithSchema } from "../dist/index.js";
import { toTypedArray } from "../dist/binary.js";
import {
  WATER,
  addSection,
  baseArchive,
  binaryMember,
  buildZip,
  float64Bytes,
  jsonBytes,
  jsonMember,
  opaqueMember,
  pack,
} from "./helpers.mjs";

// These tests pin the semantic checks, each archive isolating one rule, so they
// validate without the JSON Schema check generated from the schema (the
// behaviour of a validator without a schema engine: W_SCHEMA_SKIPPED);
// schemaCheck.test.mjs covers the checker.
/** @type {typeof validateWithSchema} */
const validate = (bytes, options = {}) => validateWithSchema(bytes, { schemaCheck: false, ...options });

/** @param {() => unknown} fn @param {string} code */
function assertQvfError(fn, code) {
  assert.throws(fn, (err) => err instanceof QvfError && err.code === code, `expected ${code}`);
}

/** @param {Promise<unknown>} promise @param {string} code */
async function assertRejectsWith(promise, code) {
  await assert.rejects(promise, (err) => err instanceof QvfError && err.code === code, `expected ${code}`);
}

/** An archive with one member of every dtype plus JSON and opaque members. */
function richArchive() {
  const a = baseArchive();
  /** @type {Record<string, Uint8Array>} */
  const files = {};
  /** @type {Record<string, unknown>} */
  const members = {};
  const dtypes = /** @type {[string, number][]} */ ([
    ["int8", 1], ["int16", 2], ["int32", 4], ["int64", 8],
    ["uint8", 1], ["uint16", 2], ["uint32", 4], ["uint64", 8],
    ["float32", 4], ["float64", 8],
  ]);
  for (const [dtype, size] of dtypes) {
    // Distinct little-endian bytes: element 0 = 1, element 1 = 2 (and so on).
    const data = new Uint8Array(size * 3);
    for (let e = 0; e < 3; e++) data[e * size] = e + 1;
    if (dtype === "float32") new DataView(data.buffer).setFloat32(0, 1.5, true);
    if (dtype === "float64") new DataView(data.buffer).setFloat64(0, 1.5, true);
    files[`arrays/${dtype}.dat`] = data;
    members[dtype] = binaryMember(`arrays/${dtype}.dat`, data, dtype, [3]);
  }
  const matrix = float64Bytes([1, 2, 3, 4, 5, 6]);
  files["arrays/matrix.dat"] = matrix;
  members.matrix = binaryMember("arrays/matrix.dat", matrix, "float64", [2, 3]);
  const note = new TextEncoder().encode("opaque text å");
  files["arrays/note.txt"] = note;
  members.note = opaqueMember("arrays/note.txt", note);
  const doc = jsonBytes({ a: [1, 2, { b: "x" }] });
  files["arrays/doc.json"] = doc;
  members.doc = jsonMember("arrays/doc.json", doc);
  addSection(a, { id: "rich", kind: "x_test.rich", members }, files);
  return a;
}

test("sections, sectionsOf and section", () => {
  const reader = QvfReader.fromBytes(pack(richArchive()));
  assert.deepEqual(reader.sections.map((s) => s.id), ["structure", "rich"]);
  assert.equal(reader.sectionsOf("structure").length, 1);
  assert.equal(reader.sectionsOf("nothing").length, 0);
  assert.equal(reader.section("rich")?.kind, "x_test.rich");
  assert.equal(reader.section("absent"), undefined);
  assert.equal(reader.manifest.source.program, "qvf-test");
  assert.equal(reader.versionReadable, true);
  assert.equal(reader.limits.max_json_depth, DEFAULT_LIMITS.max_json_depth);
});

test("malformed sections are skipped by the accessors and never throw", () => {
  const a = baseArchive();
  a.manifest.sections.push(null, 7, { id: 5, kind: "structure", members: {} }, { id: "nomembers", kind: "structure" });
  const reader = QvfReader.fromBytes(pack(a));
  assert.deepEqual(reader.sections.map((s) => s.id), ["structure"]);
  assert.equal(reader.manifest.sections.length, 5);
  const noSections = baseArchive();
  noSections.manifest.sections = "nope";
  assert.deepEqual(QvfReader.fromBytes(pack(noSections)).sections, []);
});

test("versionReadable accepts 1 and the withdrawn 2, not others", () => {
  for (const [version, want] of /** @type {[unknown, boolean][]} */ ([[1, true], [2, true], [3, false], ["1", false], [null, false]])) {
    const a = baseArchive();
    a.manifest.qvf_version = version;
    assert.equal(QvfReader.fromBytes(pack(a)).versionReadable, want, String(version));
  }
});

test("readJson decodes a JSON member", async () => {
  const reader = QvfReader.fromBytes(pack(richArchive()));
  assert.deepEqual(await reader.readJson("rich", "doc"), { a: [1, 2, { b: "x" }] });
  const structure = await reader.readJson("structure", "structure");
  assert.deepEqual(structure, WATER);
});

test("readBinary returns the matching typed array, dtype and shape", async () => {
  const reader = QvfReader.fromBytes(pack(richArchive()));
  const expected = /** @type {[string, Function][]} */ ([
    ["int8", Int8Array], ["int16", Int16Array], ["int32", Int32Array], ["int64", BigInt64Array],
    ["uint8", Uint8Array], ["uint16", Uint16Array], ["uint32", Uint32Array], ["uint64", BigUint64Array],
    ["float32", Float32Array], ["float64", Float64Array],
  ]);
  for (const [dtype, ctor] of expected) {
    const arr = await reader.readBinary("rich", dtype);
    assert.equal(arr.dtype, dtype);
    assert.deepEqual(arr.shape, [3]);
    assert.ok(arr.data instanceof ctor, `${dtype} -> ${ctor.name}`);
    assert.equal(arr.data.length, 3);
    if (dtype === "float32" || dtype === "float64") {
      assert.equal(arr.data[0], 1.5);
    } else if (dtype.endsWith("64")) {
      assert.deepEqual([...arr.data], [1n, 2n, 3n]);
    } else {
      assert.deepEqual([...arr.data], [1, 2, 3]);
    }
  }
  const m = await reader.readBinary("rich", "matrix");
  assert.deepEqual(m.shape, [2, 3]);
  assert.deepEqual([...m.data], [1, 2, 3, 4, 5, 6]);
});

test("readBinary decodes little-endian bytes", async () => {
  const a = baseArchive();
  const data = Uint8Array.of(0x01, 0x02, 0x03, 0x04, 0xff, 0xff, 0xff, 0x7f);
  addSection(
    a,
    { id: "le", kind: "x_test.le", members: { d: binaryMember("le.dat", data, "int32", [2]) } },
    { "le.dat": data },
  );
  const arr = await QvfReader.fromBytes(pack(a)).readBinary("le", "d");
  assert.deepEqual([...arr.data], [0x04030201, 0x7fffffff]);
});

test("a zero-length and a scalar array decode", async () => {
  const a = baseArchive();
  addSection(a, { id: "e", kind: "x_test.e", members: { d: binaryMember("e.dat", new Uint8Array(0), "float64", [0, 3]) } }, { "e.dat": new Uint8Array(0) });
  const arr = await QvfReader.fromBytes(pack(a)).readBinary("e", "d");
  assert.equal(arr.data.length, 0);
  assert.deepEqual(arr.shape, [0, 3]);
});

test("toTypedArray copies when the byte offset is not aligned and views otherwise", () => {
  const backing = new Uint8Array(1 + 16 + 8);
  new DataView(backing.buffer).setFloat64(1, 2.5, true);
  new DataView(backing.buffer).setFloat64(9, -7.25, true);
  const unaligned = backing.subarray(1, 17);
  assert.equal(unaligned.byteOffset % 8, 1);
  const copied = /** @type {Float64Array} */ (toTypedArray("float64", unaligned));
  assert.deepEqual([...copied], [2.5, -7.25]);
  assert.notEqual(copied.buffer, backing.buffer, "unaligned input is copied");

  const aligned = new Uint8Array(16);
  new DataView(aligned.buffer).setFloat64(0, 9.5, true);
  const viewed = /** @type {Float64Array} */ (toTypedArray("float64", aligned));
  assert.equal(viewed.buffer, aligned.buffer, "aligned input is viewed");
  assert.equal(viewed[0], 9.5);

  assert.throws(() => toTypedArray("float64", new Uint8Array(7)), RangeError);
});

test("readBinary works when the archive itself sits at an odd offset", async () => {
  const archive = pack(richArchive());
  const shifted = new Uint8Array(archive.length + 3);
  shifted.set(archive, 3);
  const reader = QvfReader.fromBytes(shifted.subarray(3));
  assert.deepEqual([...(await reader.readBinary("rich", "matrix")).data], [1, 2, 3, 4, 5, 6]);
  const fromBuffer = QvfReader.fromBytes(archive.buffer.slice(archive.byteOffset, archive.byteOffset + archive.length));
  assert.equal(fromBuffer.sections.length, 2);
});

test("a Node Buffer is accepted, at any offset, and results never alias the input", async () => {
  const archive = pack(richArchive());
  const padded = Buffer.alloc(archive.length + 5);
  archive.forEach((b, i) => (padded[i + 5] = b));
  for (const input of [Buffer.from(archive), padded.subarray(5), padded.subarray(5).buffer.slice(5)]) {
    const reader = QvfReader.fromBytes(input);
    const matrix = await reader.readBinary("rich", "matrix");
    assert.deepEqual([...matrix.data], [1, 2, 3, 4, 5, 6]);
    assert.equal((await validate(input)).ok, true);
  }
  // A stored (uncompressed) member is copied out, so editing it leaves the archive intact.
  const stored = Buffer.from(buildZip([{ name: "manifest.json", method: 0, data: jsonBytes(baseArchive().manifest) }]));
  const before = Buffer.from(stored);
  ZipArchive.open(stored).read("manifest.json").fill(0);
  assert.deepEqual(stored, before);
});

test("readBytes returns opaque bytes", async () => {
  const reader = QvfReader.fromBytes(pack(richArchive()));
  const bytes = await reader.readBytes("rich", "note");
  assert.equal(new TextDecoder().decode(bytes), "opaque text å");
});

test("sha256 is verified by default and can be skipped", async () => {
  const a = richArchive();
  a.manifest.sections[1].members.note.sha256 = "0".repeat(64);
  const reader = QvfReader.fromBytes(pack(a));
  await assertRejectsWith(reader.readBytes("rich", "note"), "E_SHA256_MISMATCH");
  await assertRejectsWith(reader.readBytes("rich", "note", true), "E_SHA256_MISMATCH");
  assert.equal((await reader.readBytes("rich", "note", false)).length > 0, true);
  // The other members are unaffected.
  assert.equal((await reader.readBytes("rich", "doc")).length > 0, true);
});

test("readBinary rejects a wrong dtype, shape or byte length", async () => {
  const a = baseArchive();
  const data = new Uint8Array(24);
  addSection(
    a,
    {
      id: "bad",
      kind: "x_test.bad",
      members: {
        dtype: binaryMember("d1.dat", data, "float128", [3]),
        shape: binaryMember("d2.dat", data, "float64", [3.5]),
        size: binaryMember("d3.dat", data, "float64", [4]),
        opaque: opaqueMember("d4.dat", data),
      },
    },
    { "d1.dat": data, "d2.dat": data, "d3.dat": data, "d4.dat": data },
  );
  const reader = QvfReader.fromBytes(pack(a));
  await assertRejectsWith(reader.readBinary("bad", "dtype"), "E_DTYPE");
  await assertRejectsWith(reader.readBinary("bad", "shape"), "E_MEMBER_MALFORMED");
  await assertRejectsWith(reader.readBinary("bad", "size"), "E_BINARY_SIZE");
  await assertRejectsWith(reader.readBinary("bad", "opaque"), "E_DTYPE");
});

test("readJson rejects invalid, too deep and oversized JSON", async () => {
  const a = baseArchive();
  const bad = new TextEncoder().encode("{not json");
  const deep = new TextEncoder().encode("[".repeat(100) + "]".repeat(100));
  const latin1 = Uint8Array.of(0x22, 0xe9, 0x22);
  const big = jsonBytes({ pad: "x".repeat(5000) });
  addSection(
    a,
    {
      id: "j",
      kind: "x_test.j",
      members: {
        bad: jsonMember("bad.json", bad),
        deep: jsonMember("deep.json", deep),
        latin1: jsonMember("latin1.json", latin1),
        big: jsonMember("big.json", big),
      },
    },
    { "bad.json": bad, "deep.json": deep, "latin1.json": latin1, "big.json": big },
  );
  const bytes = pack(a);
  const reader = QvfReader.fromBytes(bytes);
  await assertRejectsWith(reader.readJson("j", "bad"), "E_JSON_INVALID");
  await assertRejectsWith(reader.readJson("j", "deep"), "E_JSON_TOO_DEEP");
  await assertRejectsWith(reader.readJson("j", "latin1"), "E_JSON_INVALID");
  const small = QvfReader.fromBytes(bytes, { max_json_bytes: 4000 });
  await assertRejectsWith(small.readJson("j", "big"), "E_JSON_TOO_LARGE");
  const big5000 = /** @type {{ pad: string }} */ (await reader.readJson("j", "big"));
  assert.equal(big5000.pad.length, 5000);
  assert.deepEqual(await QvfReader.fromBytes(bytes, { max_json_depth: 128 }).readJson("j", "deep").then((v) => Array.isArray(v)), true);
});

test("lookup failures throw RangeError, not a finding error", async () => {
  const reader = QvfReader.fromBytes(pack(richArchive()));
  await assert.rejects(reader.readJson("absent", "x"), RangeError);
  await assert.rejects(reader.readJson("rich", "absent"), RangeError);
  assert.throws(() => reader.memberSpec("rich", "toString"), RangeError);
});

test("a member whose path is illegal or missing cannot be read", async () => {
  const a = baseArchive();
  addSection(
    a,
    {
      id: "p",
      kind: "x_test.p",
      members: {
        up: { path: "../x.json", format: "json" },
        gone: { path: "gone.json", format: "json" },
        nopath: { format: "json" },
      },
    },
    {},
  );
  const reader = QvfReader.fromBytes(pack(a));
  await assertRejectsWith(reader.readJson("p", "up"), "E_MEMBER_PATH");
  await assertRejectsWith(reader.readJson("p", "gone"), "E_MEMBER_MISSING");
  await assertRejectsWith(reader.readJson("p", "nopath"), "E_MEMBER_MALFORMED");
});

test("per-member, ratio and total caps apply to reads", async () => {
  const a = baseArchive();
  const zeros = new Uint8Array(65536);
  addSection(a, { id: "z", kind: "x_test.z", members: { d: binaryMember("z.dat", zeros, "uint8", [65536]) } }, { "z.dat": zeros });
  const bytes = pack(a);
  await assertRejectsWith(QvfReader.fromBytes(bytes, { max_member_bytes: 2048 }).readBytes("z", "d"), "E_MEMBER_TOO_LARGE");
  await assertRejectsWith(
    QvfReader.fromBytes(bytes, { max_ratio: 100, ratio_exempt_bytes: 4096 }).readBytes("z", "d"),
    "E_COMPRESSION_RATIO",
  );
  await assertRejectsWith(QvfReader.fromBytes(bytes, { max_total_bytes: 4096 }).readBytes("z", "d"), "E_TOTAL_TOO_LARGE");
  assert.equal((await QvfReader.fromBytes(bytes).readBytes("z", "d")).length, 65536);
});

test("fromBytes throws QvfError for an unreadable container", () => {
  assertQvfError(() => QvfReader.fromBytes(new TextEncoder().encode("hello")), "E_ZIP_UNREADABLE");
  const noManifest = baseArchive();
  noManifest.omitManifest = true;
  assertQvfError(() => QvfReader.fromBytes(pack(noManifest)), "E_MANIFEST_MISSING");
  const badJson = baseArchive();
  badJson.manifestBytes = new TextEncoder().encode("{truncated");
  assertQvfError(() => QvfReader.fromBytes(pack(badJson)), "E_MANIFEST_JSON");
  const notObject = baseArchive();
  notObject.manifestBytes = new TextEncoder().encode("[1, 2]");
  assertQvfError(() => QvfReader.fromBytes(pack(notObject)), "E_MANIFEST_JSON");
  const deep = baseArchive();
  deep.manifestBytes = new TextEncoder().encode("[".repeat(100) + "]".repeat(100));
  assertQvfError(() => QvfReader.fromBytes(pack(deep)), "E_JSON_TOO_DEEP");
  assertQvfError(() => QvfReader.fromBytes(pack(baseArchive()), { max_json_bytes: 10 }), "E_JSON_TOO_LARGE");
  const dup = buildZip([
    { name: "manifest.json", data: jsonBytes(baseArchive().manifest), method: 0 },
    { name: "x", data: "1" },
    { name: "x", data: "2" },
  ]);
  assertQvfError(() => QvfReader.fromBytes(dup), "E_ZIP_DUPLICATE_ENTRY");
});

test("fromBytes reads the last of several manifest.json entries (spec § 2.3)", async () => {
  const a = baseArchive();
  const stale = structuredClone(a.manifest);
  stale.sections = [];
  const bytes = buildZip([
    { name: "manifest.json", data: jsonBytes(stale), method: 0 },
    ...a.entries,
    { name: "manifest.json", data: jsonBytes(a.manifest), method: 0 },
  ]);
  const reader = QvfReader.fromBytes(bytes);
  assert.equal(reader.sections.length, 1);
  assert.deepEqual(await reader.readJson("structure", "structure"), WATER);
});

test("fromBytes refuses a byte_order other than little (spec § 2.2)", () => {
  const a = baseArchive();
  a.manifest.byte_order = "little";
  assert.equal(QvfReader.fromBytes(pack(a)).manifest.byte_order, "little");
  a.manifest.byte_order = "big";
  assertQvfError(() => QvfReader.fromBytes(pack(a)), "E_SCHEMA");
});

test("a member whose declared size disagrees with its entry cannot be read (spec § 4.2)", async () => {
  const a = baseArchive();
  const member = a.manifest.sections[0].members.structure;
  member.size = jsonBytes(WATER).length;
  assert.deepEqual(await QvfReader.fromBytes(pack(a)).readJson("structure", "structure"), WATER);
  member.size += 1;
  await assertRejectsWith(QvfReader.fromBytes(pack(a)).readJson("structure", "structure"), "E_BINARY_SIZE");
  member.size = "490";
  await assertRejectsWith(QvfReader.fromBytes(pack(a)).readBytes("structure", "structure"), "E_MEMBER_MALFORMED");
});

test("limits are resolved with the Python names and defaults", () => {
  assert.deepEqual(DEFAULT_LIMITS, {
    max_member_bytes: 8 * 1024 ** 3,
    max_total_bytes: 64 * 1024 ** 3,
    max_ratio: 0,
    ratio_exempt_bytes: 1024 ** 2,
    max_json_bytes: 256 * 1024 ** 2,
    max_json_depth: 64,
  });
  assert.equal(resolveLimits({ max_ratio: 5 }).max_ratio, 5);
  assert.equal(resolveLimits({ max_ratio: Infinity }).max_ratio, Infinity);
  assert.equal(resolveLimits(null).max_json_depth, 64);
  assert.throws(() => resolveLimits(/** @type {any} */ ({ maxRatio: 5 })), TypeError);
  assert.throws(() => resolveLimits({ max_ratio: -1 }), TypeError);
  assert.throws(() => resolveLimits({ max_ratio: NaN }), TypeError);
});
