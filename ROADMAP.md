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

## Where we are (2026-10-22)

Phases 1 and the scheduled Phase 2 work are complete. Phase 0 still has
schema hosting (WP-06) open; the core of Phase 3 and the JavaScript reader
of Phase 4 have landed. Toolkit 0.5.0 collects WP-42, WP-43, WP-44, WP-46
and WP-47: C++/C/Python facades and a unified CLI, plus optional Fortran
bindings, cube/XYZ converters and native packaging improvements.
Toolkit 0.4.0 (2026-10-15) defines canonical unrestricted NTO pairing and
completes the v0.3.0 writer APIs while preserving deprecated archive input.
Toolkit 0.2.0 (2026-10-14) releases everything since 0.1.0, with
the sketch-document decisions taken for vibe-sketch on top. Toolkit 0.3.0
(2026-10-15) makes this repository the single source of the format for the
vibe-qc family and merges what its programs already wrote or read.

- ✅ Normative **specification** + machine-readable **JSON Schema**, drift-guarded; every JSON member payload has a schema definition and every unit a name (§ 4.3 vocabulary).
- ✅ Kinds for forces, Hessians, energy components, excited states and NTOs, transition densities, ECPs, overlap and density matrices, two-component wavefunctions, vector / complex / series / Laplacian volumes with periodic-grid semantics, periodic MD trajectories, electric / elastic / dielectric properties, FAIR root metadata, typed provenance and job specs, container rules (`size`, in-place updates, `byte_order`), and provisional `wavefunction.bloch`.
- ✅ Reference **writers** in Python and C++17 (zero-dependency, streaming, ZIP64, `open_for_update`, `repack`), **validators** in Python, C++ and JavaScript with the same stable finding codes; C++ and JavaScript check the schema with the checker generated from it (`scripts/gen_kinds.py`), so the three validators agree on the conformance corpus.
- ✅ Sketch documents (2026-10-14): chemical identity on `structure` sections, `reaction.scheme`, `preview` with the member field `media_type`, job sets (`run.record` `job_ref`), one media type and macOS UTI for `.qvf`, `x_vibesketch` registered, and the withdrawn `qvf_version` 2 read as a warning.
- ✅ Family data (2026-10-15, toolkit 0.3.0): `localization_reference_basis` and three deprecated `mo_metadata` keys, `null` for a `job.spec` `functional` or `basis`, the viewer hints `energy_window`, `camera` and `crossfade`, `structure_ref` on standalone `bonds` sections, and one rule for the withdrawn `qvf_version` 2; qvf is the single source of the format for the family.
- ✅ **Conformance suite**: 75 golden archives (canonical kinds, edge cases and compatibility), 110 must-fail archives, one legacy archive; Python, C++ and JavaScript runners in CI.
- ✅ Typed `Manifest` / `Section` / `MemberSpec` model in C++ and Python, generated kind and unit tables, single-header amalgamation, and `@qvf/core` reader. The complete C ABI covers every canonical kind and preserves all legacy symbols.
- ✅ Governance: every contract change has a dated record in `GOVERNANCE.md` and a `registry.json` promotion; nothing bumped `qvf_version`.

## Release boundary and current main

The latest tagged toolkit is **0.5.0** (2026-10-16), implementing **QVF v1**.
The next candidate is **0.6.0**, prepared on 2026-10-22 for the bounded
adoption-readiness milestone. Qualification and publication are pending.
A toolkit version increment does not require a new archive format, and the
v2 ledger below is not a release gate for additive toolkit work.

Main adds static XSF and geometry-only PDB conversion, a local Conan recipe
with installed C/C++ consumer checks, and `qvf prepare-job` / `qvf.jobs.prepare_job`.
The latter preserves drawing and geometry data while creating an explicit
pending single-job request; the [family workflow](docs/family_workflow.md)
includes an executable Sketch example. These additions form the **0.6.0 candidate**;
they do not imply registry publication, full biomolecular PDB conversion or
multi-species reaction scheduling. See [CHANGELOG](CHANGELOG.md) and the
individual work packages for supported boundaries.

## Milestones and weekly reconciliation

The canonical GitLab project tracks **Next toolkit - adoption readiness** and
**Ecosystem adoption - Phase 4** as development milestones. The first groups
the landed converters, drawing-preserving job preparation and installed
consumer/packaging work for the next bounded release. The second tracks
selection and acceptance of independent consumers and language bindings.
Their acceptance issues link the existing work packages rather than replacing
the briefs. Toolkit 0.6.0 is the selected adoption-readiness candidate; its release
requires qualification and publication acceptance. These milestones do not
schedule a breaking archive format or require all ecosystem proposals for
an additive release.

Every week compare this roadmap and its linked work packages/design records
with main, tags, release notes, issue state and conformance/consumer evidence.
Correct stale status, distinguish implementation from validation and release,
and preserve explicitly deferred work. Once a bounded milestone's acceptance
passes, mark the release target ready and select/advance the next toolkit
version under the normal release process. Package versions and tags still
require candidate checks; archive-format changes follow [governance](GOVERNANCE.md).
Neither a paper deadline nor toolkit milestones automatically increments the
archive format. The v2 ledger remains unscheduled.

## Guiding goals

1. **No vendor section for mainstream data.** A code that computes energies, gradients, Hessians, orbitals (with ECPs), densities, excited states, spectra, bands, phonons, or MD should find a canonical kind for all of it.
2. **Contract, not convention.** Every member payload has a schema; every unit has a name; every reference resolves; the validator proves it.
3. **One library, every language.** Streaming, ZIP64, in-place update, complete C ABI, Fortran, Python, JS reader, Rust crate — all certified by one corpus.
4. **Still v1.** Everything above is additive. Breaking ideas go to the v2 ledger and wait.

