# qvf-writer (Python)

The `qvf` package writes, reads, validates and updates **QVF** (`.qvf`, the
*Quantum Visualization Format*), a ZIP container for quantum-chemistry data
with a typed, checksummed manifest. The distribution name stays `qvf-writer`.

The package and its raw-buffer writer, reader and editor use only the standard
library. Install optional dependencies for numeric convenience writers and
full JSON Schema validation:

```sh
pip install "qvf-writer[numpy,validate]"
```

From a toolkit checkout, use `pip install "./python[numpy,validate]"`.
`qvf_writer` and `qvf_reader` remain importable with a `DeprecationWarning`;
existing `QvfWriter`, `QvfReader` and `qvf-validate` callers keep working.

```python
import struct
from qvf import Reader, Section, Writer

with Writer("density.qvf", program="example", version="1.0") as writer:
    writer.add_section(Section(id="rho", kind="volume.density", members={}))
    writer.add_json("rho", "grid", {
        "origin": [0, 0, 0], "voxel_vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "shape": [1, 1, 2],
    })
    with writer.begin_binary("rho", "data", "float64", [1, 1, 2]) as member:
        member.write(struct.pack("<2d", 0.5, 0.25))

with Reader("density.qvf") as reader:
    tensor = reader.tensor("rho", "data")
    print(tensor.tolist())                # [[[0.5, 0.25]]]
    raw = tensor.data                     # read-only byte memoryview
    assert reader.validate()["ok"]
```

Members are written as they are added, and the manifest is written last.
`Reader` checks resource limits at open and loads payloads on demand.
`Editor` appends updates, optionally commits atomically, and repacks orphans.
`qvf.validate.run` shares finding codes with the C++ and JavaScript validators.
The installed package contains the normative schema for structural checks.

```sh
qvf info density.qvf
qvf validate density.qvf
qvf cat density.qvf rho grid
qvf-validate density.qvf  # compatibility entry point
```

The `qvf` command also provides `extract`, numeric `diff`, `repack`, explicit-output
`scrub`, `conformance` and `schema`. `python -m qvf --help` lists the commands.
Validation has cumulative container, manifest, payload, semantic and reference
stages; full checks are the default. Output commands refuse existing files.
Scrub offers a dry-run change report and keeps the original archive intact.

See the [format specification, integration guide, and library
guide](https://vibe-qc.com/docs/qvf/). The C++ library and language-independent
conformance suite live in the same toolkit. Licensed Apache-2.0.
