<!-- attribution -->

_Created and maintained by Dr. Michael F. Peintinger._

# QVF — a standalone archive format and toolkit

**QVF** (`.qvf`, *Quantum Visualization Format*) is a ZIP-based container for
quantum-chemistry visualization and analysis data: structures, job requests,
scalar fields, spectra, bands, trajectories, wavefunctions, provenance, and
viewer hints in a single random-access file, instead of a scatter of Cube, XYZ,
Molden, XSF, log, and program-specific sidecar files.

This toolkit lets **any** quantum-chemistry code produce valid `.qvf` archives
without depending on vibe-qc. Within the vibe-qc family (vibe-qc, vibe-view,
vibe-sketch, vibe-queue) QVF is the standard format the programs read, write
and hand each other; see [GOVERNANCE.md](GOVERNANCE.md#qvf-in-the-vibe-qc-family). It is licensed **Apache-2.0** (see `LICENSE`), so
it can be linked into proprietary as well as open-source codes.

Toolkit **0.6.0** implements **QVF v1** (`qvf_version = 1`). It includes
streaming C++/Python APIs, the complete C ABI, optional Fortran bindings,
a unified CLI, cube/XYZ/XSF/PDB converters, drawing-preserving job preparation
and local Conan packaging; see the [release notes](CHANGELOG.md#060---2026-10-22).

## What's in here

| Path | What it is |
|------|-----------|
| [`spec/qvf-format-spec.md`](spec/qvf-format-spec.md) | The standalone, normative QVF format specification. |
| [`spec/qvf_manifest.schema.json`](spec/qvf_manifest.schema.json) | The machine-readable JSON Schema for `manifest.json` (single source of truth). |
| [`spec/file-type/`](spec/file-type/) | The `.qvf` file-type declarations every program copies: the macOS UTI (`com.vibe-qc.qvf`) and the freedesktop.org media type (`application/vnd.vibe-qc.qvf+zip`). |
| [`python/qvf/`](python/qvf/) | Python streaming **writer**, lazy typed **reader**, **editor** and **validator**. Standard library core; NumPy is optional. |
| [`python/qvf_writer.py`](python/qvf_writer.py), [`python/qvf_reader.py`](python/qvf_reader.py) | Compatible top-level imports for existing applications. |
| [`cpp/`](cpp/) | Zero-dependency C++17 streaming writer, lazy reader, validator and editor. Existing `qvf::QvfWriter` calls remain supported. |
| [`cpp/include/qvf/qvf_c.h`](cpp/include/qvf/qvf_c.h) | C ABI 1 for all canonical kinds, reading, validation and editing; static or shared-library builds. |
| [`docs/library_guide.md`](docs/library_guide.md) | How to build, link, and call both writers. |
| [`docs/family_workflow.md`](docs/family_workflow.md) | A runnable job across vibe-qc, vibe-queue, vibe-view and vibe-sketch, with consumer limits and a portable example. |
| [`docs/orca_integration.md`](docs/orca_integration.md) | Worked mapping from an engine's data (GBW-style wavefunction, spectra, properties) onto QVF sections. |
| [`GOVERNANCE.md`](GOVERNANCE.md) + [`registry.json`](registry.json) | How QVF is stewarded, versioned, and evolved — an open standard created and stewarded by vibe-qc; the registry of canonical kinds + vendor namespaces. |
| [`conformance/`](conformance/) | Golden corpus + runner so any producer/consumer can self-certify. |
| [`ROADMAP.md`](ROADMAP.md) | Phased plan for the format and the library; entry point to the planning docs below. |
| [`docs/format_review.md`](docs/format_review.md) | Coverage matrix, defects, additive proposals, and the v2 ledger. |
| [`docs/library_design.md`](docs/library_design.md) | Target architecture of libqvf: container, model, validation, facades, bindings. |
| [`docs/work_packages.md`](docs/work_packages.md) | Implementation briefs (WP-nn) with a Definition of Done. |

## 60-second Python example

Install `qvf-writer[numpy,validate]` (or `./python[numpy,validate]` from a
checkout). New applications can use the [streaming package API](docs/library_guide.md#python-package-api);
this existing API remains compatible.

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
./build/write_h2o
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

Every finding carries a stable code (`E_SHA256_MISMATCH`, `W_ORPHAN_MEMBER`, …)
from spec Appendix B, shared by the Python, C++ and JavaScript validators. The
[`conformance/`](conformance/) suite certifies both directions: a golden corpus
every consumer must decode, and a negative corpus of must-fail archives — one
per validation rule — every validator must reject with the expected code.

A conforming producer must satisfy the checklist in
[`spec/qvf-format-spec.md`](spec/qvf-format-spec.md) § "Producer conformance".

## Reference consumer

The reference GPU viewer for `.qvf` is **vibe-view**, part of the vibe family.
Use QVF's reference validators to check the format contract. Viewers and
runners support different section subsets; the [family workflow](docs/family_workflow.md)
shows the supported single-job path and current consumer limits.


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
