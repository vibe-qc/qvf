"""Explicit-output archive operations shared by the QVF command line."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from itertools import zip_longest
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import uuid
import zipfile

from .reader import Reader
from .editor import Editor
from ._container import DTYPES, iter_member, stream_member


@contextmanager
def _new_output(destination):
    """Publish a completed sibling temporary file without replacing any path."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"output already exists: {destination}")
    fd, temporary = tempfile.mkstemp(prefix=".qvf-output-", dir=destination.parent)
    os.close(fd)
    try:
        yield Path(temporary)
        # link() is atomic and fails if a concurrent writer claimed the name.
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)


def extract(source, section, role, destination):
    """Extract one declared member, checking its size, CRC and SHA-256."""
    with Reader(source) as reader, _new_output(destination) as temporary:
        member = reader._member(section, role)
        with temporary.open("wb") as sink:
            stream_member(reader._zip, member, reader.limits, sink.write)


def repack(source, destination, *, compression=None):
    """Repack to a new output; the command never overwrites the input."""
    with _new_output(destination) as temporary:
        Editor.repack(source, temporary, compression=compression)


def diff(left, right, *, atol=0.0, rtol=0.0, ignore_metadata=False,
         max_differences=20):
    """Compare logical manifests and decoded payloads, ignoring ZIP layout.

    Member paths, sizes and hashes are transport details: contents are checked
    separately and checksums are always verified. Tolerances apply to floating
    numbers; integer and opaque payloads compare exactly. NaNs differ.
    """
    if not all(math.isfinite(v) and v >= 0 for v in (atol, rtol)):
        raise ValueError("tolerances must be finite and non-negative")
    if not isinstance(max_differences, int) or max_differences < 1:
        raise ValueError("max_differences must be positive")
    differences = []
    count = 0

    def record(where, reason):
        nonlocal count
        count += 1
        if len(differences) < max_differences:
            differences.append({"where": where, "message": reason})

    def compare(a, b, where):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                location = where + "/" + str(key).replace("~", "~0").replace("/", "~1")
                if key not in a or key not in b:
                    record(location, "missing from left" if key not in a else "missing from right")
                else:
                    compare(a[key], b[key], location)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                record(where, "array lengths differ")
            for i, (av, bv) in enumerate(zip(a, b)):
                compare(av, bv, f"{where}/{i}")
        elif (isinstance(a, (int, float)) and not isinstance(a, bool)
              and isinstance(b, (int, float)) and not isinstance(b, bool)):
            if isinstance(a, int) and isinstance(b, int):
                equal = a == b
            else:
                try:
                    equal = math.isclose(a, b, abs_tol=atol, rel_tol=rtol)
                except OverflowError:
                    equal = False
            if not equal:
                record(where, "numeric values differ")
        elif type(a) is not type(b) or a != b:
            record(where, "values differ")

    def logical(manifest):
        manifest = deepcopy(manifest)
        if ignore_metadata:
            manifest.pop("metadata", None)
        for section in manifest.get("sections", []):
            for member in section.get("members", {}).values():
                for key in ("path", "size", "sha256"):
                    member.pop(key, None)
        return manifest

    with Reader(left) as a, Reader(right) as b:
        compare(logical(a.raw_manifest), logical(b.raw_manifest), "manifest")
        for section in a.sections:
            other = b.section(section.id)
            if other is None:
                continue
            for role, member in (section.members or {}).items():
                counterpart = (other.members or {}).get(role)
                if counterpart is None:
                    continue
                where = f"{section.id}/{role}"
                ma, mb = member.to_json(), counterpart.to_json()
                if ma.get("format") == mb.get("format") == "json":
                    compare(a.json(section, role), b.json(other, role), where)
                    continue
                dtype = ma.get("dtype")
                numeric = (ma.get("format") == mb.get("format") == "binary"
                           and dtype == mb.get("dtype") and dtype in DTYPES
                           and ma.get("shape") == mb.get("shape"))
                chunks_a = iter_member(a._zip, ma, a.limits)
                chunks_b = iter_member(b._zip, mb, b.limits)
                index = 0
                for raw_a, raw_b in zip_longest(chunks_a, chunks_b, fillvalue=b""):
                    if numeric and dtype.startswith("float") and len(raw_a) == len(raw_b):
                        fmt = "<" + DTYPES[dtype][1]
                        for (av,), (bv,) in zip(struct.iter_unpack(fmt, raw_a), struct.iter_unpack(fmt, raw_b)):
                            if not math.isclose(av, bv, abs_tol=atol, rel_tol=rtol):
                                record(f"{where}[{index}]", "numeric values differ")
                            index += 1
                    elif raw_a != raw_b:
                        record(where, "raw payload chunks differ")
    return {"equal": count == 0, "difference_count": count,
            "differences": differences, "truncated": count > len(differences)}


