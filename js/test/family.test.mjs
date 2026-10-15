// Toolkit 0.3.0: what the family's programs already write or read. The IAO
// reference basis and three deprecated mo_metadata keys (spec § 5.3), null
// and the deprecated "" for a job.spec functional or basis (spec § 5.9), the
// viewer hints camera, crossfade and energy_window (spec § 3.4), and
// structure_ref on a standalone bonds section (spec § 5.1), with the codes,
// severities and JSON pointers of the Python reference validator.

import assert from "node:assert/strict";
import { test } from "node:test";

import { validate } from "../dist/index.js";
import { WATER, addSection, baseArchive, binaryMember, float64Bytes, jsonBytes, jsonMember, pack } from "./helpers.mjs";

/** `[code, severity, where]` of every finding. */
function located(/** @type {{ findings: { code: string, severity: string, where: string }[] }} */ report) {
  return report.findings.map((f) => [f.code, f.severity, f.where]);
}

const H2 = {
  atoms: [
    { symbol: "H", position: [0.0, 0.0, 0.0], atomic_number: 1 },
    { symbol: "H", position: [0.0, 0.0, 0.74], atomic_number: 1 },
  ],
  pbc: [false, false, false],
  lattice_vectors: null,
};

/** A water structure and an H2 wavefunction.gto whose mo_metadata is `meta`. */
function wavefunctionArchive(/** @type {Record<string, unknown>} */ meta) {
  const a = baseArchive();
  const basis = jsonBytes({
    structure_ref: "structure",
    pure: true,
    n_ao: 2,
    shells: [
      { center: 1, l: 0, exponents: [1.24], coefficients: [1.0] },
      { center: 2, l: 0, exponents: [1.24], coefficients: [1.0] },
    ],
  });
  const mo = jsonBytes({ n_mo: 2, n_ao: 2, spin: "restricted", energies: [-0.58, 0.67], occupations: [2.0, 0.0], ...meta });
  const c = float64Bytes([1.0, 0.0, 0.0, 1.0]);
  addSection(
    a,
    {
      id: "wf",
      kind: "wavefunction.gto",
      members: {
        basis: jsonMember("wf/basis.json", basis),
        mo_metadata: jsonMember("wf/mo_metadata.json", mo),
        mo_coefficients: binaryMember("wf/mo_coefficients.dat", c, "float64", [2, 2]),
      },
    },
    { "wf/basis.json": basis, "wf/mo_metadata.json": mo, "wf/mo_coefficients.dat": c },
  );
  return a;
}

// --- mo_metadata (spec § 5.3) ------------------------------------------------------

test("localized orbitals with their IAO reference basis are schema-clean", async () => {
  const a = wavefunctionArchive({
    orbital_kind: "ibo",
    localization_method: "ibo",
    localization_reference_basis: "minao",
    atom_populations: [
      [0.0, 0.5, 0.5],
      [0.0, 0.5, 0.5],
    ],
    n_centres: [2, 2],
  });
  const report = await validate(pack(a));
  assert.deepEqual(located(report), []);
  assert.equal(report.ok, true);
});

test("an empty localization_reference_basis is E_PAYLOAD_SCHEMA at the member", async () => {
  const a = wavefunctionArchive({ orbital_kind: "ibo", localization_reference_basis: "" });
  assert.deepEqual(located(await validate(pack(a))), [["E_PAYLOAD_SCHEMA", "error", "/sections/1/members/mo_metadata"]]);
});

test("the deprecated mo_metadata keys are valid with no finding", async () => {
  for (const meta of [
    { orbital_kind: "localized", localization_method: "ibo", localization_reference_basis: "mini", iao_charges: [0.0, 0.1, -0.1] },
    { orbital_kind: "natural", occupation_semantics: "transition_weight", excitation_index: 1, excitation_energy_ev: 10.2 },
  ]) {
    const report = await validate(pack(wavefunctionArchive(meta)));
    assert.deepEqual(located(report), [], JSON.stringify(meta));
  }
  for (const meta of [{ iao_charges: ["0.1"] }, { excitation_index: -1 }, { excitation_energy_ev: "10.2" }]) {
    const report = await validate(pack(wavefunctionArchive(meta)));
    assert.deepEqual(located(report), [["E_PAYLOAD_SCHEMA", "error", "/sections/1/members/mo_metadata"]], JSON.stringify(meta));
  }
});

// --- job.spec functional and basis (spec § 5.9) -------------------------------------

test("a job.spec functional or basis may be null, or the deprecated empty string", async () => {
  /** @param {Record<string, unknown>} fields */
  const archive = (fields) => {
    const a = baseArchive();
    const spec = jsonBytes({ job_type: "molecular", structure_ref: "structure", ...fields });
    addSection(a, { id: "job", kind: "job.spec", members: { spec: jsonMember("job/spec.json", spec) } }, { "job/spec.json": spec });
    return a;
  };
  for (const fields of [
    { method: "rhf", functional: null, basis: "sto-3g" },
    { method: "gfn2_xtb", functional: null, basis: null },
    { method: "gfn2_xtb", basis: "" },
    { method: "rks", functional: "pbe0", basis: "def2-svp" },
  ]) {
    assert.deepEqual(located(await validate(pack(archive(fields)))), [], JSON.stringify(fields));
  }
  for (const fields of [{ functional: 3 }, { basis: ["sto-3g"] }, { basis: false }]) {
    assert.deepEqual(located(await validate(pack(archive(fields)))), [["E_PAYLOAD_SCHEMA", "error", "/sections/1/members/spec"]]);
  }
});

