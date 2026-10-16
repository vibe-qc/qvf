import assert from "node:assert/strict";
import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { DEFAULT_CORPUS, runNegative, runPositive } from "../scripts/conformance.mjs";

// The negative corpus sits beside the positive one once it exists in the tree;
// QVF_NEGATIVE_CORPUS points the test at another directory.
const NEGATIVE = process.env.QVF_NEGATIVE_CORPUS ?? fileURLToPath(new URL("../../conformance/negative/", import.meta.url));

/** @param {string[]} lines */
const collect = (lines) => (/** @type {string} */ line) => void lines.push(line);

// The legacy corpus (archives stamped qvf_version 2) beside the positive one;
// QVF_LEGACY_CORPUS points the test at another directory.
const LEGACY = process.env.QVF_LEGACY_CORPUS ?? fileURLToPath(new URL("../../conformance/legacy/", import.meta.url));

test("the positive conformance corpus passes", async () => {
  const lines = /** @type {string[]} */ ([]);
  const { total, failed } = await runPositive(DEFAULT_CORPUS, collect(lines));
  assert.ok(total >= 12, `expected the whole corpus, ran ${total}`);
  assert.equal(failed, 0, lines.filter((l) => l.startsWith("FAIL") || l.startsWith("     -")).join("\n"));
  // The container edge cases: ZIP64 structures on small members, and members
  // streamed with data descriptors (sizes only in the central directory).
  for (const name of ["zip64.qvf", "data_descriptor.qvf"]) {
    assert.ok(
      lines.some((l) => l.startsWith(`PASS ${name} `)),
      `${name} is missing from the positive corpus or does not pass`,
    );
  }
});

test("the negative conformance corpus passes, code for code", async (t) => {
  if (!existsSync(NEGATIVE) || !readdirSync(NEGATIVE).some((n) => n.endsWith(".expected.json"))) {
    t.skip("conformance/negative is not in this tree yet");
    return;
  }
  // With the generated JSON Schema check (every expectation binds, the
  // schema-only ones included), and without it (W_SCHEMA_SKIPPED: the
  // schema-only expectations are dropped).
  for (const schemaCheck of [true, false]) {
    const lines = /** @type {string[]} */ ([]);
    const { total, failed } = await runNegative(NEGATIVE, { exact: true, log: collect(lines), schemaCheck });
    assert.ok(total > 0);
    assert.equal(failed, 0, lines.filter((l) => l.startsWith("FAIL") || l.startsWith("     -")).join("\n"));
  }
});

test("the positive conformance corpus passes without the schema check too", async () => {
  const lines = /** @type {string[]} */ ([]);
  const { failed } = await runPositive(DEFAULT_CORPUS, collect(lines), { schemaCheck: false });
  assert.equal(failed, 0, lines.filter((l) => l.startsWith("FAIL") || l.startsWith("     -")).join("\n"));
});

test("the legacy conformance corpus is judged as its expectations say: valid, with W_VERSION_WITHDRAWN", async (t) => {
  if (!existsSync(LEGACY) || !readdirSync(LEGACY).some((n) => n.endsWith(".expected.json"))) {
    t.skip("conformance/legacy is not in this tree yet");
    return;
  }
  // With and without the generated JSON Schema check: the withdrawn version 2
  // is checked as 1, so the schema check reports nothing for it (spec § 3.1).
  for (const schemaCheck of [true, false]) {
    const lines = /** @type {string[]} */ ([]);
    const { total, failed } = await runNegative(LEGACY, { exact: true, log: collect(lines), schemaCheck });
    assert.ok(total > 0);
    assert.equal(failed, 0, lines.filter((l) => l.startsWith("FAIL") || l.startsWith("     -")).join("\n"));
    assert.ok(lines.some((l) => l.includes("W_VERSION_WITHDRAWN")), "the legacy archives expect W_VERSION_WITHDRAWN");
  }
});
