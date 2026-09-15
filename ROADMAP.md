# qvf-writer roadmap

Where the toolkit is and where it's going. The near-term work is about crossing
from *"two implementations that agree"* to *"a standard external codes can adopt
without friction"* — that means certifiability, frictionless distribution, and
neutral governance, more than new features.

Status legend: ✅ done · 🔨 in progress · ⬜ planned.

## Done today

- ✅ Normative **specification** + machine-readable **JSON Schema** (drift-guarded copy).
- ✅ Reference **writer** in Python (stdlib + numpy) and **C++17** (zero-dependency).
- ✅ Reference **reader / validator** in Python.
- ✅ **DEFLATE** compression in the C++ writer (original RFC-1951 codec).
- ✅ **C ABI** (`qvf/qvf_c.h`) for C / Fortran / Rust / Julia callers.
- ✅ Reference **consumer**: vibe-view renders every canonical kind.
- ✅ Canonical **`spectra.epr`** kind (first vendor→canonical promotion).
- ✅ Docs: spec, integration guide, ORCA worked example, library guide, tutorial.

## Near-term — unblock adoption (Tier 1)

- ✅ **Conformance suite + golden corpus** (`conformance/`). A language-agnostic
  set of frozen reference archives + expected decoded values + a runner
  (`run_conformance.py`), so any producer/consumer can self-certify. The
  `expected.json` check format (manifest/JSON/binary pointers) is reimplementable
  in any language. The reference writer/reader are certified both ways in CI.
  Next: grow coverage as kinds are added; add a C++ runner.
- ⬜ **Frictionless packaging.**
  - 🔨 Python writer → **PyPI** (`pip install qvf-writer`). *Release-ready:*
    `python/pyproject.toml` builds an installable wheel (`qvf-writer`, deps
    numpy; `[validate]` extra adds jsonschema; `qvf-validate` console script;
    schema bundled). Verified via a clean-venv install. **Not yet published** —
    awaiting the maintainer's go/no-go + PyPI account.
  - ✅ **Single-header amalgamation** (`cpp/qvf_single.hpp`, STB-style) for
    drop-in vendoring — one file, `#define QVF_IMPLEMENTATION`, no build step.
  - ✅ **CMake `find_package` / `FetchContent`** export (installs `qvfConfig`,
    exports the `qvf::qvf` target; verified with a consumer project).
  - ⬜ vcpkg / Conan recipes once there's demand.
- ⬜ **Endianness hardening.** Binary members are little-endian-assumed with no
  byte-order tag (spec § 9 open item). Add an explicit marker or a mandated-LE
  validator check for true cross-platform portability.
- ✅ **Reference C++ reader** (`qvf/qvf_reader.hpp`). Completes the round-trip:
  zero-dependency ZIP reader + INFLATE (stored/fixed/dynamic Huffman) + JSON
  parser + sha256 verify. Reads any producer's output (verified reading the
  Python-written golden corpus); included in the single header.

## Standard maturity (Tier 2)

- 🔨 **Neutral, open governance.** Established in-place: `GOVERNANCE.md`
  (open standard stewarded by vibe-qc, producer-neutral, versioning + change +
  promotion process) and a machine-readable `registry.json` (canonical kinds +
  vendor namespaces, drift-guarded against the schema). vibe-qc's origin stays
  explicit. *Optional future step (maintainer + adopter decision):* move to a
  vendor-neutral hosting org with a steering group as independent adopters land.
- ⬜ **A second independent producer** (PySCF is the natural first target — pure
  Python + libcint, so the reference writer drops straight in). A second
  producer is what *earns* vendor→canonical promotions and makes a community
  write-up credible.
- ⬜ **Tighten the loose schemas** (`spectra.nmr`, `spectra.epr`) once two
  producers converge on field names.

## Capability growth (Tier 3, demand-driven)

- ⬜ Canonical **k-resolved Bloch wavefunctions** (spec § 9 open item).
- ⬜ **Large / streaming volumes**: chunking for time-dependent grids; streaming
  writes so a producer needn't hold a giant grid in memory.
- ✅ **`run.record`** (2026-07-24) — verbatim program input + full log +
  attachments with a `program` identity field; makes an archive a
  self-contained record of a calculation (spec § 5.8).
- ✅ **`job.spec`** (2026-07-25) — declarative specification of the requested
  calculation plus a formalized `provenance.run_status` lifecycle
  (`pending | running | converged | failed`); makes an archive an executable
  input a runner can execute and update in place (spec § 5.9, § 3.2).
- ⬜ New canonical kinds as adopters ask (NTOs, transition densities, ESP
  charges, MECP, …) — gated by the vendor namespace + promotion process, not
  guessed up front.

## Toolkit quality

- ⬜ **CI matrix** for the standalone toolkit: gcc / clang / MSVC × a couple of
  C++ standards, the Python writer across Python versions, and the conformance
  suite on every change.
- ⬜ **Fuzz the reader / validator** — it parses untrusted archives.

## Getting involved

If you write a quantum-chemistry code and want to emit QVF (or have vibe-view
read your native format), see the
[integration guide](docs/integration_guide.md). We actively want more producers,
and the format grows with them — missing a field or a kind you need is a
conversation, not a dead end.
