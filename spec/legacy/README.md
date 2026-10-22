# Legacy schemas

`qvf_manifest_v2.schema.json` is a frozen legacy artefact: the v1 manifest schema of qvf 0.1.0, identical to it except that `qvf_version` may be 1 or 2, and its `$id` (`https://vibe-qc.org/spec/qvf/2/manifest.schema.json`). It is kept only so that anything resolving that `$id` still finds a document. No validator uses it, and it is not a superset of the current v1 schema, which has grown additively since 0.1.0; its bytes never change.

The rule for an archive stamped `qvf_version: 2` (vibe-qc v0.10.0–v0.15.x) is spec § 3.1: it is read and validated as `qvf_version: 1` against the **current** v1 schema, and validators report the warning `W_VERSION_WITHDRAWN`. Producers MUST NOT emit `qvf_version: 2`, and consumers apply § 3.1 instead of keeping a schema of their own for version 2. See the 2026-07-10 and 2026-10-15 decisions in [`GOVERNANCE.md`](../../GOVERNANCE.md).
