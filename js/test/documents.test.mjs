// Documents before a calculation: the withdrawn qvf_version 2 (spec § 3.1),
// the member-spec media_type and opaque vendor members (spec § 4.2, § 7.3),
// the chemical identity of a structure (spec § 5.1), a run.record job_ref
// (spec § 5.8), reaction.scheme (spec § 5.14) and preview (spec § 5.15),
// with the codes, severities and JSON pointers of the Python reference
// validator.

import assert from "node:assert/strict";
import { test } from "node:test";

import { FINDING_CODES, QvfReader, validate as validateWithSchema } from "../dist/index.js";
import { WATER, addSection, baseArchive, binaryMember, float64Bytes, jsonBytes, jsonMember, opaqueMember, pack } from "./helpers.mjs";

// Each archive isolates one rule, so most tests validate without the JSON
// Schema check generated from the schema (W_SCHEMA_SKIPPED), like the other
// semantic tests; the ones that pass `schemaCheck: true` show that a valid
// document is schema-clean too.
/** @type {typeof validateWithSchema} */
const validate = (bytes, options = {}) => validateWithSchema(bytes, { schemaCheck: false, ...options });

const enc = new TextEncoder();

/** The codes of a report, without the always-present W_SCHEMA_SKIPPED. */
function codes(/** @type {{ findings: { code: string }[] }} */ report) {
  return report.findings.map((f) => f.code).filter((c) => c !== "W_SCHEMA_SKIPPED");
}

/** `[code, where]` of every finding but W_SCHEMA_SKIPPED. */
function located(/** @type {{ findings: { code: string, where: string }[] }} */ report) {
  return report.findings.filter((f) => f.code !== "W_SCHEMA_SKIPPED").map((f) => [f.code, f.where]);
}

/** Every finding carries the fixed severity of its code. */
function assertSeverities(/** @type {{ findings: { code: string, severity: string }[] }} */ report) {
  for (const f of report.findings) {
    assert.equal(FINDING_CODES[/** @type {keyof typeof FINDING_CODES} */ (f.code)], f.severity, `${f.code} has its fixed severity`);
  }
}

// --- the withdrawn qvf_version 2 (spec § 3.1) -----------------------------------

test("qvf_version 2 is the warning W_VERSION_WITHDRAWN and the archive is valid", async () => {
  const a = baseArchive();
  a.manifest.qvf_version = 2;
  for (const schemaCheck of [true, false]) {
    const report = await validateWithSchema(pack(a), { schemaCheck });
    assert.deepEqual(located(report), [["W_VERSION_WITHDRAWN", "/qvf_version"]], JSON.stringify(report.findings));
    assert.equal(report.ok, true);
    assertSeverities(report);
  }
});

test("qvf_version 2 is checked as version 1, the JSON Schema check included", async () => {
  // The schema check sees qvf_version 1, so it reports only the real defect.
  const a = baseArchive();
  a.manifest.qvf_version = 2;
  a.manifest.byte_order = "big";
  const report = await validateWithSchema(pack(a));
  assert.deepEqual(located(report), [
    ["W_VERSION_WITHDRAWN", "/qvf_version"],
    ["E_SCHEMA", "/byte_order"],
  ]);
  assert.equal(report.ok, false);
});

test("qvf_version 2.0 reads as 2; every other value is E_VERSION", async () => {
  const a = baseArchive();
  a.manifestBytes = enc.encode(JSON.stringify(a.manifest).replace('"qvf_version":1', '"qvf_version":2.0'));
  assert.deepEqual(codes(await validate(pack(a))), ["W_VERSION_WITHDRAWN"]);
  for (const version of [0, 3, "2", true, null, 1.5]) {
    const b = baseArchive();
    b.manifest.qvf_version = version;
    const report = await validate(pack(b));
    assert.deepEqual(located(report), [["E_VERSION", "/qvf_version"]], `qvf_version ${JSON.stringify(version)}`);
  }
});

