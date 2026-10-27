#!/usr/bin/env python3
"""Cross-producer check of a wavefunction.gto archive against the PySCF adapter.

Usage::

    python scripts/pyscf_cross_producer.py REFERENCE.qvf [--out PYSCF.qvf]
        [--basis-from-archive] [--no-reference-guess] [--json]

Rebuilds the reference archive's molecule (geometry, charge, multiplicity)
in PySCF with the method, functional and basis its ``provenance`` names,
converges the SCF tightly from the reference density (so that a degenerate
open shell lands on the same of its equal-energy solutions), writes it with ``qvf.adapters.pyscf`` and reads
both archives back through the ``qvf`` reader. It then compares, in the
common QVF AO convention of spec Appendix A, the SCF energies and the AO
density matrices (total, and the alpha and beta ones of an unrestricted
pair) and reports ``max |ΔP|`` and the Frobenius norm ``‖ΔP‖_F``, and the
Mulliken and Löwdin charges when both archives carry them (informational).
Differences at the SCF convergence level prove that both producers agree on
the AO order, the real-solid-harmonic phases and the primitive
normalization; a convention error shows up as an order-one ``ΔP``.

The basis payloads are compared first: the two archives must describe the
same AOs (shell order, centres, ``l``, exponents and contraction coefficients
on ``N_i``-normalized primitives, each up to 1e-6 relative after scaling to
a unit axial self-overlap). ``--basis-from-archive`` builds the PySCF basis
from the reference ``basis`` payload instead of the named basis, for a
reference whose basis-set data differ from PySCF's library.

Needs ``pip install 'qvf-writer[pyscf]'``. Exits 0 when the energies agree
within 1e-6 hartree and ``max |ΔP|`` is below 1e-4, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))

import numpy as np  # noqa: E402

from qvf import Reader, validate_qvf  # noqa: E402
from qvf.adapters import pyscf as adapter  # noqa: E402
from qvf.units import BOHR_PER_ANGSTROM  # noqa: E402

ENERGY_TOL = 1e-6
DENSITY_TOL = 1e-4


def _unit_norm(shell):
    """The shell's coefficients scaled to a unit axial self-overlap."""
    l, es, cs = shell["l"], shell["exponents"], shell["coefficients"]
    s = sum(a * b * (2 * math.sqrt(x * y) / (x + y)) ** (l + 1.5)
            for x, a in zip(es, cs) for y, b in zip(es, cs))
    return [c / math.sqrt(s) for c in cs]


def _read(path):
    """Structure, wavefunction and provenance of an archive, in QVF form."""
    with Reader(path) as reader:
        manifest = reader.raw_manifest
        structure = next(s for s in reader.sections if s.kind == "structure")
        atoms = reader.json(structure, "structure")["atoms"]
        raw = next(s for s in manifest["sections"] if s["id"] == structure.id)
        wf = next(s for s in reader.sections if s.kind == "wavefunction.gto")
        basis = reader.json(wf, "basis")
        meta = reader.json(wf, "mo_metadata")
        if meta["spin"] == "unrestricted":
            dms = {}
            for ch in ("alpha", "beta"):
                c = reader.tensor(wf, f"mo_coefficients_{ch}").numpy()
                occ = np.asarray(meta[ch]["occupations"])
                dms[ch] = (c.T * occ) @ c
            dms["total"] = dms["alpha"] + dms["beta"]
        else:
            c = reader.tensor(wf, "mo_coefficients").numpy()
            occ = np.asarray(meta["occupations"])
            dms = {"total": (c.T * occ) @ c}
        charges = {}
        for props in reader.sections_of("atom_properties"):
            for role in ("mulliken_charge", "loewdin_charge"):
                if role in (props.members or {}) and role not in charges:
                    charges[role] = reader.tensor(props, role).numpy()
    return {"atoms": atoms, "charges": charges, "structure": raw, "basis": basis, "meta": meta,
            "dms": dms, "provenance": manifest.get("provenance", {}),
            "source": manifest.get("source", {})}


