"""Audit immutable QVF inputs across an additive program handoff.

Usage: python python/examples/audit_interchange.py pending.qvf result.qvf

Repeat for result.qvf -> reopened.qvf when testing a lossless save. This is
an interchange check, not a chemistry acceptance or an archive converter.
It writes only a JSON report to stdout and never changes either archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from qvf import Reader


def identity(path):
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"name": Path(path).name, "sha256": digest.hexdigest(), "size": size}


def audit(source, result):
    """Require all submitted section declarations and payloads to survive.

    Root metadata may evolve; this does not assert its scientific meaning.
    A drawing edit or lossy conversion fails this additive-preservation check
    intentionally. Keep the unedited result separately in either case.
    """
    report = {"source": identity(source), "result": identity(result),
              "scientific_validity": "not_assessed", "errors": []}
    with Reader(source) as original, Reader(result) as updated:
        for label, reader in (("source", original), ("result", updated)):
            validation = reader.validate()
            report[label]["validation"] = validation
            if not validation["ok"]:
                report["errors"].append(f"{label}: structural/integrity validation failed")
            if any(f["code"] == "W_SCHEMA_SKIPPED" for f in validation["findings"]):
                report["errors"].append(f"{label}: schema validation unavailable")
        if report["errors"]:
            report["ok"] = False
            return report
        sections = {s["id"]: s for s in updated.raw_manifest["sections"]}
        for section in original.raw_manifest["sections"]:
            sid = section["id"]
            if sections.get(sid) != section:
                report["errors"].append(f"section {sid}: missing or changed declaration")
                continue
            for role, member in section["members"].items():
                # Compare bytes even when a legacy descriptor has no SHA-256.
                # Reader bounds and CRC/hash checks apply to both reads.
                if original.read_member(member) != updated.read_member(member):
                    report["errors"].append(f"section {sid} member {role}: changed bytes")
        # An extension declaration is part of the interpretation contract too.
        for namespace, declaration in original.raw_manifest.get("extensions", {}).items():
            if updated.raw_manifest.get("extensions", {}).get(namespace) != declaration:
                report["errors"].append(f"extension {namespace}: missing or changed declaration")
    report["ok"] = not report["errors"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.source, args.result)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        report = {"ok": False, "scientific_validity": "not_assessed", "errors": [str(exc)]}
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
