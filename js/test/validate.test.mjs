import assert from "node:assert/strict";
import { test } from "node:test";

import { deflateSync } from "fflate";

import { FINDING_CODES, QvfError, QvfReader, validate as validateWithSchema } from "../dist/index.js";
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

const enc = new TextEncoder();

/** The codes of a report, without the always-present W_SCHEMA_SKIPPED. */
function codes(/** @type {{ findings: { code: string }[] }} */ report) {
  return report.findings.map((f) => f.code).filter((c) => c !== "W_SCHEMA_SKIPPED");
}

/**
 * A vendor section with one member.
 * @param {ReturnType<typeof baseArchive>} a
 * @param {string} sid
 * @param {string} path
 * @param {Uint8Array} data
 * @param {Record<string, unknown>} [extra]
 */
function addVendorJson(a, sid, path, data, extra = {}) {
  return addSection(a, { id: sid, kind: `x_test.${sid}`, members: { m: jsonMember(path, data) }, ...extra }, { [path]: data });
}

const CUSTOM_ENTRY = { units: "e", description: "Net flux.", kind: "scalar" };

/**
 * An `atom_properties` section with the given custom roles (two atoms each)
 * and, when `meta` is not undefined, a `meta` member holding it.
 * @param {string[]} roles
 * @param {unknown} [meta]
 */
function customArchive(roles, meta) {
  const a = baseArchive();
  /** @type {Record<string, any>} */
  const members = {};
  /** @type {Record<string, Uint8Array>} */
  const files = {};
  for (const role of roles) {
    const data = float64Bytes([0.5, -0.5]);
    members[role] = binaryMember(`ap/${role}.bin`, data, "float64", [2]);
    files[`ap/${role}.bin`] = data;
  }
  if (meta !== undefined) {
    const data = jsonBytes(meta);
    members.meta = jsonMember("ap/meta.json", data);
    files["ap/meta.json"] = data;
  }
  addSection(a, { id: "ap", kind: "atom_properties", members }, files);
  return a;
}