def _molecule(ref, basis_from_archive):
    from pyscf import gto
    prov = ref["provenance"]
    charge = ref["structure"].get("charge", prov.get("charge", 0))
    multiplicity = ref["structure"].get("multiplicity", prov.get("multiplicity", 1))
    labels = [f"{a['symbol']}{i + 1}" if basis_from_archive else a["symbol"]
              for i, a in enumerate(ref["atoms"])]
    atom = [[label, [x * BOHR_PER_ANGSTROM for x in a["position"]]]
            for label, a in zip(labels, ref["atoms"])]
    if basis_from_archive:
        basis = {label: [] for label in labels}
        for shell in ref["basis"]["shells"]:
            basis[labels[shell["center"]]].append(
                [shell["l"]] + [[e, c] for e, c in zip(shell["exponents"], shell["coefficients"])])
    else:
        basis = prov.get("basis")
        if not basis:
            raise SystemExit("the reference names no basis; use --basis-from-archive")
    pure = ref["basis"].get("pure", True)
    return gto.M(atom=atom, unit="Bohr", basis=basis, charge=int(charge),
                 spin=int(multiplicity) - 1, cart=not pure, verbose=0)


def _reference_guess(mol, ref):
    """The reference densities in PySCF's AO basis, as the initial guess.

    Degenerate open shells (the π hole of OH, for example) have several
    UHF solutions of one energy. Starting from the reference density selects
    the same one. The map is the adapter's own, inverted; a wrong map gives
    a poor guess, never a false agreement, because the comparison is made
    after convergence in the QVF AO basis.
    """
    amap = adapter.ao_map(mol)
    perm, reason = _match_shells({"shells": amap.shells, "pure": amap.pure}, ref["basis"])
    if perm is None:
        raise SystemExit(f"basis payloads differ: {reason}; try --basis-from-archive")
    inverse = np.linalg.inv(amap.matrix)

    def to_pyscf(dm):
        mine = np.zeros_like(dm)
        mine[np.ix_(perm, perm)] = dm
        return inverse @ mine @ inverse.T

    dms = ref["dms"]
    if "alpha" in dms:
        return np.asarray([to_pyscf(dms["alpha"]), to_pyscf(dms["beta"])])
    return to_pyscf(dms["total"])


def _scf(mol, ref, guess):
    from pyscf import dft, scf
    method = str(ref["provenance"].get("method", "")).lower()
    functional = ref["provenance"].get("functional")
    builders = {"rhf": scf.RHF, "uhf": scf.UHF, "rohf": scf.ROHF,
                "rks": dft.RKS, "uks": dft.UKS, "roks": dft.ROKS}
    if method not in builders:
        raise SystemExit(f"unsupported reference method {method!r}")
    mf = builders[method](mol)
    if method.endswith("ks"):
        mf.xc = functional
        mf.grids.level = 9
    mf.conv_tol = 1e-12
    mf.conv_tol_grad = 1e-8
    mf.max_cycle = 200
    dm0 = None
    if guess:
        dm0 = _reference_guess(mol, ref)
        if method in ("rhf", "rks") and dm0.ndim == 3:
            dm0 = dm0[0] + dm0[1]
        elif method not in ("rhf", "rks") and dm0.ndim == 2:
            dm0 = np.asarray([dm0 / 2, dm0 / 2])
    mf.kernel(dm0)
    if not mf.converged:
        raise SystemExit("PySCF SCF did not converge")
    return mf


def _shell_size(shell, pure):
    l = shell["l"]
    return 2 * l + 1 if shell.get("pure", pure) else (l + 1) * (l + 2) // 2


