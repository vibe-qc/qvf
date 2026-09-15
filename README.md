<!-- attribution -->

_Created and maintained by Dr. Michael F. Peintinger._

# qvf-writer — a standalone QVF writer toolkit

**QVF** (`.qvf`, *Quantum Visualization Format*) is a ZIP-based container for
quantum-chemistry visualization and analysis data: one calculation's structure,
scalar fields, spectra, bands, trajectories, wavefunctions, provenance, and
viewer hints in a single random-access file, instead of a scatter of Cube, XYZ,
Molden, XSF, log, and program-specific sidecar files.

This toolkit lets **any** quantum-chemistry code produce valid `.qvf` archives
without depending on vibe-qc. It is licensed **Apache-2.0** (see `LICENSE`), so
it can be linked into proprietary as well as open-source codes.

Toolkit version **0.1.0**, implementing **QVF v1** (`qvf_version = 1`).

## What's in here

| Path | What it is |
|------|-----------|
| [`spec/qvf-format-spec.md`](spec/qvf-format-spec.md) | The standalone, normative QVF format specification. |
| [`spec/qvf_manifest.schema.json`](spec/qvf_manifest.schema.json) | The machine-readable JSON Schema for `manifest.json` (single source of truth). |
| [`python/qvf_writer.py`](python/qvf_writer.py) | Reference **writer** in Python. Depends only on the standard library + NumPy. |
| [`python/qvf_reader.py`](python/qvf_reader.py) | Reference **reader / validator** in Python — self-check your archives. |
| [`cpp/`](cpp/) | Zero-dependency **C++17 writer library** (`qvf::QvfWriter`) you can link into your code. Vendors its own ZIP + SHA-256; no external build deps. |
| [`docs/library_guide.md`](docs/library_guide.md) | How to build, link, and call both writers. |
| [`docs/orca_integration.md`](docs/orca_integration.md) | Worked mapping from an engine's data (GBW-style wavefunction, spectra, properties) onto QVF sections. |
| [`GOVERNANCE.md`](GOVERNANCE.md) + [`registry.json`](registry.json) | How QVF is stewarded, versioned, and evolved — an open standard created and stewarded by vibe-qc; the registry of canonical kinds + vendor namespaces. |
| [`conformance/`](conformance/) | Golden corpus + runner so any producer/consumer can self-certify. |

## 60-second Python example

```python
import numpy as np
from qvf_writer import QvfWriter

w = QvfWriter(program="my-code", version="1.2.3", calculation="h2o/rhf/sto-3g")
w.add_structure(
    atoms=[
        {"symbol": "O", "position": [0.0, 0.0, 0.1173], "atomic_number": 8},
        {"symbol": "H", "position": [0.0, 0.7572, -0.4692], "atomic_number": 1},
        {"symbol": "H", "position": [0.0, -0.7572, -0.4692], "atomic_number": 1},
    ],
)
w.add_spectrum("spectra.ir", frequencies=[1595.0, 3657.0, 3756.0],
               intensities=[67.0, 5.0, 42.0])
w.set_provenance(method="RHF", basis="STO-3G", scf_energy_eh=-74.963,
                 scf_converged=True)
w.write("h2o.qvf")
```

## 60-second C++ example

```cpp
#include "qvf/qvf.hpp"

int main() {
    qvf::QvfWriter w({"my-code", "1.2.3", "h2o/rhf/sto-3g"});
    w.add_structure({
        {"O", 8, {0.0, 0.0, 0.1173}},
        {"H", 1, {0.0, 0.7572, -0.4692}},
        {"H", 1, {0.0, -0.7572, -0.4692}},
    });
    qvf::Spectrum ir;
    ir.frequencies = {1595.0, 3657.0, 3756.0};
    ir.intensities = {67.0, 5.0, 42.0};
    w.add_spectrum("spectra.ir", ir);
    w.write("h2o.qvf");
}
```

Build:

```sh
cmake -S cpp -B build && cmake --build build
./build/examples/write_h2o
```

Or skip the build entirely and vendor the **single-header** drop-in
`cpp/qvf_single.hpp` (STB-style): `#define QVF_IMPLEMENTATION` in one `.cpp`,
`#include` it, done. C, Fortran, Rust, and Julia can use the stable **C ABI**
in `cpp/include/qvf/qvf_c.h`. See the [library guide](docs/library_guide.md).

## Design principles (why QVF looks the way it does)

1. **One shareable artifact** — a calculation travels as one `.qvf` file.
2. **Random access** — a consumer reads only the members it needs; a
   structure-only viewer never loads a 500 MB density grid.
3. **Typed payloads** — every member declares its format, dtype, shape, and a
   sha256 checksum.
4. **Stable vocabulary** — common data uses canonical section kinds
   (`structure`, `volume.density`, `bands`, `spectra.ir`, …).
5. **Partial support** — a consumer can support a subset of kinds and still open
   the file. Unknown vendor sections are reported, never misinterpreted.
6. **Producer neutrality** — `source.program` names any code. The core kinds are
   not vibe-qc-specific.

## Conformance

Run the bundled validator against anything you write:

```sh
python python/qvf_reader.py h2o.qvf     # prints a validation report; non-zero exit on error
```

A conforming producer must satisfy the checklist in
[`spec/qvf-format-spec.md`](spec/qvf-format-spec.md) § "Producer conformance".

## Reference consumer

The reference GPU viewer for `.qvf` is **vibe-view** (part of vibe-qc). Any file
this toolkit writes should open in vibe-view and validate against vibe-qc's
`validate_qvf()`.


## History

This repository begins at the commit below. Development before that
point took place in a private monorepo, which is retained privately;
the history was deliberately not transferred.

Copyright (c) 2026 Michael F. Peintinger and vibe-qc contributors.

## Local source archives

Run `scripts/make_archive.sh` from a clean committed standalone Git checkout.
Git and Python 3 are required. Only the committed tree
is packaged. Untracked files, caches and Git history are never copied. The
builder checks the committed schema and generated single header and fails on
drift; refresh and commit them before retrying.

Artifacts remain in `dist/`, or an explicit `--output-dir DIR`. Publication
uses separate operator tooling with an explicitly selected destination.