test("the version warning is a manifest-level finding", async () => {
  const a = baseArchive();
  a.manifest.qvf_version = 2;
  const bytes = pack(a);
  assert.deepEqual(codes(await validate(bytes, { level: "container" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "manifest" })), ["W_VERSION_WITHDRAWN"]);
});

test("the reader opens a version 2 archive", () => {
  const a = baseArchive();
  a.manifest.qvf_version = 2;
  assert.equal(QvfReader.fromBytes(pack(a)).versionReadable, true);
});

// --- media_type and opaque vendor members (spec § 4.2, § 7.3) -----------------

test("an opaque vendor member, with or without media_type, is valid", async () => {
  const a = baseArchive();
  const svg = enc.encode('<svg xmlns="http://www.w3.org/2000/svg"/>');
  const blob = Uint8Array.of(0, 1, 2, 255);
  const doc = jsonBytes({ format: "drawing", version: 1 });
  const grid = float64Bytes([1, 2]);
  addSection(
    a,
    {
      id: "drawing",
      kind: "x_test.drawing",
      members: {
        picture: { ...opaqueMember("drawing/picture.svg", svg), media_type: "image/svg+xml" },
        blob: opaqueMember("drawing/blob.bin", blob),
        document: { ...jsonMember("drawing/document.json", doc), media_type: "application/json" },
        values: { ...binaryMember("drawing/values.bin", grid, "float64", [2]), media_type: "application/octet-stream" },
      },
    },
    { "drawing/picture.svg": svg, "drawing/blob.bin": blob, "drawing/document.json": doc, "drawing/values.bin": grid },
  );
  for (const schemaCheck of [true, false]) {
    const report = await validateWithSchema(pack(a), { schemaCheck });
    assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
    assert.equal(report.ok, true);
  }
});

test("media_type is a typed field of every member spec", async () => {
  const a = baseArchive();
  const png = Uint8Array.of(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13);
  const doc = jsonBytes({ note: "x" });
  a.manifest.sections[0].members.structure.media_type = "application/json";
  addSection(
    a,
    {
      id: "v",
      kind: "x_test.v",
      members: {
        picture: { ...opaqueMember("v/picture.png", png), media_type: "image/png" },
        plain: jsonMember("v/plain.json", doc),
      },
    },
    { "v/picture.png": png, "v/plain.json": doc },
  );
  const reader = QvfReader.fromBytes(pack(a));
  // `media_type` is declared on both member-spec types, so it reads without a cast.
  /** @type {import("../dist/index.js").MemberSpec} */
  const structure = reader.memberSpec("structure", "structure");
  /** @type {import("../dist/index.js").BinaryMemberSpec} */
  const picture = /** @type {import("../dist/index.js").BinaryMemberSpec} */ (reader.memberSpec("v", "picture"));
  /** @type {string | undefined} */
  const plain = reader.memberSpec("v", "plain").media_type;
  assert.equal(structure.media_type, "application/json");
  assert.equal(picture.media_type, "image/png");
  assert.equal(picture.dtype, undefined);
  assert.equal(plain, undefined);
  assert.deepEqual(await reader.readBytes("v", "picture"), png);
});

// --- chemical identity of a structure (spec § 5.1) -----------------------------

/**
 * The water archive (Σ Z = 10) with `fields` on the structure section and,
 * when given, a root `provenance`.
 * @param {Record<string, unknown>} fields
 * @param {Record<string, unknown>} [provenance]
 * @param {unknown} [payload]
 */
function identityArchive(fields, provenance, payload = WATER) {
  const a = baseArchive();
  const data = jsonBytes(payload);
  a.entries[0] = { name: "structure/structure.json", data };
  Object.assign(a.manifest.sections[0], fields, { members: { structure: jsonMember("structure/structure.json", data) } });
  if (provenance) a.manifest.provenance = provenance;
  return a;
}

