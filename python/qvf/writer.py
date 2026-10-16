"""Streaming QVF writer: members are written immediately, manifest last."""
from __future__ import annotations

import copy
import hashlib
import os
import re
import sys
import warnings
import zipfile

from . import _kinds, model
from ._container import DTYPES, tensor_size
from ._legacy_writer import QvfWriter, _json_bytes, _MEDIA_TYPE_RE
from . import _legacy_writer as _legacy


class MemberSink:
    """One declared binary member; context exit verifies its complete size.

    ``write`` takes contiguous buffer-protocol objects, interpreted in the
    declared ``byte_order``. Partial elements may cross writes. At most one
    element and one converted slab are retained between writes.
    """
    def __init__(self, writer, section, role, path, dtype, shape, byte_order):
        self.writer, self.section, self.role = writer, section, role
        self.path, self.dtype, self.shape = path, dtype, tuple(shape)
        self.expected = tensor_size(dtype, self.shape)
        if byte_order not in ("little", "big", "native"):
            raise ValueError("byte_order must be little, big, or native")
        self.byte_order = sys.byteorder if byte_order == "native" else byte_order
        self._itemsize = DTYPES[dtype][0]
        self._pending = b""
        self._size = 0
        self._hash = hashlib.sha256()
        self.closed = False
        self.member = None
        info = zipfile.ZipInfo(path)
        info.compress_type = writer._compression
        info.file_size = self.expected
        self._entry = writer._zip.open(info, "w", force_zip64=writer._force_zip64)

    def write(self, data):
        if self.closed:
            raise ValueError("member sink is closed")
        view = memoryview(data)
        if not view.c_contiguous:
            raise ValueError("binary slabs must be C-contiguous")
        view = view.cast("B")
        size = len(view)
        if self._size + len(self._pending) + size > self.expected:
            self.writer._failed = True
            raise ValueError("E_BINARY_SIZE: binary member exceeds declared shape")
        if self.byte_order == "big" and self._itemsize > 1:
            import array
            raw = self._pending + view.tobytes()
            boundary = len(raw) // self._itemsize * self._itemsize
            self._pending = raw[boundary:]
            swapped = array.array({2: "H", 4: "I", 8: "Q"}[self._itemsize])
            if swapped.itemsize != self._itemsize:
                raise RuntimeError("host array integer widths do not support this dtype")
            swapped.frombytes(memoryview(raw)[:boundary])
            swapped.byteswap()
            view = memoryview(swapped).cast("B")
        try:
            self._entry.write(view)
        except BaseException:
            self.writer._failed = True
            raise
        self._size += len(view)
        self._hash.update(view)
        return size

    def close(self):
        if self.closed:
            return model.MemberSpec.from_json(self.member) if self.member is not None else None
        self.closed = True
        try:
            self._entry.close()
            if self._size != self.expected or self._pending:
                self.writer._failed = True
                raise ValueError(f"E_BINARY_SIZE: wrote {self._size} bytes, expected {self.expected}")
            self.member = {"path": self.path, "format": "binary", "dtype": self.dtype,
                           "shape": list(self.shape), "sha256": self._hash.hexdigest(),
                           "size": self._size}
            self.section["members"][self.role] = self.member
            return model.MemberSpec.from_json(self.member)
        except BaseException:
            self.writer._failed = True
            raise
        finally:
            self.writer._active = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.writer._failed = True
            self._entry.close()
            self.closed = True
            self.writer._active = None
        else:
            self.close()


