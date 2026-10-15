"""Issue 12: unrestricted NTO writer and validator contract."""
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf_writer import QvfWriter
from qvf_reader import QvfReader, validate_qvf

ROOT = Path(__file__).resolve().parents[2]
SHELLS = [{"center": i, "l": 0, "exponents": [1.0], "coefficients": [1.0]} for i in range(2)]

def archive_contents(w):
    # ZIP header timestamps can cross a two-second boundary between writes.
    # Compare the complete entry inventory and payloads, including manifest.
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(w.to_bytes())) as z:
        return [(entry.filename, z.read(entry)) for entry in z.infolist()]


def writer():
    w = QvfWriter("test", "1", "unrestricted NTO")
    w.add_structure([{"symbol": "H", "position": [0, 0, 0]}, {"symbol": "H", "position": [0, 0, .74]}])
    return w

def add(w, role="hole", alpha=(.55, .15), beta=(.3,), **kwargs):
    params = dict(mo_coefficients_alpha=np.eye(2), mo_coefficients_beta=np.eye(2)[:len(beta)],
                  occupations_alpha=alpha, occupations_beta=beta, orbital_kind="nto",
                  state_ref="es", state_index=1, nto_role=role, section_id="nto_" + role)
    params.update(kwargs)
    return w.add_wavefunction_gto(SHELLS, **params)

@pytest.mark.parametrize("beta,alpha", [((.3,), (.55, .15)), ((), (.8, .2)), ((.3,), (.7, .2)), ((.5,), (.25, .25))])
def test_round_trip(tmp_path, beta, alpha):
    w = writer()
    for role in ("particle", "hole"):
        add(w, role, alpha, beta, n_electrons=2)
    w.add_excited_states([{"index": 1, "excitation_energy": 4., "nto_ref": "nto_hole"}], section_id="es")
    path = tmp_path / "nto.qvf"
    w.write(path)
    report = validate_qvf(str(path))
    assert report["ok"], report["findings"]
    with QvfReader(str(path)) as r:
        for s in r.sections:
            if s["kind"] == "wavefunction.gto":
                m = r.read_json(s["members"]["mo_metadata"])
                assert m["alpha"]["occupations"] == list(alpha)
                assert m["beta"]["occupations"] == list(beta)
                assert m["alpha"]["energies"] == [0., 0.]
                assert m["beta"]["n_mo"] == len(beta)

@pytest.mark.parametrize("change", [
    {"occupations_alpha": [.15, .55]}, {"occupations_beta": [-.3]},
    {"occupations_alpha": [.7]}, {"energies_alpha": [0.]},
    {"occupations_alpha": [float("nan"), .15]},
    {"occupations_beta": [float("inf")]}, {"state_ref": None},
    {"state_index": None}, {"nto_role": None}, {"occupations_beta": None},
])
def test_writer_refuses_without_mutation(change):
    w = writer()
    before = archive_contents(w)
    with pytest.raises(ValueError):
        add(w, **change)
    assert archive_contents(w) == before
    add(w)  # failed operation did not reserve the id

@pytest.mark.parametrize("name", ["nto_unrestricted", "nto_unrestricted_empty_beta", "nto_unrestricted_tddft", "nto_unrestricted_legacy"])
def test_positive_corpus(name):
    report = validate_qvf(str(ROOT / "conformance/corpus" / (name + ".qvf")))
    assert report["ok"], report["findings"]

@pytest.mark.parametrize("defect,code,where", [
    ("rows", "E_MEMBER_MALFORMED", [1, 2]),
    ("weights", "E_MEMBER_MALFORMED", [1, 2]),
    ("order", "E_MEMBER_MALFORMED", [1, 2]),
    ("negative", "E_MEMBER_MALFORMED", [1, 2]),
    ("metadata_rows", "E_MEMBER_MALFORMED", [1]),
    ("energies_rows", "E_MEMBER_MALFORMED", [1]),
    ("partner_missing", "E_REF_UNRESOLVED", [1]),
    ("state", "E_REF_UNRESOLVED", [1, 2]),
    ("missing_role", "E_REF_UNRESOLVED", [2]),
    ("missing_state", "E_PAYLOAD_SCHEMA", [1]),
])
def test_negative_corpus_locations(defect, code, where):
    path = ROOT / "conformance/negative" / ("nto_unrestricted_" + defect + ".qvf")
    report = validate_qvf(str(path))
    assert not report["ok"]
    assert sorted({f["where"] for f in report["findings"] if f["code"] == code}) == [
        f"/sections/{i}/members/mo_metadata" for i in where]
