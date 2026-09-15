# qvf-writer (Python)

Standalone reference **writer** and **reader/validator** for **QVF** (`.qvf`, the
*Quantum Visualization Format*) — a ZIP container for quantum-chemistry
visualization and analysis data (structure, wavefunctions, spectra, bands,
volumes, trajectories, provenance) with a typed, checksummed manifest.

Depends only on NumPy. Any quantum-chemistry code can emit `.qvf` archives that
open in [vibe-view](https://vibe-qc.com) or any QVF consumer.

```python
from qvf_writer import QvfWriter

w = QvfWriter(program="my-code", version="1.0", calculation="h2o/rhf")
w.add_structure([{"symbol": "O", "position": [0, 0, 0.117], "atomic_number": 8}])
w.add_spectrum("spectra.ir", frequencies=[1595.0], intensities=[67.0])
w.write("h2o.qvf")
```

Validate anything you write (semantic checks always run; install the `validate`
extra for full JSON-Schema conformance):

```sh
pip install "qvf-writer[validate]"
qvf-validate h2o.qvf
```

See the [format specification, integration guide, and library
guide](https://vibe-qc.com/docs/qvf/). The C++ writer/reader library and a
language-agnostic conformance suite live in the same toolkit. Licensed
Apache-2.0.
