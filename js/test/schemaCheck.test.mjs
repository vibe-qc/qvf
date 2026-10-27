// The table-driven JSON Schema checker (src/schemaCheck.ts) and its use by the
// validator. The parity test against the Python reference (jsonschema) is
// python/tests/test_schema_checker_parity.py; these cases pin the semantics
// in this language.

import assert from "node:assert/strict";
import { test } from "node:test";

import { validate } from "../dist/index.js";
import { checkDefinition, checkManifest, payloadDefinition, rxSearch } from "../dist/schemaCheck.js";
import { RX_SOURCES } from "../dist/schemaTable.js";
import { addSection, baseArchive, jsonBytes, jsonMember, pack } from "./helpers.mjs";

/** @param {string} def @param {unknown} doc */
const pointers = (def, doc) => (def ? checkDefinition(def, doc) : checkManifest(doc)).map((e) => e.pointer);

const HEX64 = "a".repeat(64);

test("patterns: the Pike VM over code points, ECMA-262 anchors", () => {
  assert.deepEqual(pointers("Sha256Hex", HEX64), []);
  assert.deepEqual(pointers("Sha256Hex", "A".repeat(64)), [""]);
  assert.deepEqual(pointers("Sha256Hex", `${HEX64}a`), [""]);
  assert.deepEqual(pointers("Sha256Hex", `${HEX64}\n`), [""]); // `$` is the end of the string
  assert.deepEqual(pointers("ZipPath", "dir/file.json"), []);
  assert.deepEqual(pointers("ZipPath", "a/..b/c"), []);
  assert.deepEqual(pointers("ZipPath", "a/../b"), [""]);
  assert.deepEqual(pointers("ZipPath", ".."), [""]);
  assert.deepEqual(pointers("ZipPath", "/abs"), [""]);
  assert.deepEqual(pointers("ZipPath", ""), ["", ""]); // minLength and pattern
  assert.deepEqual(pointers("ZipPath", "café/ü.json"), []);
  assert.deepEqual(pointers("Metadata", { uuid: "3f2504e0-4f89-41d3-9a0c-0305e82c3301" }), []);
  assert.deepEqual(pointers("Metadata", { uuid: "3f2504e04f8941d39a0c0305e82c3301" }), ["/uuid"]);
  assert.deepEqual(pointers("Metadata", { created_utc: "2026-06-30T23:59:60.25Z" }), []);
  assert.deepEqual(pointers("Metadata", { created_utc: "2026-13-01T00:00:00Z" }), ["/created_utc"]);
  assert.deepEqual(pointers("Metadata", { x_tool: { anything: [1] }, license: "CC-BY-4.0" }), []);
  assert.deepEqual(pointers("Metadata", { licence: "x" }), [""]);
  const custom = RX_SOURCES.indexOf("^custom\\.[A-Za-z0-9_]+$");
  assert.ok(custom >= 0);
  assert.ok(rxSearch(custom, "custom.flux_2") && !rxSearch(custom, "custom.") && !rxSearch(custom, "xcustom.a"));
});

test("types, numbers and code points", () => {
  assert.deepEqual(pointers("MemberSize", 2), []);
  assert.deepEqual(pointers("MemberSize", 2.5), [""]);
  assert.deepEqual(pointers("MemberSize", true), [""]);
  assert.deepEqual(pointers("MemberSize", -1), [""]);
  const camera = { position: [0, 0, 1], focal_point: [0, 0, 0], view_up: [0, 1, 0], view_angle: 180 };
  assert.deepEqual(pointers("Camera", camera), ["/view_angle"]); // exclusiveMaximum
  assert.deepEqual(pointers("StructureAtom", { symbol: "ÅÅÅ", position: [0, 0, 0], atomic_number: 0 }), []);
  assert.deepEqual(pointers("StructureAtom", { symbol: "😀😀😀", position: [0, 0, 0], atomic_number: 0 }), []);
  assert.deepEqual(pointers("StructureAtom", { symbol: "ÅÅÅÅ", position: [0, 0], atomic_number: -1 }), [
    "/symbol",
    "/position",
    "/atomic_number",
  ]);
  assert.deepEqual(pointers("ValueWithUnits", { value: 1, units: "Eh" }), []); // oneOf: legacy spelling
  assert.deepEqual(pointers("ValueWithUnits", { value: 1, units: "EV" }), ["/units"]);
});