test("a structure's chemical identity that fits its atoms is valid", async () => {
  for (const fields of /** @type {Record<string, unknown>[]} */ ([
    { charge: 0, multiplicity: 1, name: "water", smiles: "O", inchi: "InChI=1S/H2O/h1H2", inchikey: "XLYOFNOQVPJJNP-UHFFFAOYSA-N", label: "1" },
    { charge: 1, multiplicity: 2 }, // H2O+: 9 electrons, one unpaired
    { charge: -2, multiplicity: 3 }, // 12 electrons, two unpaired
    { charge: 10, multiplicity: 1 }, // no electrons left, none unpaired
    { charge: 0 }, // no multiplicity: only the electron count
    { multiplicity: 2 }, // no charge: nothing to check
  ])) {
    for (const schemaCheck of [true, false]) {
      const report = await validateWithSchema(pack(identityArchive(fields)), { schemaCheck });
      assert.deepEqual(codes(report), [], `${JSON.stringify(fields)}: ${JSON.stringify(report.findings)}`);
    }
  }
});

for (const [label, fields, field] of /** @type {[string, Record<string, unknown>, string][]} */ ([
  ["a charge that leaves a negative electron count", { charge: 11 }, "charge"],
  ["a charge above the electron count, with a multiplicity", { charge: 12, multiplicity: 1 }, "charge"],
  ["a multiplicity of the wrong parity", { charge: 0, multiplicity: 2 }, "multiplicity"],
  ["more unpaired electrons than electrons", { charge: 0, multiplicity: 13 }, "multiplicity"],
  ["a multiplicity impossible for the cation", { charge: 1, multiplicity: 1 }, "multiplicity"],
])) {
  test(`E_CHARGE_MULTIPLICITY: ${label}`, async () => {
    const report = await validate(pack(identityArchive(fields)));
    assert.deepEqual(located(report), [["E_CHARGE_MULTIPLICITY", `/sections/0/${field}`]], JSON.stringify(report.findings));
    assert.equal(report.ok, false);
    assertSeverities(report);
  });
}

test("the electron count is not judged without integer charges or atomic numbers", async () => {
  const noZ = { ...WATER, atoms: WATER.atoms.map((atom, k) => (k === 1 ? { symbol: atom.symbol, position: atom.position } : atom)) };
  const negativeZ = { ...WATER, atoms: WATER.atoms.map((atom, k) => (k === 1 ? { ...atom, atomic_number: -1 } : atom)) };
  const fractionalZ = { ...WATER, atoms: WATER.atoms.map((atom, k) => (k === 1 ? { ...atom, atomic_number: 1.5 } : atom)) };
  for (const [fields, payload] of /** @type {[Record<string, unknown>, unknown][]} */ ([
    [{ charge: 11 }, noZ],
    [{ charge: 11 }, negativeZ],
    [{ charge: 11 }, fractionalZ],
    [{ charge: 0.5, multiplicity: 2 }, WATER],
    [{ charge: "0", multiplicity: 2 }, WATER],
    [{ charge: 0, multiplicity: 2.5 }, WATER],
    [{ charge: 0, multiplicity: 0 }, WATER],
  ])) {
    const report = await validate(pack(identityArchive(fields, undefined, payload)));
    assert.ok(!codes(report).includes("E_CHARGE_MULTIPLICITY"), `${JSON.stringify(fields)}: ${JSON.stringify(report.findings)}`);
  }
});

test("an empty structure has no electrons", async () => {
  const empty = { atoms: [] };
  assert.deepEqual(codes(await validate(pack(identityArchive({ charge: 0, multiplicity: 1 }, undefined, empty)))), []);
  assert.deepEqual(located(await validate(pack(identityArchive({ charge: 1 }, undefined, empty)))), [
    ["E_CHARGE_MULTIPLICITY", "/sections/0/charge"],
  ]);
});