def _match_shells(mine, ref):
    """AO permutation taking ``mine`` into the shell order of ``ref``.

    Shells match on centre, ``l``, angular type, exponents and unit-axial
    coefficients (1e-6 relative). Producers may order the shells of one atom
    differently (a split ``sp`` shell, for example); each archive states its
    own order, so the comparison follows it. Returns ``(permutation, None)``
    or ``(None, reason)``.
    """
    def key(shell, pure):
        return (shell["center"], shell["l"], bool(shell.get("pure", pure)))

    def same(x, y):
        if len(x["exponents"]) != len(y["exponents"]):
            return False
        return (all(abs(e1 - e2) <= 1e-6 * abs(e2)
                    for e1, e2 in zip(x["exponents"], y["exponents"]))
                and all(abs(c1 - c2) <= 1e-6 * max(abs(c2), 1e-3)
                        for c1, c2 in zip(_unit_norm(x), _unit_norm(y))))

    pm, pr = mine.get("pure", True), ref.get("pure", True)
    if len(mine["shells"]) != len(ref["shells"]):
        return None, f"{len(mine['shells'])} vs {len(ref['shells'])} shells"
    offsets, start = [], 0
    for shell in mine["shells"]:
        offsets.append(start)
        start += _shell_size(shell, pm)
    used, perm = set(), []
    for k, y in enumerate(ref["shells"]):
        match = next((j for j, x in enumerate(mine["shells"])
                      if j not in used and key(x, pm) == key(y, pr) and same(x, y)), None)
        if match is None:
            return None, f"reference shell {k} (l = {y['l']}) has no counterpart"
        used.add(match)
        perm.extend(range(offsets[match], offsets[match] + _shell_size(y, pr)))
    return perm, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference")
    parser.add_argument("--out", help="where to write the PySCF archive")
    parser.add_argument("--basis-from-archive", action="store_true")
    parser.add_argument("--no-reference-guess", action="store_true",
                        help="start PySCF from its own guess, not the reference density")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    ref = _read(args.reference)
    mol = _molecule(ref, args.basis_from_archive)
    mf = _scf(mol, ref, guess=not args.no_reference_guess)
    out = args.out or os.path.join(tempfile.mkdtemp(prefix="qvf-pyscf-"), "pyscf.qvf")
    adapter.write_scf(mf, out)
    report = validate_qvf(out)
    mine = _read(out)

    result = {"reference": os.path.basename(args.reference),
              "reference_source": ref["source"], "method": adapter.method_name(mf),
              "basis": ref["provenance"].get("basis"), "pure": ref["basis"].get("pure", True),
              "n_ao": int(mine["dms"]["total"].shape[0]),
              "max_l": max(s["l"] for s in mine["basis"]["shells"]),
              "pyscf_archive_findings": [f["code"] for f in report["findings"]],
              }
    perm, result["basis_difference"] = _match_shells(mine["basis"], ref["basis"])
    result["shell_order_differs"] = perm is not None and perm != sorted(perm)
    e_ref = ref["provenance"].get("scf_energy", {}).get("value")
    e_mine = mine["provenance"]["scf_energy"]["value"]
    result["energy_reference"] = e_ref
    result["energy_pyscf"] = e_mine
    result["delta_energy"] = None if e_ref is None else e_mine - e_ref
    ok = report["ok"] and result["basis_difference"] is None
    for name, p in mine["dms"].items():
        q = ref["dms"].get(name)
        if perm is not None:
            p = p[np.ix_(perm, perm)]
        if q is None or q.shape != p.shape:
            ok = False
            result[f"density_{name}"] = "missing or shape mismatch"
            continue
        delta = p - q
        result[f"max_abs_dP_{name}"] = float(np.abs(delta).max())
        result[f"frobenius_dP_{name}"] = float(np.linalg.norm(delta))
        ok = ok and result[f"max_abs_dP_{name}"] < DENSITY_TOL
    for role, values in mine["charges"].items():
        if role in ref["charges"]:
            result[f"max_abs_d_{role}"] = float(np.abs(values - ref["charges"][role]).max())
    if result["delta_energy"] is not None:
        ok = ok and abs(result["delta_energy"]) < ENERGY_TOL
    result["ok"] = bool(ok)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