class Writer(QvfWriter):
    """Write to a path or binary sink, retaining no previously written payload.

    All established ``add_*`` conveniences remain available. Numeric array
    conveniences use optional NumPy. ``add_section``, ``add_json``,
    ``add_binary`` and ``begin_binary`` are standard-library-only paths.
    Use a context or call ``finish`` once. A non-seekable sink emits standard
    ZIP data descriptors; large members use ZIP64 automatically.
    """
    def __init__(self, target, program=None, version=None, calculation="", *,
                 source=None, auto_metadata=True, compression=zipfile.ZIP_DEFLATED,
                 force_zip64=False, _base=None):
        if source is not None:
            if isinstance(source, model.Source):
                program, version, calculation = source.program, source.version, source.calculation
            else:
                program, version = source["program"], source["version"]
                calculation = source.get("calculation", "")
        super().__init__(program, version, calculation, auto_metadata=auto_metadata)
        self._target = target
        self._compression = compression
        self._force_zip64 = force_zip64
        self._active = None
        self._closed = False
        self._failed = False
        self._original_paths = set()
        if _base is not None:
            # The editor parsed the latest manifest without reading payloads.
            for name in ("_source", "_sections", "_files", "_stored", "_ids", "_root",
                         "_auto_values", "_update_root", "_update_loaded_modified"):
                setattr(self, name, copy.deepcopy(getattr(_base, name)))
            self.auto_metadata = False
            self._original_paths = set(self._files)
            self._update_path = os.fspath(target)
        self._zip = zipfile.ZipFile(target, "a" if _base is not None else "w",
                                    compression=compression, allowZip64=True)

    def _ensure_open(self):
        if self._closed:
            raise ValueError("writer is closed")
        if self._failed:
            raise ValueError("writer cannot finish after a failed member write")
        if self._active is not None:
            raise ValueError("finish the active binary member first")

    def _path(self, path):
        self._ensure_open()
        if (not isinstance(path, str) or not path or path == "manifest.json"
                or ".." in path.split("/") or path.startswith("/") or "\\" in path
                or "\0" in path or _legacy._DRIVE_RE.match(path)):
            raise ValueError(f"illegal member path {path!r}")
        if path in self._files:
            if path not in self._original_paths:
                raise ValueError(f"duplicate member path {path!r}")
            head, slash, tail = path.rpartition("/")
            stem, dot, suffix = tail.partition(".")
            n = 2
            while f"{head}{slash}{stem}.{n}{dot}{suffix}" in self._files:
                n += 1
            path = f"{head}{slash}{stem}.{n}{dot}{suffix}"
        self._files[path] = None  # names only; payload bytes are never retained
        return path

    def _write_file(self, path, data, compression):
        path = self._path(path)
        try:
            _legacy._zip_write(self._zip, path, data, compression, self._force_zip64)
        except BaseException:
            self._failed = True
            raise
        return path

    def _add_file(self, path, data):
        return self._write_file(path, data, self._compression)

    def _opaque_member(self, path, data, media_type=None):
        if media_type is not None and not (isinstance(media_type, str)
                                           and _MEDIA_TYPE_RE.fullmatch(media_type)):
            raise ValueError(f"invalid media type {media_type!r}")
        method = (zipfile.ZIP_STORED if media_type in
                  ("image/png", "image/jpeg", "image/svg+xml") else self._compression)
        path = self._write_file(path, data, method)
        result = {"path": path, "format": "binary", "sha256": hashlib.sha256(data).hexdigest(),
                  "size": len(data)}
        if media_type is not None:
            result["media_type"] = media_type
        return result

    @staticmethod
    def _lattice_value(value, *, columns=False):
        if isinstance(value, model.Lattice):
            return value.columns_bohr() if columns else value.rows_angstrom()
        if isinstance(value, (list, tuple)) and any(isinstance(v, model.Lattice) for v in value):
            if not all(isinstance(v, model.Lattice) for v in value):
                raise ValueError("a lattice sequence must contain only Lattice objects")
            return [Writer._lattice_value(v, columns=columns) for v in value]
        return value

    def add_structure(self, atoms, **kwargs):
        if "lattice_vectors" in kwargs:
            kwargs["lattice_vectors"] = self._lattice_value(kwargs["lattice_vectors"])
        return super().add_structure(atoms, **kwargs)

    def add_trajectory(self, metadata, coords, **kwargs):
        if "lattice" in kwargs:
            kwargs["lattice"] = self._lattice_value(kwargs["lattice"])
        return super().add_trajectory(metadata, coords, **kwargs)

    def add_reaction_path(self, metadata, coords, **kwargs):
        if "lattice" in kwargs:
            kwargs["lattice"] = self._lattice_value(kwargs["lattice"], columns=True)
        return super().add_reaction_path(metadata, coords, **kwargs)

    def add_section(self, section):
        """Add a typed Section (or mapping); attach payloads through member APIs.

        Members already present must refer to bytes written by this writer or
        retained by an Editor. This prevents a manifest from silently naming a
        missing payload.
        """
        self._ensure_open()
        value = section.to_json() if isinstance(section, model.Section) else copy.deepcopy(dict(section))
        sid, kind = value.get("id"), value.get("kind")
        self._check_new_id(sid)
        if not isinstance(kind, str) or (kind not in _kinds.CANONICAL_KINDS and
                                       not _legacy._VENDOR_RE.fullmatch(kind)):
            raise ValueError(f"unknown section kind {kind!r}")
        members = value.setdefault("members", {})
        if not isinstance(members, dict):
            raise TypeError("members must be a mapping")
        for member in members.values():
            if not isinstance(member, dict) or member.get("path") not in self._files:
                raise ValueError("section member does not name an existing payload")
        self._reserve_id(sid)
        return self._push(value)

    def add(self, section):
        """Add a Section or a kind object implementing ``to_writer(writer)``."""
        if hasattr(section, "to_writer"):
            return section.to_writer(self)
        return self.add_section(section)

    def _member_target(self, section_id, role, format, dtype=None, shape=None):
        self._ensure_open()
        if not isinstance(role, str) or not role:
            raise ValueError("member role must be a nonempty string")
        section = next((s for s in self._sections if s.get("id") == section_id), None)
        if section is None:
            raise KeyError(section_id)
        if role in section["members"]:
            raise ValueError(f"duplicate member role {role!r}")
        kind_info = _kinds.kind_info(section["kind"])
        if kind_info is not None:
            info = kind_info.role(role)
            if info is None:
                info = next((r for r in kind_info.roles if r.pattern and re.fullmatch(r.role, role)), None)
            if info is None and not kind_info.allow_extra_members:
                raise ValueError(f"kind {section['kind']!r} has no role {role!r}")
            if info is not None:
                if info.format != format:
                    raise ValueError(f"role {role!r} requires {info.format}")
                if dtype is not None and info.dtypes and dtype not in info.dtypes:
                    raise ValueError(f"role {role!r} does not accept dtype {dtype!r}")
                if shape is not None and ((info.min_rank is not None and len(shape) < info.min_rank)
                                          or (info.max_rank is not None and len(shape) > info.max_rank)):
                    raise ValueError(f"role {role!r} does not accept rank {len(shape)}")
        return section

    def add_json(self, section_id, role, payload, *, path=None):
        section = self._member_target(section_id, role, "json")
        member = self._json_member(path or f"{section_id}/{role}.json", payload)
        section["members"][role] = member
        return model.MemberSpec.from_json(member)

    def add_opaque(self, section_id, role, data, *, path=None, media_type=None):
        section = self._member_target(section_id, role, "opaque")
        member = self._opaque_member(path or f"{section_id}/{role}.bin", data, media_type)
        section["members"][role] = member
        return model.MemberSpec.from_json(member)

    def begin_binary(self, section_id, role, dtype, shape, *, path=None, byte_order="little"):
        shape = tuple(shape)
        tensor_size(dtype, shape)
        if byte_order not in ("little", "big", "native"):
            raise ValueError("byte_order must be little, big, or native")
        section = self._member_target(section_id, role, "binary", dtype, shape)
        path = self._path(path or f"{section_id}/{role}.bin")
        try:
            sink = MemberSink(self, section, role, path, dtype, shape, byte_order)
        except BaseException:
            self._failed = True
            raise
        self._active = sink
        return sink

    def add_binary(self, section_id, role, data, dtype, shape, *, path=None, byte_order="little"):
        """Write a contiguous raw buffer with explicit dtype, shape and byte order."""
        shape = tuple(shape)
        expected = tensor_size(dtype, shape)
        view = memoryview(data)
        if not view.c_contiguous or view.nbytes != expected:
            raise ValueError("E_BINARY_SIZE: buffer does not match the declared shape")
        with self.begin_binary(section_id, role, dtype, shape, path=path, byte_order=byte_order) as sink:
            sink.write(view)
        return model.MemberSpec.from_json(sink.member)

    def remove_section(self, section_id):
        self._ensure_open()
        section = next((s for s in self._sections if s.get("id") == section_id), None)
        if self._update_path is not None and section and section.get("kind") == "job.spec":
            raise ValueError("updates preserve job.spec sections verbatim (spec § 5.9)")
        return super().remove_section(section_id)

    def finish(self):
        if self._closed:
            return
        self._ensure_open()
        try:
            raw = _json_bytes(self._final_manifest())
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Duplicate name: 'manifest.json'")
                _legacy._zip_write(self._zip, zipfile.ZipInfo("manifest.json"), raw,
                                   zipfile.ZIP_STORED, self._force_zip64)
        except BaseException:
            self._failed = True
            raise
        finally:
            self._zip.close()
            self._closed = True

    def close(self):
        self.finish()

    def abort(self):
        """Close without a new manifest after a failed operation."""
        if self._active is not None:
            self._active._entry.close()
            self._active.closed = True
            self._active = None
        self._zip.close()
        self._closed = True
        self._failed = True

    def to_bytes(self, **kwargs):
        raise TypeError("streaming Writer already writes its target; use io.BytesIO and finish()")

    def write(self, *args, **kwargs):
        raise TypeError("streaming Writer already writes its target; call finish()")

    @classmethod
    def open_for_update(cls, path):
        raise TypeError("use Editor.open(path) for streaming updates")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.abort()
        else:
            try:
                self.finish()
            except BaseException:
                self.abort()
                raise