// --- viewer_defaults (spec § 3.4) --------------------------------------------------

test("camera, crossfade and energy_window never fail an archive", async () => {
  const camera = { position: [0, -12, 4], focal_point: [0, 0, 0], view_up: [0, 0, 1], view_angle: 30 };
  for (const hints of [
    { camera, crossfade: { a: "a", b: "b", blend: 0.25 }, structure: { energy_window: [-15, 10] } },
    { camera: "front", crossfade: 5, structure: { energy_window: "valence" } },
    { camera: { position: [0, 0, 1] }, crossfade: { a: "nowhere" }, structure: { energy_window: [10, -15] } },
    { camera: null, crossfade: [], structure: { energy_window: null } },
  ]) {
    const a = baseArchive();
    a.manifest.viewer_defaults = hints;
    const report = await validate(pack(a));
    assert.deepEqual(located(report), [], JSON.stringify(hints));
  }
});

test("camera and crossfade are reserved section ids", async () => {
  for (const id of ["camera", "crossfade"]) {
    const a = baseArchive();
    a.manifest.sections[0].id = id;
    assert.deepEqual(located(await validate(pack(a))), [["E_RESERVED_ID", "error", "/sections/0/id"]], id);
  }
});

// --- structure_ref on a standalone bonds section (spec § 5.1) -----------------------

/**
 * Water, H2 and a bonds section with `pairs` (and `structureRef`, when given);
 * with `bondsFirst` the bonds section comes before the structures.
 * @param {unknown[]} pairs
 * @param {string | undefined} structureRef
 * @param {boolean} [bondsFirst]
 */
function bondsArchive(pairs, structureRef, bondsFirst = false) {
  const water = jsonBytes(WATER);
  const h2 = jsonBytes(H2);
  const bonds = jsonBytes({ pairs });
  const structures = [
    { id: "structure_water", kind: "structure", members: { structure: jsonMember("water/structure.json", water) } },
    { id: "structure_h2", kind: "structure", members: { structure: jsonMember("h2/structure.json", h2) } },
  ];
  /** @type {Record<string, unknown>} */
  const section = { id: "bonds", kind: "bonds", members: { bonds: jsonMember("bonds/connectivity.json", bonds) } };
  if (structureRef !== undefined) section.structure_ref = structureRef;
  const job = jsonBytes({ job_type: "molecular" });
  const a = {
    manifest: {
      qvf_version: 1,
      source: { program: "qvf-test", version: "0.0.1", calculation: "bonds" },
      sections: bondsFirst
        ? [section, ...structures]
        : [...structures, { id: "job", kind: "job.spec", members: { spec: jsonMember("job/spec.json", job) } }, section],
    },
    entries: [
      { name: "water/structure.json", data: water },
      { name: "h2/structure.json", data: h2 },
      { name: "bonds/connectivity.json", data: bonds },
      ...(bondsFirst ? [] : [{ name: "job/spec.json", data: job }]),
    ],
  };
  return { bytes: pack(a), index: bondsFirst ? 0 : 3 };
}

test("bond indices are checked against the structure structure_ref names", async () => {
  const pairs = [
    { i: 0, j: 1 },
    { i: 0, j: 2 },
  ];
  assert.deepEqual(located(await validate(bondsArchive(pairs, "structure_water").bytes)), []);
  const { bytes, index } = bondsArchive(pairs, "structure_h2");
  const report = await validate(bytes);
  assert.deepEqual(located(report), [["E_MEMBER_MALFORMED", "error", `/sections/${index}/members/bonds`]]);
  assert.match(report.findings[0]?.message ?? "", /pairs\[1\]\.j 2 .*'structure_h2'/);
  // Below the references level the structure is not resolved.
  assert.deepEqual(located(await validate(bytes, { level: "semantics" })), []);
});

test("bond indices resolve a structure that comes later", async () => {
  const { bytes, index } = bondsArchive([{ i: 1, j: 2 }], "structure_h2", true);
  assert.deepEqual(located(await validate(bytes)), [["E_MEMBER_MALFORMED", "error", `/sections/${index}/members/bonds`]]);
});

test("bonds without structure_ref are not counted against a structure", async () => {
  assert.deepEqual(located(await validate(bondsArchive([{ i: 0, j: 7 }], undefined).bytes)), []);
});

test("an unresolved bonds structure_ref is E_REF_UNRESOLVED and no index is checked", async () => {
  for (const ref of ["missing", "job"]) {
    const { bytes, index } = bondsArchive([{ i: 0, j: 7 }], ref);
    assert.deepEqual(located(await validate(bytes)), [["E_REF_UNRESOLVED", "error", `/sections/${index}/structure_ref`]], ref);
  }
});
