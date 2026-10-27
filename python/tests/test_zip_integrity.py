"""Highly compressible scientific members remain valid; ZIP integrity does not."""

import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf_reader import validate_qvf
from qvf_writer import QvfWriter


@pytest.fixture(params=["python", "cpp"])
def validate(request):
    if request.param == "python":
        def run(path):
            report = validate_qvf(path)
            return report["ok"], repr(report["findings"])
        return run
    executable = os.environ.get("QVF_CPP_READER")
    if not executable:
        pytest.skip("set QVF_CPP_READER to the compiled read_qvf executable")

    def run(path):
        result = subprocess.run([executable, str(path)], capture_output=True,
                                text=True, timeout=30)
        return result.returncode == 0, result.stdout + result.stderr
    return run


def test_reference_writer_zero_spin_density(tmp_path, validate):
    writer = QvfWriter(program="test", version="1", calculation="spin")
    writer.add_structure([{"symbol": "He", "position": [0, 0, 0],
                           "atomic_number": 2}])
    writer.add_volume("volume.spin", np.zeros((64, 64, 64), dtype=np.float64),
                      [0, 0, 0], np.eye(3), dtype="float64")
    path = writer.write(str(tmp_path / "zero-spin.qvf"))
    with zipfile.ZipFile(path) as archive:
        member = next(info for info in archive.infolist()
                      if info.file_size == 64 ** 3 * 8)
        assert member.file_size / member.compress_size > 1000
    ok, output = validate(path)
    assert ok, output


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_crc_is_checked_without_member_sha256(tmp_path, validate, method):
    path = tmp_path / "bad-crc.qvf"
    manifest = {"qvf_version": 1,
                "source": {"program": "test", "version": "1", "calculation": "crc"},
                "sections": [{"id": "data", "kind": "x_test.data", "members": {
                    "data": {"path": "data.bin", "format": "binary",
                             "dtype": "uint8", "shape": [4096], "size": 4096}}}]}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data.bin", bytes(4096), compress_type=method)
        archive.writestr("manifest.json", json.dumps(manifest))
    raw = bytearray(path.read_bytes())
    # Corrupt only the advertised checksum, leaving valid payload and sizes.
    for signature, offset in ((b"PK\x03\x04", 14), (b"PK\x01\x02", 16)):
        at = raw.index(signature)
        struct.pack_into("<I", raw, at + offset,
                         struct.unpack_from("<I", raw, at + offset)[0] ^ 1)
    path.write_bytes(raw)
    ok, output = validate(path)
    assert not ok, output
    assert "E_ZIP_UNREADABLE" in output, output
