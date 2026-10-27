#!/usr/bin/env node
// QVF conformance runner for @qvf/core (Node).
//
// Reimplements the `expected.json` check format of conformance/README.md over
// the golden corpus, and the must-fail format over a negative corpus and over
// the legacy corpus.
//
//   node scripts/conformance.mjs [CORPUS_DIR] [--negative DIR] [--legacy DIR] [--exact]
//                                [--no-schema-check]
//
//   CORPUS_DIR     positive corpus (default: ../conformance/corpus)
//   --negative DIR also run the negative corpus in DIR
//   --legacy DIR   also run the legacy corpus in DIR (archives stamped
//                  qvf_version 2, which the validators check as version 1
//                  with the warning W_VERSION_WITHDRAWN); it uses the negative
//                  format and is reported separately
//   --exact        negative and legacy corpora: require exactly the expected
//                  finding codes (ignoring the JSON Schema codes E_SCHEMA,
//                  E_PAYLOAD_SCHEMA and W_SCHEMA_SKIPPED, which a schema check
//                  also reports for several archives), as the Python and C++
//                  reference validators do, instead of "at least these"
//   --no-schema-check
//                  validate without the JSON Schema check generated from the
//                  schema (W_SCHEMA_SKIPPED): the schema-only expectations are
//                  then dropped and the verdict is judged on the other codes
//
// Exits 0 when every archive passes, 1 on any failure, 2 on a usage error.
// Run `npm run build` first (the `npm run conformance` script does).

import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { QvfReader, validate } from "../dist/index.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
export const DEFAULT_CORPUS = join(HERE, "..", "..", "conformance", "corpus");

/** The JSON Schema finding codes; only a validator that runs the schema reports the errors. */
const SCHEMA_ONLY_CODES = new Set(["E_SCHEMA", "E_PAYLOAD_SCHEMA", "W_SCHEMA_SKIPPED"]);

/**
 * @typedef {{ section?: string, member?: string, manifest_pointer?: (string|number)[],
 *   json_pointer?: (string|number)[], binary_index?: number[], decode?: string,
 *   equals?: unknown, contains?: string, tol?: number }} Check
 * @typedef {{ archive: string, kinds?: string[], source_program?: string, checks?: Check[] }} Expected
 * @typedef {{ code: string, severity: string }} ExpectedFinding
 * @typedef {{ archive: string, limits?: Record<string, number>, expect: ExpectedFinding[] }} ExpectedNegative
 */

/**
 * Walk a nested value by a list of keys and indices.
 * @param {unknown} value
 * @param {(string|number)[]} pointer
 * @returns {unknown}
 */
function navigate(value, pointer) {
  let cur = value;
  for (const step of pointer) {
    if (cur === null || typeof cur !== "object" || !(step in cur)) {
      throw new Error(`pointer step ${JSON.stringify(step)} does not exist`);
    }
    cur = /** @type {Record<string|number, unknown>} */ (cur)[step];
  }
  return cur;
}

/**
 * Element of a flat C-order array at a multi-dimensional index.
 * @param {{ shape: number[], data: ArrayLike<number|bigint> }} array
 * @param {number[]} index
 * @returns {number|bigint}
 */
function elementAt(array, index) {
  const { shape, data } = array;
  if (index.length !== shape.length) {
    throw new Error(`index rank ${index.length} does not match array rank ${shape.length}`);
  }
  let flat = 0;
  for (let axis = 0; axis < shape.length; axis++) {
    const extent = /** @type {number} */ (shape[axis]);
    let i = /** @type {number} */ (index[axis]);
    if (i < 0) i += extent; // negative indices count from the end, as in NumPy
    if (!Number.isInteger(i) || i < 0 || i >= extent) {
      throw new Error(`index ${index[axis]} out of range for axis ${axis} of extent ${extent}`);
    }
    flat = flat * extent + i;
  }
  return /** @type {number|bigint} */ (data[flat]);
}

/**
 * @param {unknown} a
 * @param {unknown} b
 * @returns {boolean}
 */
function deepEqual(a, b) {
  if (typeof a === "bigint" || typeof b === "bigint") {
    return typeof a !== "object" && typeof b !== "object" && BigInt(/** @type {any} */ (a)) === BigInt(/** @type {any} */ (b));
  }
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  }
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return (
      ka.length === kb.length &&
      ka.every((k) => Object.hasOwn(b, k) && deepEqual(/** @type {any} */ (a)[k], /** @type {any} */ (b)[k]))
    );
  }
  return false;
}

/**
 * @param {unknown} got
 * @param {unknown} want
 * @param {number|undefined} tol
 * @returns {boolean}
 */
function matches(got, want, tol) {
  if (tol !== undefined) return Math.abs(Number(got) - Number(want)) <= Number(tol);
  return deepEqual(got, want);
}

/**
 * Run the checks of one expected.json against one archive.
 * @param {string} archivePath
 * @param {Expected} expected
 * @returns {Promise<string[]>} failure messages; empty means pass
 */
