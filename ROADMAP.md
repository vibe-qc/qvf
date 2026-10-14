# QVF roadmap

Where the format and the toolkit are, and the order in which they grow. The
plan has two threads that run side by side: **the format** must be able to
carry every mainstream quantum-chemistry result without a vendor section, and
**the library** must be something any code links once and then writes, reads,
validates, and updates archives from C++, C, Fortran, Python, and more.

Three documents hold the detail:

| Document | What it holds |
|---|---|
| [`docs/format_review.md`](docs/format_review.md) | Coverage matrix, defects (D-nn), additive proposals (P-nn), v2 ledger (V2-nn), decisions needed |
| [`docs/library_design.md`](docs/library_design.md) | Target architecture and APIs of libqvf, bindings, packaging, testing |
| [`docs/work_packages.md`](docs/work_packages.md) | Self-contained implementation briefs (WP-nn) with Definition of Done, sized and ordered |

Status legend: ✅ done · 🔨 in progress · ⬜ planned.

## Where we are (verified 2026-10-14)

Phases 0 to 2 are complete, and the core of Phase 3 and the JavaScript reader
of Phase 4 have landed. Work is paused here; the next packages are WP-42, WP-43
and WP-46. Toolkit 0.2.0 (2026-10-14) releases everything since 0.1.0, with
the sketch-document decisions taken for vibe-sketch on top.

- ✅ Normative **specification** + machine-readable **JSON Schema**, drift-guarded; every JSON member payload has a schema definition and every unit a name (§ 4.3 vocabulary).
- ✅ Kinds for forces, Hessians, energy components, excited states and NTOs, transition densities, ECPs, overlap and density matrices, two-component wavefunctions, vector / complex / series / Laplacian volumes with periodic-grid semantics, periodic MD trajectories, electric / elastic / dielectric properties, FAIR root metadata, typed provenance and job specs, container rules (`size`, in-place updates, `byte_order`), and provisional `wavefunction.bloch`.
- ✅ Reference **writers** in Python and C++17 (zero-dependency, streaming, ZIP64, `open_for_update`, `repack`), **validators** in Python, C++ and JavaScript with the same stable finding codes; C++ and JavaScript check the schema with the checker generated from it (`scripts/gen_kinds.py`), so the three validators agree on the conformance corpus.
- ✅ Sketch documents (2026-10-14): chemical identity on `structure` sections, `reaction.scheme`, `preview` with the member field `media_type`, job sets (`run.record` `job_ref`), one media type and macOS UTI for `.qvf`, `x_vibesketch` registered, and the withdrawn `qvf_version` 2 read as a warning.
- ✅ **Conformance suite**: 66 golden archives (one per canonical kind and the edge cases), 94 must-fail archives, one legacy archive; Python, C++ and JavaScript runners in CI.
- ✅ Typed `Manifest` / `Section` / `MemberSpec` model in C++ and Python, generated kind and unit tables, single-header amalgamation, C ABI for most kinds, `@qvf/core` reader.
- ✅ Governance: every contract change has a dated record in `GOVERNANCE.md` and a `registry.json` promotion; nothing bumped `qvf_version`.

## Guiding goals

1. **No vendor section for mainstream data.** A code that computes energies, gradients, Hessians, orbitals (with ECPs), densities, excited states, spectra, bands, phonons, or MD should find a canonical kind for all of it.
2. **Contract, not convention.** Every member payload has a schema; every unit has a name; every reference resolves; the validator proves it.
3. **One library, every language.** Streaming, ZIP64, in-place update, complete C ABI, Fortran, Python, JS reader, Rust crate — all certified by one corpus.
4. **Still v1.** Everything above is additive. Breaking ideas go to the v2 ledger and wait.

## Phase 0 — hygiene and defects (done)

Small, independent, mostly mechanical. Clears the ground so later packages do not fight stale references.

