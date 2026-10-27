#!/usr/bin/env node
// Generate js/src/kinds.ts from the repository's registry.json.
//
//   node scripts/gen-kinds.mjs           write src/kinds.ts
//   node scripts/gen-kinds.mjs --check   exit 1 if src/kinds.ts is stale
//
// The canonical kind list is the registry's `canonical_kinds` (the registry is
// itself drift-guarded against the schema), so the validator never carries a
// hand-maintained copy. The output is deterministic; a test regenerates it and
// compares.

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

export const REGISTRY_PATH = fileURLToPath(new URL("../../registry.json", import.meta.url));
export const KINDS_PATH = fileURLToPath(new URL("../src/kinds.ts", import.meta.url));

/**
 * The text of src/kinds.ts for a parsed registry.
 * @param {{ canonical_kinds: string[], readable_versions: number[] }} registry
 * @returns {string}
 */
export function generateKindsSource(registry) {
  const kinds = registry.canonical_kinds;
  const versions = registry.readable_versions;
  if (!Array.isArray(kinds) || kinds.length === 0 || !kinds.every((k) => typeof k === "string")) {
    throw new Error("registry.json: canonical_kinds must be a non-empty array of strings");
  }
  if (new Set(kinds).size !== kinds.length) {
    throw new Error("registry.json: canonical_kinds contains duplicates");
  }
  if (!Array.isArray(versions) || !versions.every((v) => Number.isInteger(v))) {
    throw new Error("registry.json: readable_versions must be an array of integers");
  }
  const lines = [
    "// GENERATED FILE - do not edit.",
    "// Source: registry.json (canonical_kinds, readable_versions).",
    "// Regenerate with `npm run gen-kinds` in js/; a test fails when this file is stale.",
    "",
    "/** Canonical section kinds of QVF v1 (spec § 5), in registry order. */",
    "export const CANONICAL_KINDS: readonly string[] = [",
    ...kinds.map((k) => `  ${JSON.stringify(k)},`),
    "];",
    "",
    "/** The `qvf_version` values a consumer opens (registry `readable_versions`). */",
    `export const READABLE_VERSIONS: readonly number[] = [${versions.join(", ")}];`,
    "",
  ];
  return lines.join("\n");
}

function main() {
  const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf8"));
  const text = generateKindsSource(registry);
  if (process.argv.includes("--check")) {
    const current = readFileSync(KINDS_PATH, "utf8");
    if (current !== text) {
      console.error("src/kinds.ts is stale; run `npm run gen-kinds` in js/ and commit the result");
      process.exitCode = 1;
    } else {
      console.log("src/kinds.ts is up to date");
    }
    return;
  }
  writeFileSync(KINDS_PATH, text);
  console.log(`wrote src/kinds.ts (${registry.canonical_kinds.length} canonical kinds)`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
