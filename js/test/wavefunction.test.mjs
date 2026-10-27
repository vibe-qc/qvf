// wavefunction.gto (spec § 5.3, Appendix A.1): the coefficient rank against
// `complex`, `symmetry_labels` lengths, the shape and pairing of the overlap
// and density members, `basis.n_electrons` against the occupations and
// `provenance.n_electrons`, and the normalization check of an `overlap`
// member (E_NORMALIZATION), as in the Python and C++ reference validators.

import assert from "node:assert/strict";
import { test } from "node:test";

import { validate } from "../dist/index.js";
import { addSection, baseArchive, binaryMember, float64Bytes, jsonBytes, jsonMember, pack } from "./helpers.mjs";

/** The codes of a report, without the always-present W_SCHEMA_SKIPPED. */
function codes(/** @type {{ findings: { code: string }[] }} */ report) {
  return report.findings.map((f) => f.code).filter((c) => c !== "W_SCHEMA_SKIPPED");
}

/** @param {number[]} d */
function diagonal(d) {
  const m = new Array(d.length * d.length).fill(0);
  d.forEach((v, i) => {
    m[i * d.length + i] = v;
  });
  return m;
}

/**
 * structure + wavefunction.gto "wf" with these payloads and float64 members.
 * @param {unknown} basis
 * @param {unknown} meta
 * @param {Record<string, { shape: number[], values?: number[] }>} binaries
 * @param {Record<string, unknown>} [root]
 */
function wfArchive(basis, meta, binaries, root = {}) {
  const a = baseArchive();
  Object.assign(a.manifest, root);
  const b = jsonBytes(basis);
  const m = jsonBytes(meta);
  /** @type {Record<string, unknown>} */
  const members = { basis: jsonMember("wf/basis.json", b), mo_metadata: jsonMember("wf/mo_metadata.json", m) };
  /** @type {Record<string, Uint8Array>} */
  const files = { "wf/basis.json": b, "wf/mo_metadata.json": m };
  for (const [role, { shape, values }] of Object.entries(binaries)) {
    const n = shape.reduce((x, y) => x * y, 1);
    const data = float64Bytes(values ?? new Array(n).fill(0));
    members[role] = binaryMember(`wf/${role}.dat`, data, "float64", shape);
    files[`wf/${role}.dat`] = data;
  }
  addSection(a, { id: "wf", kind: "wavefunction.gto", members }, files);
  return pack(a);
}

const third = 1 / 3;
// An s and a Cartesian d shell, one primitive each with coefficient 1.
const CART = {
  structure_ref: "structure",
  pure: false,
  shells: [
    { center: 0, l: 0, exponents: [1.2], coefficients: [1.0] },
    { center: 0, l: 2, exponents: [0.8], coefficients: [1.0] },
  ],
};
const META7 = { spin: "restricted", energies: new Array(7).fill(0), occupations: [2, 0, 0, 0, 0, 0, 0] };
const C7 = { shape: [7, 7], values: diagonal(new Array(7).fill(1)) };
const DIAG7 = [1, 1, third, third, 1, third, 1];

test("an overlap with the Appendix A.1 diagonal passes", async () => {
  const report = await validate(wfArchive(CART, META7, { mo_coefficients: C7, overlap: { shape: [7, 7], values: diagonal(DIAG7) } }));
  assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
});

test("a d_xy self-overlap of 1 instead of 1/3 is E_NORMALIZATION", async () => {
  const bad = [...DIAG7];
  bad[2] = 1;
  const report = await validate(wfArchive(CART, META7, { mo_coefficients: C7, overlap: { shape: [7, 7], values: diagonal(bad) } }));
  assert.deepEqual(codes(report), ["E_NORMALIZATION"]);
  const finding = report.findings.find((f) => f.code === "E_NORMALIZATION");
  assert.equal(finding?.where, "/sections/1/members/overlap");
  assert.match(finding?.message ?? "", /AO 2 \(shell 1, l = 2, Cartesian xy \[1, 1, 0\]\)/);
});

test("a spherical shell has the axial self-overlap on every component", async () => {
  const sph = { structure_ref: "structure", shells: [{ center: 0, l: 2, exponents: [0.8], coefficients: [1.0] }] };
  const meta = { spin: "restricted", energies: [0, 0, 0, 0, 0], occupations: [0, 0, 0, 0, 0] };
  const c = { shape: [5, 5] };
  assert.deepEqual(codes(await validate(wfArchive(sph, meta, { mo_coefficients: c, overlap: { shape: [5, 5], values: diagonal([1, 1, 1, 1, 1]) } }))), []);
  assert.deepEqual(
    codes(await validate(wfArchive(sph, meta, { mo_coefficients: c, overlap: { shape: [5, 5], values: diagonal([third, 1, 1, 1, 1]) } }))),
    ["E_NORMALIZATION"],
  );
});