test("the only structure's identity must agree with provenance", async () => {
  // Agreement, or a provenance that states nothing comparable: no finding.
  for (const provenance of [{ charge: 0, multiplicity: 1 }, { charge: 0 }, { method: "rks" }, { charge: 0.5, multiplicity: "1" }]) {
    assert.deepEqual(codes(await validate(pack(identityArchive({ charge: 0, multiplicity: 1 }, provenance)))), [], JSON.stringify(provenance));
  }
  assert.deepEqual(codes(await validate(pack(identityArchive({}, { charge: 1, multiplicity: 3 })))), []);
  const report = await validate(pack(identityArchive({ charge: 0, multiplicity: 1 }, { charge: 1, multiplicity: 3 })));
  assert.deepEqual(located(report), [
    ["E_ROOT_INCONSISTENT", "/sections/0/charge"],
    ["E_ROOT_INCONSISTENT", "/sections/0/multiplicity"],
  ]);
  assertSeverities(report);
  // Both rules can fire on one structure.
  assert.deepEqual(located(await validate(pack(identityArchive({ charge: 0, multiplicity: 2 }, { multiplicity: 1 })))), [
    ["E_CHARGE_MULTIPLICITY", "/sections/0/multiplicity"],
    ["E_ROOT_INCONSISTENT", "/sections/0/multiplicity"],
  ]);
});

test("provenance describes no structure in an archive with several", async () => {
  const a = identityArchive({ charge: 0, multiplicity: 1 }, { charge: 1 });
  const data = jsonBytes(WATER);
  addSection(a, { id: "s2", kind: "structure", charge: 0, members: { structure: jsonMember("s2.json", data) } }, { "s2.json": data });
  assert.deepEqual(codes(await validate(pack(a))), []);
  // The electron count is still checked on every structure.
  a.manifest.sections[1].charge = 20;
  assert.deepEqual(located(await validate(pack(a))), [["E_CHARGE_MULTIPLICITY", "/sections/1/charge"]]);
});

test("the identity rules run from the semantics level up", async () => {
  const bytes = pack(identityArchive({ charge: 0, multiplicity: 2 }, { charge: 1 }));
  assert.deepEqual(codes(await validate(bytes, { level: "payloads" })), []);
  const want = ["E_CHARGE_MULTIPLICITY", "E_ROOT_INCONSISTENT"];
  assert.deepEqual(codes(await validate(bytes, { level: "semantics" })), want);
  assert.deepEqual(codes(await validate(bytes)), want);
});

// --- run.record job_ref (spec § 5.8) ------------------------------------------

/**
 * structure + job.spec "job" + run.record "run" with `fields` on its section.
 * @param {Record<string, unknown>} fields
 */
function jobRefArchive(fields) {
  const a = baseArchive();
  const spec = jsonBytes({ job_type: "molecular", method: "rks", basis: "def2-svp", structure_ref: "structure" });
  addSection(a, { id: "job", kind: "job.spec", structure_ref: "structure", members: { spec: jsonMember("job/spec.json", spec) } }, { "job/spec.json": spec });
  const log = enc.encode("done\n");
  addSection(a, { id: "run", kind: "run.record", program: "t", members: { log: opaqueMember("run/log.txt", log) }, ...fields }, { "run/log.txt": log });
  return pack(a);
}

test("a run.record job_ref that names a job.spec section is valid", async () => {
  for (const fields of [{ job_ref: "job", run_status: "converged" }, {}]) {
    for (const schemaCheck of [true, false]) {
      const report = await validateWithSchema(jobRefArchive(fields), { schemaCheck });
      assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
    }
  }
});

