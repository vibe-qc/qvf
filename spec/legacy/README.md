# Legacy schemas

`qvf_manifest_v2.schema.json` is a frozen legacy artefact, a strict superset of the v1 schema (identical except that `qvf_version` may be 1 or 2), retained only so archives stamped `qvf_version: 2` (vibe-qc v0.10.0–v0.15.x) keep validating. Producers MUST NOT emit `qvf_version: 2`; see the 2026-07-10 decision in [`GOVERNANCE.md`](../../GOVERNANCE.md).
