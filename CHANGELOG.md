# Changelog

All notable changes to the QVF format and to this toolkit are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Decisions that affect the on-disk contract are argued in full in
[`GOVERNANCE.md`](GOVERNANCE.md); this file is the short, dated index of them.
The toolkit version is in [`VERSION`](VERSION) and the format version
(`qvf_version`) is described in the governance versioning policy.

## [Unreleased]

## [0.2.0] - 2026-10-14

The format and toolkit changes since 0.1.0, all within QVF v1
(`qvf_version = 1`). The last group of format decisions makes QVF the document
format of vibe-sketch, the structure and reaction sketcher: chemical identity
on `structure` sections, the `reaction.scheme` and `preview` kinds, the member
field `media_type`, job sets, one media type and one macOS UTI for `.qvf`,
and the withdrawn `qvf_version` 2 read as a warning
([Decisions](GOVERNANCE.md#2026-10-14--sketch-documents-chemical-identity-reactionscheme-preview-job-sets)).
None of the changes bumps `qvf_version`.

### Deprecated

- `provenance.hostname` (spec § 3.2): producers SHOULD NOT emit it; consumers
  MUST ignore it except for display. The schema property is annotated
  `"deprecated": true`; existing archives remain valid. No `qvf_version`
  bump (D11, WP-07).
- The unit spellings `Eh`, `eV` and `Hartree` in a `{value, units}` object
  (`provenance.scf_energy`, `provenance.fermi_energy`): still valid there as
  `$defs/LegacyUnitName`, read as `hartree` and `ev`; producers SHOULD write
  the unit name (D12, WP-13).

### Added

- Chemical identity on `structure` sections (spec § 5.1): optional section
  fields `charge`, `multiplicity`, `name`, `smiles`, `inchi` and `inchikey`;
  the generic `label` is the species' compound label. Validators report a
  charge and multiplicity impossible for the atoms as the new error
  `E_CHARGE_MULTIPLICITY`, and, in an archive with one structure, a
  disagreement with `provenance.charge` / `provenance.multiplicity` as
  `E_ROOT_INCONSISTENT`. Python `add_structure` takes the six fields.
- `reaction.scheme`, a canonical kind (spec § 5.14): steps in reading order
  relating `structure` sections as reactants, reagents and products, each
  with an optional stoichiometric coefficient, under a `forward`,
  `equilibrium`, `retrosynthetic` or `resonance` arrow, with the conditions
  and the yield (`yield_percent`, `yield_text`). Roles are chemical whatever
  the arrow; the step key `energies` is reserved for reaction energies.
  Validators resolve every participant (`E_REF_UNRESOLVED`) and reject
  duplicate step ids and repeated participants (`E_MEMBER_MALFORMED`).
  Python `add_reaction_scheme`.
- `preview`, a canonical kind (spec § 5.15): a raster `thumbnail`
  (`image/png` or `image/jpeg`) and an optional `image` (also
  `image/svg+xml`), both opaque members with a required `media_type`; the
  archive's picture is the thumbnail of the first `preview` section, and SVG
  is self-contained and inert. Validators check the bytes against the media
  type (`E_MEMBER_MALFORMED`, `E_UTF8`). Python `add_preview` sniffs and
  checks the image type and stores the members uncompressed.
- `media_type`, an optional field of every member spec (spec § 4.2): the IANA
  media type of the member's bytes. Vendor sections may carry opaque members
  (binary without dtype and shape); Python `add_vendor_section` takes
  `opaque_members=`.
- Job sets (spec § 5.9): an archive may carry several `job.spec` sections,
  each naming its structure; `run.record` gains `job_ref` (the job it ran,
  resolved by validators) and `run_status` (its outcome), and
  `provenance.run_status` summarises the set. Python `add_run_record` takes
  `job_ref=` and `run_status=`, and `add_job_spec` writes `structure_ref` on
  the section object as well as in the payload.
- File identification (spec § 2.4): the extension `.qvf`, the media type
  `application/vnd.vibe-qc.qvf+zip` and the macOS Uniform Type Identifier
  `com.vibe-qc.qvf` (conforming to `public.zip-archive` and
  `public.content`), in `registry.json` (`file_type`) and as declarations to
  copy in `spec/file-type/` (`qvf-uti.plist`, `qvf-mime.xml`).
- `registry.json` registers the vendor namespace `x_vibesketch`.
- Finding codes `W_VERSION_WITHDRAWN` and `E_CHARGE_MULTIPLICITY`
  (Appendix B).
- C++ reference writer: `add_reaction_scheme`, `add_preview`,
  `set_structure_identity`, `remove_section`, `add_opaque_member` and an
  `add_vendor_section` overload with `OpaqueMember`s, `RunRecord::job_ref`
  and `run_status`; `qvf::MemberSpec::media_type` in the typed model; a member
  of an update whose path the archive already holds gets a fresh path
  (`<stem>.<n><suffix>`) instead of an exception, `begin_binary` included;
  `open_for_update` accepts `qvf_version: 2` and writes 1.
  `write_all_kinds` covers all 56 canonical kinds. The C++ and JavaScript
  validators implement every new rule with the codes and locations of the
  Python one (`@qvf/core` also types `media_type` and regenerates its kind
  list).
- Python reference writer: `label=` on every `add_*` method;
  `remove_section(id)`, which with an `add_*` under the same id replaces a
  section; `open_for_update` takes an archive's bytes as well as its path;
  `to_bytes(repack=True)` and `write(..., repack=True)` drop superseded
  entries; a member of an update whose default path the archive already
  holds gets a fresh path instead of an error.
- Conformance corpus: `reaction_scheme.qvf` (eight species with their
  identity, a three-step scheme, a preview, an opaque vendor member) and
  `job_set.qvf` (a job set halfway through); ten negative archives for the
  new rules.
- Spec § 5.8 "Sharing and sanitisation": run.record inputs, logs,
  attachments, `command`, and `files` filenames may carry paths, user names,
  and host names; producers SHOULD offer suppression or redaction; a toolkit
  `scrub` operation is the intended mechanism (WP-07).
- C++ `qvf::Json::erase(key)` (WP-07).
- Payload schemas for the spectra and analysis members (spec § 5.4, § 5.7,
  § 6): `$defs/SpectrumPayload` for the six 1-D spectra, with new optional
  `x_units`, `y_units`, `x`, `peaks`, `broadening`, `temperature_k`, `raman`
  and `uvvis` (`frequencies` keeps the x axis in the kind's § 4.3 unit);
  typed `NmrSpectrumPayload` and `EprSpectrumPayload`; strict `BondsPayload`
  (also the `structure` section's `bonds` member), `BondOrdersPayload` and
  `ScfHistoryPayload`; `QtaimPayload` with an optional `units` object
  (positions in Å unless declared, a provisional default); `SymmetryPayload`.
  Validators check each with `E_PAYLOAD_SCHEMA`, including the equal-length
  rule of a 1-D spectrum, so malformed payloads that used to pass now fail.
  Corpus `spectra_all.qvf`, `nmr.qvf`, `qtaim.qvf`, `symmetry.qvf`; three
  negative payload archives. Python `add_spectrum` checks array lengths and
  takes `x_units`, `y_units`, `peaks`, `broadening`; `add_topology_qtaim`
  takes `units`. No `qvf_version` bump (P01, P13, D05, D18, WP-11).
- Payload definitions for the geometry and wavefunction JSON members: volume
  `grid` and `reaction.path` `volume_grid` (`$defs/VolumeGridPayload`),
  `wavefunction.gto` `basis` and `mo_metadata` (`BasisPayload`,
  `MoMetadataPayload`), and the `metadata` / `waypoints` payloads of
  `trajectory`, `reaction.path`, `reaction.waypoints`, `scan.surface` and
  `vibrations`. Spec § 5.2, § 5.3 and § 5.5 gain payload tables, and § 6
  checks every JSON member that has a payload definition (`E_PAYLOAD_SCHEMA`).
  Additive, no `qvf_version` bump; a previously unconstrained malformed
  payload now fails validation. Corpus gains `trajectory.qvf`,
  `vibrations.qvf`, `scan_surface.qvf` and `reaction_path.qvf`; the negative
  corpus gains three `payload_*` archives (P01, D07, WP-10).
- Schema and spec § 5.6: optional members `phonon_bands.eigenvectors`
  (float64 `[n_q, n_modes, n_atoms, 3]`, or `[n_q, n_modes, n_atoms, 3, 2]`
  with the last axis `[re, im]`) and `phonon_dos.projected` (float64
  `[n_channels, n_points]`, rows labelled by `meta.channels`); the `dos.total`
  / `dos.projected` section fields `n_spin`, `smearing`, `smearing_type`,
  `fermi_energy_ev`, `n_electrons` and `channels` named as optional typed
  properties. The `atom_properties` roles (`mulliken_charge`,
  `loewdin_charge`, `hirshfeld_charge`, `iao_charge`, `spin_population`) are
  one list in the schema and spec § 5 / § 5.7. Corpus archives `phonons.qvf`
  and `atom_properties_all.qvf`. No `qvf_version` bump (D02, D03, D08, WP-04).
- Payload definitions for the periodic kinds and the run-record `files` index
  (spec § 5.6, § 5.8): strict `$defs/KpathPayload` (with `KpathSegment`),
  `FermiMeshPayload`, `QpathPayload`, `EosFitPayload` and
  `RunRecordFilesPayload`; typed-open `DosMetaPayload` (`dos.coop` /
  `dos.cohp` `meta`), `PhononMetaPayload` and the shared `DosChannel`. The
  Python validator checks each member against its definition
  (`E_PAYLOAD_SCHEMA`) through a `(kind, role)` table. No `qvf_version` bump
  (P01, P14, D07, WP-12).
- Spin axis on projections: `bands.projections` `[n_spin, n_k, n_bands,
  n_channels]` and `dos.projected.projections` `[n_spin, n_channels,
  n_points]`; the lower-rank shapes stay legal and mean `n_spin = 1`. New
  optional `bands.occupations` `[n_spin, n_k, n_bands]`. Both validators report
  shapes that disagree with `eigenvalues` as `E_MEMBER_MALFORMED`; Python and
  C++ `add_bands` take `occupations` (C++: a new overload), and the writers
  refuse disagreeing shapes (D04, WP-12).
- Conformance corpus: `bands_spin.qvf`, `dos.qvf`, `fermi_surface.qvf`,
  `eos.qvf`; negative corpus: `bands_spin_mismatch.qvf`,
  `eos_model_unknown.qvf` (WP-12).
- Unit vocabulary (spec § 4.3, "Unit names" and "Declared units";
  `$defs/UnitName`, 25 names from `angstrom` to `dimensionless`). Every payload
  `units` object (now also on the volume grid), the 1-D spectrum's `x_units`,
  `y_units` and `broadening.units`, and `ValueWithUnits.units` are typed as
  unit names, and declarations of units § 4.3 fixes are `const` in the payload
  definitions. New warning `W_UNIT_UNKNOWN` in the Python, C++ and JavaScript
  validators. Python module `qvf_units` (`UNITS`, `LEGACY_UNITS`, `is_unit`,
  `canonical`, `convert`, `fixed_units`) and C++ header `qvf/units.hpp`
  (`qvf::Unit`, `unit_name`, `parse_unit`, `canonical_unit`, `convert`), with
  CODATA 2018 length and energy conversions; JavaScript `UNIT_NAMES`,
  `isUnitName`, `canonicalUnit`. Python `add_volume`, `add_trajectory` and
  `add_scan_surface` take `units=`; C++ `Grid::units`, `Spectrum::x_units` /
  `y_units`. Corpus `units_declared.qvf`; negative `unit_unknown.qvf`,
  `unit_contradicts_fixed.qvf`. No `qvf_version` bump (P02, D12, WP-13).
- Root `energies` block (spec § 3.6, `$defs/Energies`): `total`, `method`,
  `components` (`nuclear_repulsion`, `electronic`, `one_electron`,
  `two_electron`, `exchange_correlation`, `exchange`, `correlation`,
  `dispersion`, `solvation`, `zpve`, `thermal`, `embedding`, `x_` keys),
  `by_method` and `units_note`. An energy stated for the method
  `provenance.method` names must agree with `provenance.scf_energy`, and
  `components.zpve` with `thermochemistry.zpve_eh`, within 1e-8 hartree; new
  finding code `E_ROOT_INCONSISTENT` in Appendix B and all three validators.
  No `qvf_version` bump (P05, WP-21).
- Canonical kinds `forces` (spec § 5.10: `gradient` float64 `[n_atoms, 3]`
  in hartree/bohr, the energy gradient, so forces are its negative; optional
  `stress` `[3, 3]` in hartree/bohr³ and strict `meta`) and `hessian` (spec
  § 5.11: `matrix` float64 `[3N, 3N]` in hartree/bohr², optional strict
  `meta` with `mass_weighted`, `projected`, `atom_masses_amu`), registered as
  promotions by maintainer decision; optional `vibrations.hessian_ref`.
  Validators check the shapes against the section's structure
  (`E_MEMBER_MALFORMED`) and resolve `meta.structure_ref` and `hessian_ref`
  (`E_REF_UNRESOLVED`). Writers: Python `set_energies`, `add_forces`,
  `add_hessian`, `add_vibrations(hessian_ref=)`; C++ `set_energies`,
  `add_forces`, `add_hessian`, `add_vibrations(..., hessian_ref)`; C ABI
  `qvf_set_energies_json`, `qvf_add_forces`, `qvf_add_hessian`. The
  JavaScript reader exports the `Energies` types. Corpus `forces_hessian.qvf`;
  negative corpus `forces_atom_count.qvf`, `hessian_not_square.qvf`,
  `energies_inconsistent.qvf`. No `qvf_version` bump (P06, P07, WP-21).
- Periodic grid semantics (spec § 5.2, `$defs/VolumeGridPayload`): optional
  grid fields `periodic` (three booleans), `includes_endpoint` (default
  `true`, cube style: the last plane repeats the first; `false`, CHGCAR style:
  `shape[a]` planes per period) and `structure_ref`. § 5.2 is rewritten around
  the point positions, a cube-vs-CHGCAR worked example and the rule that a
  consumer tiling a cube-style grid MUST drop the duplicated plane. All three
  validators check that a periodic axis is periodic in the grid's structure
  and that `voxel_vectors[a] × (shape[a] − 1)` (or `× shape[a]`) equals the
  lattice row in bohr within 1e-6 relative (`E_MEMBER_MALFORMED`), and
  resolve a grid `structure_ref` (`E_REF_UNRESOLVED`). This resolves a silent
  cube/CHGCAR interoperability bug. No `qvf_version` bump (P11, WP-25).
- Canonical kinds `volume.vector` (`[nx, ny, nz, 3]`,
  `$defs/Volume4DVectorBinary`), `volume.complex` (`[nx, ny, nz, 2]`, last
  axis `[re, im]`, `$defs/Volume4DComplexBinary`), `volume.series`
  (`[n, nx, ny, nz]` with a required strict `axis` member,
  `$defs/VolumeSeriesAxisPayload`: `kind` time / frame / state / custom,
  `values`, `units`, `labels`, `trajectory_ref`) and `volume.laplacian`
  (∇²ρ in e/bohr⁵, a new § 4.3 row), registered as promotions by maintainer
  decision. Validators check the rank and trailing axis of each, a series
  axis against its slabs (`E_MEMBER_MALFORMED`) and its `trajectory_ref`
  (`E_REF_UNRESOLVED`); an unknown series axis unit is `W_UNIT_UNKNOWN`.
  `reaction.path` `frame_volumes` + `volume_grid` are documented as the older
  form of a frame `volume.series`, which producers SHOULD prefer; both stay
  valid. Writers: Python `add_volume(..., periodic=, includes_endpoint=,
  structure_ref=, axis=)` with 4-D data for the new kinds; C++
  `Grid::periodic` / `includes_endpoint` / `structure_ref`, `add_volume` for
  the new kinds and `add_volume_series`; C ABI `qvf_add_volume` and
  `qvf_add_volume_series` (the first generic volume entry points). The
  JavaScript reader exports `BOHR_PER_ANGSTROM`. Corpus `volume_periodic.qvf`,
  `volume_vector.qvf`, `volume_complex.qvf`, `volume_series.qvf`,
  `volume_laplacian.qvf`; negative corpus `volume_periodic_span.qvf`,
  `volume_endpoint_count.qvf`, `volume_series_axis_length.qvf`,
  `volume_vector_trailing_axis.qvf`. No `qvf_version` bump (P11, WP-25).
- Canonical kind `wavefunction.bloch`, **provisional** (spec § 5.3.1): the
  k-resolved Bloch orbitals of a periodic system over the `wavefunction.gto`
  `basis` payload, with a strict `kpoints` payload
  (`$defs/BlochKpointsPayload`: fractional k-points, `weights` summing to 1,
  `labels`, `mesh`, `shift`, `time_reversal`), a strict `mo_metadata`
  (`$defs/BlochMoMetadataPayload`: `spin`, `n_spin`, `n_mo`, `n_ao`,
  `complex`, `k_point_convention`, `orbital_kind`, `n_mo_per_k`,
  `fermi_energy`), complex `mo_coefficients` float64 `[n_k, n_spin, n_mo,
  n_ao, 2]`, and `energies` (hartree) and `occupations` `[n_k, n_spin,
  n_mo]`. The spec states the Bloch sum φ_μk(r) = N^(−1/2) Σ_T e^{+ik·T}
  χ_μ(r − T). Promoted from `x_vibeqc.bloch_wavefunction` ahead of the
  two-producer threshold by maintainer decision; the registry `promotions`
  entry carries `"status": "provisional"` until a second producer ships it.
  The Python, C++ and JavaScript validators check the member shapes, the
  weights and a periodic structure (`E_MEMBER_MALFORMED`,
  `E_REF_UNRESOLVED`). Writers: Python `add_wavefunction_bloch`, C++
  `WavefunctionBloch` + `add_wavefunction_bloch`, C ABI
  `qvf_add_wavefunction_bloch`. Corpus `bloch.qvf` (with a `bands` section at
  the same k-points); negative corpus `bloch_weights_sum.qvf`,
  `bloch_coefficients_trailing_axis.qvf`, `bloch_occupations_shape.qvf`,
  `bloch_structure_molecular.qvf`. Spec § 7.5 records provisional
  promotions and § 9 item 2 what is still open. No `qvf_version` bump (P15,
  WP-30).
- `atom_properties` roles (spec § 5 table, § 5.7, schema
  `$defs/SectionAtomProperties`): 17 new scalar roles, float64 `[n_atoms]`
  (`cm5_charge`, `chelpg_charge`, `resp_charge`, `esp_charge`, `nbo_charge`,
  `mbis_charge`, `bader_charge`, `ddec_charge`, `valence`, `bonded_valence`,
  `fukui_plus`, `fukui_minus`, `fukui_zero`, `dual_descriptor`,
  `atomic_energy_eh`, `atomic_volume_bohr3`, `nmr_shielding_iso_ppm`), two
  vector roles, float64 `[n_atoms, 3]` (`$defs/AtomVectorBinary`:
  `magnetic_moment` in μB and `force_eh_bohr`, the energy gradient in
  hartree/bohr), and `custom.<name>` roles described by a strict `meta`
  member (`$defs/AtomPropertiesMetaPayload`: `units`, `description`,
  `kind`). Spec § 5.7 gains a role table with unit and sign conventions.
  Validators report a `custom.*` member without a `meta` entry as
  `E_MEMBER_MALFORMED` (Python, C++, JavaScript). Corpus
  `atom_properties_extended.qvf` and four negative archives
  (`atom_properties_custom_no_meta.qvf`,
  `atom_properties_custom_meta_entry_missing.qvf`,
  `atom_properties_vector_shape.qvf`, `atom_properties_role_unknown.qvf`).
  No `qvf_version` bump (P10, WP-24).
- Root `metadata` block (spec § 3.5, `$defs/Metadata`): `title`,
  `description`, `created_utc`, `modified_utc`, `uuid`, `authors`
  (`$defs/MetadataAuthor`), `license`, `doi`, `keywords`, `derived_from`,
  `tags`; strict, with the time stamps (ISO 8601 UTC, `Z`) and the RFC 4122
  `uuid` pattern-checked by the schema. Authors' `email` and `affiliation`
  are personal data that producers SHOULD NOT emit by default. No
  `qvf_version` bump (P03, WP-20).
- Section fields `structure_ref`, `run_ref` and `group` on any section (spec
  § 4.1). All three validators (Python, C++, JS) report a `structure_ref`
  that does not name a `structure` section, or a `run_ref` that does not name
  a `run.record`, as `E_REF_UNRESOLVED`. A section's `structure_ref` takes
  precedence over the one in a `wavefunction.gto` `basis` payload. No
  `qvf_version` bump (P04, WP-20).
- Writers: Python `set_metadata(**fields)` and `annotate_section(section_id,
  structure_ref=, run_ref=, group=, label=)`; C++ `set_metadata(Json)`,
  `set_section_field(id, key, value)` and `annotate_section(id,
  structure_ref, run_ref, group)`; C ABI `qvf_set_metadata_json` and
  `qvf_annotate_section`. The JS model types gain `Metadata`,
  `MetadataAuthor` and the three section fields (WP-20).
- Conformance corpus: `multi_structure.qvf`; negative corpus:
  `structure_ref_wrong_kind.qvf`, `run_ref_unresolved.qvf`,
  `trajectory_ref_wrong_kind.qvf`, `metadata_uuid_invalid.qvf` (WP-20).
- Conformance corpus v2 and a C++ runner. Every canonical kind of
  `registry.json` now has a positive archive, and
  `python/tests/test_corpus_coverage.py` keeps it so (new: `bonds.qvf`,
  `volume_orbital.qvf`, `volume_spin.qvf`, `volume_elf.qvf`,
  `volume_potential.qvf`, `volume_rdg.qvf`, `volume_generic.qvf`,
  `volume_difference.qvf`, `basis_ao.qvf`, `dos_coop.qvf`, `citations.qvf`).
  Edge cases: `wavefunction_uhf.qvf`; `wavefunction_cartesian.qvf`, a
  `pure: false` d shell whose Appendix A.1 self-overlaps (1 axial, 1/3 for
  `d_xy`) are stored in an `x_conformance.overlap_diagonal` vendor section;
  `structure_wire_1d.qvf`; `reaction_path_variable_cell.qvf`; `zip64.qvf`
  (ZIP64 structures forced on small members) and `data_descriptor.qvf`
  (streamed members). A new `conformance/legacy/` holds an archive stamped
  `qvf_version: 2`, which the validators reject with `E_VERSION` pending a
  maintainer decision; the Python and JavaScript runners treat it like
  `negative/`. `cpp/examples/run_conformance.cpp` implements the whole check
  format for the C++ reader (CTest `qvf_conformance`, and a step in both CI
  pipelines); it lists `zip64.qvf` as a known gap, because the C++ ZIP layer
  has no ZIP64 yet. No spec or schema change, no `qvf_version` bump (WP-14).
- Typed `provenance` fields (spec § 3.2, now a table of every recognised
  field): `software` (`$defs/ProvenanceSoftware`: `name`, `version`, `url`),
  `git_commit` (7 to 64 hexadecimal characters), `n_threads`, `n_mpi_ranks`,
  `n_gpus`, `started_utc` and `finished_utc` (ISO 8601 UTC); the block stays
  open and `wall_seconds` keeps its name. `provenance.n_electrons` must agree
  with `basis.n_electrons`. Python `set_provenance` and C++ `set_provenance`
  check them. No `qvf_version` bump (P18, WP-27).
- Typed `job.spec` fields (spec § 5.9): `structure_ref`, `solvation`
  (`model`, `solvent`, `epsilon`), `dispersion`, `relativistic`, `scf`
  (`convergence`, `max_iterations`, `guess`, `damping`), `geometry`
  (`convergence`, `max_steps`, `coordinates`) and `resources` (`n_cores`,
  `memory_mb`, `walltime_s`; hints, not requirements); the blocks are strict
  with `x_` keys allowed, the root stays open and engine keywords stay under
  `options`. All three validators resolve a payload's `structure_ref` with
  `E_REF_UNRESOLVED`. Python `add_job_spec` takes the new fields as
  arguments, C++ `add_job_spec(Json)` checks them, and the C ABI gains
  `qvf_add_job_spec_json`. Corpus `job_spec_full.qvf` and
  `provenance_full.qvf`; negative `job_spec_structure_ref_wrong_kind.qvf`,
  `provenance_git_commit_not_hex.qvf`, `provenance_started_utc_not_utc.qvf`.
  The JS model types gain the provenance fields. No `qvf_version` bump (P18,
  WP-27).
- Optional member `size` on every member spec (`$defs/MemberSize`, spec
  § 4.2): the uncompressed byte count of the stored member, equal to the size
  its ZIP entry records. The Python and C++ writers write it for every
  member; the Python, C++ and JavaScript validators check it against the
  central directory before reading the member (`E_BINARY_SIZE`, wording
  widened; a malformed `size` is `E_MEMBER_MALFORMED`), and the readers refuse
  such a member. No `qvf_version` bump (P19, WP-28).
- Spec § 2.3 "Updating an archive in place": an update appends entries,
  writes a new `manifest.json` last and never reuses another entry's name;
  the previous manifest and replaced members are orphans (`W_ORPHAN_MEMBER`)
  that consumers ignore; consumers read the last `manifest.json`; `repack`
  removes orphans; `metadata.modified_utc`, `run.record.sequence` and
  `provenance.run_status` record the update. Validators report a duplicated
  `manifest.json` as `W_ORPHAN_MEMBER` for each superseded copy instead of
  `E_ZIP_DUPLICATE_ENTRY`, a clarification of the 2026-10-07 duplicate rule;
  the Python, C++ and JavaScript readers open such archives. No `qvf_version`
  bump (P19, WP-28).
- Optional root `byte_order`, `const: "little"` (spec § 2.2, § 3.1): states
  the byte order every v1 archive already has; any other value fails the
  schema (`E_SCHEMA`) and the readers refuse it. Both writers emit it; v2
  moves the byte order into the dtype names (V2-01). No `qvf_version` bump
  (P20, WP-28).
- Conformance corpus `updated_in_place.qvf` (two `manifest.json` entries, an
  orphaned member, validates with warnings) and `size_declared.qvf`; negative
  corpus `member_size_mismatch.qvf` and `byte_order_big.qvf` (WP-28).
- Trajectory extensions (spec § 4.3, § 5.5): optional `trajectory` members
  `lattice` (float64 `[3, 3]` or `[n_frames, 3, 3]` in the **structure
  convention**, rows in Å, unlike `reaction.path.lattice`), `velocities`
  (`[n_frames, n_atoms, 3]`, Å/fs), `gradient` (`[n_frames, n_atoms, 3]`, the
  energy gradient in hartree/bohr; forces are its negative), `times` (fs),
  binary `energies` (hartree), `cell_volumes` (Å³) and `temperatures`
  (kelvin), each `[n_frames]`; `reaction.path` gains `velocities`,
  `gradient`, `times` and `energies`. `coords` may be float32 with
  `metadata.precision: "float32"` (`$defs/TrajectoryCoords` widened). Metadata
  gains `ensemble` and `timestep_fs`; `pbc` is required with a trajectory
  `lattice`. Schema `$defs/TrajectoryLattice`, `TrajectoryFrameVectors`,
  `TrajectoryFrameScalars` and the shared `TrajectoryMetadataCommon`; § 4.3
  "Lattice conventions" states all three cell carriers. The Python, C++ and
  JavaScript validators check the per-frame extents against `coords`, the
  float32 / `precision` rule, binary `energies` against `metadata.energies`
  (1e-10 hartree) and `lattice` / `pbc` (`E_MEMBER_MALFORMED`). Writers:
  Python `add_trajectory(..., lattice=, velocities=, gradient=, times=,
  energies=, cell_volumes=, temperatures=, precision=)` and
  `add_reaction_path(..., velocities=, gradient=, times=, energies=)`; C++
  `TrajectoryExtras`, `add_trajectory(metadata, coords, extras)` with
  `Lattice` and `std::vector<Lattice>` overloads, `add_reaction_path(...,
  lattice, extras)`; C ABI `qvf_add_trajectory`. Corpus `md_periodic.qvf`;
  negative corpus `trajectory_lattice_without_pbc.qvf`,
  `trajectory_float32_without_precision.qvf`,
  `trajectory_velocities_frame_count.qvf`,
  `trajectory_energies_disagree.qvf`. No `qvf_version` bump (P12, D06, WP-26).
- C++ container layer `qvf/container.hpp` (`qvf::container`): `ZipWriter`
  over a `FileSink`, `MemorySink` or `CallbackSink`, with whole or streamed
  entries (`begin` -> `EntrySink`: CRC-32, SHA-256 and DEFLATE on the fly;
  local headers patched on seekable sinks, data descriptors on others),
  ZIP64 extra fields, end record and locator when a size, offset or entry
  count needs them or when forced, `append(path)` (existing records kept as
  they are) and `allow_repeated_name()` for the superseded `manifest.json` of
  spec § 2.3; `ZipReader` with ZIP64 and data-descriptor support, CRC-32 and
  local-header checks, a repeated name resolved to its last record, and
  `read_into()` streaming an entry under `Limits`, which moved here
  (`qvf::Limits` is an alias). The DEFLATE and INFLATE codecs stream. The C++
  reader now opens `zip64.qvf`: the known gap and the sanitizer jobs' skip are
  gone (D13, WP-40).
- C++ `QvfWriter` streaming and update: `QvfWriter(source, path)` writes
  members to the file as they are added; `begin_binary(section_id, role,
  dtype, shape)` returns a `MemberSink` that computes sha256 and size on the
  fly; `open_for_update(path)` updates an archive in place as spec § 2.3
  prescribes (members appended, a new `manifest.json` last, the superseded
  one kept as an orphan, `metadata.modified_utc` stamped, no other entry
  name reused); `write()` finishes a bound writer; `force_zip64`; free
  function `repack(in, out)` drops orphans and superseded manifests
  (D19, P19, WP-40).
- Python `QvfWriter.open_for_update(path)` (spec § 2.3 through `zipfile`
  mode `"a"`: members appended, a new `manifest.json` last, the superseded
  one kept, `metadata.modified_utc` stamped, no other entry name reused),
  module function `repack(src, dst)`, and `force_zip64=` on `to_bytes()` /
  `write()` (D19, P19, WP-40).
- `cpp/fuzz/zip_reader_fuzzer.cpp`, a libFuzzer target over the ZIP reader
  and the validator, built with `-DQVF_FUZZ=ON` (clang; a mutation driver
  stands in where clang has no libFuzzer runtime); not run in CI yet (WP-40).
- Canonical kinds `excited_states` (spec § 5.12: one strict JSON member
  `states`, `$defs/ExcitedStatesPayload`, with per-state `index`,
  `excitation_energy` (SHOULD be `ev`), `total_energy`, `multiplicity`,
  `symmetry`, `oscillator_strength`, `rotatory_strength_cgs` (10⁻⁴⁰ esu²·cm²),
  `transition_dipole` and `transition_magnetic_dipole` (atomic units),
  `contributions`, `nto_ref`, `density_ref`, a strict `meta`, and the section
  field `wavefunction_ref`) and `volume.transition_density` (spec § 5.2, e/bohr³,
  optional section fields `excited_states_ref` and `state_index`), registered as
  promotions by maintainer decision. Natural transition orbitals are two
  `wavefunction.gto` sections per state; `mo_metadata` gains `state_index` and
  `nto_role` (`hole` / `particle`), and `state_ref` names the `excited_states`
  section (spec § 5.3). A one-dimensional spectrum payload gains `states_ref`,
  which makes `peaks[].assignment.state_index` a state `index` (spec § 5.4).
  All three validators report repeated or descending state indices, a wrong
  `n_states` and a contribution beyond the reference wavefunction's orbital
  rows (`E_MEMBER_MALFORMED`), and an unresolved `wavefunction_ref`,
  `nto_ref`, `density_ref`, `states_ref`, `excited_states_ref` or
  `state_index` (`E_REF_UNRESOLVED`); `meta.units` joins the unit-name rule.
  No `qvf_version` bump (P08, WP-22).
- Writers: Python `add_excited_states(states, *, meta=, wavefunction_ref=,
  section_id=)`, `add_volume("volume.transition_density", ...,
  excited_states_ref=, state_index=)` and `add_wavefunction_gto(...,
  state_ref=, state_index=, nto_role=)`; C++ `add_excited_states`,
  `add_volume_transition_density` and the `WavefunctionGTO` fields
  `state_ref`, `state_index`, `nto_role`; C ABI
  `qvf_add_excited_states_json`. `js/src/kinds.ts` is regenerated. Corpus
  `tddft.qvf` (water: ground-state wavefunction, three states, an NTO pair, a
  transition density and the UV-Vis stick spectrum of the table); negative
  corpus `excited_states_index_duplicate.qvf`,
  `excited_states_nto_ref_wrong_kind.qvf`,
  `excited_states_to_mo_out_of_range.qvf` (WP-22).
- `wavefunction.gto` extensions (spec § 5.3, Appendix A.1): effective core
  potentials specified (`basis.ecp`: radial functions
  `Σ c r^(n−2) exp(−α r²)` with `powers` = n, a new optional `local` flag for
  the local part, which has the centre's highest `l`); `basis.n_electrons`
  (`Σ Z − Σ n_core_electrons − charge`) must equal the summed occupations and
  `provenance.n_electrons`; `restricted_open` and `generalized` layouts
  (`generalized`: AO axis doubled as `[α AOs…, β AOs…]`, requires
  `complex: true`); `complex: true` means a trailing `[re, im]` axis on every
  coefficient member; optional float64 `[n_ao, n_ao]` members `overlap`,
  `density_matrix`, `density_matrix_alpha` + `density_matrix_beta`
  (`$defs/WavefunctionAoMatrix`). Validators check coefficient ranks,
  `symmetry_labels` lengths, matrix shapes and pairing and the electron count
  (`E_MEMBER_MALFORMED`, `E_ROOT_INCONSISTENT` against provenance), and, when
  `overlap` is present, its diagonal against the Appendix A.1 self-overlaps:
  new finding code `E_NORMALIZATION` in Appendix B and all three validators
  (Python, C++, JavaScript). Producers SHOULD write `overlap`. No
  `qvf_version` bump (P09, WP-23).
- Writers: Python `add_wavefunction_gto(..., spin=, ecp=, n_electrons=,
  symmetry_labels=, overlap=, density_matrix=, density_matrix_alpha=,
  density_matrix_beta=, complex_coefficients=)`; C++ `WavefunctionGTO`
  fields `spin`, `complex_coefficients`, `ecp`, `n_electrons`,
  `symmetry_labels` (and `_alpha` / `_beta`), `overlap`, `density_matrix`,
  `density_matrix_alpha`, `density_matrix_beta`, and
  `QvfWriter::set_wavefunction_overlap` / `set_wavefunction_ecp`; C ABI
  `qvf_add_wavefunction_gto_unrestricted`, `qvf_set_wavefunction_overlap`,
  `qvf_set_wavefunction_ecp_json` (WP-23).
- Conformance corpus: `wavefunction_ecp.qvf`, `wavefunction_overlap.qvf`
  (its `expected.json` records the overlap diagonal); negative corpus:
  `wavefunction_normalization.qvf` (`E_NORMALIZATION`),
  `wavefunction_n_electrons.qvf`, `wavefunction_complex_rank2.qvf` (WP-23).
- Canonical kinds `properties.electric`, `properties.elastic` and
  `properties.dielectric` (spec § 5.13, "Property kinds"), each with one
  strict JSON member `properties` (`$defs/ElectricPropertiesPayload`,
  `ElasticPropertiesPayload`, `DielectricPropertiesPayload`), registered as
  promotions by maintainer decision. Electric: `dipole` (debye), `quadrupole`
  (debye·Å, Buckingham or Cartesian, with a `traceless` flag), `octupole`,
  `polarizability` and `hyperpolarizability` (atomic units) and `origin`.
  Elastic: the symmetric 6 × 6 Voigt `stiffness` in GPa, `compliance`, moduli
  and their `average` scheme. Dielectric: `electronic`, `ionic` and `static`
  tensors, one Born tensor per atom in e, and the piezoelectric tensor in
  C/m². Fixed units, with a typed `units` object that restates them where the
  vocabulary has a name (spec § 4.3 gains the rows). Validators in Python, C++
  and JavaScript check symmetric elastic matrices, `static` = `electronic` +
  `ionic` and the Born tensor count (`E_MEMBER_MALFORMED`), and an electric
  dipole against the root `dipole_moment` within 1e-6 debye
  (`E_ROOT_INCONSISTENT`). Writers: Python `add_electric_properties`,
  `add_elastic_properties`, `add_dielectric_properties`; C++ the same names
  taking the payload as JSON; C ABI `qvf_add_electric_properties_json`,
  `qvf_add_elastic_properties_json`, `qvf_add_dielectric_properties_json`.
  Corpus `properties_molecular.qvf` and `properties_periodic.qvf`; negative
  corpus `elastic_not_symmetric.qvf`, `dielectric_static_mismatch.qvf`,
  `dielectric_born_atom_count.qvf`, `electric_dipole_inconsistent.qvf`. No
  `qvf_version` bump (P14, P17, WP-29).
- Schema-driven generated tables (design § 4–5): `scripts/gen_kinds.py`
  (standard library only) reads `spec/qvf_manifest.schema.json`,
  `registry.json` and spec Appendix B and writes, deterministically,
  `cpp/include/qvf/kinds_generated.hpp` (`namespace qvf::gen`: `KindInfo` /
  `RoleInfo` per canonical kind with formats, dtypes, rank bounds and payload
  definitions, `kind_info()`, `kCanonicalKinds`, `payload_def()`, the `Unit`
  enum with `unit_name()` / `parse_unit()`, the finding codes, the schema
  `$id`), `python/qvf_kinds.py` (the same tables, `PAYLOAD_DEFS`,
  `FIXED_UNITS`), and the compiled schema `cpp/src/qvf_schema_table.hpp` /
  `js/src/schemaTable.ts`. `--check` fails on drift; a test, both CI pipelines
  and `scripts/make_archive.sh` run it. The generator refuses JSON Schema
  keywords outside the supported subset, unsupported regular expressions, an
  unmapped `*Payload` definition and a registry that disagrees with the
  schema (WP-41).
- A table-driven JSON Schema checker for the C++ and JavaScript validators
  (`cpp/src/qvf_schema_check.hpp`, `js/src/schemaCheck.ts`): an interpreter
  of the generated instruction table, with patterns on a Pike VM over code
  points and no schema engine or `<regex>`. Both validators now report
  `E_SCHEMA` for `manifest.json` and `E_PAYLOAD_SCHEMA` for every JSON member
  with a payload definition, at the same locations as the Python validator
  (`jsonschema`), and the equal-length rule of a 1-D spectrum.
  `qvf::ValidationOptions::schema_check` (C++) and `schemaCheck` (JS) disable
  the check (then `W_SCHEMA_SKIPPED`); the C++ and JS conformance runners take
  `--no-schema-check`. `python/tests/test_schema_checker_parity.py` holds both
  checkers to `jsonschema` on the positive, negative and legacy corpora and on
  mutated corpus documents (WP-41).
- Typed, lossless manifest model (design § 4): C++ `qvf/model.hpp`
  (`Manifest`, `Section`, `MemberSpec` with `from_json` / `to_json`, unknown
  and wrongly typed fields kept in `extra`) exposed as
  `QvfReader::typed_manifest()`, and Python `qvf_model` (dataclasses,
  `QvfReader.typed_manifest`); round-trip tests over every conformance
  manifest (CTest `qvf_model_roundtrip`, `python/tests/test_model.py`). The
  writers do not use it yet (WP-41).

### Changed

- Validators read an archive stamped with the withdrawn `qvf_version: 2` as
  version 1, the JSON Schema check included, and report the warning
  `W_VERSION_WITHDRAWN` instead of the error `E_VERSION`, as spec § 3.1 and
  `registry.json` (`readable_versions`) asked of consumers; the legacy corpus
  expects the warning. Python `QvfWriter.open_for_update` accepts such an
  archive and writes `qvf_version: 1` and the v1 `schema_uri`.
- A pending archive carries at least one `job.spec` section, no longer
  exactly one (spec § 5.9).
- The conformance runner reports the legacy corpus as "judged as expected".
- Reference writers drop a `hostname` provenance key by default; opt in with
  Python `set_provenance(..., allow_hostname=True)` or C++
  `set_provenance(prov, /*allow_hostname=*/true)`. The C ABI
  `qvf_set_provenance_json` always drops it and now reports malformed JSON as
  an error instead of writing it verbatim (WP-07).
- Schema descriptions no longer cite internal documents or implementation
  details, and every spec citation uses the current section number and
  title; descriptions only, no contract change (D01, WP-02).
- The `Extensions` schema description now says keys carry their `x_`
  prefix, matching the pattern, spec § 7.4, and the vendor corpus archive.
- Writer APIs follow the schema: Python `add_atom_properties` gains
  `hirshfeld_charge=` and `iao_charge=`; C++ gains
  `add_atom_properties(std::map<std::string, std::vector<double>>)` and
  `add_atom_property(role, values)`, plus an `std::initializer_list` overload
  that keeps `add_atom_properties({q0, q1})` unambiguous; the C ABI gains
  `qvf_add_atom_property`. Both writers now reject `atom_properties` roles of
  different lengths, and phonon eigenvectors or a projected phonon DOS of the
  wrong rank, trailing axes, dtype or extent, before writing anything; the
  Python writer splits complex eigenvectors into the `[re, im]` form (D02,
  D03, WP-04).
- Spec § 5.6 is rewritten around per-member payload tables with a *Spin
  axis* rule; § 5.8 documents the `files` index in a table. The schema
  requires `bands.projections` to be float64 (WP-12).
- The negative-corpus runners hold an expectation of a schema-only code
  (`E_SCHEMA`, `E_PAYLOAD_SCHEMA`) only against a validator that runs the
  JSON Schema check (WP-12).
- The writers write the unit names `hartree` and `ev` for
  `set_provenance(scf_energy_eh=, fermi_energy_ev=)` and refuse a declared
  unit that is not a unit name or that contradicts a fixed unit; a payload
  `units` value outside the vocabulary, previously accepted by the schema, now
  fails with `E_PAYLOAD_SCHEMA`. `qvf::kBohrPerAngstrom` moved to
  `qvf/units.hpp`, which `qvf/qvf.hpp` includes (WP-13).
- Writer APIs follow the enlarged `atom_properties` list: Python
  `add_atom_properties` takes every role by keyword plus `custom={name:
  (array, entry)}` and `meta=` and writes the `meta` member; C++ gains
  `add_atom_vector_property` and `set_atom_properties_meta`, its map overload
  and `add_atom_property` accept the enlarged scalar list and scalar custom
  roles; the C ABI gains `qvf_add_atom_vector_property` and
  `qvf_set_atom_properties_meta_json`, and `qvf_add_atom_property` accepts the
  enlarged scalar list. Roles named `cm5_charge` or `bader_charge` were
  rejected as unknown before and are valid now (P10, WP-24).
- The reference writers (Python, C++, and through it the C ABI) add
  `metadata.created_utc` and a random version-4 `metadata.uuid` to every
  archive by default, made once per writer; opt out with
  `QvfWriter(..., auto_metadata=False)` or C++ `w.auto_metadata = false`. A
  consumer that validates against an older vendored schema rejects the new
  root key until it updates. The positive conformance generator opts out, so
  the frozen archives keep their manifests (WP-20).
- Validators now check that a `reaction.waypoints` `trajectory_ref` names a
  `trajectory` section, as spec § 6 already required, not merely an existing
  one (`E_REF_UNRESOLVED`, WP-20).
- `set_provenance` (Python and C++, so also `qvf_set_provenance_json`) and
  `add_job_spec` check the typed fields they write and refuse a wrong value
  (`ValueError`, `std::runtime_error`, a non-zero C return) before anything
  changes; the C++ `set_provenance` now also refuses a provenance that is not
  a JSON object. Both Python writer checks match whole strings, so a time
  stamp or hash with a trailing newline is refused (WP-27).
- Trajectory writers check every member before writing: Python
  `add_trajectory` writes float32 `coords` when the metadata already names
  `precision: "float32"`, and refuses a lattice without `pbc` or a periodic
  `pbc` without a lattice; Python and C++ `add_reaction_path` keep float64
  coordinates and refuse a metadata `precision` of `"float32"`; C++
  `add_trajectory` adds `precision: "float32"` for float32 coordinates and
  refuses raw metadata that does not parse. Validators now enforce that
  `metadata.precision` agrees with the dtype of `coords`, as spec § 5.5
  already required (WP-26).
- Both reference writers write `manifest.json` last (still STOREd), after the
  members, as spec § 2.1 recommends; it used to be the first entry. The C++
  `write(path)` streams the archive to the file instead of building it in
  memory, and a 32-bit archive's ZIP encoding is unchanged byte for byte.
  The C++ ZIP writer sets the UTF-8 flag (bit 11) for non-ASCII entry names
  (WP-40).
- The C++ reader verifies each entry's CRC-32 and that its local header names
  the same entry as the central directory (as the Python and JavaScript
  readers do), reports both as `E_ZIP_UNREADABLE`, and applies every
  `Limits` cap (member and total size, ratio) to member reads. Its inflater
  rejects DEFLATE streams zlib rejects too (a stored block whose length check
  fails, more than 286/30 codes, a code-length repeat past the end, no
  end-of-block code).
  `QvfReader::open` and `validate_file` read from the file on demand instead
  of loading it whole (WP-40).
- Spec § 5.3 now says what `mo_metadata.state_ref` refers to for natural
  transition orbitals (it was "not yet specified"), and the writers'
  `add_spectrum` refuses a one-dimensional payload whose `states_ref` names no
  `excited_states` section already added (WP-22).
- Spec § 9 item 5 (Cartesian shells) now points producers at the `overlap`
  check. The Python and C++ `add_wavefunction_gto` refuse coefficient
  matrices whose AO extent is not the basis's `n_ao` (2 `n_ao` for
  `generalized`), and check everything before writing anything; a
  `generalized` `mo_metadata` without `complex: true` now fails the schema
  (`E_PAYLOAD_SCHEMA`), a layout no archive could use before (WP-23).
- The finding code `E_ROOT_INCONSISTENT` now also covers a section that
  restates a root block: a `properties.electric` dipole that differs from the
  root `dipole_moment`. The code is not renamed (spec § 3.3, § 5.13,
  Appendix B; WP-29).

- The C++ and JavaScript validators run the JSON Schema by default, so an
  archive that only the schema rejects (for example `byte_order` `"big"` or a
  payload outside its definition) is now invalid to them, as it already was
  to the Python validator with `jsonschema`; their negative-corpus runners
  hold the schema-only expectations and compare the other codes exactly.
  The C++ reader's refusal of a `byte_order` other than `"little"` now starts
  with `E_SCHEMA:` (WP-41).
- `qvf::Unit`, `unit_name()`, `parse_unit()` and the canonical kinds come from
  the generated `qvf/kinds_generated.hpp` (`qvf/units.hpp` re-exports the unit
  names; enumerator names are unchanged), `qvf::Source` moved to
  `qvf/model.hpp` (still included by `qvf/qvf.hpp`), and `qvf_reader`'s
  canonical kinds, payload definitions and finding codes and `qvf_units`'s
  vocabulary come from `qvf_kinds` instead of hand-kept copies and a schema
  read at import. A new payload definition is wired to its `(kind, role)` in
  `PAYLOAD_DEFS` of `scripts/gen_kinds.py`. The C++ JSON parser now joins an
  escaped surrogate pair into one code point (WP-41).

## [0.1.0] - 2026-09-08

First public release of the toolkit, implementing QVF v1 (`qvf_version = 1`).
The release date is the date of the first public commit of this repository.
The format decisions below were taken earlier, while development still took
place in a private monorepo (see the History section of
[`README.md`](README.md)); each bullet carries the date of the decision as
recorded in `GOVERNANCE.md`.

### Format decisions

Newest first. None of them changed `qvf_version`.

- 2026-08-05 - `basis.ao`: optional `cartesian_powers` (`[l_x, l_y, l_z]`)
  names the components of Cartesian (`pure: false`) shells; `angular_momentum`
  keeps its shape and stays required. No `qvf_version` bump.
  [Decision](GOVERNANCE.md#2026-08-05--basisao-cartesian-components-named-by-cartesian_powers).
- 2026-07-26 - `structure`: the optional biomolecule fields `chains`,
  `residues`, `secondary_structure` and the new `b_factors` (plus per-atom
  `b_factor`) are schema'd as optional properties; a requested v3 schema was
  declined. No `qvf_version` bump.
  [Decision](GOVERNANCE.md#2026-07-26--biomolecule-metadata-schemad-on-structure-no-v3).
- 2026-07-25 - `job.spec`: new canonical kind carrying a declarative job
  specification; `provenance.run_status` formalized with the values
  `pending`, `running`, `converged` and `failed`. No `qvf_version` bump.
  [Decision](GOVERNANCE.md#2026-07-25--jobspec-canonical-kind--run_status-lifecycle-executable-archives).
- 2026-07-24 - `run.record`: new canonical kind carrying the verbatim input,
  log and attachments of a program invocation, with a required `program`
  section field. No `qvf_version` bump.
  [Decision](GOVERNANCE.md#2026-07-24--runrecord-canonical-kind-added-self-contained-archives).
- 2026-07-10 - `qvf_version: 2` withdrawn: `reaction.path` gains an optional
  `lattice` member under v1. Producers MUST NOT emit `qvf_version: 2`;
  consumers SHOULD accept it and treat it as `1`. The frozen schema for
  already-stamped archives is kept at
  [`spec/legacy/qvf_manifest_v2.schema.json`](spec/legacy/qvf_manifest_v2.schema.json).
  [Decision](GOVERNANCE.md#2026-07-10--qvf_version-2-withdrawn-periodic-reactionpath).
- 2026-07-10 - `structure`: the member payload is schema'd as
  `$defs/StructurePayload`; `pbc` is required whenever `lattice_vectors` is
  non-null, and `dimensionality` is optional and derived
  (`dimensionality == sum(pbc)`). No `qvf_version` bump.
  [Decision](GOVERNANCE.md#2026-07-10--structure-payload-schemad-pbc-required-when-periodic).

### Toolkit

- Normative specification
  ([`spec/qvf-format-spec.md`](spec/qvf-format-spec.md)) and the JSON Schema
  for `manifest.json`
  ([`spec/qvf_manifest.schema.json`](spec/qvf_manifest.schema.json)), kept in
  step with the registry by a drift test.
- Reference writer in Python ([`python/qvf_writer.py`](python/qvf_writer.py);
  standard library and NumPy only) and in C++17 (`qvf::QvfWriter` under
  [`cpp/`](cpp/); no external build dependencies).
- Reference reader and validator in Python
  ([`python/qvf_reader.py`](python/qvf_reader.py)) and in C++17.
- C ABI in [`cpp/include/qvf/qvf_c.h`](cpp/include/qvf/qvf_c.h), covering
  about a third of the canonical kinds.
- Conformance suite: a golden corpus of 12 archives and a runner
  ([`conformance/`](conformance/)); the reference writer and reader are
  certified against it in CI.
- Single-header amalgamation
  ([`cpp/qvf_single.hpp`](cpp/qvf_single.hpp)), generated by
  [`scripts/amalgamate.py`](scripts/amalgamate.py) and checked for staleness
  in CI.
- CMake package export (`qvf::` targets) and a PyPI-ready Python package
  (not yet published).
- Governance documents: [`GOVERNANCE.md`](GOVERNANCE.md) and
  [`registry.json`](registry.json), the registry of canonical kinds and
  vendor namespaces. `spectra.epr` was promoted ahead of the two-producer
  threshold as a maintainer decision (see "Vendor → canonical promotion" in
  `GOVERNANCE.md`).