## Phase 0 — hygiene and defects (implementation complete except hosting)

Small, independent, mostly mechanical. Clears the ground so later packages do not fight stale references.

- ✅ **WP-01** CHANGELOG, frozen legacy v2 schema, dangling references (D10)
- ✅ **WP-02** Schema description scrub, section-number sync (D01)
- ✅ **WP-03** Portable pi, GitHub Actions matrix incl. MSVC, sanitizers (D14)
- ✅ **WP-04** Writer/schema mismatches: phonon members, `atom_properties` roles, DOS peer fields (D02, D03, D08)
- ✅ **WP-05** Validator hardening + negative corpus + stable finding codes (D15, D17)
- ⬜ **WP-06** Schema `$id` domain and hosting (D09) — current `$id` retained by 2026-10-15 decision; hosting pending
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

## Phase 3 — libqvf (core and C++/C/Python facades landed)

The library other codes link. Core first, then the facades, then every binding over them.

- ✅ **WP-40** Container core: ZIP64, streaming write, append mode, limits, fuzz target (D13, D19)
- ✅ **WP-41** Typed model + schema-driven codegen (kind tables, generated payload checker, unit enum)
- ✅ **WP-42** C++ `Writer`, chunked `TensorView`, all canonical typed kinds and `Editor` (append, optional atomic commit, streaming repack)
- ✅ **WP-43** C++ lazy `Reader`, typed manifest/tensor access, streaming, `get<K>` protocol and staged validation with shared finding codes; canonical kind decoders are supplied by WP-42
- ✅ **WP-44** Complete C ABI: writer for every kind, reader, validator, editor; shared-library export; ABI versioning (D16)
- 🔨 **WP-45** Fortran module over the complete C ABI and checked writers landed; Linux GNU 12 candidate and focused GNU 16/Python interoperability checks pass; other compiler/platform coverage remains
- ✅ **WP-46** Python `qvf` package: model, streaming writer, lazy typed reader, editor, shims (D20)
- ✅ **WP-47** CLI `qvf`: staged validate, info, cat, extract, numeric diff, repack, reported scrub, conformance, schema
- 🔨 **WP-48** Converters: scalar cube and geometry-only XYZ/extXYZ with trajectories are in 0.5.0 ([guide](docs/converters.md)); static XSF primitive geometry/scalar grids and single-model PDB geometry are in the 0.6.0 candidate. Richer extXYZ properties, broader XSF support, Molden, PDB biomolecular metadata, POSCAR/CHGCAR and CIF remain.
- 🔨 **WP-49** Packaging: CMake library-only options and pkg-config metadata landed; a local Conan 2 recipe, installed C/C++ consumers and release/adoption checklist are in the 0.6.0 candidate. PyPI trusted publishing, vcpkg and registry distribution remain.
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

1. Canonical schema domain (WP-06) — decided 2026-10-15: retain the current `$id`; hosting pending.
2. QTAIM position unit (WP-11) — decided: ångström, provisional.
3. Closed `Section` branches once peer fields are named (WP-04) — done.
4. Python distribution name after restructuring (WP-46) — decided 2026-10-15: keep `qvf-writer` and the `qvf_writer` / `qvf_reader` imports.
5. Provisional promotion of `wavefunction.bloch` (WP-30) — decided: promoted, provisional.
6. Whether validators accept the withdrawn `qvf_version` 2 — decided 2026-10-14: read as 1, warning `W_VERSION_WITHDRAWN`.
7. Registering `application/vnd.vibe-qc.qvf+zip` with IANA — decided 2026-10-15: prepare a [draft for maintainer review](docs/iana-media-type-registration.md); submission is not authorized and the media type remains unregistered.

The implementation chats also recorded smaller readings in their
`GOVERNANCE.md` entries (for example the Buckingham quadrupole convention, the
periodic-grid span rule, the Bloch-sum phase, and that writers stamp
`metadata.uuid` / `created_utc` by default); each is open to revision before
the next release.

## Remaining work (reviewed 2026-10-22)

The 2026-10-10 pause has ended. The remaining work is:

- Qualify and publish the bounded 0.6.0 adoption-readiness candidate. Reuse the
  accepted drawing-to-job round trip and installed-consumer evidence; broader
  Fortran/compiler coverage, additional converters and registry publishing remain
  explicit follow-ups, not claims made by this release.
- Phase 3 continues with WP-45 / WP-48, then packaging and broader platform checks. WP-46 supplies the Python `qvf` package while keeping `qvf_writer`, `qvf_reader`, `qvf_kinds`, `qvf_model` and `qvf_units` as compatibility imports. `pip install <checkout>/python` preserves those imports for consumers such as vibe-sketch.
- Parked: WP-06 (hosting the retained schema `$id`), WP-61 (needs a Rust toolchain in CI), compound unit names such as hartree/bohr in the § 4.3 vocabulary, a CI job that runs the C++ / JavaScript / Python schema-checker parity test (it needs all three toolchains in one job), and a coverage-guided fuzzing run on Linux (WP-50).
- Known consumer gap: no consumer renders `wavefunction.bloch` yet. The cc-pV6Z `l = 6` channel-export defect is fixed on vibe-qc main (#546); existing consumer releases may still need that fix. Fresh checks did not reproduce `space_group_number: 0`: absent symmetry is omitted and a genuine group 221 passes.

## Getting involved

If you write a quantum-chemistry code and want to emit QVF, see the
[integration guide](docs/integration_guide.md). Missing a kind or a field is
a conversation, not a dead end: open an issue naming the data, and it enters
Phase 2 with a proposal id.