- ✅ **WP-01** CHANGELOG, frozen legacy v2 schema, dangling references (D10)
- ✅ **WP-02** Schema description scrub, section-number sync (D01)
- ✅ **WP-03** Portable pi, GitHub Actions matrix incl. MSVC, sanitizers (D14)
- ✅ **WP-04** Writer/schema mismatches: phonon members, `atom_properties` roles, DOS peer fields (D02, D03, D08)
- ✅ **WP-05** Validator hardening + negative corpus + stable finding codes (D15, D17)
- ⬜ **WP-06** Schema `$id` domain and hosting (D09) — needs decision
- ✅ **WP-07** Deprecate `provenance.hostname`; sanitisation guidance (D11)

## Phase 1 — contract completeness (done)

Turns prose into schema. The largest single step toward "a standard external codes can adopt". Opus-grade work; three batches that can run in parallel.

- ✅ **WP-10** Payload schemas A: grid, basis, mo_metadata, trajectory family, vibrations (P01)
- ✅ **WP-11** Payload schemas B: spectra (typed NMR/EPR, peaks, broadening), bonds, bond orders, SCF history, QTAIM with unit, symmetry (P01, P13, D05, D18)
- ✅ **WP-12** Payload schemas C: kpath, DOS meta, Fermi mesh, qpath, phonon meta, EOS fit, run-record files; spin axis on projections; `bands.occupations` (P01, P14, D04)
- ✅ **WP-13** Units vocabulary and self-describing `units` objects (P02, D12)
- ✅ **WP-14** Corpus v2: one archive per kind, edge cases, ZIP64 and descriptor archives, C++ runner
- ✅ **WP-15** Lattice conventions documented + `Lattice` helper (D06)

## Phase 2 — format expansion (additive under v1; done, demand-driven items open)

Each item is spec + schema + registry + both writers + validator + corpus + docs + decision record. Ordered by how often the data appears in practice.

- ✅ **WP-20** Root `metadata` (FAIR) and generic `structure_ref` / `run_ref` / `group` (P03, P04)
- ✅ **WP-21** `energies` root block, `forces`, `hessian` kinds (P05–P07)
- ✅ **WP-22** `excited_states` kind, NTOs, `volume.transition_density` (P08)
- ✅ **WP-23** Wavefunction: ECP, overlap, density matrix, two-component, labels; normalization becomes checkable (P09)
- ✅ **WP-24** `atom_properties`: more schemes, vector roles, `custom.<name>` (P10)
- ✅ **WP-25** Volumes: vector, complex, series, Laplacian; periodic grid endpoint rule (P11)
- ✅ **WP-26** Trajectories: cell, velocities, forces, times, float32 MD (P12)
- ✅ **WP-27** Provenance and job-spec tightening (P18)
- ✅ **WP-28** Container rules: member `size`, orphans, in-place update semantics, `byte_order` (P19, P20)
- ✅ **WP-29** Periodic extras: Fermi mesh shifts, electric/elastic/dielectric properties, magnetic moments (P14, P17)
- ✅ **WP-30** `wavefunction.bloch` provisional canonical (P15) — promoted provisionally
- ⬜ Demand-driven, not scheduled: `wavefunction.nao` / `.sto` (P16), `spectra.xas` / `.mossbauer` (P13)

## Phase 3 — libqvf (core landed; paused)

The library other codes link. Core first, then the facades, then every binding over them.

- ✅ **WP-40** Container core: ZIP64, streaming write, append mode, limits, fuzz target (D13, D19)
- ✅ **WP-41** Typed model + schema-driven codegen (kind tables, generated payload checker, unit enum)
- ⬜ **WP-42** C++ `Writer` (streaming sinks, `TensorView`) and `Editor` (in-place update, repack)
- ⬜ **WP-43** C++ `Reader` typed accessors + validator with shared finding codes
- ⬜ **WP-44** Complete C ABI: writer for every kind, reader, validator, editor; shared-library export; ABI versioning (D16)
- ⬜ **WP-45** Fortran module over the C ABI, gfortran CI
- ⬜ **WP-46** Python `qvf` package: model, streaming writer, lazy typed reader, editor, shims (D20)
- ⬜ **WP-47** CLI `qvf`: validate, info, cat, extract, diff, repack, scrub, conformance
- ⬜ **WP-48** Converters: cube, XYZ/extXYZ, Molden, PDB, XSF, POSCAR/CHGCAR, CIF
- ⬜ **WP-49** Packaging: PyPI (trusted publishing), pkg-config, vcpkg, conan, release checklist
- ⬜ **WP-50** Fuzzing in CI, big-endian QEMU job

