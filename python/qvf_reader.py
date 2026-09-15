"""qvf_reader — a standalone reference reader / validator for QVF archives.

Depends only on the Python standard library (NumPy is optional and only used for
convenience array decoding). Mirrors the semantic checks that vibe-qc's
``validate_qvf`` performs, so an adopter can self-check archives without
installing vibe-qc. If ``jsonschema`` happens to be importable, the bundled
``spec/qvf_manifest.schema.json`` is additionally enforced for full structural
validation — both of ``manifest.json`` and of the ``structure`` member's payload
(``$defs/StructurePayload``).

CLI::

    python qvf_reader.py file.qvf        # prints a report; exits non-zero on error

Library::

    from qvf_reader import validate_qvf, QvfReader
    report = validate_qvf("file.qvf")
    if not report["ok"]:
        print(report["errors"])

License: Apache-2.0.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from typing import Any

def _find_schema() -> str:
    """Locate the bundled JSON Schema.

    Works in the repo (``../spec``), next to this module (dev / sdist), and in an
    installed wheel (shipped under ``<prefix>/share/qvf-writer/`` via data-files).
    """
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "qvf_manifest.schema.json"),
        os.path.join(here, "..", "spec", "qvf_manifest.schema.json"),
        os.path.join(sys.prefix, "share", "qvf-writer", "qvf_manifest.schema.json"),
    ]
    for cand in candidates:
        if os.path.exists(cand):
            return cand
    return candidates[0]  # may be absent → jsonschema check is skipped gracefully


_SCHEMA_PATH = _find_schema()

# Canonical kinds (schema Section.oneOf branches). Kept in lock-step with the
# writer; a vendor kind (x_<...>) is always accepted.
_CANONICAL_KINDS = frozenset({
    "structure", "bonds", "bond_orders",
    "volume.density", "volume.orbital", "volume.spin", "volume.elf",
    "volume.difference", "volume.generic", "volume.potential", "volume.rdg",
    "wavefunction.gto", "basis.ao", "atom_properties",
    "trajectory", "reaction.path", "reaction.waypoints", "scan.surface",
    "vibrations",
    "spectra.ir", "spectra.raman", "spectra.uvvis", "spectra.ecd",
    "spectra.vcd", "spectra.nmr", "spectra.epr", "spectra.generic",
    "bands", "dos.total", "dos.projected", "dos.coop", "dos.cohp",
    "structure.symmetry", "scf_history", "citations",
    "fermi_surface", "phonon_bands", "phonon_dos", "equation_of_state",
    "topology.qtaim", "run.record", "job.spec",
})

_DTYPE_ITEMSIZE = {
    "int8": 1, "int16": 2, "int32": 4, "int64": 8,
    "uint8": 1, "uint16": 2, "uint32": 4, "uint64": 8,
    "float32": 4, "float64": 8,
}

# Guard against zip-bomb inputs: 8 GiB per member uncompressed (matches vibe-qc).
_MAX_MEMBER_BYTES = (1024 ** 3) * 8


class QvfReader:
    """Lazy reader for a ``.qvf`` archive. Verifies member checksums on read."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._zip = zipfile.ZipFile(path, "r")
        self.manifest: dict[str, Any] = json.loads(self._zip.read("manifest.json"))

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "QvfReader":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def sections(self) -> list[dict[str, Any]]:
        return self.manifest.get("sections", [])

    def read_member(self, member: dict[str, Any], *, verify: bool = True) -> bytes:
        raw = self._zip.read(member["path"])
        if verify and "sha256" in member:
            got = hashlib.sha256(raw).hexdigest()
            if got != member["sha256"]:
                raise ValueError(f"sha256 mismatch for {member['path']}")
        return raw

    def read_json(self, member: dict[str, Any]) -> Any:
        return json.loads(self.read_member(member))

    def read_array(self, member: dict[str, Any]):
        import numpy as np
        raw = self.read_member(member)
        dt = np.dtype(member["dtype"]).newbyteorder("<")
        return np.frombuffer(raw, dtype=dt).reshape(member["shape"])


def _load_schema_validator():
    """Return a jsonschema validator for the bundled schema, or None."""
    try:
        import jsonschema  # type: ignore
    except Exception:
        return None
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        return jsonschema.Draft202012Validator(schema)
    except Exception:
        return None