def scrub(source, destination=None, *, patterns=(), replacement="[redacted]",
          dry_run=False):
    """Report/remove deprecated hostname and author contact fields.

    Caller-supplied regular expressions also redact run.record command,
    UTF-8 input/log/attachments and string values in the files index. Binary
    attachments and unselected content are reported, never silently certified
    safe. No built-in personal-name or site-specific scanner policy is used.
    A new archive is repacked, with a fresh UUID and derived_from provenance.
    """
    if not dry_run and destination is None:
        raise ValueError("scrub requires an explicit output or dry_run=True")
    expressions = [re.compile(pattern) for pattern in patterns]
    changes, skipped = [], []

    def redact(value, where):
        if isinstance(value, dict):
            return {key: redact(item, f"{where}/{key}") for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item, f"{where}/{i}") for i, item in enumerate(value)]
        if isinstance(value, str):
            total = 0
            for pattern in expressions:
                value, n = pattern.subn(lambda _: replacement, value)
                total += n
            if total:
                changes.append({"where": where, "action": "redact", "matches": total})
        return value

    with Reader(source) as reader, tempfile.TemporaryDirectory(prefix="qvf-scrub-") as scratch:
        manifest = deepcopy(reader.raw_manifest)
        provenance = manifest.get("provenance", {})
        if "hostname" in provenance:
            del provenance["hostname"]
            changes.append({"where": "/provenance/hostname", "action": "remove"})
        metadata = manifest.setdefault("metadata", {})
        for i, author in enumerate(metadata.get("authors", [])):
            for field in ("email", "affiliation"):
                if field in author:
                    del author[field]
                    changes.append({"where": f"/metadata/authors/{i}/{field}", "action": "remove"})
        members, replacements, uses = {}, {}, {}
        for section in manifest.get("sections", []):
            for member in section.get("members", {}).values():
                path = member["path"]
                if path in members and members[path] != member:
                    raise ValueError("inconsistent declarations for a shared member")
                members[path] = member
                uses[path] = uses.get(path, 0) + 1
        for section in manifest.get("sections", []):
            if section.get("kind") != "run.record":
                continue
            sid = section["id"]
            if "command" in section:
                section["command"] = redact(section["command"], f"{sid}/command")
            for role, member in section.get("members", {}).items():
                path = member["path"]
                if not expressions:
                    skipped.append({"where": f"{sid}/{role}", "reason": "no patterns selected"})
                    continue
                if role == "files" and member.get("format") == "json":
                    original = reader.json(sid, role)
                    result = redact(original, f"{sid}/{role}")
                    data = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                    changed = result != original
                elif role in ("input", "log") or role.startswith("attachment."):
                    # Text is bounded by the JSON/text cap before materializing.
                    if reader._zip.getinfo(path).file_size > reader.limits.max_json_bytes:
                        raise ValueError(f"text member exceeds scrub cap: {path!r}")
                    raw = reader.read_member(member)
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        skipped.append({"where": f"{sid}/{role}", "reason": "non-UTF-8 attachment"})
                        if role in ("input", "log"):
                            raise ValueError(f"E_UTF8: {path!r}") from None
                        continue
                    result = redact(text, f"{sid}/{role}")
                    data = result.encode("utf-8")
                    changed = data != raw
                else:
                    skipped.append({"where": f"{sid}/{role}", "reason": "outside text scrub scope"})
                    continue
                if changed:
                    if uses[path] > 1:
                        raise ValueError("cannot scrub a shared member; separate its declarations first")
                    staged = Path(scratch) / str(len(replacements))
                    staged.write_bytes(data)
                    replacements[path] = staged
                    member["size"] = len(data)
                    member["sha256"] = hashlib.sha256(data).hexdigest()
        changes.append({"where": "/metadata", "action": "new UUID and derivation on write"})
        report = {"dry_run": dry_run, "changes": changes, "skipped": skipped,
                  "scope": "hostname, author contacts, selected run.record text; other content unchanged"}
        if dry_run:
            return report
        previous = metadata.get("uuid")
        if previous:
            metadata.setdefault("derived_from", []).append(previous)
        metadata["uuid"] = str(uuid.uuid4())
        metadata["created_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        metadata.pop("modified_utc", None)
        with _new_output(destination) as temporary:
            with zipfile.ZipFile(temporary, "w", allowZip64=True) as output:
                for path, member in members.items():
                    if path in replacements:
                        target = zipfile.ZipInfo(path)
                        target.compress_type = zipfile.ZIP_DEFLATED
                        target.file_size = member["size"]
                        with output.open(target, "w") as sink, replacements[path].open("rb") as payload:
                            while True:
                                chunk = payload.read(1 << 20)
                                if not chunk:
                                    break
                                sink.write(chunk)
                    else:
                        info = reader._zip.getinfo(path)
                        target = zipfile.ZipInfo(path, date_time=info.date_time)
                        target.compress_type = info.compress_type
                        target.file_size = info.file_size
                        with output.open(target, "w") as sink:
                            stream_member(reader._zip, member, reader.limits, sink.write)
                output.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode(),
                                compress_type=zipfile.ZIP_STORED)
        return report
