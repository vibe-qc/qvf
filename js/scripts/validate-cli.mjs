#!/usr/bin/env node
// Validate .qvf files from the command line with the built package.
//
//   node scripts/validate-cli.mjs [--json] FILE.qvf [FILE.qvf ...]
//
// Prints each finding (or the report as JSON) and exits 1 if any archive has an
// error finding, 2 on a usage error. Run `npm run build` first.

import { readFileSync } from "node:fs";

import { validate } from "../dist/index.js";

const args = process.argv.slice(2);
const asJson = args.includes("--json");
const files = args.filter((a) => a !== "--json");
if (files.length === 0 || files.some((f) => f.startsWith("-"))) {
  console.error("usage: node scripts/validate-cli.mjs [--json] FILE.qvf [FILE.qvf ...]");
  process.exit(2);
}

let failed = false;
for (const file of files) {
  const report = await validate(new Uint8Array(readFileSync(file)));
  if (!report.ok) failed = true;
  if (asJson) {
    console.log(JSON.stringify({ path: file, ...report }, null, 2));
    continue;
  }
  console.log(`QVF validation: ${file}`);
  console.log(`  sections: ${report.nSections}`);
  for (const f of report.findings) console.log(`  ${f.code}: ${f.message}`);
  console.log(report.ok ? "  OK" : "  FAILED");
}
process.exitCode = failed ? 1 : 0;