def _load_payload_validator(defname: str):
    """Return a jsonschema validator for one ``$defs`` entry, or None.

    Payload definitions describe archive members rather than manifest content, so
    they are unreachable from the schema root. Re-rooting a document at the
    definition — carrying ``$defs`` along so its internal ``$ref``s still
    resolve — is what makes them usable.
    """
    try:
        import jsonschema  # type: ignore
    except Exception:
        return None
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        return jsonschema.Draft202012Validator({
            "$schema": schema["$schema"],
            "$ref": f"#/$defs/{defname}",
            "$defs": schema["$defs"],
        })
    except Exception:
        return None


def _structure_payload_errors(sid: str, payload: Any) -> list[str]:
    """Semantic checks on a ``structure`` payload (QVF spec § 5.1).

    Enforced without ``jsonschema`` so the periodicity contract holds for every
    validator, not only those with the optional dependency installed. ``pbc`` is
    the normative carrier; ``dimensionality`` is derived from it.
    """
    if not isinstance(payload, dict):
        return [f"section {sid!r}: structure payload must be a JSON object"]

    errors: list[str] = []
    pbc = payload.get("pbc")
    lattice = payload.get("lattice_vectors")
    dim = payload.get("dimensionality")

    if pbc is None:
        if lattice is not None:
            errors.append(
                f"section {sid!r}: structure payload has lattice_vectors but no "
                f"'pbc'; pbc is REQUIRED for periodic structures (spec § 5.1)")
        if dim not in (None, 0):
            errors.append(
                f"section {sid!r}: dimensionality {dim!r} without 'pbc'; absent "
                f"pbc means a molecule, so dimensionality must be 0 (spec § 5.1)")
        return errors

    if (not isinstance(pbc, list) or len(pbc) != 3
            or not all(isinstance(x, bool) for x in pbc)):
        return [f"section {sid!r}: pbc must be three booleans, got {pbc!r}"]

    n_periodic = sum(pbc)
    if n_periodic and not isinstance(lattice, list):
        errors.append(
            f"section {sid!r}: pbc marks {n_periodic} periodic axis/axes but "
            f"lattice_vectors is {'null' if lattice is None else 'absent'}")
    if dim is not None and int(dim) != n_periodic:
        errors.append(
            f"section {sid!r}: dimensionality {dim} != sum(pbc) {n_periodic} "
            f"(spec § 5.1 invariant)")
    return errors


