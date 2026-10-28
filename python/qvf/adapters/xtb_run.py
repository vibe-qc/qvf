"""Run an explicitly configured xTB binary, then export its settled results.

This is a serial local-job entry point, suitable as a vq payload. xTB's
termination and optimisation markers follow src/mctc/error.f90 and
src/geoopt_driver.f90 in https://github.com/grimme-lab/xtb/tree/v6.7.1.
It does not submit jobs, discover executables or install software.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from .xtb import _geometry, _integer, _json, _text, _xtb_xyz, write_xtb

__all__ = ["run_xtb"]


def run_xtb(request, *, binary):
    """Run an xTB bundle once and create ``result.qvf`` alongside its request.

    The version-1 JSON request names method, task, integer charge and
    multiplicity, and boolean orbitals/bond_orders/density outputs. Inputs
    are the sibling ``coord`` and ``xcontrol`` files. A fresh ``xtb-results``
    directory isolates generated files from stale results. All output remains
    available there on failure; no QVF with a success status is published.
    The engine's combined log is streamed and saved as ``xtb.out``. Return
    the exporter report on success; raise on execution or export failure.
    """
    request = Path(request).resolve()
    spec = json.loads(_text(request))
    fields = {"version", "method", "task", "charge", "multiplicity", "outputs"}
    if not isinstance(spec, dict) or set(spec) - {"frozen_atoms"} != fields or type(spec["version"]) is not int or spec["version"] != 1:
        raise ValueError("invalid xTB run request (expected version 1)")
    methods = {"GFN0-xTB": "0", "GFN1-xTB": "1", "GFN2-xTB": "2"}
    if spec["method"] not in methods or spec["task"] not in ("single_point", "optimization", "frequencies"):
        raise ValueError("xTB runner supports molecular GFN0/1/2 single points, optimisation and Hessians")
    charge = _integer(spec["charge"], "charge")
    mult = _integer(spec["multiplicity"], "multiplicity", 1)
    outputs = spec["outputs"]
    if (not isinstance(outputs, dict) or set(outputs) != {"orbitals", "bond_orders", "density"}
            or any(type(value) is not bool for value in outputs.values())):
        raise ValueError("xTB outputs must be boolean orbitals/bond_orders/density selections")
    executable = Path(binary)
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("xTB binary must be an absolute executable path")
    base = request.parent
    destination = base / "result.qvf"
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("result.qvf already exists")
    for name in ("coord", "xcontrol"):
        if not (base / name).is_file():
            raise ValueError(f"xTB bundle is missing {name}")
    atoms, _ = _geometry(base / "coord")
    frozen = spec.get("frozen_atoms", [])
    if (not isinstance(frozen, list) or any(type(i) is not int or not 0 <= i < len(atoms) for i in frozen)
            or len(set(frozen)) != len(frozen) or (frozen and spec["task"] != "optimization")):
        raise ValueError("frozen_atoms requires unique zero-based indices and optimisation")
    work = base / "xtb-results"
    work.mkdir()  # Never reuse outputs or success markers from an earlier run.
    for name in ("coord", "xcontrol"):
        shutil.copyfile(base / name, work / name)
    command = [str(executable), "coord", "--gfn", methods[spec["method"]],
               "--chrg", str(charge), "--uhf", str(mult - 1), "--input", "xcontrol"]
    if spec["task"] != "single_point":
        command.append("--opt" if spec["task"] == "optimization" else "--hess")
    for enabled, option in ((outputs["orbitals"], "--molden"), (outputs["bond_orders"], "--wbo")):
        if enabled:
            command.append(option)
    environment = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    normal = False
    with (work / "xtb.out").open("x", encoding="utf-8") as log:
        with subprocess.Popen(command, cwd=work, env=environment, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors="replace") as process:
            for line in process.stdout:
                log.write(line); log.flush()
                print(line, end="", flush=True)
                if line.strip() == "normal termination of xtb":
                    normal = True
            returncode = process.wait()
    if returncode != 0 or not normal or (work / "NOT_CONVERGED").exists():
        raise RuntimeError(f"xTB calculation failed or did not establish normal termination (exit {returncode}); see xtb-results/xtb.out")
    if spec["task"] == "optimization" and not (work / ".xtboptok").is_file():
        raise RuntimeError("xTB optimisation did not produce .xtboptok; no converged QVF exported")
    data = _json(work / "xtbout.json")
    if data["method"] != spec["method"]:
        raise ValueError("xTB output method differs from the submitted request")
    options = {"charge": charge, "multiplicity": mult, "run_status": "converged"}
    geometry = work / "coord"
    if spec["task"] == "optimization":
        geometry = work / "xtbopt.coord"
        options["trajectory"] = work / "xtbopt.log"
        if frozen:
            final, _ = _geometry(geometry)
            frames = _xtb_xyz(_text(work / "xtbopt.log"))
            for positions in [final] + [frame["atoms"] for frame in frames]:
                if len(positions) != len(atoms) or any(
                    positions[i]["atomic_number"] != atoms[i]["atomic_number"] or
                    any(abs(x-y) > 2e-5 for x,y in zip(positions[i]["position"], atoms[i]["position"]))
                    for i in frozen
                ):
                    raise RuntimeError("xTB moved a frozen atom; no accepted QVF exported. Inspect xtb-results and the optimiser settings.")
    elif spec["task"] == "frequencies":
        options["modes"] = work / "g98.out"
    if outputs["orbitals"]:
        options.update(molden=work / "molden.input", spin="restricted" if mult == 1 else "restricted_open",
                       canonical_orbitals=True)
    if outputs["bond_orders"]:
        options["wbo"] = work / "wbo"
    if outputs["density"]:
        options["cubes"] = [(work / "density.cub", "volume.density")]
    report = write_xtb(work / "xtbout.json", geometry, destination, **options)
    # Local operational report only; the QVF does not embed the engine log.
    (base / "xtb-export-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