test("an unnormalized contraction: the diagonal is S_axial, with a relative tolerance of 1e-6", async () => {
  const basis = { structure_ref: "structure", shells: [{ center: 0, l: 0, exponents: [2.0, 0.5], coefficients: [0.6, 0.5] }] };
  const meta = { spin: "restricted", energies: [0], occupations: [2] };
  const s01 = ((2 * Math.sqrt(2.0 * 0.5)) / 2.5) ** 1.5;
  const sAxial = 0.36 + 0.25 + 2 * 0.6 * 0.5 * s01;
  for (const [scale, want] of /** @type {[number, string[]][]} */ ([
    [1, []],
    [1 + 5e-7, []],
    [1 + 2e-6, ["E_NORMALIZATION"]],
  ])) {
    const report = await validate(wfArchive(basis, meta, { mo_coefficients: { shape: [1, 1], values: [1] }, overlap: { shape: [1, 1], values: [sAxial * scale] } }));
    assert.deepEqual(codes(report), want, `scale ${scale}`);
  }
});

// s + spherical p: n_ao 4.
const SP = {
  structure_ref: "structure",
  shells: [
    { center: 0, l: 0, exponents: [1.0], coefficients: [1.0] },
    { center: 0, l: 1, exponents: [0.5], coefficients: [1.0] },
  ],
};
/** @param {Record<string, unknown>} [extra] */
const meta4 = (extra = {}) => ({ spin: "restricted", energies: [0, 0, 0, 0], occupations: [2, 0, 0, 0], ...extra });
const UHF = {
  spin: "unrestricted",
  alpha: { energies: [0, 0, 0, 0], occupations: [1, 0, 0, 0] },
  beta: { energies: [0, 0, 0, 0], occupations: [1, 0, 0, 0] },
};
const M44 = { shape: [4, 4] };

for (const [label, basis, meta, binaries, root, want, role] of /** @type {[string, unknown, unknown, Record<string, {shape: number[]}>, Record<string, unknown>, string[], string?][]} */ ([
  ["complex true with rank-2 coefficients", SP, meta4({ complex: true }), { mo_coefficients: M44 }, {}, ["E_MEMBER_MALFORMED"], "mo_coefficients"],
  ["real with rank-3 coefficients", SP, meta4(), { mo_coefficients: { shape: [4, 4, 2] } }, {}, ["E_MEMBER_MALFORMED"], "mo_coefficients"],
  ["complex rank-3 coefficients", SP, meta4({ complex: true }), { mo_coefficients: { shape: [4, 4, 2] } }, {}, []],
  ["coefficient_encoding read when complex is absent", SP, meta4({ coefficient_encoding: "complex_split_last_axis" }), { mo_coefficients: { shape: [4, 4, 2] } }, {}, []],
  ["symmetry_labels one short", SP, meta4({ symmetry_labels: ["a", "b", "c"] }), { mo_coefficients: M44 }, {}, ["E_MEMBER_MALFORMED"], "mo_metadata"],
  ["overlap of the wrong shape", SP, meta4(), { mo_coefficients: M44, overlap: { shape: [3, 3] } }, {}, ["E_MEMBER_MALFORMED"], "overlap"],
  ["density_matrix with alpha and beta coefficients", SP, UHF, { mo_coefficients_alpha: M44, mo_coefficients_beta: M44, density_matrix: M44 }, {}, ["E_MEMBER_MALFORMED"], "density_matrix"],
  ["density_matrix_alpha without beta", SP, UHF, { mo_coefficients_alpha: M44, mo_coefficients_beta: M44, density_matrix_alpha: M44 }, {}, ["E_MEMBER_MALFORMED"], "density_matrix_alpha"],
  ["density_matrix_alpha with a single set", SP, meta4(), { mo_coefficients: M44, density_matrix_alpha: M44, density_matrix_beta: M44 }, {}, ["E_MEMBER_MALFORMED", "E_MEMBER_MALFORMED"]],
  ["the unrestricted density pair", { ...SP, n_electrons: 2 }, UHF, { mo_coefficients_alpha: M44, mo_coefficients_beta: M44, density_matrix_alpha: M44, density_matrix_beta: M44 }, {}, []],
  ["n_electrons disagrees with the occupations", { ...SP, n_electrons: 3 }, meta4(), { mo_coefficients: M44 }, {}, ["E_MEMBER_MALFORMED"], "basis"],
  ["NTO weights are not electrons", { ...SP, n_electrons: 2 }, meta4({ occupation_semantics: "transition_weight", occupations: [0.9, 0.1, 0, 0] }), { mo_coefficients: M44 }, {}, []],
  ["provenance.n_electrons agrees", { ...SP, n_electrons: 2 }, meta4(), { mo_coefficients: M44 }, { provenance: { n_electrons: 2 } }, []],
  ["provenance.n_electrons disagrees", { ...SP, n_electrons: 2 }, meta4(), { mo_coefficients: M44 }, { provenance: { n_electrons: 3 } }, ["E_ROOT_INCONSISTENT"], "basis"],
])) {
  test(`wavefunction: ${label}`, async () => {
    const report = await validate(wfArchive(basis, meta, binaries, root));
    assert.deepEqual(codes(report), want, JSON.stringify(report.findings));
    if (role) assert.equal(report.findings.find((f) => f.code === want[0])?.where, `/sections/1/members/${role}`);
  });
}

test("the wavefunction rules run at the semantics level, not below", async () => {
  const bytes = wfArchive(SP, meta4({ complex: true }), { mo_coefficients: M44 });
  assert.deepEqual(codes(await validate(bytes, { level: "payloads" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "semantics" })), ["E_MEMBER_MALFORMED"]);
});
