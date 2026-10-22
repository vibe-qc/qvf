"""Append QVF updates and repack superseded entries without loading payloads."""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile

from . import _legacy_writer
from .reader import Reader
from .writer import Writer
from ._container import stream_member


class Editor:
    """Update an archive while retaining its job specifications and source.

    ``writer`` has the full streaming Writer API. ``atomic=True`` stages a copy
    beside the target and replaces it only after commit. The default appends
    in place; interrupted updates may leave unreferenced members. Repack drops
    those orphans and superseded manifests.
    """
    def __init__(self, path, *, atomic=False, limits=None,
                 compression=zipfile.ZIP_DEFLATED, force_zip64=False):
        self.path = os.fspath(path)
        self._temporary = None
        self._closed = False
        # Bounds and path checks precede the compatibility loader and any copy.
        with Reader(path, limits=limits):
            pass
        base = _legacy_writer.QvfWriter.open_for_update(self.path)
        target = self.path
        if atomic:
            fd, target = tempfile.mkstemp(prefix=".qvf-update-", suffix=".tmp",
                                          dir=os.path.dirname(os.path.abspath(self.path)))
            os.close(fd)
            self._temporary = target
            try:
                shutil.copy2(self.path, target)
            except BaseException:
                os.unlink(target)
                self._temporary = None
                raise
        try:
            self.writer = Writer(target, source=base._source, auto_metadata=False,
                                 compression=compression, force_zip64=force_zip64, _base=base)
        except BaseException:
            if self._temporary:
                os.unlink(self._temporary)
            raise

    @classmethod
    def open(cls, path, **kwargs):
        return cls(path, **kwargs)

    def remove_section(self, section_id):
        return self.writer.remove_section(section_id)

    def set_run_status(self, status, *, run_id=None):
        """Set the root lifecycle status or one named run.record outcome."""
        self.writer._ensure_open()
        allowed = ("pending", "running", "converged", "failed")
        if status not in allowed or (run_id is not None and status == "pending"):
            raise ValueError(f"invalid run status {status!r}")
        if run_id is None:
            provenance = dict(self.writer._root.get("provenance", {}))
            provenance["run_status"] = status
            self.writer._root["provenance"] = provenance
        else:
            for section in self.writer._sections:
                if section.get("id") == run_id:
                    if section.get("kind") != "run.record":
                        raise ValueError("run_id must name run.record")
                    section["run_status"] = status
                    break
            else:
                raise KeyError(run_id)

    def commit(self):
        if self._closed:
            return self.path
        self.writer.finish()
        if self._temporary:
            os.replace(self._temporary, self.path)
            self._temporary = None
        self._closed = True
        return self.path

    def abort(self):
        if not self._closed:
            self.writer.abort()
            if self._temporary:
                os.unlink(self._temporary)
                self._temporary = None
            self._closed = True

    @staticmethod
    def repack(source, destination, *, compression=None, limits=None):
        """Copy referenced members, then the last manifest, dropping all orphans.

        ``compression=None`` preserves each method; STORE or DEFLATE selects
        a new one. Content hashes are verified while copying bounded chunks.
        Output replacement is atomic, including when both paths are equal.
        """
        if compression not in (None, zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError("compression must be STORE or DEFLATE")
        destination = os.fspath(destination)
        fd, temporary = tempfile.mkstemp(prefix=".qvf-repack-", suffix=".tmp",
                                         dir=os.path.dirname(os.path.abspath(destination)))
        os.close(fd)
        try:
            with Reader(source, limits=limits) as reader:
                members = {}
                for section in reader.sections:
                    for member in (section.members or {}).values():
                        if member.path:
                            value = member.to_json()
                            if member.path in members and members[member.path] != value:
                                raise ValueError("inconsistent declarations for a shared member")
                            members[member.path] = value
                with zipfile.ZipFile(temporary, "w", allowZip64=True) as output:
                    for info in reader._zip.infolist():
                        if info.filename not in members:
                            continue
                        target = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                        target.compress_type = info.compress_type if compression is None else compression
                        target.file_size = info.file_size
                        target.external_attr = info.external_attr
                        with output.open(target, "w") as sink:
                            stream_member(reader._zip, members.pop(info.filename), reader.limits, sink.write)
                    if members:
                        raise ValueError(f"E_MEMBER_MISSING: {sorted(members)!r}")
                    raw = reader._zip.read("manifest.json")
                    output.writestr("manifest.json", raw, compress_type=zipfile.ZIP_STORED)
            os.replace(temporary, destination)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return destination

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.abort()
        else:
            try:
                self.commit()
            except BaseException:
                self.abort()
                raise
