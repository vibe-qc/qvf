"""Prepare an explicit single-job request without discarding its drawing."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import shutil
import uuid
import zipfile

from ._container import stream_member
from ._legacy_writer import QvfWriter, _UNSET, _ELEMENT_SYMBOLS, _charge_multiplicity_problem
from .operations import _new_output
from .reader import Reader


def _name(value, field):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(f"{field} must be a non-empty name without surrounding whitespace or controls")
    return value


def _validated(reader, label):
    report = reader.validate()
    if not report["ok"]:
        raise ValueError(f"{label} failed validation: " + "; ".join(report["errors"]))
    if any(f["code"] == "W_SCHEMA_SKIPPED" for f in report["findings"]):
        raise RuntimeError("prepare_job requires full schema validation; install qvf-writer[validate]")
    return report["findings"]


def prepare_job(source, destination, *, job_type, method, task,
                basis=_UNSET, functional=_UNSET, charge=0, multiplicity=1,
                kpoints=None, limits=None):
    """Create a validated pending request at a new path, preserving the source.

    Require one geometry plus optional bonds, preview, citations and opaque
    vendor sections; refuse existing jobs, runs and canonical results. Every
    source section and non-manifest member is retained, with declared hashes
    unchanged. Superseded manifests are consolidated into one new manifest.
    A fresh UUID links back to the source UUID, when present.

    ``job_type``, ``method`` and one ``task`` (single_point/optimize/hessian)
    are explicit. Charge/multiplicity use job.spec's 0/1 defaults, never the
    geometry's values; conflicting identity is refused. Omitted basis and
    functional stay absent; ``None`` writes explicit null. Method/basis names
    are producer-neutral; the runner decides which scientific methods it
    supports. Engine options are outside this helper's scope.

    Requires the ``validate`` extra, not NumPy. No calculation or submission
    occurs. The returned report includes source and output findings.
    """
    if job_type not in ("molecular", "periodic"):
        raise ValueError("job_type must be molecular or periodic")
    _name(method, "method")
    if task not in ("single_point", "optimize", "hessian"):
        raise ValueError("task must be single_point, optimize or hessian")
    for field, value in (("basis", basis), ("functional", functional)):
        if value is not _UNSET and value is not None:
            _name(value, field)
    if type(charge) is not int or type(multiplicity) is not int or multiplicity < 1:
        raise ValueError("charge must be an integer and multiplicity an integer >= 1")
    if kpoints is not None:
        if (job_type != "periodic" or not isinstance(kpoints, (list, tuple))
                or len(kpoints) != 3 or any(type(n) is not int or n < 1 for n in kpoints)):
            raise ValueError("kpoints must be three positive integers for a periodic job")

    with Reader(source, limits=limits) as reader:
        source_findings = _validated(reader, "source")
        manifest = deepcopy(reader.raw_manifest)
        # Structural validation can establish that a critical vendor namespace
        # is declared, but cannot establish that this consumer understands it.
        # Keeping opaque bytes is insufficient when they change interpretation
        # of the geometry or request that we are about to create (spec 7.4).
        for namespace, declaration in manifest.get("extensions", {}).items():
            if declaration.get("critical", False):
                raise ValueError(f"prepare_job refuses unsupported critical extension: {namespace}")
        for section in manifest["sections"]:
            if section.get("critical", False) and section["kind"].startswith("x_"):
                raise ValueError(f"prepare_job refuses unsupported critical section: {section['kind']}")
        # The reader accepts the withdrawn spelling 2; producers write v1.
        manifest["qvf_version"] = 1
        structures = reader.sections_of("structure")
        if len(structures) != 1:
            raise ValueError("prepare_job requires exactly one structure")
        for section in manifest["sections"]:
            kind = section["kind"]
            if kind not in ("structure", "bonds", "preview", "citations") and not kind.startswith("x_"):
                raise ValueError(f"prepare_job refuses existing jobs, runs or non-geometry sections: {kind}")
        if any(key in manifest for key in ("energies", "thermochemistry", "dipole_moment", "constraints")):
            raise ValueError("prepare_job refuses result metadata or calculation constraints")
        provenance = manifest.setdefault("provenance", {})
        if any(key not in ("charge", "multiplicity", "dimensionality") and not key.startswith("x_")
               for key in provenance):
            raise ValueError("prepare_job refuses lifecycle, calculation or unrecognized provenance")
        structure = structures[0]
        payload = reader.json(structure, "structure")
        periodic = any(payload.get("pbc", (False,) * 3))
        if periodic != (job_type == "periodic"):
            raise ValueError("job_type is incompatible with structure periodicity")
        for field, value in (("charge", charge), ("multiplicity", multiplicity)):
            for identity in (structure.to_json(), payload, provenance):
                if field in identity and identity[field] != value:
                    raise ValueError(f"job {field} conflicts with source {field}; supply an explicit matching value")
        atoms = payload["atoms"]
        if not atoms:
            raise ValueError("prepare_job requires a non-empty structure")
        numbers = [a.get("atomic_number", _ELEMENT_SYMBOLS.index(a["symbol"])
                   if a.get("symbol") in _ELEMENT_SYMBOLS else 0) for a in atoms]
        if any(n < 1 for n in numbers):
            raise ValueError("prepare_job requires known atomic numbers, without dummy atoms")
        problem = _charge_multiplicity_problem(sum(numbers), charge, multiplicity)
        if problem:
            raise ValueError(problem)

        # Reuse the established writer's job.spec payload and member contract.
        used_ids = {s["id"] for s in manifest["sections"]}
        paths = set(reader._zip.namelist())
        sid = "job"
        index = 1
        while sid in used_ids or f"{sid}/spec.json" in paths:
            sid = f"job_{index}"
            index += 1
        writer = QvfWriter("qvf", "1", auto_metadata=False)
        writer.add_job_spec(job_type=job_type, method=method, tasks=[task],
                            basis=basis, functional=functional, charge=charge,
                            multiplicity=multiplicity, kpoints=kpoints,
                            structure_ref=structure.id, section_id=sid)
        manifest["sections"].extend(writer.build_manifest()["sections"])
        provenance.update(run_status="pending", charge=charge, multiplicity=multiplicity)
        metadata = manifest.setdefault("metadata", {})
        previous = metadata.get("uuid")
        if previous:
            metadata.setdefault("derived_from", []).append(previous)
        metadata["uuid"] = str(uuid.uuid4())
        metadata["created_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        metadata.pop("modified_utc", None)
        members = {}
        for section in reader.raw_manifest["sections"]:
            for member in section.get("members", {}).values():
                path = member["path"]
                if path in members and members[path] != member:
                    raise ValueError("inconsistent declarations for a shared member")
                members[path] = member
        with _new_output(destination) as temporary:
            with zipfile.ZipFile(temporary, "w", allowZip64=True) as output:
                for info in reader._zip.infolist():
                    if info.filename == "manifest.json":
                        continue
                    target = deepcopy(info)
                    with output.open(target, "w") as sink:
                        if info.filename in members:
                            stream_member(reader._zip, members[info.filename], reader.limits, sink.write)
                        else:
                            # Keep orphan/opaque bytes too; reading to EOF checks CRC.
                            with reader._zip.open(info) as original:
                                shutil.copyfileobj(original, sink, 1 << 20)
                for path, data in writer._files.items():
                    output.writestr(path, data, compress_type=zipfile.ZIP_DEFLATED)
                output.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode(),
                                compress_type=zipfile.ZIP_STORED)
            with Reader(temporary, limits=reader.limits) as prepared:
                findings = _validated(prepared, "prepared job")
        return {"output": str(destination), "job_ref": sid, "structure_ref": structure.id,
                "source_findings": source_findings, "findings": findings}
