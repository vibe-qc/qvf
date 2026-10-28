"""Serial producer runner: explicit executable, isolated outputs, fail closed."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qvf import Reader
from qvf.adapters.xtb_run import run_xtb
from qvf.validate import run


def bundle(tmp_path, *, task="single_point", marker=True, exit_code=0, normal=True,
           not_converged=False, missing=False):
    request = tmp_path / "xtb-job.json"
    request.write_text(json.dumps(dict(version=1, method="GFN2-xTB", task=task,
        charge=0, multiplicity=1, outputs=dict(orbitals=False, bond_orders=False, density=False))))
    coord = "$coord angs\n0 0 0 he\n$end\n"
    (tmp_path / "coord").write_text(coord)
    (tmp_path / "xcontrol").write_text("$write\n json=true\n$end\n")
    engine = tmp_path / "synthetic-xtb"
    engine.write_text(f"#!{sys.executable}\n" + f"""
import json, os, sys
from pathlib import Path
assert os.environ['OMP_NUM_THREADS'] == '1'
assert os.environ['OPENBLAS_NUM_THREADS'] == '1'
assert '--chrg' in sys.argv and '--uhf' in sys.argv
Path('invocation.json').write_text(json.dumps(sys.argv[1:]))
if not {missing!r}:
    Path('xtbout.json').write_text(json.dumps({{'method':'GFN2-xTB','xtb version':'6.7.1','total energy':-1.,'number of electrons':2,'number of unpaired electrons':0}}))
if {task!r} == 'optimization':
    Path('xtbopt.coord').write_text({coord!r})
    Path('xtbopt.log').write_text('1\\n energy: -1.0 gnorm: .0 xtb: 6.7.1\\nhe 0 0 0\\n')
    if {marker!r}: Path('.xtboptok').touch()
if {not_converged!r}: Path('NOT_CONVERGED').touch()
if {normal!r}: print('normal termination of xtb')
sys.exit({exit_code!r})
""")
    engine.chmod(0o700)
    return request, engine


def test_run_export_and_repeat_refusal(tmp_path):
    request, binary = bundle(tmp_path, task="optimization")
    report = run_xtb(request, binary=str(binary))
    assert report["sections"] == ["structure", "trajectory"]
    assert run(tmp_path / "result.qvf")["ok"]
    with Reader(tmp_path / "result.qvf") as reader:
        assert reader.raw_manifest["provenance"]["run_status"] == "converged"
        assert reader.json("trajectory", "metadata")["energies"] == [-1.]
    original = (tmp_path / "result.qvf").read_bytes()
    with pytest.raises(FileExistsError):
        run_xtb(request, binary=str(binary))
    assert original == (tmp_path / "result.qvf").read_bytes()


@pytest.mark.parametrize("settings", [dict(exit_code=1), dict(normal=False),
    dict(not_converged=True), dict(task="optimization", marker=False), dict(missing=True)])
def test_failed_engine_never_publishes_success(tmp_path, settings):
    request, binary = bundle(tmp_path, **settings)
    with pytest.raises((RuntimeError, FileNotFoundError)):
        run_xtb(request, binary=str(binary))
    assert not (tmp_path / "result.qvf").exists()
    assert (tmp_path / "xtb-results/xtb.out").exists()
    with pytest.raises(FileExistsError):
        run_xtb(request, binary=str(binary))


def test_request_and_required_output_failures(tmp_path):
    request, binary = bundle(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        run_xtb(request, binary="xtb")
    spec = json.loads(request.read_text())
    spec["version"] = True
    request.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="version"):
        run_xtb(request, binary=str(binary))
    assert not (tmp_path / "xtb-results").exists()
    spec["version"] = 1; spec["outputs"]["density"] = True
    request.write_text(json.dumps(spec))
    with pytest.raises(FileNotFoundError):
        run_xtb(request, binary=str(binary))
    assert not (tmp_path / "result.qvf").exists()


def test_shell_metacharacters_are_literal_paths(tmp_path):
    folder = tmp_path / "with space;literal"; folder.mkdir()
    request, binary = bundle(folder)
    run_xtb(request, binary=str(binary))
    assert (folder / "result.qvf").exists()


def test_frozen_atom_movement_refuses_acceptance(tmp_path):
    request, binary = bundle(tmp_path, task="optimization")
    spec = json.loads(request.read_text()); spec["frozen_atoms"] = [0]
    request.write_text(json.dumps(spec))
    binary.write_text(binary.read_text().replace("he 0 0 0", "he 0 0 0.1"))
    with pytest.raises(RuntimeError, match="frozen atom"):
        run_xtb(request, binary=str(binary))
    assert not (tmp_path / "result.qvf").exists()
