import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { validate } from "../dist/index.js";

for (const name of ["nto_unrestricted", "nto_unrestricted_empty_beta", "nto_unrestricted_tddft", "nto_unrestricted_legacy"]) {
  test(`${name} validates`, async () => {
    const r = await validate(readFileSync(new URL(`../../conformance/corpus/${name}.qvf`, import.meta.url)));
    assert.equal(r.ok, true, JSON.stringify(r.findings));
  });
}
/** @type {Array<[string, string, number[]]>} */
const cases = [
  ["rows", "E_MEMBER_MALFORMED", [1, 2]], ["weights", "E_MEMBER_MALFORMED", [1, 2]],
  ["order", "E_MEMBER_MALFORMED", [1, 2]], ["negative", "E_MEMBER_MALFORMED", [1, 2]],
  ["metadata_rows", "E_MEMBER_MALFORMED", [1]], ["energies_rows", "E_MEMBER_MALFORMED", [1]],
  ["partner_missing", "E_REF_UNRESOLVED", [1]], ["state", "E_REF_UNRESOLVED", [1, 2]],
  ["missing_role", "E_REF_UNRESOLVED", [2]], ["missing_state", "E_PAYLOAD_SCHEMA", [1]],
];
for (const [defect, code, indices] of cases) {
  test(`unrestricted NTO ${defect}: shared finding code and location`, async () => {
    const bytes = readFileSync(new URL(`../../conformance/negative/nto_unrestricted_${defect}.qvf`, import.meta.url));
    const r = await validate(bytes);
    assert.equal(r.ok, false);
    const found = [...new Set(r.findings.filter(f => f.code === code).map(f => f.where))].sort();
    assert.deepEqual(found, indices.map(i => `/sections/${i}/members/mo_metadata`));
  });
}
