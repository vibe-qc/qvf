import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { BOHR_PER_ANGSTROM, LEGACY_UNIT_NAMES, UNIT_NAMES, canonicalUnit, isUnitName, validate as validateWithSchema } from "../dist/index.js";
import { addSection, baseArchive, jsonBytes, jsonMember, pack } from "./helpers.mjs";

// These tests pin the semantic checks, each archive isolating one rule, so they
// validate without the JSON Schema check generated from the schema (the
// behaviour of a validator without a schema engine: W_SCHEMA_SKIPPED);
// schemaCheck.test.mjs covers the checker.
/** @type {typeof validateWithSchema} */
const validate = (bytes, options = {}) => validateWithSchema(bytes, { schemaCheck: false, ...options });

const schemaPath = fileURLToPath(new URL("../../spec/qvf_manifest.schema.json", import.meta.url));
const defs = JSON.parse(readFileSync(schemaPath, "utf8")).$defs;

test("the unit names are the schema's $defs/UnitName, in order", () => {
  assert.deepEqual([...UNIT_NAMES], defs.UnitName.enum);
  assert.deepEqual(Object.keys(LEGACY_UNIT_NAMES), defs.LegacyUnitName.enum);
  for (const name of Object.values(LEGACY_UNIT_NAMES)) assert.ok(isUnitName(name));
});

test("BOHR_PER_ANGSTROM is the CODATA 2018 value of spec § 4.3", () => {
  assert.equal(BOHR_PER_ANGSTROM, 1.8897261246);
  assert.ok(Math.abs(BOHR_PER_ANGSTROM - 1 / 0.529177210903) < 1e-10);
});

test("isUnitName and canonicalUnit", () => {
  assert.ok(isUnitName("cm-1") && isUnitName("ev"));
  assert.ok(!isUnitName("eV") && !isUnitName("rad") && !isUnitName(3));
  assert.equal(canonicalUnit("Eh"), "hartree");
  assert.equal(canonicalUnit("eV"), "ev");
  assert.equal(canonicalUnit("bohr"), "bohr");
  assert.equal(canonicalUnit("toString"), null);
  assert.equal(canonicalUnit("kJ/mol"), null);
});

/**
 * @param {Record<string, unknown> | undefined} provenance
 * @param {string} [kind]
 * @param {unknown} [payload]
 */
function archiveWith(provenance, kind, payload) {
  const a = baseArchive();
  if (provenance) a.manifest.provenance = provenance;
  if (kind) {
    const data = jsonBytes(payload);
    addSection(a, { id: "p", kind, members: { m: jsonMember("p/m.json", data) } }, { "p/m.json": data });
  }
  return pack(a);
}

/** @param {{ findings: { code: string, where: string }[] }} report */
const unitFindings = (report) => report.findings.filter((f) => f.code === "W_UNIT_UNKNOWN");

test("validate: legacy spellings in provenance are accepted, unknown units warn", async () => {
  let report = await validate(archiveWith({ scf_energy: { value: -1, units: "Eh" }, fermi_energy: { value: 0, units: "ev" } }));
  assert.equal(unitFindings(report).length, 0);
  report = await validate(archiveWith({ scf_energy: { value: -1, units: "kJ/mol" }, other: { units: "x" } }));
  assert.equal(report.ok, true);
  assert.deepEqual(unitFindings(report).map((f) => f.where), ["/provenance/scf_energy/units"]);
});

test("validate: declared units of canonical payloads are checked, vendor payloads are not", async () => {
  const spectrum = {
    frequencies: [1],
    intensities: [1],
    x_units: "nm",
    y_units: "arb",
    broadening: { type: "none", units: "1/cm" },
    units: { x: "ev" },
  };
  let report = await validate(archiveWith(undefined, "spectra.uvvis", spectrum));
  assert.equal(report.ok, true);
  assert.deepEqual(
    unitFindings(report).map((f) => f.where),
    ["/sections/1/members/m", "/sections/1/members/m"],
  );
  report = await validate(archiveWith(undefined, "x_test.grid", { units: { data: "furlong" } }));
  assert.equal(unitFindings(report).length, 0);
  report = await validate(archiveWith(undefined, "topology.qtaim", { points: [], units: { position: 7 } }));
  assert.equal(unitFindings(report).length, 1);
  report = await validate(archiveWith(undefined, "topology.qtaim", { points: [], units: { position: "au" } }), {
    level: "payloads",
  });
  assert.equal(unitFindings(report).length, 0);
});
