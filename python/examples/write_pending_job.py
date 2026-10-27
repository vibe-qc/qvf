"""Write a pending molecular QVF job using the QVF writer API (v0.4.0+).

Run from the QVF checkout with qvf-writer installed:
    python python/examples/write_pending_job.py job.qvf
    qvf-validate --json job.qvf

This writes an illustrative H2 geometry and an RHF/STO-3G request. It does not
run a calculation, invent results, or overwrite an existing archive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from qvf_writer import QvfWriter


def write_pending_job(path: Path) -> None:
    writer = QvfWriter(
        program="qvf-pending-job-example",
        version="1.0.0",
        calculation="H2 RHF/STO-3G single point",
    )
    structure_id = writer.add_structure(
        atoms=[
            {"symbol": "H", "atomic_number": 1, "position": [0.0, 0.0, 0.0]},
            {"symbol": "H", "atomic_number": 1, "position": [0.0, 0.0, 0.74]},
        ],
        pbc=[False, False, False],
        bonds=[{"i": 0, "j": 1, "order": 1.0}],
        charge=0,
        multiplicity=1,
        smiles="[H][H]",
        name="H2",
        section_id="geometry",
    )
    writer.add_job_spec(
        job_type="molecular",
        method="rhf",
        basis="sto-3g",
        functional=None,
        charge=0,
        multiplicity=1,
        tasks=["single_point"],
        structure_ref=structure_id,
        section_id="job",
    )
    writer.set_provenance(run_status="pending", charge=0, multiplicity=1)
    writer.write(str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("job.qvf"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"{args.output} already exists; choose a new output path")
    write_pending_job(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
