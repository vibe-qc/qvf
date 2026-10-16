# QVF command line

The `qvf` command uses the reference Python library to inspect, compare and
maintain archives. Install from the toolkit checkout with
`pip install './python[validate]'`. The `validate` extra enables full JSON
Schema checks. NumPy is unnecessary for these commands. `python -m qvf`
works identically, and the original `qvf-validate [--json] FILE` stays available.

```sh
qvf info result.qvf
qvf validate result.qvf --json
qvf cat result.qvf
qvf cat result.qvf structure structure
qvf extract result.qvf rho data --output density.bin
qvf diff before.qvf after.qvf --atol 1e-8 --rtol 1e-6
qvf repack result.qvf --output compact.qvf --compression deflate
qvf schema > manifest.schema.json
qvf conformance conformance/corpus
```

`info` displays section IDs and kinds, member roles and archive paths, formats,
tensor shapes and uncompressed sizes. `--json` also includes compressed sizes.
It reads the manifest and central directory only. `cat` prints the manifest
when no section/member pair is given, or decodes one JSON member when both
are present. `extract` writes one declared member's exact bytes to an explicit
new file, including opaque logs, images and little-endian tensors. It checks
sizes, CRC and SHA-256 before publishing that file.

Exit status is **0** for success/equal, **1** for failed validation, differing
archives or failed conformance, and **2** for usage or operational errors.
A partially verified extraction or archive rewrite is discarded. Output files
must be new: `extract`, `repack` and `scrub` refuse existing paths, including
the input and symlinks. They stage a sibling temporary file and publish it
without replacing a concurrently created destination. No command edits an
input archive in place.

## Validation levels

`qvf validate FILE --level LEVEL` selects a cumulative stage. The library
accepts the same names in `qvf.validate.run(FILE, level="manifest")` and
`reader.validate(level="manifest")`.

| Level | Checks added |
|---|---|
| `container` | ZIP directory, duplicate and illegal paths, resource caps, presence of manifest; no entries decompressed |
| `manifest` | Manifest JSON/depth/schema, section IDs/kinds, declared member existence and size; only the manifest is read |
| `payloads` | Member CRC/SHA-256, binary sizes/dtypes, JSON parsing and payload schemas, run text UTF-8, preview signatures |
| `semantics` | Scientific consistency, shapes across members, units and normalization |
| `references` | Cross-section reference findings |
| `all` | All stages; the default, identical to the full reference validator |

Findings use the existing shared codes, with `severity`, `code`, `where` and
`message` in `--json` output. `W_SCHEMA_SKIPPED` means the optional schema engine
was unavailable; it is not evidence that structural schema checks passed.
The early stages avoid later reads and checks. A successful early stage does
not certify stages that have not run. Container-only reports have zero parsed
sections. Stage boundaries follow the C++ facade; JavaScript retains its full
validation entry point.

## Compare and repack

`diff` compares logical manifest metadata and common member contents. ZIP
compression, entry ordering, superseded manifests, orphans, and member transport
paths/sizes/hashes do not themselves cause a difference. Section order, kinds,
roles, dtypes and shapes are significant. JSON object key order is immaterial.
Members being compared are checksum-verified; use `validate` to check an entire
archive independently of a comparison.

Floating JSON numbers and tensor values use
`abs(a-b) <= max(atol, rtol * max(abs(a), abs(b)))`, with both tolerances zero
by default. Integers, booleans and opaque bytes compare exactly. NaNs differ;
equal infinities compare equal. `--ignore-metadata` excludes only the root
`metadata` object (including UUID, timestamps and authors). Source information
and other root fields still count. `--json` emits the verdict and locations;
`--max-differences N` limits reported locations, without stopping comparison
or checksum verification. Binary comparisons use bounded chunks.

`repack` copies only members referenced by the current manifest and writes one
manifest, removing orphan entries and old manifests. It preserves scientific
content, source metadata and UUID. `--compression preserve` is the default;
`store` and `deflate` select a new ZIP method. This is useful after append-mode
library edits, and `diff` can confirm that the logical content is unchanged.

## Scrub for review

Scrubbing always reports changes and requires either `--dry-run` or an explicit
new `--output`. The original archive remains available to undo or review the
operation. First inspect the proposed changes:

```sh
qvf scrub result.qvf --dry-run \
  --path-pattern '/scratch/example' --user-pattern 'user=example'
qvf scrub result.qvf --output shared.qvf \
  --path-pattern '/scratch/example' --user-pattern 'user=example'
qvf validate shared.qvf
```

The command removes deprecated root `provenance.hostname` and author `email`
and `affiliation` fields. Repeated `--path-pattern REGEX` and
`--user-pattern REGEX` options select additional replacements in `run.record`
commands, UTF-8 inputs/logs/attachments, and string values of the `files` index.
They use Python regular expressions. There is no built-in list of people,
paths or hosts. The replacement is the literal `[redacted]` by default;
`--replacement TEXT` changes it. Pattern matches and removals are reported by
location and count, without echoing matched text.

Text processing is bounded by the reader's JSON/text cap per member; changed
payloads are staged on disk, keeping memory bounded to one text member.
Shared payloads that would change are rejected rather than silently changing
another section's data. The new archive has updated member sizes/hashes, one
manifest, no orphans, a new UUID and a `derived_from` link to the original UUID
when available. `job.spec` payload bytes and scientific sections are preserved.

The report lists skipped members, including non-UTF-8 attachments and run text
for which no patterns were selected. Names in other fields, section IDs,
archive member paths, author names, arbitrary vendor payloads and binary
attachments are outside the scrub scope. Review them before sharing; a scrub
report does not certify that an archive contains no personal information.
This command does not alter the repository's publication-scanner policy.

## Run a corpus

`qvf conformance DIRECTORY` runs the positive `*.expected.json` cases there,
then `negative/` and `legacy/` siblings if present. `--negative DIRECTORY`
and `--legacy DIRECTORY` select explicit alternatives. `--no-negative` runs
only positives (also skipping automatic legacy cases); `--no-legacy` skips
just legacy. Corpus archives must resolve within their selected directory.
The corpus comes from the QVF source release and is not bundled into the
Python wheel. The installed command and `conformance/run_conformance.py`
share one runner and the same expected findings; neither needs NumPy.

## Text conversion (toolkit 0.5.0)

`qvf convert INPUT --from xyz --to qvf -o OUTPUT` imports geometry; use
`--from qvf --to extxyz --section ID` to export a selected structure or
trajectory. Scalar cube import/export supports explicit kind and periodic
endpoint choices. Every operation returns a conversion report and requires
a new output path. See [supported subsets and examples](converters.md).
