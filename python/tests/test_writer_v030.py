"""Writer access to the already-released v0.3.0 contract."""
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf_writer import QvfWriter
from qvf_reader import QvfReader, validate_qvf

def archive_contents(w):
    # ZIP header timestamps can cross a two-second boundary between writes.
    # Compare the complete entry inventory and payloads, including manifest.
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(w.to_bytes())) as z:
        return [(entry.filename, z.read(entry)) for entry in z.infolist()]


def writer():
    return QvfWriter("test", "1", "writer contract", auto_metadata=False)

@pytest.mark.parametrize("values", [{}, {"basis": None, "functional": None},
                                    {"basis": "", "functional": ""},
                                    {"basis": "sto-3g", "functional": "pbe"}])
def test_job_choices(tmp_path, values):
    w = writer()
    w.add_job_spec(job_type="molecular", **values)
    path = tmp_path / "job.qvf"
    w.write(path)
    assert validate_qvf(str(path))["ok"]
    with QvfReader(str(path)) as r:
        payload = r.read_json(r.sections[0]["members"]["spec"])
    assert payload == {"job_type": "molecular", **values}

@pytest.mark.parametrize("field", ["basis", "functional"])
@pytest.mark.parametrize("value", [1, False, [], {}])
def test_invalid_job_choice_is_atomic(field, value):
    w = writer()
    before = archive_contents(w)
    with pytest.raises(ValueError):
        w.add_job_spec(job_type="molecular", **{field: value})
    assert archive_contents(w) == before

@pytest.mark.parametrize("basis", [None, "minao", "mini"])
def test_localization_reference_basis(tmp_path, basis):
    w = writer()
    w.add_structure([{"symbol": "H", "position": [0, 0, 0]}])
    w.add_wavefunction_gto([{"center": 0, "l": 0, "exponents": [1.0], "coefficients": [1.0]}],
                          mo_coefficients=np.eye(1), orbital_kind="iao",
                          localization_reference_basis=basis)
    path = tmp_path / "iao.qvf"
    w.write(path)
    assert validate_qvf(str(path))["ok"]
    with QvfReader(str(path)) as r:
        payload = r.read_json(r.sections[1]["members"]["mo_metadata"])
    assert ("localization_reference_basis" in payload) == (basis is not None)
    if basis is not None:
        assert payload["localization_reference_basis"] == basis

@pytest.mark.parametrize("basis", ["", 3, False])
def test_invalid_reference_basis_is_atomic(basis):
    w = writer()
    before = archive_contents(w)
    with pytest.raises(ValueError):
        w.add_wavefunction_gto([], mo_coefficients=np.zeros((0, 0)),
                              localization_reference_basis=basis)
    assert archive_contents(w) == before


def test_every_section_adder_rejects_ids_without_orphans(monkeypatch):
    """Exercise real valid calls from the complete writer example, with bad IDs.

    Comparing complete ZIP contents catches pending payload entries as well as
    manifest mutations. Existing add_density/add_orbital convenience calls
    delegate to the checked add_volume method.
    """
    import functools
    import inspect
    from test_reference_writer import _every_option_writer
    checked = set()
    for name, fn in list(vars(QvfWriter).items()):
        if not name.startswith("add_") or not inspect.isfunction(fn):
            continue
        sig = inspect.signature(fn)
        if "section_id" not in sig.parameters:
            continue
        def wrap(name=name, fn=fn, sig=sig):
            @functools.wraps(fn)
            def guarded(self, *args, **kwargs):
                bad_ids = ["invalid/id", "bad\n", "camera", "", None, 42]
                # None is the documented automatic-id sentinel on these APIs.
                if sig.parameters["section_id"].default is None:
                    bad_ids.remove(None)
                if self._ids:
                    bad_ids.append(next(iter(self._ids)))
                for bad in bad_ids:
                    bound = sig.bind(self, *args, **kwargs)
                    bound.arguments["section_id"] = bad
                    before = archive_contents(self)
                    with pytest.raises(ValueError):
                        fn(*bound.args, **bound.kwargs)
                    assert archive_contents(self) == before, (name, bad)
                checked.add(name)
                return fn(self, *args, **kwargs)
            return guarded
        monkeypatch.setattr(QvfWriter, name, wrap())
    _every_option_writer()
    assert len(checked) >= 30


def test_duplicate_automatic_id_is_atomic():
    w = writer()
    w.add_vendor_section("x_test.data", json_members={"first": {}})
    before = archive_contents(w)
    with pytest.raises(ValueError, match="duplicate section id"):
        w.add_vendor_section("x_test.data", json_members={"second": {}})
    assert archive_contents(w) == before
