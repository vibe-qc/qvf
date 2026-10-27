"""Write a one-species Sketch drawing for the QVF prepare-job example.

Run in an environment with vibe-sketch's chemistry dependencies and
qvf-writer[numpy,validate] from development main installed:
    python python/examples/write_sketch_drawing.py drawing.qvf
    qvf prepare-job drawing.qvf --output job.qvf --job-type molecular \
        --method rhf --task single_point --basis sto-3g --no-functional

The H2 coordinates are illustrative, supplied explicitly in angstrom. No
geometry optimization, calculation, submission or preview rendering occurs.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def drawing_bytes() -> bytes:
    from vibesketch.document import Document, new_document
    from vibesketch.document.qvf import to_qvf

    data = new_document().to_json_data()
    data["canvas"] = {
        "format": "ket",
        "data": {
            "root": {"nodes": [{"$ref": "mol0"}], "connections": [], "templates": []},
            "mol0": {
                "type": "molecule",
                "atoms": [
                    {"label": "H", "location": [0.0, 0.0, 0.0]},
                    {"label": "H", "location": [1.0, 0.0, 0.0]},
                ],
                "bonds": [{"type": 1, "atoms": [0, 1]}],
            },
        },
    }
    data["species"] = [{
        "id": "h2", "label": "1", "smiles": "[H][H]",
        "charge": 0, "multiplicity": 1,
        "conformers": [{
            "method": "imported", "symbols": ["H", "H"],
            "xyz_angstrom": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]],
        }],
    }]
    return to_qvf(Document.model_validate(data), preview=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("drawing.qvf"))
    args = parser.parse_args()
    archive = drawing_bytes()
    try:
        with args.output.open("xb") as output:
            output.write(archive)
    except FileExistsError:
        parser.error(f"{args.output} already exists; choose a new output path")
    print(args.output)


if __name__ == "__main__":
    main()