def validate_qvf(path: str) -> dict[str, Any]:
    """Validate a ``.qvf`` archive. Returns ``{ok, errors, warnings, n_sections}``.

    Performs the semantic checks of the QVF spec § 6: zip readability, manifest
    parseability, id uniqueness, member existence, sha256 integrity, JSON
    parseability, binary byte-size, operand / trajectory_ref resolution,
    extension-critical governance, and the ``structure`` payload's periodicity
    contract. Schema conformance — of the manifest and of the ``structure``
    payload — is added when ``jsonschema`` is installed.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        zf = zipfile.ZipFile(path, "r")
    except Exception as exc:
        return {"ok": False, "errors": [f"not a readable zip: {exc}"],
                "warnings": [], "n_sections": 0}

    names = set(zf.namelist())
    if "manifest.json" not in names:
        return {"ok": False, "errors": ["missing manifest.json"], "warnings": [],
                "n_sections": 0}

    # Zip-bomb guard.
    for info in zf.infolist():
        if info.file_size > _MAX_MEMBER_BYTES:
            errors.append(f"member {info.filename} exceeds size cap "
                          f"({info.file_size} bytes)")

    try:
        manifest = json.loads(zf.read("manifest.json"))
    except Exception as exc:
        return {"ok": False, "errors": [f"manifest.json is not valid JSON: {exc}"],
                "warnings": [], "n_sections": 0}

    # Root sanity.
    if manifest.get("qvf_version") != 1:
        errors.append(f"qvf_version must be 1, got {manifest.get('qvf_version')!r}")
    src = manifest.get("source", {})
    for key in ("program", "version", "calculation"):
        if key not in src:
            errors.append(f"source.{key} is missing")
    if not src.get("program") or not src.get("version"):
        errors.append("source.program and source.version must be non-empty")

    # Optional full schema validation.
    validator = _load_schema_validator()
    if validator is not None:
        for err in validator.iter_errors(manifest):
            loc = "/".join(str(p) for p in err.path)
            errors.append(f"schema: {loc}: {err.message}")
    else:
        warnings.append("jsonschema not installed; structural schema check skipped")
    payload_validator = _load_payload_validator("StructurePayload")
    job_spec_validator = _load_payload_validator("JobSpecPayload")

    sections = manifest.get("sections", [])
    seen_ids: set[str] = set()
    section_ids: set[str] = {s.get("id") for s in sections if isinstance(s, dict)}
    declared_ext = manifest.get("extensions", {})

    for s in sections:
        sid = s.get("id", "<no-id>")
        kind = s.get("kind", "<no-kind>")
        if sid in seen_ids:
            errors.append(f"duplicate section id {sid!r}")
        seen_ids.add(sid)

        if kind not in _CANONICAL_KINDS and not str(kind).startswith("x_"):
            errors.append(f"section {sid!r}: unknown non-vendor kind {kind!r}")

        # critical governance (spec § 7.4).
        if s.get("critical") and str(kind).startswith("x_"):
            vendor = str(kind).split(".", 1)[0]
            if vendor not in declared_ext:
                errors.append(f"section {sid!r} is critical but its namespace "
                              f"{vendor!r} is not declared in root extensions")

        # Members.
        for role, m in s.get("members", {}).items():
            if not isinstance(m, dict) or "path" not in m:
                errors.append(f"section {sid!r} member {role!r}: malformed spec")
                continue
            mpath = m["path"]
            if ".." in mpath.split("/") or mpath.startswith("/"):
                errors.append(f"member {mpath!r}: illegal path")
            if mpath not in names:
                errors.append(f"member {mpath!r} declared but not in archive")
                continue
            raw = zf.read(mpath)
            if "sha256" in m and hashlib.sha256(raw).hexdigest() != m["sha256"]:
                errors.append(f"member {mpath!r}: sha256 mismatch")
            fmt = m.get("format")
            if fmt == "json":
                try:
                    doc = json.loads(raw)
                except Exception as exc:
                    errors.append(f"member {mpath!r}: not valid JSON ({exc})")
                else:
                    if kind == "structure" and role == "structure":
                        errors.extend(_structure_payload_errors(sid, doc))
                        if payload_validator is not None:
                            for err in payload_validator.iter_errors(doc):
                                loc = "/".join(str(p) for p in err.path)
                                errors.append(
                                    f"schema: {mpath}: {loc}: {err.message}")
                    if kind == "job.spec" and role == "spec":
                        if job_spec_validator is not None:
                            for err in job_spec_validator.iter_errors(doc):
                                loc = "/".join(str(p) for p in err.path)
                                errors.append(
                                    f"schema: {mpath}: {loc}: {err.message}")
            elif fmt == "binary" and "dtype" in m:
                itemsize = _DTYPE_ITEMSIZE.get(m["dtype"])
                if itemsize is None:
                    errors.append(f"member {mpath!r}: bad dtype {m['dtype']!r}")
                else:
                    n = 1
                    for d in m.get("shape", []):
                        n *= int(d)
                    if len(raw) != itemsize * n:
                        errors.append(
                            f"member {mpath!r}: byte length {len(raw)} != "
                            f"itemsize*prod(shape) {itemsize * n}")
            if kind == "run.record" and role in ("input", "log"):
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    errors.append(f"member {mpath!r}: run.record {role} "
                                  f"must decode as UTF-8 ({exc})")

        # Cross-references.
        if kind == "volume.difference":
            for op in ("operand_a", "operand_b"):
                ref = s.get(op)
                if ref is not None and ref not in section_ids:
                    errors.append(f"section {sid!r}: {op} {ref!r} does not resolve")
        if kind == "reaction.waypoints":
            ref = s.get("trajectory_ref")
            if ref not in section_ids:
                errors.append(f"section {sid!r}: trajectory_ref {ref!r} does not "
                              f"resolve")
        if kind == "run.record":
            fspec = s.get("members", {}).get("files")
            if isinstance(fspec, dict) and fspec.get("path") in names:
                try:
                    fdoc = json.loads(zf.read(fspec["path"]))
                except Exception:
                    fdoc = None  # malformed JSON already reported above
                if isinstance(fdoc, dict):
                    for frole in fdoc:
                        if frole not in s.get("members", {}):
                            errors.append(
                                f"section {sid!r}: files index names role "
                                f"{frole!r} with no matching member")

    zf.close()
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "n_sections": len(sections)}


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python qvf_reader.py FILE.qvf", file=sys.stderr)
        return 2
    report = validate_qvf(argv[1])
    print(f"QVF validation: {argv[1]}")
    print(f"  sections: {report['n_sections']}")
    for w in report["warnings"]:
        print(f"  warning: {w}")
    for e in report["errors"]:
        print(f"  ERROR: {e}")
    print("  OK" if report["ok"] else "  FAILED")
    return 0 if report["ok"] else 1


def _main_entrypoint() -> int:
    """Console-script entry point (`qvf-validate FILE.qvf`)."""
    return _main(sys.argv)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