export async function runOne(archivePath, expected, schemaCheck = true) {
  const bytes = new Uint8Array(readFileSync(archivePath));
  const report = await validate(bytes, { schemaCheck });
  if (!report.ok) {
    const errors = report.findings.filter((f) => f.severity === "error");
    return errors.map((f) => `validation failed: ${f.code}: ${f.message}`);
  }

  /** @type {string[]} */
  const fails = [];
  const reader = QvfReader.fromBytes(bytes);

  const gotKinds = [...new Set(reader.sections.map((s) => s.kind))].sort();
  const wantKinds = [...(expected.kinds ?? gotKinds)].sort();
  if (JSON.stringify(gotKinds) !== JSON.stringify(wantKinds)) {
    fails.push(`kinds mismatch: got ${JSON.stringify(gotKinds)}, want ${JSON.stringify(wantKinds)}`);
  }
  if (expected.source_program !== undefined) {
    const got = reader.manifest.source?.program;
    if (got !== expected.source_program) {
      fails.push(`source.program: got ${JSON.stringify(got)}, want ${JSON.stringify(expected.source_program)}`);
    }
  }

  for (const chk of expected.checks ?? []) {
    const label = chk.section !== undefined ? `${chk.section}/${chk.member}` : "manifest";
    try {
      /** @type {unknown} */
      let got;
      if (chk.manifest_pointer !== undefined) {
        got = navigate(reader.manifest, chk.manifest_pointer);
      } else if (chk.section === undefined || chk.member === undefined) {
        fails.push(`malformed check (no section/member or manifest_pointer): ${JSON.stringify(chk)}`);
        continue;
      } else if (chk.json_pointer !== undefined) {
        got = navigate(await reader.readJson(chk.section, chk.member), chk.json_pointer);
      } else if (chk.binary_index !== undefined) {
        got = elementAt(await reader.readBinary(chk.section, chk.member), chk.binary_index);
      } else if (chk.decode === "utf8") {
        // An opaque member (citations.references, run.record input/log/attachment):
        // decode the raw bytes as UTF-8 text.
        const text = new TextDecoder("utf-8", { fatal: true }).decode(await reader.readBytes(chk.section, chk.member));
        if (chk.contains !== undefined) {
          if (!text.includes(chk.contains)) {
            fails.push(`check failed (${label}): text does not contain ${JSON.stringify(chk.contains)}`);
          }
          continue;
        }
        got = text;
      } else {
        fails.push(`malformed check (no pointer): ${JSON.stringify(chk)}`);
        continue;
      }
      if (!matches(got, chk.equals, chk.tol)) {
        fails.push(
          `check failed (${label}): got ${String(JSON.stringify(got, (_, v) => (typeof v === "bigint" ? `${v}n` : v)))}, ` +
            `want ${JSON.stringify(chk.equals)}${chk.tol !== undefined ? ` (tol ${chk.tol})` : ""}`,
        );
      }
    } catch (err) {
      fails.push(`check errored ${JSON.stringify(chk)}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  return fails;
}

/**
 * Run one negative (must-fail) archive.
 * @param {string} archivePath
 * @param {ExpectedNegative} expected
 * @param {boolean} exact
 * @param {boolean} [schemaCheck] run the JSON Schema check (default true)
 * @returns {Promise<string[]>} failure messages; empty means pass
 */
export async function runOneNegative(archivePath, expected, exact, schemaCheck = true) {
  const bytes = new Uint8Array(readFileSync(archivePath));
  const report = await validate(bytes, { schemaCheck, ...(expected.limits ? { limits: expected.limits } : {}) });
  /** @type {string[]} */
  const fails = [];
  // Without the schema check (W_SCHEMA_SKIPPED) the schema-only expectations
  // (E_SCHEMA, E_PAYLOAD_SCHEMA) are dropped and the verdict is judged on the
  // other codes, as conformance/run_conformance.py and the C++ runner do: an
  // archive whose only expected errors are schema findings must then validate
  // without another error.
  const skipped = report.findings.some((f) => f.code === "W_SCHEMA_SKIPPED");
  const expect = expected.expect.filter((w) => !(skipped && SCHEMA_ONLY_CODES.has(w.code)));
  for (const want of expect) {
    if (!report.findings.some((f) => f.code === want.code && f.severity === want.severity)) {
      fails.push(`missing expected finding ${want.code} (${want.severity})`);
    }
  }
  const wantInvalid = expect.some((w) => w.severity === "error");
  const invalid = report.findings.some(
    (f) => f.severity === "error" && !(skipped && SCHEMA_ONLY_CODES.has(f.code)),
  );
  if (invalid !== wantInvalid) {
    fails.push(`verdict: validator says ok=${!invalid}, expected ok=${!wantInvalid}`);
  }
  if (exact) {
    const got = [...new Set(report.findings.map((f) => f.code).filter((c) => !SCHEMA_ONLY_CODES.has(c)))].sort();
    const want = [...new Set(expected.expect.map((w) => w.code).filter((c) => !SCHEMA_ONLY_CODES.has(c)))].sort();
    if (JSON.stringify(got) !== JSON.stringify(want)) {
      fails.push(`codes: got ${JSON.stringify(got)}, want exactly ${JSON.stringify(want)}`);
    }
  }
  return fails;
}

/**
 * @param {string} dir
 * @returns {string[]} the *.expected.json paths, sorted
 */
function expectedFiles(dir) {
  return readdirSync(dir)
    .filter((n) => n.endsWith(".expected.json"))
    .sort()
    .map((n) => join(dir, n));
}

/**
 * @param {string} dir
 * @param {(line: string) => void} log
 * @param {boolean} negative
 * @param {boolean} exact
 * @param {boolean} schemaCheck
 * @returns {Promise<{ total: number, failed: number }>}
 */
async function runDirectory(dir, log, negative, exact, schemaCheck) {
  let total = 0;
  let failed = 0;
  for (const file of expectedFiles(dir)) {
    const expected = JSON.parse(readFileSync(file, "utf8"));
    const archive = join(dir, expected.archive);
    total++;
    if (!existsSync(archive)) {
      failed++;
      log(`FAIL ${expected.archive}: archive missing`);
      continue;
    }
    const fails = negative
      ? await runOneNegative(archive, expected, exact, schemaCheck)
      : await runOne(archive, expected, schemaCheck);
    if (fails.length > 0) {
      failed++;
      log(`FAIL ${expected.archive}`);
      for (const f of fails) log(`     - ${f}`);
    } else {
      const what = negative
        ? `(${expected.expect.map((/** @type {ExpectedFinding} */ e) => e.code).join(", ")})`
        : `(${(expected.checks ?? []).length} checks)`;
      log(`PASS ${expected.archive}  ${what}`);
    }
  }
  return { total, failed };
}

/**
 * Run the positive corpus in `dir`.
 * @param {string} dir
 * @param {(line: string) => void} [log]
 * @param {{ schemaCheck?: boolean }} [options]
 */
export function runPositive(dir, log = console.log, { schemaCheck = true } = {}) {
  return runDirectory(dir, log, false, false, schemaCheck);
}

/**
 * Run the negative corpus in `dir`.
 * @param {string} dir
 * @param {{ exact?: boolean, log?: (line: string) => void, schemaCheck?: boolean }} [options]
 */
export function runNegative(dir, { exact = false, log = console.log, schemaCheck = true } = {}) {
  return runDirectory(dir, log, true, exact, schemaCheck);
}

async function main() {
  const args = process.argv.slice(2);
  /** @type {string | undefined} */
  let corpus;
  /** @type {string | undefined} */
  let negative;
  /** @type {string | undefined} */
  let legacy;
  let exact = false;
  let schemaCheck = true;
  for (let i = 0; i < args.length; i++) {
    const a = /** @type {string} */ (args[i]);
    if (a === "--negative") negative = args[++i];
    else if (a === "--legacy") legacy = args[++i];
    else if (a === "--exact") exact = true;
    else if (a === "--no-schema-check") schemaCheck = false;
    else if (a.startsWith("-") || corpus !== undefined) {
      console.error(
        "usage: node scripts/conformance.mjs [CORPUS_DIR] [--negative DIR] [--legacy DIR] [--exact] [--no-schema-check]",
      );
      return 2;
    } else corpus = a;
  }
  for (const flag of ["--negative", "--legacy"]) {
    if (args.includes(flag) && !(flag === "--negative" ? negative : legacy)) {
      console.error(`${flag} needs a directory`);
      return 2;
    }
  }

  const dir = corpus ?? DEFAULT_CORPUS;
  if (!existsSync(dir) || expectedFiles(dir).length === 0) {
    console.error(`no *.expected.json found in ${dir}`);
    return 2;
  }
  if (!schemaCheck) console.log("JSON Schema check disabled (--no-schema-check)\n");
  const positive = await runPositive(dir, console.log, { schemaCheck });
  console.log(`\nconformance: ${positive.total - positive.failed}/${positive.total} archives passed`);
  let failed = positive.failed;

  if (negative) {
    if (!existsSync(negative) || expectedFiles(negative).length === 0) {
      console.error(`no *.expected.json found in ${negative}`);
      return 2;
    }
    console.log("");
    const neg = await runNegative(negative, { exact, schemaCheck });
    console.log(`\nnegative conformance: ${neg.total - neg.failed}/${neg.total} archives passed`);
    failed += neg.failed;
  }

  if (legacy) {
    if (!existsSync(legacy) || expectedFiles(legacy).length === 0) {
      console.error(`no *.expected.json found in ${legacy}`);
      return 2;
    }
    console.log("");
    const leg = await runNegative(legacy, { exact, schemaCheck });
    console.log(`\nlegacy conformance: ${leg.total - leg.failed}/${leg.total} archives passed`);
    failed += leg.failed;
  }
  return failed > 0 ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
