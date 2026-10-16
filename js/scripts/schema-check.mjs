#!/usr/bin/env node
// Drive the generated JSON Schema checker from a test.
//
// Used by python/tests/test_schema_checker_parity.py to compare the checker
// and the validator with the Python reference (jsonschema), document by
// document and archive by archive; the same protocol as the C++
// cpp/tests/schema_check_tool.cpp. Run `npm run build` first.
//
// Reads one JSON object per line from stdin and prints one JSON line per input:
//   {"def": NAME, "doc": VALUE}
//       NAME null checks VALUE against the root schema (as manifest.json),
//       otherwise against $defs/NAME. Prints an array of [pointer, message]
//       pairs, one per schema error, in the order the checker reports them.
//   {"archive": PATH, "limits": {...} | null, "schema_check": true | false}
//       Validates the archive (limits as in the negative corpus) and prints
//       its findings as an array of {"severity", "code", "where", "message"}.
// A request that cannot be served prints {"error": MESSAGE}.

import { readFileSync } from "node:fs";

import { validate } from "../dist/index.js";
import { checkDefinition, checkManifest } from "../dist/schemaCheck.js";

/** @param {any} req */
async function serve(req) {
  if (typeof req.archive === "string") {
    const report = await validate(new Uint8Array(readFileSync(req.archive)), {
      schemaCheck: req.schema_check !== false,
      ...(req.limits ? { limits: req.limits } : {}),
    });
    return report.findings;
  }
  const errors = req.def === null ? checkManifest(req.doc) : checkDefinition(req.def, req.doc);
  return errors.map((e) => [e.pointer, e.message]);
}

if (process.argv.length > 2) {
  console.error("usage: node scripts/schema-check.mjs < requests (one JSON object per line)");
  process.exitCode = 2;
} else {
  const out = [];
  for (const line of readFileSync(0, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      out.push(JSON.stringify(await serve(JSON.parse(line))));
    } catch (err) {
      out.push(JSON.stringify({ error: err instanceof Error ? err.message : String(err) }));
    }
  }
  process.stdout.write(out.length ? `${out.join("\n")}\n` : "");
}