/** @type {[string, () => { bytes: Uint8Array, limits?: Record<string, number> }, string[]][]} */
const NEGATIVE = [
  ["not a zip", () => ({ bytes: enc.encode("this is not a zip archive, only text") }), ["E_ZIP_UNREADABLE"]],
  [
    "manifest missing",
    () => {
      const a = baseArchive();
      a.omitManifest = true;
      return { bytes: pack(a) };
    },
    ["E_MANIFEST_MISSING"],
  ],
  [
    "manifest not json",
    () => {
      const a = baseArchive();
      a.manifestBytes = enc.encode('{"qvf_version": 1, "source":');
      return { bytes: pack(a) };
    },
    ["E_MANIFEST_JSON"],
  ],
  [
    "manifest not an object",
    () => {
      const a = baseArchive();
      a.manifestBytes = enc.encode("[1]");
      return { bytes: pack(a) };
    },
    ["E_MANIFEST_JSON"],
  ],
  [
    "manifest not utf-8",
    () => {
      const a = baseArchive();
      a.manifestBytes = Uint8Array.of(0x7b, 0x22, 0xe9, 0x22, 0x3a, 0x31, 0x7d);
      return { bytes: pack(a) };
    },
    ["E_MANIFEST_JSON"],
  ],
  [
    "manifest too deep",
    () => {
      const a = baseArchive();
      a.manifest.provenance = JSON.parse("[".repeat(70) + "]".repeat(70));
      return { bytes: pack(a) };
    },
    ["E_JSON_TOO_DEEP"],
  ],
  [
    "manifest too large",
    () => ({ bytes: pack(baseArchive()), limits: { max_json_bytes: 100 } }),
    ["E_JSON_TOO_LARGE"],
  ],
  [
    "version unsupported",
    () => {
      const a = baseArchive();
      a.manifest.qvf_version = 3;
      return { bytes: pack(a) };
    },
    ["E_VERSION"],
  ],
  [
    "version 2 is withdrawn",
    () => {
      const a = baseArchive();
      a.manifest.qvf_version = 2;
      return { bytes: pack(a) };
    },
    ["W_VERSION_WITHDRAWN"],
  ],
  [
    "version missing",
    () => {
      const a = baseArchive();
      delete a.manifest.qvf_version;
      return { bytes: pack(a) };
    },
    ["E_VERSION"],
  ],
  [
    "source empty program",
    () => {
      const a = baseArchive();
      a.manifest.source.program = "";
      return { bytes: pack(a) };
    },
    ["E_SOURCE"],
  ],
  [
    "source missing calculation",
    () => {
      const a = baseArchive();
      delete a.manifest.source.calculation;
      return { bytes: pack(a) };
    },
    ["E_SOURCE"],
  ],
  [
    "source not an object",
    () => {
      const a = baseArchive();
      a.manifest.source = "x";
      return { bytes: pack(a) };
    },
    ["E_SOURCE", "E_SOURCE", "E_SOURCE", "E_SOURCE", "E_SOURCE"],
  ],
  [
    "sections not an array",
    () => {
      const a = baseArchive();
      a.manifest.sections = {};
      return { bytes: pack(a) };
    },
    ["E_SECTION_MALFORMED", "W_ORPHAN_MEMBER"],
  ],
  [
    "section not an object",
    () => {
      const a = baseArchive();
      a.manifest.sections.push("nope");
      return { bytes: pack(a) };
    },
    ["E_SECTION_MALFORMED"],
  ],
  [
    "section without id, kind, members",
    () => {
      const a = baseArchive();
      a.manifest.sections.push({ id: 3, kind: 4, members: [] });
      return { bytes: pack(a) };
    },
    ["E_SECTION_MALFORMED", "E_SECTION_MALFORMED", "E_SECTION_MALFORMED"],
  ],
  [
    "duplicate section id",
    () => {
      const a = baseArchive();
      addSection(a, { id: "structure", kind: "x_test.dup", members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_SECTION_ID_DUPLICATE"],
  ],
  [
    "reserved id auto_open",
    () => {
      const a = baseArchive();
      addSection(a, { id: "auto_open", kind: "x_test.r", members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_RESERVED_ID"],
  ],
  [
    "reserved id bookmarks",
    () => {
      const a = baseArchive();
      addSection(a, { id: "bookmarks", kind: "x_test.r", members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_RESERVED_ID"],
  ],
  [
    "unknown kind",
    () => {
      const a = baseArchive();
      addSection(a, { id: "k", kind: "volume.mystery", members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_KIND_UNKNOWN"],
  ],
  [
    "critical vendor section, namespace undeclared",
    () => {
      const a = baseArchive();
      addSection(a, { id: "c", kind: "x_test.c", critical: true, members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_CRITICAL_UNDECLARED"],
  ],
  [
    "member spec without a path",
    () => {
      const a = baseArchive();
      addSection(a, { id: "m", kind: "x_test.m", members: { a: { format: "json" }, b: 5 } }, {});
      return { bytes: pack(a) };
    },
    ["E_MEMBER_MALFORMED", "E_MEMBER_MALFORMED"],
  ],
  [
    "member missing",
    () => {
      const a = baseArchive();
      addSection(a, { id: "m", kind: "x_test.m", members: { a: { path: "gone.json", format: "json", sha256: "0".repeat(64) } } }, {});
      return { bytes: pack(a) };
    },
    ["E_MEMBER_MISSING"],
  ],
  [
    "sha256 mismatch",
    () => {
      const a = baseArchive();
      a.manifest.sections[0].members.structure.sha256 = "f".repeat(64);
      return { bytes: pack(a) };
    },
    ["E_SHA256_MISMATCH"],
  ],
  [
    "member json invalid",
    () => {
      const a = baseArchive();
      addVendorJson(a, "j", "j.json", enc.encode("{nope"));
      return { bytes: pack(a) };
    },
    ["E_JSON_INVALID"],
  ],
  [
    "member json not utf-8",
    () => {
      const a = baseArchive();
      addVendorJson(a, "j", "j.json", Uint8Array.of(0x22, 0xe9, 0x22));
      return { bytes: pack(a) };
    },
    ["E_JSON_INVALID"],
  ],
  [
    "member json too deep",
    () => {
      const a = baseArchive();
      addVendorJson(a, "j", "j.json", enc.encode("[".repeat(100) + "]".repeat(100)));
      return { bytes: pack(a) };
    },
    ["E_JSON_TOO_DEEP"],
  ],
  [
    "member json too large",
    () => {
      const a = baseArchive();
      addVendorJson(a, "j", "j.json", jsonBytes({ pad: "x".repeat(4000) }));
      return { bytes: pack(a), limits: { max_json_bytes: 2048 } };
    },
    ["E_JSON_TOO_LARGE"],
  ],
  [
    "dtype unknown",
    () => {
      const a = baseArchive();
      const data = new Uint8Array(8);
      addSection(a, { id: "d", kind: "x_test.d", members: { m: binaryMember("d.dat", data, "float128", [1]) } }, { "d.dat": data });
      return { bytes: pack(a) };
    },
    ["E_DTYPE"],
  ],
  [
    "shape not non-negative integers",
    () => {
      const a = baseArchive();
      const data = new Uint8Array(8);
      addSection(a, { id: "d", kind: "x_test.d", members: { m: binaryMember("d.dat", data, "float64", [-1]) } }, { "d.dat": data });
      return { bytes: pack(a) };
    },
    ["E_MEMBER_MALFORMED"],
  ],
  [
    "binary size mismatch",
    () => {
      const a = baseArchive();
      const data = new Uint8Array(16);
      addSection(a, { id: "d", kind: "x_test.d", members: { m: binaryMember("d.dat", data, "float64", [3]) } }, { "d.dat": data });
      return { bytes: pack(a) };
    },
    ["E_BINARY_SIZE"],
  ],
  [
    "run.record log not utf-8",
    () => {
      const a = baseArchive();
      const log = Uint8Array.of(0x66, 0xff, 0xfe);
      addSection(a, { id: "rr", kind: "run.record", program: "x", members: { log: opaqueMember("rr/log", log) } }, { "rr/log": log });
      return { bytes: pack(a) };
    },
    ["E_UTF8"],
  ],
  [
    "run.record files index names a role without a member",
    () => {
      const a = baseArchive();
      const input = enc.encode("input");
      const files = jsonBytes({ input: { filename: "a.inp" }, ghost: { filename: "ghost.txt" } });
      addSection(
        a,
        {
          id: "rr",
          kind: "run.record",
          program: "x",
          members: { input: opaqueMember("rr/input", input), files: jsonMember("rr/files.json", files) },
        },
        { "rr/input": input, "rr/files.json": files },
      );
      return { bytes: pack(a) };
    },
    ["E_FILES_INDEX"],
  ],
  [
    "volume.difference operand does not resolve",
    () => {
      const a = baseArchive();
      addSection(a, { id: "diff", kind: "volume.difference", operand_a: "structure", operand_b: "nowhere", members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_REF_UNRESOLVED"],
  ],
  [
    "volume.difference operand of the wrong type",
    () => {
      const a = baseArchive();
      addSection(a, { id: "diff", kind: "volume.difference", operand_a: 5, members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_REF_UNRESOLVED"],
  ],
  [
    "reaction.waypoints trajectory_ref does not resolve",
    () => {
      const a = baseArchive();
      addSection(a, { id: "wp", kind: "reaction.waypoints", trajectory_ref: "nowhere", members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_REF_UNRESOLVED"],
  ],
  [
    "reaction.waypoints without trajectory_ref",
    () => {
      const a = baseArchive();
      addSection(a, { id: "wp", kind: "reaction.waypoints", members: {} }, {});
      return { bytes: pack(a) };
    },
    ["E_REF_UNRESOLVED"],
  ],
  [
    "structure with lattice but no pbc",
    () => {
      const a = baseArchive();
      const payload = jsonBytes({ ...WATER, pbc: undefined, lattice_vectors: [[1, 0, 0], [0, 1, 0], [0, 0, 1]] });
      a.entries[0] = { name: "structure/structure.json", data: payload };
      a.manifest.sections[0].members.structure = jsonMember("structure/structure.json", payload);
      return { bytes: pack(a) };
    },
    ["E_STRUCTURE_PERIODICITY"],
  ],
  [
    "structure with pbc true but no lattice",
    () => {
      const a = baseArchive();
      const payload = jsonBytes({ ...WATER, pbc: [true, false, false] });
      a.entries[0] = { name: "structure/structure.json", data: payload };
      a.manifest.sections[0].members.structure = jsonMember("structure/structure.json", payload);
      return { bytes: pack(a) };
    },
    ["E_STRUCTURE_PERIODICITY"],
  ],
  [
    "structure dimensionality differs from sum(pbc)",
    () => {
      const a = baseArchive();
      const payload = jsonBytes({ ...WATER, dimensionality: 2 });
      a.entries[0] = { name: "structure/structure.json", data: payload };
      a.manifest.sections[0].members.structure = jsonMember("structure/structure.json", payload);
      return { bytes: pack(a) };
    },
    ["E_STRUCTURE_PERIODICITY"],
  ],
  [
    "structure pbc not three booleans",
    () => {
      const a = baseArchive();
      const payload = jsonBytes({ ...WATER, pbc: [1, 0, 0] });
      a.entries[0] = { name: "structure/structure.json", data: payload };
      a.manifest.sections[0].members.structure = jsonMember("structure/structure.json", payload);
      return { bytes: pack(a) };
    },
    ["E_STRUCTURE_PERIODICITY"],
  ],
  [
    "structure payload not an object",
    () => {
      const a = baseArchive();
      const payload = jsonBytes([1, 2]);
      a.entries[0] = { name: "structure/structure.json", data: payload };
      a.manifest.sections[0].members.structure = jsonMember("structure/structure.json", payload);
      return { bytes: pack(a) };
    },
    ["E_STRUCTURE_PERIODICITY"],
  ],
  [
    "atom_properties custom role without a meta member",
    () => ({ bytes: pack(customArchive(["custom.flux", "custom.other"])) }),
    ["E_MEMBER_MALFORMED", "E_MEMBER_MALFORMED"],
  ],
  [
    "atom_properties meta without the role's entry",
    () => ({ bytes: pack(customArchive(["custom.flux", "custom.other"], { "custom.flux": CUSTOM_ENTRY })) }),
    ["E_MEMBER_MALFORMED"],
  ],
  [
    "atom_properties meta entry that is not an object",
    () => ({ bytes: pack(customArchive(["custom.flux"], { "custom.flux": "scalar" })) }),
    ["E_MEMBER_MALFORMED"],
  ],
  [
    "atom_properties meta that is not an object",
    () => ({ bytes: pack(customArchive(["custom.flux"], [])) }),
    ["E_MEMBER_MALFORMED"],
  ],
  [
    "orphan entry is a warning",
    () => {
      const a = baseArchive();
      a.entries.push({ name: "stale/old.json", data: "{}" });
      return { bytes: pack(a) };
    },
    ["W_ORPHAN_MEMBER"],
  ],
  ...["/structure/structure.json", "structure\\structure.json", "structure/../../structure.json", "C:/structure/structure.json"].map(
    /** @returns {[string, () => { bytes: Uint8Array }, string[]]} */
    (path) => [
      `illegal member path ${JSON.stringify(path)}`,
      () => {
        const a = baseArchive();
        const data = a.entries[0].data;
        a.entries[0] = { name: path, data };
        a.manifest.sections[0].members.structure.path = path;
        return { bytes: pack(a) };
      },
      ["E_MEMBER_PATH", "E_MEMBER_PATH"],
    ],
  ),
  [
    "illegal member path whose entry does not exist",
    () => {
      const a = baseArchive();
      addSection(a, { id: "p", kind: "x_test.p", members: { m: { path: "a/../b.json", format: "json", sha256: "0".repeat(64) } } }, {});
      return { bytes: pack(a) };
    },
    ["E_MEMBER_PATH"],
  ],
  [
    "duplicate ZIP entry",
    () => {
      const a = baseArchive();
      // The decoy comes first; the last entry of a name wins, as in Python's zipfile.
      a.entries.unshift({ name: "structure/structure.json", data: jsonBytes({ ...WATER, extra: 1 }) });
      return { bytes: pack(a) };
    },
    ["E_ZIP_DUPLICATE_ENTRY"],
  ],
  [
    "member over the per-member cap",
    () => {
      const a = baseArchive();
      const data = new Uint8Array(4096);
      addSection(a, { id: "d", kind: "x_test.d", members: { m: binaryMember("d.dat", data, "uint8", [4096]) } }, { "d.dat": data });
      return { bytes: pack(a), limits: { max_member_bytes: 2048 } };
    },
    ["E_MEMBER_TOO_LARGE"],
  ],
  [
    "archive over the total cap",
    () => {
      const a = baseArchive();
      for (const n of ["a", "b", "c"]) {
        const data = new Uint8Array(1500).fill(n.charCodeAt(0));
        addSection(a, { id: n, kind: `x_test.${n}`, members: { m: binaryMember(`${n}.dat`, data, "uint8", [1500]) } }, { [`${n}.dat`]: data });
      }
      return { bytes: pack(a), limits: { max_total_bytes: 4096 } };
    },
    ["E_TOTAL_TOO_LARGE"],
  ],
  [
    "compression ratio",
    () => {
      const a = baseArchive();
      const data = new Uint8Array(65536);
      addSection(a, { id: "z", kind: "x_test.z", members: { m: binaryMember("z.dat", data, "uint8", [65536]) } }, { "z.dat": data });
      return { bytes: pack(a), limits: { max_ratio: 100, ratio_exempt_bytes: 4096 } };
    },
    ["E_COMPRESSION_RATIO"],
  ],
  [
    "entry whose declared size understates its data",
    () => {
      const a = baseArchive();
      const data = new Uint8Array(8192).fill(0x20);
      a.entries.push({ name: "j.json", data, usize: 1024 });
      addSection(a, { id: "j", kind: "x_test.j", members: { m: jsonMember("j.json", data) } }, {});
      return { bytes: pack(a) };
    },
    ["E_ZIP_UNREADABLE"],
  ],
  [
    "entry with a CRC-32 mismatch",
    () => {
      const a = baseArchive();
      a.entries[0] = { ...a.entries[0], crc: 99 };
      return { bytes: pack(a) };
    },
    ["E_ZIP_UNREADABLE"],
  ],
];

for (const [name, build, expected] of NEGATIVE) {
  test(`validate: ${name}`, async () => {
    const { bytes, limits } = build();
    const report = await validate(bytes, limits ? { limits } : {});
    assert.deepEqual(codes(report), expected);
    const wantOk = expected.every((c) => FINDING_CODES[/** @type {keyof typeof FINDING_CODES} */ (c)] === "warning");
    assert.equal(report.ok, wantOk);
    for (const f of report.findings) {
      assert.equal(FINDING_CODES[f.code], f.severity, `${f.code} has its fixed severity`);
      assert.ok(typeof f.where === "string" && f.where.length > 0);
      assert.ok(typeof f.message === "string" && f.message.length > 0);
    }
  });
}

test("validate: an atom_properties custom role with a meta entry is fine", async () => {
  const report = await validate(pack(customArchive(["custom.flux"], { "custom.flux": CUSTOM_ENTRY })));
  assert.deepEqual(codes(report), []);
  assert.equal(report.ok, true);
});

test("validate: a listed atom_properties role needs no meta", async () => {
  const report = await validate(pack(customArchive(["mulliken_charge"])));
  assert.deepEqual(codes(report), []);
});

test("validate: the finding for a custom role without meta points at the member", async () => {
  const report = await validate(pack(customArchive(["custom.flux"])));
  const finding = report.findings.find((f) => f.code === "E_MEMBER_MALFORMED");
  assert.equal(finding?.where, "/sections/1/members/custom.flux");
});

test("validate: an unreadable meta member is not judged twice", async () => {
  const a = customArchive(["custom.flux"], {});
  a.entries = a.entries.map((e) => (e.name === "ap/meta.json" ? { ...e, data: "{not json" } : e));
  const report = await validate(pack(a));
  const got = codes(report);
  assert.ok(got.includes("E_JSON_INVALID"));
  assert.ok(!got.includes("E_MEMBER_MALFORMED"));
});

test("validate: the custom-role meta check needs the payload level", async () => {
  const bytes = pack(customArchive(["custom.flux"]));
  assert.deepEqual(codes(await validate(bytes, { level: "manifest" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "semantics" })), ["E_MEMBER_MALFORMED"]);
});

test("validate: a valid archive is ok with the single W_SCHEMA_SKIPPED warning", async () => {
  const a = baseArchive();
  const grid = float64Bytes([0, 1, 2, 3, 4, 5, 6, 7]);
  addSection(a, { id: "g", kind: "x_test.g", members: { m: binaryMember("g.dat", grid, "float64", [2, 2, 2]) } }, { "g.dat": grid });
  const report = await validate(pack(a));
  assert.equal(report.ok, true);
  assert.equal(report.nSections, 2);
  assert.deepEqual(report.findings.map((f) => [f.severity, f.code, f.where]), [
    ["warning", "W_SCHEMA_SKIPPED", "manifest.json"],
  ]);
});

test("validate: where locates findings by JSON Pointer, entry or archive", async () => {
  const a = baseArchive();
  addSection(a, { id: "d~e/f", kind: "x_test.d", members: { "r/ole": { path: "gone.dat", format: "binary" } } }, {});
  a.entries.push({ name: "orphan.txt", data: "x" });
  const report = await validate(pack(a));
  const where = Object.fromEntries(report.findings.map((f) => [f.code, f.where]));
  assert.equal(where.E_MEMBER_MISSING, "/sections/1/members/r~1ole");
  assert.equal(where.W_ORPHAN_MEMBER, "entry:orphan.txt");
  assert.equal(where.W_SCHEMA_SKIPPED, "manifest.json");
  assert.equal((await validate(enc.encode("junk"))).findings[0].where, "archive");
});

test("validate: a critical vendor section is fine once its namespace is declared", async () => {
  const a = baseArchive();
  a.manifest.extensions = { x_test: { version: "1", critical: true } };
  addSection(a, { id: "c", kind: "x_test.c", critical: true, members: {} }, {});
  assert.deepEqual(codes(await validate(pack(a))), []);
});

test("validate: version 1 given as 1.0 and an extra root key are fine", async () => {
  const a = baseArchive();
  a.manifestBytes = enc.encode(JSON.stringify(a.manifest).replace('"qvf_version":1', '"qvf_version":1.0'));
  a.manifest.unknown_root = true;
  assert.deepEqual(codes(await validate(pack(a))), []);
});

test("validate: a member path pointing at manifest.json is not an orphan or an error", async () => {
  const a = baseArchive();
  addSection(a, { id: "self", kind: "x_test.self", members: { m: { path: "manifest.json", format: "binary" } } }, {});
  assert.deepEqual(codes(await validate(pack(a))), []);
});

test("validate: directory entries are not orphans", async () => {
  const a = baseArchive();
  a.entries.push({ name: "structure/", data: "", method: 0 });
  assert.deepEqual(codes(await validate(pack(a))), []);
});

test("validate: findings accumulate across independent defects", async () => {
  const a = baseArchive();
  a.manifest.source.version = "";
  a.manifest.sections[0].members.structure.sha256 = "0".repeat(64);
  addSection(a, { id: "k", kind: "nope", members: {} }, {});
  a.entries.push({ name: "orphan", data: "x" });
  assert.deepEqual(codes(await validate(pack(a))), ["E_SOURCE", "E_SHA256_MISMATCH", "E_KIND_UNKNOWN", "W_ORPHAN_MEMBER"]);
});

test("validate: levels are cumulative", async () => {
  const a = baseArchive();
  a.manifest.sections[0].members.structure.sha256 = "0".repeat(64); // payloads
  const periodic = jsonBytes({ ...WATER, dimensionality: 3 });
  addSection(
    a,
    { id: "s2", kind: "structure", members: { structure: jsonMember("s2.json", periodic) } },
    { "s2.json": periodic },
  ); // semantics
  addSection(a, { id: "wp", kind: "reaction.waypoints", trajectory_ref: "none", members: {} }, {}); // references
  a.manifest.sections.push({ id: "bad", kind: "nonsense", members: {} }); // manifest
  a.entries.push({ name: "orphan", data: "x" }); // manifest
  const bytes = pack(a);
  const run = async (/** @type {any} */ level) => codes(await validate(bytes, { level }));
  assert.deepEqual(await run("container"), []);
  assert.deepEqual(await run("manifest"), ["E_KIND_UNKNOWN", "W_ORPHAN_MEMBER"]);
  assert.deepEqual(await run("payloads"), ["E_SHA256_MISMATCH", "E_KIND_UNKNOWN", "W_ORPHAN_MEMBER"]);
  assert.deepEqual(await run("semantics"), ["E_SHA256_MISMATCH", "E_STRUCTURE_PERIODICITY", "E_KIND_UNKNOWN", "W_ORPHAN_MEMBER"]);
  const full = ["E_SHA256_MISMATCH", "E_STRUCTURE_PERIODICITY", "E_REF_UNRESOLVED", "E_KIND_UNKNOWN", "W_ORPHAN_MEMBER"];
  assert.deepEqual(await run("references"), full);
  assert.deepEqual(await run("all"), full);
  assert.deepEqual(codes(await validate(bytes)), full);
  const container = await validate(bytes, { level: "container" });
  assert.equal(container.nSections, 0);
  assert.equal(container.findings.length, 0);
  await assert.rejects(validate(bytes, { level: /** @type {any} */ ("everything") }), TypeError);
});

test("validate: container-level findings do not need a manifest", async () => {
  const a = baseArchive();
  a.omitManifest = true;
  a.entries.push({ name: "../evil", data: "x" });
  const report = await validate(pack(a), { level: "container" });
  assert.deepEqual(codes(report), ["E_MEMBER_PATH"]);
});

test("validate: invalid limits are a TypeError, an unreadable archive is not", async () => {
  await assert.rejects(validate(enc.encode("x"), { limits: /** @type {any} */ ({ bogus: 1 }) }), TypeError);
  assert.equal((await validate(new Uint8Array(0))).ok, false);
});

test("validate: accepts an ArrayBuffer", async () => {
  const bytes = pack(baseArchive());
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length);
  assert.equal((await validate(buffer)).ok, true);
});

test("validate: an unreadable member is a finding and later members are still checked", async () => {
  const a = baseArchive();
  const broken = enc.encode("broken");
  a.entries.push({ name: "broken.json", data: broken, crc: 1 });
  addSection(a, { id: "b", kind: "x_test.b", members: { m: jsonMember("broken.json", broken) } }, {});
  const bad = enc.encode("{nope");
  addVendorJson(a, "after", "after.json", bad);
  assert.deepEqual(codes(await validate(pack(a))), ["E_ZIP_UNREADABLE", "E_JSON_INVALID"]);
});

test("validate: a ZIP64 archive with more than 65535 entries validates", async () => {
  const a = baseArchive();
  const entries = [{ name: "manifest.json", method: 0, data: jsonBytes(a.manifest) }, ...a.entries];
  for (let i = 0; i < 70_000; i++) entries.push({ name: `extra/${i}`, data: "", method: 0 });
  const report = await validate(buildZip(entries));
  assert.equal(report.ok, true);
  assert.equal(report.findings.filter((f) => f.code === "W_ORPHAN_MEMBER").length, 70_000);
});

test("validate and the reader never throw anything but QvfError on damaged archives", async () => {
  const a = baseArchive();
  const grid = float64Bytes([1, 2, 3, 4]);
  addSection(a, { id: "g", kind: "x_test.g", members: { m: binaryMember("g.dat", grid, "float64", [4]) } }, { "g.dat": grid });
  const good = pack(a);

  // A simple deterministic generator, so a failure is reproducible.
  let seed = 12345;
  const rand = () => (seed = (Math.imul(seed, 1103515245) + 12345) >>> 0) / 2 ** 32;

  const variants = [];
  for (let cut = 0; cut < good.length; cut += 7) variants.push(good.subarray(0, cut));
  for (let i = 0; i < 300; i++) {
    const copy = good.slice();
    for (let k = 0; k < 1 + Math.floor(rand() * 4); k++) copy[Math.floor(rand() * copy.length)] ^= 1 << Math.floor(rand() * 8);
    variants.push(copy);
  }
  for (let i = 0; i < 50; i++) variants.push(Uint8Array.from({ length: Math.floor(rand() * 400) }, () => Math.floor(rand() * 256)));

  for (const bytes of variants) {
    const report = await validate(bytes);
    assert.equal(typeof report.ok, "boolean");
    assert.equal(report.ok, !report.findings.some((f) => f.severity === "error"));
    try {
      const reader = QvfReader.fromBytes(bytes);
      for (const s of reader.sections) {
        for (const role of Object.keys(s.members)) {
          await reader.readBytes(s.id, role).catch((err) => assert.ok(err instanceof QvfError || err instanceof RangeError));
        }
      }
    } catch (err) {
      assert.ok(err instanceof QvfError, `unexpected ${err}`);
    }
  }
});

test("validate: deflated and stored manifests both work", async () => {
  const a = baseArchive();
  const stored = pack(a);
  assert.equal((await validate(stored)).ok, true);
  const body = jsonBytes(a.manifest);
  const deflated = buildZip([...a.entries, { name: "manifest.json", method: 8, data: body, stored: deflateSync(body) }]);
  assert.equal((await validate(deflated)).ok, true);
});

/**
 * A water archive with a forces or hessian section whose main member has the
 * given shape (zero-filled float64), plus optional meta and section fields.
 * @param {"forces"|"hessian"} kind
 * @param {number[]} shape
 * @param {Record<string, unknown>|null} [meta]
 * @param {Record<string, unknown>} [fields]
 */
function derivativeArchive(kind, shape, meta = null, fields = {}) {
  const a = baseArchive();
  const role = kind === "forces" ? "gradient" : "matrix";
  const data = float64Bytes(new Array(shape.reduce((x, y) => x * y, 1)).fill(0));
  /** @type {Record<string, unknown>} */
  const members = { [role]: binaryMember(`d/${role}.bin`, data, "float64", shape) };
  /** @type {Record<string, Uint8Array>} */
  const files = { [`d/${role}.bin`]: data };
  if (meta) {
    const m = jsonBytes(meta);
    members.meta = jsonMember("d/meta.json", m);
    files["d/meta.json"] = m;
  }
  addSection(a, { id: kind, kind, ...fields, members }, files);
  return pack(a);
}

test("validate: forces and hessian shapes against the structure (spec § 5.10, § 5.11)", async () => {
  /** @type {[Uint8Array, string[], string?][]} */
  const cases = [
    [derivativeArchive("forces", [3, 3], { structure_ref: "structure" }), []],
    [derivativeArchive("forces", [2, 3], { structure_ref: "structure" }), ["E_MEMBER_MALFORMED"], "/sections/1/members/gradient"],
    [derivativeArchive("forces", [4, 3]), ["E_MEMBER_MALFORMED"]],
    [derivativeArchive("forces", [3, 2]), ["E_MEMBER_MALFORMED"]],
    [derivativeArchive("forces", [3, 3], { structure_ref: "nowhere" }), ["E_REF_UNRESOLVED"], "/sections/1/members/meta"],
    // The unresolved section-level structure_ref is itself reported (spec § 4.1);
    // the atom count is not checked against it.
    [derivativeArchive("forces", [5, 3], null, { structure_ref: "elsewhere" }), ["E_REF_UNRESOLVED"]],
    [derivativeArchive("hessian", [9, 9], { atom_masses_amu: [16, 1, 1] }), []],
    [derivativeArchive("hessian", [9, 6]), ["E_MEMBER_MALFORMED"], "/sections/1/members/matrix"],
    [derivativeArchive("hessian", [8, 8]), ["E_MEMBER_MALFORMED"]],
    [derivativeArchive("hessian", [6, 6]), ["E_MEMBER_MALFORMED"]],
    [derivativeArchive("hessian", [9, 9], { atom_masses_amu: [16, 1] }), ["E_MEMBER_MALFORMED"], "/sections/1/members/meta"],
  ];
  for (const [bytes, want, where] of cases) {
    const report = await validate(bytes);
    assert.deepEqual(codes(report), want);
    if (where) assert.equal(report.findings.find((f) => f.code === want[0])?.where, where);
  }
  // Below the references level the atom count is not compared.
  assert.deepEqual(codes(await validate(derivativeArchive("forces", [4, 3]), { level: "semantics" })), []);
});

test("validate: vibrations hessian_ref must name a hessian section", async () => {
  const a = baseArchive();
  const meta = jsonBytes({ frequencies: [1.0] });
  const disp = float64Bytes(new Array(9).fill(0));
  addSection(
    a,
    {
      id: "modes",
      kind: "vibrations",
      hessian_ref: "structure",
      members: { metadata: jsonMember("v/m.json", meta), displacements: binaryMember("v/d.bin", disp, "float64", [1, 3, 3]) },
    },
    { "v/m.json": meta, "v/d.bin": disp },
  );
  const report = await validate(pack(a));
  assert.deepEqual(codes(report), ["E_REF_UNRESOLVED"]);
  assert.equal(report.findings.find((f) => f.code === "E_REF_UNRESOLVED")?.where, "/sections/1/hessian_ref");
});

test("validate: root energies agree with provenance and thermochemistry (spec § 3.6)", async () => {
  const scf = { value: -74.9659011, units: "hartree" };
  const prov = { method: "RHF", scf_energy: scf };
  /**
   * @param {Record<string, unknown>} extra
   * @param {import("../dist/index.js").ValidationLevel} [level]
   */
  const run = async (extra, level = "all") => {
    const a = baseArchive();
    Object.assign(a.manifest, extra);
    return validate(pack(a), { level });
  };
  const disagree = { provenance: prov, energies: { total: { value: -74.96, units: "hartree" }, method: "rhf" } };
  let report = await run(disagree);
  assert.deepEqual(codes(report), ["E_ROOT_INCONSISTENT"]);
  assert.equal(report.findings.find((f) => f.code === "E_ROOT_INCONSISTENT")?.where, "/energies/total");
  assert.deepEqual(codes(await run(disagree, "manifest")), []);
  report = await run({
    provenance: prov,
    energies: {
      total: { value: -75.2, units: "hartree" },
      method: "mp2",
      by_method: [{ method: "rhf", total: { value: -74.95, units: "hartree" } }],
    },
  });
  assert.equal(report.findings.find((f) => f.code === "E_ROOT_INCONSISTENT")?.where, "/energies/by_method/0/total");
  report = await run({ provenance: prov, energies: { total: { value: -74.9659011 * 27.211386245988, units: "ev" }, method: "rhf" } });
  assert.deepEqual(codes(report), []);
  report = await run({ provenance: prov, energies: { total: { value: -75.2, units: "hartree" }, method: "mp2" } });
  assert.deepEqual(codes(report), []);
  report = await run({ thermochemistry: { zpve_eh: 0.0214 }, energies: { total: scf, components: { zpve: { value: 0.0213, units: "hartree" } } } });
  assert.deepEqual(codes(report), ["E_ROOT_INCONSISTENT"]);
});

/**
 * The base water structure, a wavefunction.gto "wf" (restricted with 2 orbital
 * rows, or unrestricted with 2 alpha and 3 beta rows), an excited_states
 * section "es" with `payload` and section `fields`, and `extra` callbacks that
 * add further sections.
 * @param {unknown} payload
 * @param {Record<string, unknown>} [fields]
 * @param {{ unrestricted?: boolean, extra?: ((a: ReturnType<typeof baseArchive>) => void)[] }} [options]
 */
function excitedArchive(payload, fields = {}, options = {}) {
  const a = baseArchive();
  const basis = jsonBytes({
    structure_ref: "structure",
    pure: true,
    n_ao: 2,
    shells: [
      { center: 0, l: 0, exponents: [1.0], coefficients: [1.0] },
      { center: 1, l: 0, exponents: [1.0], coefficients: [1.0] },
    ],
  });
  const mo = jsonBytes(
    options.unrestricted
      ? { n_ao: 2, spin: "unrestricted", alpha: { energies: [0, 0], occupations: [1, 0] }, beta: { energies: [0, 0, 0], occupations: [1, 0, 0] } }
      : { n_mo: 2, n_ao: 2, spin: "restricted", energies: [-0.5, 0.5], occupations: [2, 0] },
  );
  /** @type {Record<string, unknown>} */
  const members = { basis: jsonMember("wf/basis.json", basis), mo_metadata: jsonMember("wf/mo.json", mo) };
  /** @type {Record<string, Uint8Array>} */
  const files = { "wf/basis.json": basis, "wf/mo.json": mo };
  const coeffs = (/** @type {string} */ role, /** @type {number} */ rows) => {
    const data = float64Bytes(new Array(rows * 2).fill(0));
    members[role] = binaryMember(`wf/${role}.bin`, data, "float64", [rows, 2]);
    files[`wf/${role}.bin`] = data;
  };
  if (options.unrestricted) {
    coeffs("mo_coefficients_alpha", 2);
    coeffs("mo_coefficients_beta", 3);
  } else {
    coeffs("mo_coefficients", 2);
  }
  addSection(a, { id: "wf", kind: "wavefunction.gto", members }, files);
  const states = jsonBytes(payload);
  addSection(a, { id: "es", kind: "excited_states", ...fields, members: { states: jsonMember("es/states.json", states) } }, { "es/states.json": states });
  for (const add of options.extra ?? []) add(a);
  return pack(a);
}

/** @param {number} index @param {Record<string, unknown>} [more] */
const state = (index, more = {}) => ({ index, excitation_energy: { value: 7 + index, units: "ev" }, ...more });

/** A volume.transition_density "td" with the given section fields. @param {Record<string, unknown>} fields */
const transitionDensity = (fields) => (/** @type {ReturnType<typeof baseArchive>} */ a) => {
  const grid = jsonBytes({ origin: [0, 0, 0], voxel_vectors: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], shape: [2, 2, 2] });
  const data = float64Bytes(new Array(8).fill(0));
  addSection(
    a,
    { id: "td", kind: "volume.transition_density", ...fields, members: { grid: jsonMember("td/grid.json", grid), data: binaryMember("td/data.bin", data, "float64", [2, 2, 2]) } },
    { "td/grid.json": grid, "td/data.bin": data },
  );
};

/** A spectra.uvvis "uv" with the given payload. @param {unknown} payload */
const uvvis = (payload) => (/** @type {ReturnType<typeof baseArchive>} */ a) => {
  const data = jsonBytes(payload);
  addSection(a, { id: "uv", kind: "spectra.uvvis", members: { spectrum: jsonMember("uv/s.json", data) } }, { "uv/s.json": data });
};

test("validate: excited_states indices, n_states, references and orbital rows (spec § 5.12)", async () => {
  const contrib = (/** @type {number} */ to, /** @type {Record<string, unknown>} */ more = {}) => ({ contributions: [{ from_mo: 0, to_mo: to, weight: 1, ...more }] });
  const wf = { wavefunction_ref: "wf" };
  /** @type {[Uint8Array, string[], string?][]} */
  const cases = [
    [excitedArchive({ states: [state(1, contrib(1)), state(2)], meta: { n_states: 2 } }, wf), []],
    [excitedArchive({ states: [state(1), state(2), state(2)] }), ["E_MEMBER_MALFORMED"], "/sections/2/members/states"],
    [excitedArchive({ states: [state(2), state(1)] }), ["E_MEMBER_MALFORMED"]],
    [excitedArchive({ states: [state(1)], meta: { n_states: 3 } }), ["E_MEMBER_MALFORMED"]],
    [excitedArchive({ states: [state(1)] }, { wavefunction_ref: "structure" }), ["E_REF_UNRESOLVED"], "/sections/2/wavefunction_ref"],
    [excitedArchive({ states: [state(1, { nto_ref: "wf" })] }), []],
    [excitedArchive({ states: [state(1, { nto_ref: "structure" })] }), ["E_REF_UNRESOLVED"], "/sections/2/members/states"],
    [excitedArchive({ states: [state(1, { density_ref: "wf" })] }), ["E_REF_UNRESOLVED"]],
    [excitedArchive({ states: [state(1, contrib(2))] }, wf), ["E_MEMBER_MALFORMED"]],
    [excitedArchive({ states: [state(1, contrib(2))] }), []],
    [excitedArchive({ states: [state(1, contrib(2, { spin: "beta" }))] }, wf, { unrestricted: true }), []],
    [excitedArchive({ states: [state(1, contrib(2, { spin: "alpha" }))] }, wf, { unrestricted: true }), ["E_MEMBER_MALFORMED"]],
    [excitedArchive({ states: [state(1, contrib(2))] }, wf, { unrestricted: true }), ["E_MEMBER_MALFORMED"]],
    [excitedArchive({ states: [state(1)], meta: { units: { excitation_energy: "electronvolt" } } }), ["W_UNIT_UNKNOWN"]],
  ];
  for (const [bytes, want, where] of cases) {
    const report = await validate(bytes);
    assert.deepEqual(codes(report), want);
    if (where) assert.equal(report.findings.find((f) => f.code === want[0])?.where, where);
  }
  // The index rule is a semantics-level check; the references are not.
  const refsOnly = excitedArchive({ states: [state(1, { nto_ref: "structure" })] });
  assert.deepEqual(codes(await validate(refsOnly, { level: "semantics" })), []);
  const dup = excitedArchive({ states: [state(1), state(1)] });
  assert.deepEqual(codes(await validate(dup, { level: "semantics" })), ["E_MEMBER_MALFORMED"]);
});

test("validate: transition densities and spectra name states (spec § 5.2, § 5.4)", async () => {
  const two = { states: [state(1, { density_ref: "td" }), state(2)] };
  const spectrum = (/** @type {number} */ index, /** @type {string} */ ref) => ({
    frequencies: [8, 9],
    intensities: [0.1, 0.0],
    peaks: [{ x: 8, assignment: { state_index: index } }],
    states_ref: ref,
  });
  /** @type {[Uint8Array, string[], string?][]} */
  const cases = [
    [excitedArchive(two, {}, { extra: [transitionDensity({ excited_states_ref: "es", state_index: 1 })] }), []],
    [excitedArchive(two, {}, { extra: [transitionDensity({ excited_states_ref: "es", state_index: 5 })] }), ["E_REF_UNRESOLVED"], "/sections/3/state_index"],
    [excitedArchive(two, {}, { extra: [transitionDensity({ excited_states_ref: "wf" })] }), ["E_REF_UNRESOLVED"], "/sections/3/excited_states_ref"],
    [excitedArchive(two, {}, { extra: [transitionDensity({}), uvvis(spectrum(2, "es"))] }), []],
    [excitedArchive(two, {}, { extra: [transitionDensity({}), uvvis(spectrum(7, "es"))] }), ["E_REF_UNRESOLVED"], "/sections/4/members/spectrum"],
    [excitedArchive(two, {}, { extra: [transitionDensity({}), uvvis(spectrum(1, "wf"))] }), ["E_REF_UNRESOLVED"]],
  ];
  for (const [bytes, want, where] of cases) {
    const report = await validate(bytes);
    assert.deepEqual(codes(report), want);
    if (where) assert.equal(report.findings.find((f) => f.code === want[0])?.where, where);
  }
});

// --- container rules: member size, superseded manifests (spec § 2.3, § 4.2) ---

test("validate: a declared size is checked against the central directory at the manifest level", async () => {
  const a = baseArchive();
  const member = a.manifest.sections[0].members.structure;
  member.size = jsonBytes(WATER).length;
  assert.deepEqual(codes(await validate(pack(a))), []);
  member.size += 8;
  let report = await validate(pack(a));
  assert.deepEqual(codes(report), ["E_BINARY_SIZE"]);
  assert.equal(report.findings.find((f) => f.code === "E_BINARY_SIZE")?.where, "/sections/0/members/structure");
  // Central directory only: reported without reading any payload.
  assert.deepEqual(codes(await validate(pack(a), { level: "manifest" })), ["E_BINARY_SIZE"]);
  assert.deepEqual(codes(await validate(pack(a), { level: "container" })), []);
  for (const bad of [-1, 1.5, "490", true, null]) {
    member.size = bad;
    report = await validate(pack(a));
    assert.deepEqual(codes(report), ["E_MEMBER_MALFORMED"], String(bad));
  }
});

test("validate: size applies to binary and opaque members too", async () => {
  const a = baseArchive();
  const q = float64Bytes([-0.66, 0.33, 0.33]);
  const bib = enc.encode("@misc{x, title={y}}\n");
  addSection(
    a,
    { id: "ap", kind: "atom_properties", members: { mulliken_charge: { ...binaryMember("ap/q.bin", q, "float64", [3]), size: 24 } } },
    { "ap/q.bin": q },
  );
  addSection(
    a,
    { id: "citations", kind: "citations", members: { references: { ...opaqueMember("c/r.bib", bib), size: bib.length } } },
    { "c/r.bib": bib },
  );
  assert.deepEqual(codes(await validate(pack(a))), []);
  a.manifest.sections[1].members.mulliken_charge.size = 16;
  a.manifest.sections[2].members.references.size = 0;
  assert.deepEqual(codes(await validate(pack(a))), ["E_BINARY_SIZE", "E_BINARY_SIZE"]);
});

test("validate: superseded manifest.json copies are orphans, the last one is the manifest", async () => {
  const a = baseArchive();
  const stale = structuredClone(a.manifest);
  stale.provenance = { run_status: "pending" };
  a.manifest.provenance = { run_status: "converged" };
  const bytes = buildZip([
    ...a.entries,
    { name: "manifest.json", data: jsonBytes(stale), method: 0 },
    { name: "old.json", data: "{}" },
    { name: "manifest.json", data: jsonBytes(stale), method: 0 },
    { name: "manifest.json", data: jsonBytes(a.manifest), method: 0 },
  ]);
  const report = await validate(bytes);
  assert.ok(report.ok);
  assert.deepEqual(codes(report), ["W_ORPHAN_MEMBER", "W_ORPHAN_MEMBER", "W_ORPHAN_MEMBER"]);
  assert.deepEqual(
    report.findings.filter((f) => f.code === "W_ORPHAN_MEMBER").map((f) => f.where),
    ["entry:manifest.json", "entry:manifest.json", "entry:old.json"],
  );
  assert.equal(QvfReader.fromBytes(bytes).manifest.provenance?.run_status, "converged");
  // Any other duplicated name is still an ambiguous archive.
  const dup = buildZip([...a.entries, ...a.entries, { name: "manifest.json", data: jsonBytes(a.manifest), method: 0 }]);
  assert.deepEqual(codes(await validate(dup)), ["E_ZIP_DUPLICATE_ENTRY"]);
});

/**
 * A water archive with one trajectory-family section: coords [4, 3, 3] of
 * `coordsDtype` (zero-filled), metadata `meta` and float64 `extra` members
 * (role -> [shape, values?]).
 * @param {string} kind
 * @param {Record<string, unknown>} meta
 * @param {Record<string, [number[], number[]?]>} [extra]
 * @param {"float64"|"float32"} [coordsDtype]
 */
function trajectoryArchive(kind, meta, extra = {}, coordsDtype = "float64") {
  const a = baseArchive();
  const m = jsonBytes(meta);
  const coords = new Uint8Array(36 * (coordsDtype === "float32" ? 4 : 8));
  /** @type {Record<string, unknown>} */
  const members = { metadata: jsonMember("t/metadata.json", m), coords: binaryMember("t/coords.bin", coords, coordsDtype, [4, 3, 3]) };
  /** @type {Record<string, Uint8Array>} */
  const files = { "t/metadata.json": m, "t/coords.bin": coords };
  for (const [role, [shape, values]] of Object.entries(extra)) {
    const data = float64Bytes(values ?? new Array(shape.reduce((x, y) => x * y, 1)).fill(0));
    members[role] = binaryMember(`t/${role}.bin`, data, "float64", shape);
    files[`t/${role}.bin`] = data;
  }
  addSection(a, { id: "t", kind, members }, files);
  return pack(a);
}

test("validate: trajectory and reaction.path members (spec § 5.5)", async () => {
  const sym = { symbols: ["O", "H", "H"] };
  const pbc = { ...sym, pbc: [true, true, false] };
  const e4 = [-76.0, -76.1, -76.2, -76.3];
  /** @type {[Uint8Array, string?][]} */
  const cases = [
    [
      trajectoryArchive(
        "trajectory",
        { ...pbc, energies: e4, kind: "md", ensemble: "npt", timestep_fs: 0.5 },
        {
          lattice: [[4, 3, 3]],
          velocities: [[4, 3, 3]],
          gradient: [[4, 3, 3]],
          times: [[4]],
          energies: [[4], e4],
          cell_volumes: [[4]],
          temperatures: [[4]],
        },
      ),
    ],
    [trajectoryArchive("trajectory", { ...sym, precision: "float32" }, {}, "float32")],
    [trajectoryArchive("trajectory", { ...sym, pbc: [false, false, false] }, { lattice: [[3, 3]] })],
    [trajectoryArchive("reaction.path", sym, { lattice: [[4, 3, 3]], velocities: [[4, 3, 3]], times: [[4]], energies: [[4]] })],
    [trajectoryArchive("trajectory", { ...sym, energies: e4 }, { energies: [[4], [-76.0, -76.1 + 5e-11, -76.2, -76.3]] })],
    [trajectoryArchive("trajectory", sym, {}, "float32"), "coords"],
    [trajectoryArchive("trajectory", { ...sym, precision: "float32" }), "coords"],
    [trajectoryArchive("reaction.path", sym, {}, "float32"), "coords"],
    [trajectoryArchive("trajectory", sym, { velocities: [[5, 3, 3]] }), "velocities"],
    [trajectoryArchive("trajectory", sym, { gradient: [[4, 2, 3]] }), "gradient"],
    [trajectoryArchive("trajectory", sym, { times: [[3]] }), "times"],
    [trajectoryArchive("trajectory", sym, { cell_volumes: [[4, 1]] }), "cell_volumes"],
    [trajectoryArchive("trajectory", sym, { temperatures: [[1]] }), "temperatures"],
    [trajectoryArchive("reaction.path", sym, { gradient: [[3, 3, 3]] }), "gradient"],
    [trajectoryArchive("trajectory", pbc, { lattice: [[3, 3, 3]] }), "lattice"],
    [trajectoryArchive("reaction.path", sym, { lattice: [[5, 3, 3]] }), "lattice"],
    [trajectoryArchive("trajectory", { ...sym, energies: e4 }, { energies: [[4], [-76.0, -76.1, -76.2 + 2e-10, -76.3]] }), "energies"],
    [trajectoryArchive("reaction.path", { ...sym, energies: [-76.0, -76.1, -76.2] }, { energies: [[4], e4] }), "energies"],
    [trajectoryArchive("trajectory", sym, { lattice: [[3, 3]] }), "metadata"],
    [trajectoryArchive("trajectory", { ...sym, pbc: [false, true, false] }), "metadata"],
  ];
  for (const [bytes, role] of cases) {
    const report = await validate(bytes);
    if (role === undefined) {
      assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
    } else {
      assert.deepEqual(codes(report), ["E_MEMBER_MALFORMED"], role);
      assert.equal(report.findings.find((f) => f.code === "E_MEMBER_MALFORMED")?.where, `/sections/1/members/${role}`);
    }
  }
  // The rules are semantic: below that level they do not run.
  assert.deepEqual(codes(await validate(trajectoryArchive("trajectory", sym, {}, "float32"), { level: "payloads" })), []);
});

/**
 * A structure (`structure`, a payload object) plus one volume section of `kind`
 * whose grid is `grid` and whose float64 data (zeros) has `shape`, with an
 * optional axis member and section fields.
 * @param {string} kind
 * @param {Record<string, unknown>} grid
 * @param {number[]} shape
 * @param {{ axis?: unknown, structure?: unknown, fields?: Record<string, unknown> }} [options]
 */
function volumeArchive(kind, grid, shape, options = {}) {
  const a = baseArchive();
  if (options.structure) {
    const data = jsonBytes(options.structure);
    a.manifest.sections[0].members.structure = jsonMember("structure/structure.json", data);
    a.entries[0] = { name: "structure/structure.json", data };
  }
  const g = jsonBytes(grid);
  const data = float64Bytes(new Array(shape.reduce((x, y) => x * y, 1)).fill(0));
  /** @type {Record<string, unknown>} */
  const members = { grid: jsonMember("v/grid.json", g), data: binaryMember("v/data.bin", data, "float64", shape) };
  /** @type {Record<string, Uint8Array>} */
  const files = { "v/grid.json": g, "v/data.bin": data };
  if (options.axis !== undefined) {
    const ax = jsonBytes(options.axis);
    members.axis = jsonMember("v/axis.json", ax);
    files["v/axis.json"] = ax;
  }
  addSection(a, { id: "v", kind, ...(options.fields ?? {}), members }, files);
  return pack(a);
}

const UNIT_GRID = { origin: [0, 0, 0], voxel_vectors: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], shape: [2, 2, 2] };

test("validate: data shapes and the series axis of the new volume kinds (spec § 5.2)", async () => {
  /** @type {[Uint8Array, string[], string?][]} */
  const cases = [
    [volumeArchive("volume.vector", UNIT_GRID, [2, 2, 2, 3]), []],
    [volumeArchive("volume.complex", UNIT_GRID, [2, 2, 2, 2]), []],
    [volumeArchive("volume.laplacian", UNIT_GRID, [2, 2, 2]), []],
    [volumeArchive("volume.series", UNIT_GRID, [3, 2, 2, 2], { axis: { kind: "time", values: [0, 1, 2], units: "fs" } }), []],
    [volumeArchive("volume.vector", UNIT_GRID, [2, 2, 2, 2]), ["E_MEMBER_MALFORMED"], "/sections/1/members/data"],
    [volumeArchive("volume.complex", UNIT_GRID, [2, 2, 2, 3]), ["E_MEMBER_MALFORMED"]],
    [volumeArchive("volume.laplacian", UNIT_GRID, [2, 2, 2, 1]), ["E_MEMBER_MALFORMED"]],
    [volumeArchive("volume.series", UNIT_GRID, [2, 2, 2], { axis: { kind: "custom", values: [0, 1] } }), ["E_MEMBER_MALFORMED"]],
    [
      volumeArchive("volume.series", UNIT_GRID, [3, 2, 2, 2], { axis: { kind: "time", values: [0, 1] } }),
      ["E_MEMBER_MALFORMED"],
      "/sections/1/members/axis",
    ],
    [volumeArchive("volume.series", UNIT_GRID, [3, 2, 2, 2], { axis: { kind: "state", values: [1, 2, 3], labels: ["S1"] } }), ["E_MEMBER_MALFORMED"]],
    [
      volumeArchive("volume.series", UNIT_GRID, [3, 2, 2, 2], { axis: { kind: "frame", values: [0, 1, 2], trajectory_ref: "structure" } }),
      ["E_REF_UNRESOLVED"],
      "/sections/1/members/axis",
    ],
    [volumeArchive("volume.series", UNIT_GRID, [3, 2, 2, 2], { axis: { kind: "time", values: [0, 1, 2], units: "sec" } }), ["W_UNIT_UNKNOWN"]],
  ];
  for (const [bytes, want, where] of cases) {
    const report = await validate(bytes);
    assert.deepEqual(codes(report), want);
    assert.equal(report.ok, !want.some((c) => c.startsWith("E_")));
    if (where) assert.equal(report.findings.find((f) => f.code === want[0])?.where, where);
  }
  // The axis reference waits for the references level; the shapes do not.
  const badRef = volumeArchive("volume.series", UNIT_GRID, [3, 2, 2, 2], {
    axis: { kind: "frame", values: [0, 1, 2], trajectory_ref: "nowhere" },
  });
  assert.deepEqual(codes(await validate(badRef, { level: "semantics" })), []);
  assert.deepEqual(codes(await validate(badRef)), ["E_REF_UNRESOLVED"]);
  const wrongShape = volumeArchive("volume.vector", UNIT_GRID, [2, 2, 2, 2]);
  assert.deepEqual(codes(await validate(wrongShape, { level: "semantics" })), ["E_MEMBER_MALFORMED"]);
});

const CUBIC = {
  atoms: [{ symbol: "Na", position: [0, 0, 0], atomic_number: 11 }],
  pbc: [true, true, true],
  lattice_vectors: [
    [4, 0, 0],
    [0, 4, 0],
    [0, 0, 4],
  ],
};

/**
 * A grid periodic on all three axes of the 4 Å cubic cell, shape [4, 4, 4],
 * `step` bohr per point.
 * @param {number} step
 * @param {Record<string, unknown>} [extra]
 */
function periodicGrid(step, extra = {}) {
  return {
    origin: [0, 0, 0],
    voxel_vectors: [
      [step, 0, 0],
      [0, step, 0],
      [0, 0, step],
    ],
    shape: [4, 4, 4],
    periodic: [true, true, true],
    ...extra,
  };
}

test("validate: a periodic grid spans the cell of its structure (spec § 5.2)", async () => {
  const chgcar = 1.8897261246; // 4 Å over 4 points
  const cube = (4 * 1.8897261246) / 3; // 4 Å over 3 steps
  const three = ["E_MEMBER_MALFORMED", "E_MEMBER_MALFORMED", "E_MEMBER_MALFORMED"];
  const withCell = { structure: CUBIC };
  /** @type {[Uint8Array, string[], string?][]} */
  const cases = [
    [volumeArchive("volume.density", periodicGrid(chgcar, { includes_endpoint: false }), [4, 4, 4], withCell), []],
    [volumeArchive("volume.density", periodicGrid(cube, { includes_endpoint: true }), [4, 4, 4], withCell), []],
    [volumeArchive("volume.density", periodicGrid(cube), [4, 4, 4], withCell), []],
    [volumeArchive("volume.density", periodicGrid(chgcar, { includes_endpoint: true }), [4, 4, 4], withCell), three, "/sections/1/members/grid"],
    [volumeArchive("volume.density", periodicGrid(chgcar * (1 + 2e-6), { includes_endpoint: false }), [4, 4, 4], withCell), three],
    [volumeArchive("volume.density", periodicGrid(chgcar * (1 + 5e-7), { includes_endpoint: false }), [4, 4, 4], withCell), []],
    // A periodic grid of a molecule: every periodic axis is reported.
    [volumeArchive("volume.density", periodicGrid(chgcar), [4, 4, 4]), three],
    [volumeArchive("volume.density", periodicGrid(chgcar, { structure_ref: "v" }), [4, 4, 4], withCell), ["E_REF_UNRESOLVED"], "/sections/1/members/grid"],
    // The section-level structure_ref names the cell when the grid names none.
    [
      volumeArchive("volume.density", periodicGrid(chgcar, { includes_endpoint: false }), [4, 4, 4], {
        structure: CUBIC,
        fields: { structure_ref: "structure" },
      }),
      [],
    ],
  ];
  for (const [bytes, want, where] of cases) {
    const report = await validate(bytes);
    assert.deepEqual(codes(report), want);
    if (where) assert.equal(report.findings.find((f) => f.code === want[0])?.where, where);
  }
  // Below the references level the span is not compared.
  const wrong = volumeArchive("volume.density", periodicGrid(chgcar, { includes_endpoint: true }), [4, 4, 4], withCell);
  assert.deepEqual(codes(await validate(wrong, { level: "semantics" })), []);
});

// --- property kinds (spec § 5.13) -------------------------------------------------

/** @param {number} x a 3 x 3 matrix with x on the diagonal */
const diag3 = (x) => [0, 1, 2].map((i) => [0, 1, 2].map((j) => (i === j ? x : 0)));

/** A cubic 6 x 6 stiffness matrix, optionally with entry (i, j) replaced. */
function cubic6(/** @type {[number, number, number] | null} */ change = null) {
  /** @type {number[][]} */
  const m = [0, 1, 2, 3, 4, 5].map((i) => [0, 1, 2, 3, 4, 5].map((j) => (i === j ? (i < 3 ? 36.4 : 8) : i < 3 && j < 3 ? 8.8 : 0)));
  if (change) m[change[0]][change[1]] = change[2];
  return m;
}

/**
 * A water archive with one property section (a `properties` JSON member).
 * @param {string} kind
 * @param {unknown} payload
 * @param {Record<string, unknown>} [fields] section fields
 * @param {Record<string, unknown>} [root] manifest root fields
 */
function propertiesArchive(kind, payload, fields = {}, root = {}) {
  const a = baseArchive();
  const sid = kind.split(".")[1];
  const data = jsonBytes(payload);
  addSection(a, { id: sid, kind, ...fields, members: { properties: jsonMember(`${sid}/properties.json`, data) } }, { [`${sid}/properties.json`]: data });
  Object.assign(a.manifest, root);
  return pack(a);
}

test("validate: elastic matrices must be symmetric (spec § 5.13)", async () => {
  const where = "/sections/1/members/properties";
  for (const [payload, want] of /** @type {[Record<string, unknown>, string[]][]} */ ([
    [{ stiffness: cubic6() }, []],
    [{ stiffness: cubic6(), compliance: cubic6() }, []],
    [{ stiffness: cubic6([1, 0, 9.9]) }, ["E_MEMBER_MALFORMED"]],
    [{ stiffness: cubic6(), compliance: cubic6([2, 4, 3]) }, ["E_MEMBER_MALFORMED"]],
    [{ stiffness: cubic6([0, 1, 8.8 + 3e-5]) }, []], // within 1e-6 of the largest entry
    [{ stiffness: cubic6([0, 1, 8.8 + 5e-5]) }, ["E_MEMBER_MALFORMED"]],
    [{ stiffness: [[0, 0, 0, 0, 0, 0]] }, []], // malformed: left to the schema
    [{ stiffness: "soft" }, []],
  ])) {
    const report = await validate(propertiesArchive("properties.elastic", payload));
    assert.deepEqual(codes(report), want);
    if (want.length) assert.equal(report.findings.find((f) => f.code === want[0])?.where, where);
  }
  // Below the semantics level nothing is compared.
  assert.deepEqual(codes(await validate(propertiesArchive("properties.elastic", { stiffness: cubic6([1, 0, 9.9]) }), { level: "payloads" })), []);
});

test("validate: static must equal electronic plus ionic (spec § 5.13)", async () => {
  const electronic = diag3(2.62);
  const ionic = diag3(4.58);
  for (const [payload, want] of /** @type {[Record<string, unknown>, string[]][]} */ ([
    [{ electronic, ionic, static: diag3(7.2) }, []],
    [{ electronic, ionic, static: diag3(7.5) }, ["E_MEMBER_MALFORMED"]],
    [{ electronic, ionic, static: [[7.2, 5e-7, 0], [0, 7.2, 0], [0, 0, 7.2]] }, []],
    [{ electronic, ionic, static: [[7.2, 2e-6, 0], [0, 7.2, 0], [0, 0, 7.2]] }, ["E_MEMBER_MALFORMED"]],
    [{ electronic, static: diag3(9) }, []], // not all three present
    [{ electronic, ionic: [[1]], static: diag3(9) }, []], // malformed: left to the schema
  ])) {
    assert.deepEqual(codes(await validate(propertiesArchive("properties.dielectric", payload))), want);
  }
});

test("validate: Born charges must number the atoms of the section's structure (spec § 5.13)", async () => {
  const born = (/** @type {number} */ n) => ({ electronic: diag3(1), born_charges: Array.from({ length: n }, () => diag3(0.5)) });
  assert.deepEqual(codes(await validate(propertiesArchive("properties.dielectric", born(3)))), []);
  const report = await validate(propertiesArchive("properties.dielectric", born(2)));
  assert.deepEqual(codes(report), ["E_MEMBER_MALFORMED"]);
  assert.equal(report.findings.find((f) => f.code === "E_MEMBER_MALFORMED")?.where, "/sections/1/members/properties");
  // The count needs the structures, so it belongs to the references level.
  assert.deepEqual(codes(await validate(propertiesArchive("properties.dielectric", born(2)), { level: "semantics" })), []);
  // A section-level structure_ref takes precedence over the only structure.
  assert.deepEqual(codes(await validate(propertiesArchive("properties.dielectric", born(2), { structure_ref: "structure" }))), ["E_MEMBER_MALFORMED"]);
  assert.deepEqual(codes(await validate(propertiesArchive("properties.dielectric", born(2), { structure_ref: "nowhere" }))), ["E_REF_UNRESOLVED"]);
});

test("validate: an electric dipole must agree with the root dipole_moment (spec § 5.13)", async () => {
  const root = { dipole_moment: { total_debye: 1.85, vector_debye: [0, 0, -1.85], origin: "center_of_mass" } };
  /** @type {[Record<string, unknown>, Record<string, unknown>, string[]][]} */
  const cases = [
    [{ vector: [0, 0, -1.85 + 5e-7], total: 1.85 - 5e-7 }, root, []],
    [{ vector: [0, 0, -1.5] }, root, ["E_ROOT_INCONSISTENT"]],
    [{ vector: [0, 0, -1.85 + 2e-6] }, root, ["E_ROOT_INCONSISTENT"]],
    [{ vector: [0, 0, -1.85], total: 1.5 }, root, ["E_ROOT_INCONSISTENT"]],
    [{ vector: [0, 0, -1.5], total: 1.5 }, root, ["E_ROOT_INCONSISTENT", "E_ROOT_INCONSISTENT"]],
    [{ vector: [0, 0, -1.5] }, {}, []], // no root block
    [{ vector: [0, 0, -1.5] }, { dipole_moment: { origin: "origin" } }, []],
    [{ vector: [0, 0, -1.85] }, { dipole_moment: { total_debye: 99 } }, []], // only the total is stated at the root
    [{ vector: [0, 0, -1.5] }, { dipole_moment: { vector_debye: [0, 0] } }, []], // malformed: left to the schema
  ];
  for (const [dipole, rootFields, want] of cases) {
    const report = await validate(propertiesArchive("properties.electric", { dipole }, {}, rootFields));
    assert.deepEqual(codes(report), want);
    if (want.length) assert.equal(report.findings.find((f) => f.code === "E_ROOT_INCONSISTENT")?.where, "/sections/1/members/properties");
  }
  assert.deepEqual(codes(await validate(propertiesArchive("properties.electric", { dipole: { vector: [0, 0, -1.5] } }, {}, root), { level: "payloads" })), []);
});

test("validate: the property kinds are canonical and declare units", async () => {
  const report = await validate(propertiesArchive("properties.elastic", { stiffness: cubic6(), units: { stiffness: "GPa" } }));
  assert.equal(report.ok, true);
  assert.deepEqual(codes(report), ["W_UNIT_UNKNOWN"]);
  assert.deepEqual(codes(await validate(propertiesArchive("properties.elastic", { stiffness: cubic6(), units: { stiffness: "gpa" } }))), []);
});

// --- wavefunction.bloch (spec § 5.3.1) ---------------------------------------

const CHAIN = {
  atoms: [
    { symbol: "H", position: [0.0, 0.0, 0.0], atomic_number: 1 },
    { symbol: "H", position: [0.8, 0.0, 0.0], atomic_number: 1 },
  ],
  pbc: [true, false, false],
  lattice_vectors: [
    [2.0, 0.0, 0.0],
    [0.0, 10.0, 0.0],
    [0.0, 0.0, 10.0],
  ],
};
const BLOCH_SHELLS = [0, 1].map((center) => ({ center, l: 0, exponents: [0.4166], coefficients: [1.0] }));
const BLOCH_META = { spin: "unrestricted", n_spin: 2, n_mo: 2, n_ao: 2, complex: true, k_point_convention: "fractional" };
const BLOCH_KPTS = [
  [0, 0, 0],
  [0.5, 0, 0],
];

/**
 * An archive with one structure (periodic chain unless `structure` says otherwise)
 * and one wavefunction.bloch section built from the given pieces.
 * @param {{ coeff?: number[], energies?: number[], occ?: number[], kpoints?: unknown, meta?: unknown,
 *           basis?: unknown, structure?: unknown, fields?: Record<string, unknown>,
 *           extraStructure?: [string, unknown] }} [o]
 */
function blochArchive(o = {}) {
  const a = baseArchive();
  a.manifest.sections = [];
  a.entries = [];
  /** @param {string} id @param {unknown} payload */
  const addStructure = (id, payload) => {
    const data = jsonBytes(payload);
    addSection(a, { id, kind: "structure", members: { structure: jsonMember(`${id}/structure.json`, data) } }, {
      [`${id}/structure.json`]: data,
    });
  };
  addStructure("structure", o.structure ?? CHAIN);
  if (o.extraStructure) addStructure(...o.extraStructure);
  /** @type {Record<string, unknown>} */
  const members = {};
  /** @type {Record<string, Uint8Array>} */
  const files = {};
  const json = {
    basis: o.basis ?? { structure_ref: "structure", pure: true, n_ao: 2, shells: BLOCH_SHELLS },
    kpoints: o.kpoints ?? { kpoints: BLOCH_KPTS, weights: [0.5, 0.5] },
    mo_metadata: o.meta ?? BLOCH_META,
  };
  for (const [role, payload] of Object.entries(json)) {
    const data = jsonBytes(payload);
    members[role] = jsonMember(`wf/${role}.json`, data);
    files[`wf/${role}.json`] = data;
  }
  const shapes = { mo_coefficients: o.coeff ?? [2, 2, 2, 2, 2], energies: o.energies ?? [2, 2, 2], occupations: o.occ ?? [2, 2, 2] };
  for (const [role, shape] of Object.entries(shapes)) {
    const data = float64Bytes(new Array(shape.reduce((x, y) => x * y, 1)).fill(0.5));
    members[role] = binaryMember(`wf/${role}.bin`, data, "float64", shape);
    files[`wf/${role}.bin`] = data;
  }
  addSection(a, { id: "wf", kind: "wavefunction.bloch", ...(o.fields ?? {}), members }, files);
  return pack(a);
}

test("validate: a valid wavefunction.bloch section is clean", async () => {
  assert.deepEqual(codes(await validate(blochArchive())), []);
  assert.deepEqual(codes(await validate(blochArchive({ kpoints: { kpoints: BLOCH_KPTS } }))), []);
  assert.deepEqual(codes(await validate(blochArchive({ kpoints: { kpoints: BLOCH_KPTS, weights: [0.5, 0.5000005] } }))), []);
});

test("validate: wavefunction.bloch shapes, weights and metadata (spec § 5.3.1)", async () => {
  const m = "/sections/1/members/";
  /** @type {[Parameters<typeof blochArchive>[0], string][]} */
  const cases = [
    [{ coeff: [2, 2, 2, 2, 1] }, "mo_coefficients"],
    [{ coeff: [2, 3, 2, 2, 2], energies: [2, 3, 2], occ: [2, 3, 2] }, "mo_coefficients"],
    [{ coeff: [2, 2, 2, 2] }, "mo_coefficients"],
    [{ energies: [2, 2, 3] }, "energies"],
    [{ energies: [2, 2] }, "energies"],
    [{ occ: [1, 2, 2] }, "occupations"],
    [{ kpoints: { kpoints: [...BLOCH_KPTS, [0.25, 0, 0]], weights: [0.5, 0.25, 0.25] } }, "kpoints"],
    [{ kpoints: { kpoints: BLOCH_KPTS, weights: [1.0] } }, "kpoints"],
    [{ kpoints: { kpoints: BLOCH_KPTS, weights: [0.5, 0.25] } }, "kpoints"],
    [{ kpoints: { kpoints: BLOCH_KPTS, labels: ["G"] } }, "kpoints"],
    [{ meta: { ...BLOCH_META, n_mo: 3 } }, "mo_metadata"],
    [{ meta: { ...BLOCH_META, n_ao: 3 } }, "mo_metadata"],
    [{ meta: { ...BLOCH_META, spin: "restricted" } }, "mo_metadata"],
    [{ meta: { ...BLOCH_META, n_mo_per_k: [2] } }, "mo_metadata"],
    [{ meta: { ...BLOCH_META, n_mo_per_k: [2, 3] } }, "mo_metadata"],
    [{ basis: { structure_ref: "structure", n_ao: 3, shells: BLOCH_SHELLS } }, "basis"],
    [{ structure: WATER }, "basis"],
  ];
  for (const [options, role] of cases) {
    const report = await validate(blochArchive(options));
    assert.deepEqual([...new Set(codes(report))], ["E_MEMBER_MALFORMED"], JSON.stringify(options));
    assert.ok(
      report.findings.some((f) => f.code === "E_MEMBER_MALFORMED" && f.where === `${m}${role}`),
      JSON.stringify(options),
    );
  }
  // The structure rule needs the references level; the shape rules do not.
  assert.deepEqual(codes(await validate(blochArchive({ structure: WATER }), { level: "semantics" })), []);
  assert.deepEqual(codes(await validate(blochArchive({ occ: [1, 2, 2] }), { level: "semantics" })), ["E_MEMBER_MALFORMED"]);
});

test("validate: the structure of a wavefunction.bloch section must resolve and be periodic", async () => {
  let report = await validate(blochArchive({ basis: { structure_ref: "nowhere", n_ao: 2, shells: BLOCH_SHELLS } }));
  assert.deepEqual(codes(report), ["E_REF_UNRESOLVED"]);
  assert.equal(report.findings.find((f) => f.code === "E_REF_UNRESOLVED")?.where, "/sections/1/members/basis");
  // The section-level structure_ref takes precedence over the basis one.
  report = await validate(
    blochArchive({
      extraStructure: ["mol", WATER],
      basis: { structure_ref: "mol", n_ao: 2, shells: BLOCH_SHELLS },
      fields: { structure_ref: "structure" },
    }),
  );
  assert.deepEqual(codes(report), []);
  report = await validate(blochArchive({ extraStructure: ["mol", WATER], fields: { structure_ref: "mol" } }));
  assert.deepEqual(codes(report), ["E_MEMBER_MALFORMED"]);
  assert.equal(report.findings.find((f) => f.code === "E_MEMBER_MALFORMED")?.where, "/sections/2/structure_ref");
  report = await validate(blochArchive({ fields: { structure_ref: "nowhere" } }));
  assert.deepEqual(codes(report), ["E_REF_UNRESOLVED"]);
  assert.equal(report.findings.find((f) => f.code === "E_REF_UNRESOLVED")?.where, "/sections/1/structure_ref");
});