for (const [label, ref] of /** @type {[string, unknown][]} */ ([
  ["names a structure", "structure"],
  ["names the run.record itself", "run"],
  ["names no section", "nowhere"],
  ["is not a string", 3],
  ["is null", null],
])) {
  test(`E_REF_UNRESOLVED: run.record job_ref ${label}`, async () => {
    const report = await validate(jobRefArchive({ job_ref: ref }));
    assert.deepEqual(located(report), [["E_REF_UNRESOLVED", "/sections/2/job_ref"]], JSON.stringify(report.findings));
    assert.equal(report.ok, false);
  });
}

test("job_ref is checked only from the references level up", async () => {
  const bytes = jobRefArchive({ job_ref: "structure" });
  assert.deepEqual(codes(await validate(bytes, { level: "semantics" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "references" })), ["E_REF_UNRESOLVED"]);
});

// --- reaction.scheme (spec § 5.14) --------------------------------------------

/** @param {string} ref @param {number} [coefficient] */
const p = (ref, coefficient) => (coefficient === undefined ? { structure_ref: ref } : { structure_ref: ref, coefficient });

/** Two steps over the structures s1 to s4: s1 + 2 s2 -> s3, then s3 <=> s4 with s1 at the arrow. */
const SCHEME = {
  steps: [
    { id: "r1", label: "a", reactants: [p("s1"), p("s2", 2)], products: [p("s3")], conditions: ["THF, −78 °C", "2 h"], yield_percent: 87, yield_text: "87%" },
    { id: "r2", label: "b", arrow: "equilibrium", reactants: [p("s3")], reagents: [p("s1")], products: [p("s4")] },
  ],
};

/**
 * Structures s1 to s4, a run.record "run" and a reaction.scheme "scheme"
 * (section 6) holding `payload`.
 * @param {unknown} payload
 */
function schemeArchive(payload) {
  const a = baseArchive();
  a.manifest.sections = [];
  a.entries = [];
  const data = jsonBytes(WATER);
  for (const sid of ["s1", "s2", "s3", "s4"]) {
    addSection(a, { id: sid, kind: "structure", label: sid.slice(1), members: { structure: jsonMember(`${sid}.json`, data) } }, { [`${sid}.json`]: data });
  }
  const log = enc.encode("done\n");
  addSection(a, { id: "run", kind: "run.record", program: "t", members: { log: opaqueMember("run/log.txt", log) } }, { "run/log.txt": log });
  const scheme = jsonBytes(payload);
  addSection(a, { id: "scheme", kind: "reaction.scheme", label: "A scheme", members: { scheme: jsonMember("scheme.json", scheme) } }, { "scheme.json": scheme });
  return pack(a);
}

/** @param {(steps: any[]) => void} edit */
function editedScheme(edit) {
  const payload = structuredClone(SCHEME);
  edit(payload.steps);
  return payload;
}

const SCHEME_WHERE = "/sections/5/members/scheme";

test("a reaction.scheme whose participants name structures is valid", async () => {
  // A species may be a reactant of one step and a product of another, or sit
  // on both sides of one step.
  const both = editedScheme((steps) => steps[1].products.push(p("s3")));
  for (const payload of [SCHEME, both]) {
    for (const schemaCheck of [true, false]) {
      const report = await validateWithSchema(schemeArchive(payload), { schemaCheck });
      assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
    }
  }
});

for (const [label, edit, want] of /** @type {[string, (steps: any[]) => void, string[]][]} */ ([
  ["a reactant names a run.record", (steps) => (steps[0].reactants[0].structure_ref = "run"), ["E_REF_UNRESOLVED"]],
  ["a product names no section", (steps) => (steps[0].products[0].structure_ref = "nowhere"), ["E_REF_UNRESOLVED"]],
  ["a reagent names the scheme", (steps) => (steps[1].reagents[0].structure_ref = "scheme"), ["E_REF_UNRESOLVED"]],
  ["two steps share an id", (steps) => (steps[1].id = "r1"), ["E_MEMBER_MALFORMED"]],
  ["a reactant repeats", (steps) => steps[0].reactants.push(p("s1")), ["E_MEMBER_MALFORMED"]],
  ["a reagent repeats", (steps) => steps[1].reagents.push(p("s1", 2)), ["E_MEMBER_MALFORMED"]],
  [
    "an unresolved participant repeats",
    (steps) => steps[0].products.push(p("nowhere"), p("nowhere")),
    ["E_REF_UNRESOLVED", "E_REF_UNRESOLVED", "E_MEMBER_MALFORMED"],
  ],
])) {
  test(`reaction.scheme: ${label}`, async () => {
    const report = await validate(schemeArchive(editedScheme(edit)));
    assert.deepEqual(located(report), want.map((code) => [code, SCHEME_WHERE]), JSON.stringify(report.findings));
    assert.equal(report.ok, false);
    assertSeverities(report);
  });
}

