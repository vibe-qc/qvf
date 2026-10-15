// Section references (spec § 4.1, § 5.5): `structure_ref` must name a
// `structure` section, `run_ref` a `run.record`, and a `reaction.waypoints`
// `trajectory_ref` a `trajectory`; anything else is E_REF_UNRESOLVED, as in
// the Python and C++ reference validators.

import assert from "node:assert/strict";
import { test } from "node:test";

import { validate as validateWithSchema } from "../dist/index.js";
import { addSection, baseArchive, binaryMember, float64Bytes, jsonBytes, jsonMember, opaqueMember, pack } from "./helpers.mjs";

// These tests pin the semantic checks, each archive isolating one rule, so they
// validate without the JSON Schema check generated from the schema (the
// behaviour of a validator without a schema engine: W_SCHEMA_SKIPPED);
// schemaCheck.test.mjs covers the checker.
/** @type {typeof validateWithSchema} */
const validate = (bytes, options = {}) => validateWithSchema(bytes, { schemaCheck: false, ...options });

/** The codes of a report, without the always-present W_SCHEMA_SKIPPED. */
function codes(/** @type {{ findings: { code: string }[] }} */ report) {
  return report.findings.map((f) => f.code).filter((c) => c !== "W_SCHEMA_SKIPPED");
}

/**
 * structure + run.record "run" + trajectory "traj" + scf_history "scf" (with
 * `scfFields` on its section object) + reaction.waypoints "wp".
 * @param {Record<string, unknown>} scfFields
 * @param {string} trajectoryRef
 */
function refsArchive(scfFields, trajectoryRef = "traj") {
  const a = baseArchive();
  const log = new TextEncoder().encode("done\n");
  addSection(a, { id: "run", kind: "run.record", program: "t", members: { log: opaqueMember("run/log.txt", log) } }, { "run/log.txt": log });
  const meta = jsonBytes({ symbols: ["O", "H", "H"] });
  const coords = float64Bytes(new Array(9).fill(0));
  addSection(
    a,
    {
      id: "traj",
      kind: "trajectory",
      members: {
        metadata: jsonMember("traj/metadata.json", meta),
        coords: binaryMember("traj/coords.bin", coords, "float64", [1, 3, 3]),
      },
    },
    { "traj/metadata.json": meta, "traj/coords.bin": coords },
  );
  const iters = jsonBytes({ iterations: [{ iter: 1, energy_eh: -74.9 }] });
  addSection(a, { id: "scf", kind: "scf_history", members: { iterations: jsonMember("scf.json", iters) }, ...scfFields }, { "scf.json": iters });
  const wp = jsonBytes({ waypoints: [{ frame_index: 0, label: "R", kind: "reactant" }] });
  addSection(a, { id: "wp", kind: "reaction.waypoints", trajectory_ref: trajectoryRef, members: { waypoints: jsonMember("wp.json", wp) } }, { "wp.json": wp });
  return pack(a);
}

test("references that name a section of the right kind pass", async () => {
  const report = await validate(refsArchive({ structure_ref: "structure", run_ref: "run", group: "step 1" }));
  assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
  assert.ok(report.ok);
});

test("a null reference counts as absent", async () => {
  const report = await validate(refsArchive({ structure_ref: null }));
  assert.deepEqual(codes(report), []);
});

for (const [label, fields, trajectoryRef, pointer] of /** @type {[string, Record<string, unknown>, string, string][]} */ ([
  ["structure_ref names a run.record", { structure_ref: "run" }, "traj", "/sections/3/structure_ref"],
  ["structure_ref names a trajectory", { structure_ref: "traj" }, "traj", "/sections/3/structure_ref"],
  ["structure_ref names no section", { structure_ref: "nowhere" }, "traj", "/sections/3/structure_ref"],
  ["run_ref names a structure", { run_ref: "structure" }, "traj", "/sections/3/run_ref"],
  ["run_ref is not a string", { run_ref: 5 }, "traj", "/sections/3/run_ref"],
  ["trajectory_ref names a structure", {}, "structure", "/sections/4/trajectory_ref"],
  ["trajectory_ref names an scf_history", {}, "scf", "/sections/4/trajectory_ref"],
])) {
  test(`E_REF_UNRESOLVED: ${label}`, async () => {
    const report = await validate(refsArchive(fields, trajectoryRef));
    assert.deepEqual(codes(report), ["E_REF_UNRESOLVED"], JSON.stringify(report.findings));
    assert.equal(report.findings.find((f) => f.code === "E_REF_UNRESOLVED")?.where, pointer);
    assert.equal(report.ok, false);
  });
}

test("references are checked only from the references level up", async () => {
  const bytes = refsArchive({ structure_ref: "run" });
  assert.deepEqual(codes(await validate(bytes, { level: "semantics" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "references" })), ["E_REF_UNRESOLVED"]);
});

/**
 * structure + run.record "run" + job.spec "job" whose payload is `payload`.
 * @param {Record<string, unknown>} payload
 */
function jobSpecArchive(payload) {
  const a = baseArchive();
  const log = new TextEncoder().encode("done\n");
  addSection(a, { id: "run", kind: "run.record", program: "t", members: { log: opaqueMember("run/log.txt", log) } }, { "run/log.txt": log });
  const spec = jsonBytes({ job_type: "molecular", ...payload });
  addSection(a, { id: "job", kind: "job.spec", members: { spec: jsonMember("job/spec.json", spec) } }, { "job/spec.json": spec });
  return pack(a);
}

// A job.spec payload's structure_ref (spec § 5.9) names a structure section.
for (const [label, payload] of /** @type {[string, Record<string, unknown>][]} */ ([
  ["names a structure", { structure_ref: "structure" }],
  ["is absent", {}],
])) {
  test(`job.spec structure_ref ${label}: no finding`, async () => {
    const report = await validate(jobSpecArchive(payload));
    assert.deepEqual(codes(report), [], JSON.stringify(report.findings));
    assert.ok(report.ok);
  });
}

for (const [label, ref] of /** @type {[string, unknown][]} */ ([
  ["names a run.record", "run"],
  ["names the job.spec itself", "job"],
  ["names no section", "nowhere"],
  ["is not a string", 7],
  ["is null", null],
])) {
  test(`E_REF_UNRESOLVED: job.spec structure_ref ${label}`, async () => {
    const report = await validate(jobSpecArchive({ structure_ref: ref }));
    assert.deepEqual(codes(report), ["E_REF_UNRESOLVED"], JSON.stringify(report.findings));
    assert.equal(report.findings.find((f) => f.code === "E_REF_UNRESOLVED")?.where, "/sections/2/members/spec");
    assert.equal(report.ok, false);
  });
}

test("job.spec structure_ref is checked only from the references level up", async () => {
  const bytes = jobSpecArchive({ structure_ref: "run" });
  assert.deepEqual(codes(await validate(bytes, { level: "semantics" })), []);
  assert.deepEqual(codes(await validate(bytes, { level: "references" })), ["E_REF_UNRESOLVED"]);
});