## Phase 4 — ecosystem

- ✅ **WP-60** JavaScript/TypeScript reader (`@qvf/core`) — enables web viewers and notebooks
- ⬜ **WP-61** Rust crate — independent implementation certified by the corpus
- ⬜ **WP-62** PySCF adapter — the second independent producer; earns real promotions
- ⬜ **WP-63** vibe-qc links libqvf instead of carrying its own implementation (maintainer note; after WP-42/43/46 stabilise; not high priority)
- ⬜ **WP-64** Docs site with generated API reference and kind catalogue
- ⬜ **WP-65** Julia binding (demand-driven)
- ⬜ Governance: as independent producers ship, the steering model broadens per `GOVERNANCE.md` § "Evolving the governance"

## Phase 5 — v2 (collect, do not schedule)

`docs/format_review.md` § 4 keeps the ledger: byte order in dtype names, chunked
members and alternative compression, dtype expansion, one length unit, one
lattice convention, spectrum axis rename, required structure refs, manifest
self-hash. A v2 is cut only when the ledger is worth a breaking release for
every consumer, and never for an optional field.

## Sequencing at a glance

```
Phase 0 (parallel, S/M) ─┬─ WP-10 ─┐
                         ├─ WP-11 ─┼─ WP-13 ─ WP-14 ─┬─ WP-60, WP-61
                         └─ WP-12 ─┘                 │
                                   └─ WP-20 … WP-30 ─┤
WP-40 ─ WP-42 ─ WP-44 ─ WP-45, WP-65                  │
WP-41 ─ WP-43, WP-46 ─ WP-47, WP-48 ─ WP-49, WP-50    │
                                      └─ WP-62, WP-63 ┘
```

## Decisions the maintainer owns before the affected packages start

1. Canonical schema domain (WP-06) — open.
2. QTAIM position unit (WP-11) — decided: ångström, provisional.
3. Closed `Section` branches once peer fields are named (WP-04) — done.
4. Python distribution name after restructuring (WP-46) — open.
5. Provisional promotion of `wavefunction.bloch` (WP-30) — decided: promoted, provisional.
6. Whether validators accept the withdrawn `qvf_version` 2 — decided 2026-10-14: read as 1, warning `W_VERSION_WITHDRAWN`.
7. Registering `application/vnd.vibe-qc.qvf+zip` with IANA — open; the media type is in use unregistered.

The implementation chats also recorded smaller readings in their
`GOVERNANCE.md` entries (for example the Buckingham quadrupole convention, the
periodic-grid span rule, the Bloch-sum phase, and that writers stamp
`metadata.uuid` / `created_utc` by default); each is open to revision before
the next release.

## Pause (2026-10-10)

Work on QVF is paused after this round. When it resumes:

- Phase 3 continues with WP-42 (C++ `Writer` / `Editor`, atomic in-place updates), WP-43 (typed reader accessors) and WP-46 (the Python `qvf` package; `python/qvf_kinds.py` and `python/qvf_model.py` are flat modules until then), then WP-44 / WP-45 / WP-47. WP-46 must keep `qvf_writer` and `qvf_reader` importable as top-level modules from `pip install <checkout>/python`: vibe-sketch installs them that way and pins a release tag.
- Parked: WP-06 (schema `$id` domain), WP-61 (needs a Rust toolchain in CI), compound unit names such as hartree/bohr in the § 4.3 vocabulary, a CI job that runs the C++ / JavaScript / Python schema-checker parity test (it needs all three toolchains in one job), and a coverage-guided fuzzing run on Linux (WP-50).
- Known consumer gaps: no consumer renders `wavefunction.bloch` yet; the C ABI cannot write periodic structures; vibe-qc still writes `l = -1` and `space_group_number: 0`, which the validators now reject.

## Getting involved

If you write a quantum-chemistry code and want to emit QVF, see the
[integration guide](docs/integration_guide.md). Missing a kind or a field is
a conversation, not a dead end: open an issue naming the data, and it enters
Phase 2 with a proposal id.
