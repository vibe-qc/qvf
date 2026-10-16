# A QVF job across the vibe family

Use one `.qvf` archive to carry a calculation request, send it to a managed
vibe-qc runtime with vibe-queue, and open the resulting structure and supported
results in vibe-view. A sketch document is another use of the same format;
its export is not automatically a runnable calculation.

This workflow uses the QVF **v0.5.0 toolkit** and **format version 1**. The
[specification](../spec/qvf-format-spec.md) defines the archive contract; each
consumer implements a subset. Conformance does not imply that every consumer
can execute, display or preserve every section.

## Install the relevant components

The Python distribution remains `qvf-writer`. It supplies the `qvf` package
and compatible `qvf_writer` and `qvf_reader` imports. From a QVF checkout
at the v0.5.0 tag, install
into the Python environment that will run the example:

```sh
python -m pip install './python[numpy,validate]'
```

The example uses the legacy NumPy array API. The `validate` extra adds JSON Schema checks to the
reference validator. This source installation does not depend on the release
already being available on a package index or mirror. Use your normal managed
installation for vibe-qc, and install/configure vibe-queue on the submission
host. The queue's `--program NAME` must name a registered vibe-qc runtime;
`NAME` and `HOST` below are placeholders for that configuration.

vibe-view's core installation can inspect QVF metadata and structures. The
interactive `vibe-view open` command also needs its `viewer` extra. Sketch
import needs vibe-sketch's chemistry dependencies and `qvf-writer` in its own
Python environment; its installer supports an explicit QVF checkout path.
These applications need not share a Python environment.

The toolkit supplies the unified **`qvf`** command and retains
**`qvf-validate`**. Use `qvf info job.qvf` to inspect an archive and
`qvf validate job.qvf` for reference validation.

## Write and inspect a pending job

Save
[write_pending_job.py](../python/examples/write_pending_job.py) in your working
directory, or use its `python/examples/` path in a checkout that includes it:

```sh
python write_pending_job.py job.qvf
qvf-validate --json job.qvf
vibe-view info job.qvf
```

[The example](../python/examples/write_pending_job.py) writes an illustrative
H2 geometry in angstrom and requests an RHF/STO-3G single point. It performs
no calculation and refuses to overwrite an existing output. The archive has
exactly one `structure`, one `job.spec` referring to it, and
`provenance.run_status = "pending"`. The explicit `functional: null` says
Hartree-Fock takes no density functional; omitting the field would leave the
choice to the engine. There are no calculated energies or orbitals yet.

For a read-only check in the vibe-qc environment:

```python
from vibeqc.qvf_job import load_job_container

job = load_job_container("job.qvf")
assert job.run_status == "pending"
assert job.spec["method"] == "rhf"
assert len(job.structure["atoms"]) == 2
```

`load_job_container` reads the request and verifies the input-member hashes;
it does not run the job and is not a substitute for the reference validator.
The current vibe-qc runner requires **exactly one structure and one job.spec**.
Its supported task names are `single_point`, `optimize` and `hessian`.
QVF itself permits job sets; a valid archive containing several jobs or
structures is outside this runner's current input surface.

## Submit, follow and fetch

These commands execute the requested calculation through the configured
runtime. Record the job ID printed by submission:

```sh
vq submit HOST job.qvf --program NAME
vq status HOST JOBID --json
vq fetch HOST JOBID --name job.qvf -o results/
```

vibe-queue recognizes the single-file payload and selects the managed
`vibeqc run` entry point. Do not pass `--python` or `--branch` for this path.
The `job.spec` is declarative data; neither the queue nor this workflow
executes a stored `run.record.input` as a script. The producer updates the
working archive with results and a sequenced `run.record`. A runtime pin may
be required by site policy; `--expected-sha FULL_SHA` requests an explicit
source identity at submission and dispatch.

Read `qvf_lifecycle` in JSON status. `done` requires both a terminal queue job
and a terminal QVF status with a complete, sequenced input/log record.
`chemistry_failed` distinguishes a recorded failed calculation from
`queue_process_failed`. A queue process exiting zero alone is insufficient.
Fetch after completion; artifact-only fetch preserves archive bytes and
excludes queue sidecars. A retry accepts an identical file and refuses to
overwrite a different result.

```sh
qvf-validate --json results/job.qvf
vibe-view open results/job.qvf
```

A clean validation report establishes the checks performed, not scientific
accuracy or the availability of every visualization. For a deliberate rerun,
submit the result with `--qvf-force`; this appends another sequenced run record.
Use a fresh fetch directory for the new result:

```sh
vq submit HOST results/job.qvf --program NAME --qvf-force
vq fetch HOST NEW_JOBID --name job.qvf -o rerun-results/
```

## Open the geometry in vibe-sketch

A foreign QVF contributes molecular structures and supported reaction-scheme
content to a sketch. Keep the original result archive and write a separate
sketch archive:

```python
from pathlib import Path
from vibesketch.document.qvf import from_qvf, to_qvf

imported = from_qvf(Path("results/job.qvf").read_bytes())
for warning in imported.warnings:
    print(warning)
Path("drawing.qvf").write_bytes(to_qvf(imported.document, preview=False))
```

This is a geometry/document conversion, **not a lossless archive update**.
Foreign job specifications, run logs, wavefunctions, other result sections and
vendor sections may be absent from the new sketch archive. An existing
`x_vibesketch.document` is the sketch's own document representation; generic
QVF readers can still read the canonical structures it exports.

A sketch document may contain several species and jobs, and `to_qvf` does not
mark it as pending. Its queue submission API currently emits engine input
files. Do not send a general sketch document directly to the single-job
vibe-qc runner. Select one molecular geometry and construct an explicit
pending job with the writer pattern above, or use the sketch's supported
engine-input submission path. Periodic structures are outside sketch's
molecular drawing scope.

The example's reference validation, vibe-qc request load, vibe-view structure
read and sketch geometry round trip are format and integration checks. They
make no claim that a quantum-chemistry calculation has been validated.

## Importing other formats with toolkit 0.5.0

The toolkit 0.5.0 [text converters](converters.md) bring XYZ/extXYZ structures
and trajectories and scalar cube fields into canonical QVF sections. They
create new, validated archives and report conversion limits. Imported
geometry has no job request: use the explicit pending-job pattern above
before submitting it to vibe-qc through vibe-queue. Keep result archives
when exporting a selected geometry or grid to a text format.