test("reaction.scheme: each repeated structure is reported once per role of a step", async () => {
  const payload = editedScheme((steps) => {
    steps[0].reactants.push(p("s2"), p("s1"), p("s1"));
    steps[0].products.push(p("s3"));
    steps.push({ ...steps[0], label: "c" });
  });
  const messages = (await validate(schemeArchive(payload))).findings.filter((f) => f.code === "E_MEMBER_MALFORMED").map((f) => f.message);
  // s1 and s2 among the reactants and s3 among the products of steps 0 and 2,
  // and the id r1 that step 2 repeats.
  assert.equal(messages.length, 7, messages.join("\n"));
  assert.ok(messages.some((m) => m.includes("'r1'")));
  assert.ok(messages.some((m) => m.includes("step 2 names 's1' more than once among its reactants")));
});

test("reaction.scheme: step ids and repeats from the semantics level, participants from references", async () => {
  const bytes = schemeArchive(
    editedScheme((steps) => {
      steps[1].id = "r1";
      steps[0].products[0].structure_ref = "run";
    }),
  );
  assert.deepEqual(codes(await validate(bytes, { level: "payloads" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "semantics" })), ["E_MEMBER_MALFORMED"]);
  assert.deepEqual(codes(await validate(bytes, { level: "references" })), ["E_REF_UNRESOLVED", "E_MEMBER_MALFORMED"]);
});

test("reaction.scheme: a payload that is not a scheme is left to the JSON Schema", async () => {
  for (const payload of [[], { steps: "r1" }, { steps: [1, { id: 2, reactants: "s1", products: [7, { structure_ref: 3 }] }] }]) {
    assert.deepEqual(codes(await validate(schemeArchive(payload))), [], JSON.stringify(payload));
    const withSchema = await validateWithSchema(schemeArchive(payload));
    assert.ok(withSchema.findings.every((f) => f.code === "E_PAYLOAD_SCHEMA"), JSON.stringify(withSchema.findings));
    assert.equal(withSchema.ok, false);
  }
});

// --- preview (spec § 5.15) ------------------------------------------------------

const PNG = Uint8Array.of(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52);
const JPEG = Uint8Array.of(0xff, 0xd8, 0xff, 0xe0, 0, 16, 0x4a, 0x46, 0x49, 0x46);
const SVG = enc.encode('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><text>é</text></svg>\n');

/**
 * The water archive with a preview section (section 1) whose members are
 * `members`: role -> [media type or undefined, bytes].
 * @param {Record<string, [string | undefined, Uint8Array]>} members
 */
function previewArchive(members) {
  const a = baseArchive();
  /** @type {Record<string, any>} */
  const specs = {};
  /** @type {Record<string, Uint8Array>} */
  const files = {};
  for (const [role, [mediaType, data]] of Object.entries(members)) {
    const path = `preview/${role}`;
    specs[role] = mediaType === undefined ? opaqueMember(path, data) : { ...opaqueMember(path, data), media_type: mediaType };
    files[path] = data;
  }
  addSection(a, { id: "preview", kind: "preview", members: specs }, files);
  return pack(a);
}

