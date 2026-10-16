import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { CANONICAL_KINDS, FINDING_CODES, READABLE_VERSIONS } from "../dist/index.js";
import { KINDS_PATH, REGISTRY_PATH, generateKindsSource } from "../scripts/gen-kinds.mjs";

const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf8"));

test("regenerating src/kinds.ts gives the committed file", () => {
  assert.equal(generateKindsSource(registry), readFileSync(KINDS_PATH, "utf8"));
});

test("`gen-kinds --check` agrees", () => {
  const script = fileURLToPath(new URL("../scripts/gen-kinds.mjs", import.meta.url));
  const out = execFileSync(process.execPath, [script, "--check"], { encoding: "utf8" });
  assert.match(out, /up to date/);
});

test("the generated kinds are the registry's canonical kinds", () => {
  assert.deepEqual([...CANONICAL_KINDS], registry.canonical_kinds);
  assert.deepEqual([...READABLE_VERSIONS], registry.readable_versions);
  assert.ok(CANONICAL_KINDS.includes("structure") && CANONICAL_KINDS.includes("run.record"));
});

test("the generator refuses a malformed registry", () => {
  assert.throws(() => generateKindsSource({ canonical_kinds: [], readable_versions: [1] }));
  assert.throws(() => generateKindsSource({ canonical_kinds: ["a", "a"], readable_versions: [1] }));
  assert.throws(() => generateKindsSource({ canonical_kinds: ["a"], readable_versions: /** @type {any} */ ("1") }));
});

test("the finding vocabulary is the one of spec Appendix B", (t) => {
  const specPath = fileURLToPath(new URL("../../spec/qvf-format-spec.md", import.meta.url));
  const spec = existsSync(specPath) ? readFileSync(specPath, "utf8") : "";
  const at = spec.indexOf("Appendix B. Validation finding codes");
  if (at < 0) {
    t.skip("spec Appendix B is not in this tree yet (it arrives with the validator-hardening change)");
    return;
  }
  const table = new Map();
  for (const m of spec.slice(at).matchAll(/^\| `([EW]_[A-Z0-9_]+)` \| (error|warning) \|/gm)) {
    table.set(m[1], m[2]);
  }
  assert.ok(table.size > 20, "found the Appendix B table");
  assert.deepEqual(Object.fromEntries(table), { ...FINDING_CODES });
});