test("locations: pointers escape '~' and '/', applicators descend", () => {
  const [e] = checkDefinition("EnergyComponents", { "x_a/b~c": { value: "no", units: "ev" } });
  assert.equal(e?.pointer, "/x_a~1b~0c/value");
  assert.equal(e?.location, "x_a/b~c/value");
  const vector = { path: "p", format: "binary", dtype: "float64", shape: [5, 4], sha256: HEX64 };
  assert.deepEqual(pointers("AtomVectorBinary", vector), ["/shape/1"]); // prefixItems
  assert.deepEqual(pointers("Vec3", [0, "y", 2]), ["/1"]); // items
  const lattice = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  const slab = { atoms: [], pbc: [true, true, false], dimensionality: 2, lattice_vectors: lattice };
  assert.deepEqual(pointers("StructurePayload", slab), []);
  assert.deepEqual(pointers("StructurePayload", { ...slab, pbc: [true, false, false] }), ["/pbc"]); // contains
  assert.deepEqual(pointers("StructurePayload", { atoms: [], lattice_vectors: lattice }), [""]); // if / then
  assert.deepEqual(pointers("MoMetadataPayload", { spin: "restricted", energies: [], occupations: [] }), []);
  assert.deepEqual(pointers("MoMetadataPayload", { spin: "unrestricted", energies: [1], occupations: [1] }), ["", "", ""]);
  assert.deepEqual(pointers("SectionVolumeDifference", { operand_a: "x" }), [""]); // dependentRequired
  // oneOf over the section kinds: one error at the section.
  assert.deepEqual(pointers("Section", { id: "s", kind: "bonds", members: {} }), [""]);
  assert.deepEqual(pointers("Section", 42), ["", ""]);
  assert.deepEqual(pointers("Section", { id: "a b", kind: "x_v.k", members: {} }), ["/id"]);
  assert.deepEqual(checkDefinition("NoSuchDefinition", {}), []);
  assert.equal(payloadDefinition("structure", "structure"), "StructurePayload");
  assert.equal(payloadDefinition("structure", "nope"), undefined);
});

test("the validator reports E_SCHEMA and E_PAYLOAD_SCHEMA, or W_SCHEMA_SKIPPED when disabled", async () => {
  const clean = await validate(pack(baseArchive()));
  assert.deepEqual(clean.findings, []);
  const big = /** @type {any} */ (baseArchive());
  big.manifest.byte_order = "big";
  let report = await validate(pack(big));
  assert.deepEqual(
    report.findings.map((f) => [f.code, f.where]),
    [["E_SCHEMA", "/byte_order"]],
  );
  report = await validate(pack(big), { schemaCheck: false });
  assert.deepEqual(report.findings.map((f) => f.code), ["W_SCHEMA_SKIPPED"]);
  assert.ok(report.ok);

  const spectrum = { frequencies: [1, 2, 3], intensities: [1, 2] };
  const a = baseArchive();
  const data = jsonBytes(spectrum);
  addSection(a, { id: "s", kind: "spectra.ir", members: { spectrum: jsonMember("s/spectrum.json", data) } }, {
    "s/spectrum.json": data,
  });
  report = await validate(pack(a));
  assert.deepEqual(report.findings.map((f) => [f.code, f.where]), [["E_PAYLOAD_SCHEMA", "/sections/1/members/spectrum"]]);
  report = await validate(pack(a), { schemaCheck: false });
  assert.deepEqual(report.findings.map((f) => f.code).sort(), ["E_PAYLOAD_SCHEMA", "W_SCHEMA_SKIPPED"]);

  const bad = /** @type {any} */ (baseArchive());
  const atoms = jsonBytes({ atoms: [{ symbol: "O", position: [0, 0, 0], atomic_number: -8 }] });
  bad.entries[0].data = atoms;
  bad.manifest.sections[0].members.structure = jsonMember("structure/structure.json", atoms);
  report = await validate(pack(bad));
  assert.equal(report.findings.length, 1);
  assert.equal(report.findings[0]?.code, "E_PAYLOAD_SCHEMA");
  assert.equal(report.findings[0]?.where, "/sections/0/members/structure");
  assert.match(report.findings[0]?.message ?? "", /atoms\/0\/atomic_number/);
});