test("preview members whose bytes are what their media_type says are valid", async () => {
  for (const members of /** @type {Record<string, [string, Uint8Array]>[]} */ ([
    { thumbnail: ["image/png", PNG] },
    { thumbnail: ["image/jpeg", JPEG], image: ["image/svg+xml", SVG] },
    { thumbnail: ["image/png", PNG], image: ["image/jpeg", JPEG] },
    { thumbnail: ["image/png", PNG], image: ["image/png", PNG] },
  ])) {
    for (const schemaCheck of [true, false]) {
      const report = await validateWithSchema(previewArchive(members), { schemaCheck });
      assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
    }
  }
});

for (const [label, members, code, role] of /** @type {[string, Record<string, [string, Uint8Array]>, string, string][]} */ ([
  ["a PNG thumbnail without the PNG signature", { thumbnail: ["image/png", JPEG] }, "E_MEMBER_MALFORMED", "thumbnail"],
  ["a PNG thumbnail shorter than the signature", { thumbnail: ["image/png", PNG.slice(0, 7)] }, "E_MEMBER_MALFORMED", "thumbnail"],
  ["a JPEG thumbnail without FF D8 FF", { thumbnail: ["image/jpeg", PNG] }, "E_MEMBER_MALFORMED", "thumbnail"],
  ["an empty JPEG image", { thumbnail: ["image/png", PNG], image: ["image/jpeg", new Uint8Array(0)] }, "E_MEMBER_MALFORMED", "image"],
  ["an SVG image that is not UTF-8", { thumbnail: ["image/png", PNG], image: ["image/svg+xml", Uint8Array.of(0x3c, 0x73, 0x76, 0x67, 0x20, 0xff, 0x3e)] }, "E_UTF8", "image"],
  ["an SVG image without <svg", { thumbnail: ["image/png", PNG], image: ["image/svg+xml", enc.encode("<html><body/></html>")] }, "E_MEMBER_MALFORMED", "image"],
])) {
  test(`preview: ${label}`, async () => {
    for (const schemaCheck of [true, false]) {
      const report = await validateWithSchema(previewArchive(members), { schemaCheck });
      assert.deepEqual(located(report), [[code, `/sections/1/members/${role}`]], JSON.stringify(report.findings));
      assert.equal(report.ok, false);
      assertSeverities(report);
    }
  });
}

test("preview: a missing or unknown media_type is left to the JSON Schema", async () => {
  for (const members of /** @type {Record<string, [string | undefined, Uint8Array]>[]} */ ([
    { thumbnail: [undefined, PNG] },
    { thumbnail: ["image/gif", PNG] },
    { thumbnail: ["image/svg+xml", SVG] },
  ])) {
    assert.deepEqual(codes(await validate(previewArchive(members))), [], JSON.stringify(members));
    const report = await validateWithSchema(previewArchive(members));
    assert.deepEqual([...new Set(codes(report))], ["E_SCHEMA"], JSON.stringify(report.findings));
  }
});

test("preview: the bytes are checked from the payloads level up", async () => {
  const bytes = previewArchive({ thumbnail: ["image/png", JPEG] });
  assert.deepEqual(codes(await validate(bytes, { level: "manifest" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "payloads" })), ["E_MEMBER_MALFORMED"]);
});

test("preview: a checksum mismatch does not stop the check of the bytes", async () => {
  const a = baseArchive();
  addSection(a, { id: "preview", kind: "preview", members: { thumbnail: { ...opaqueMember("t.png", JPEG), media_type: "image/png" } } }, { "t.png": JPEG });
  a.manifest.sections[1].members.thumbnail.sha256 = "0".repeat(64);
  assert.deepEqual(located(await validate(pack(a))), [
    ["E_SHA256_MISMATCH", "/sections/1/members/thumbnail"],
    ["E_MEMBER_MALFORMED", "/sections/1/members/thumbnail"],
  ]);
});
