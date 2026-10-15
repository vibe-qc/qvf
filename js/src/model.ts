/**
 * Types for the manifest (spec § 3, § 4) and for decoded binary members.
 *
 * The manifest interfaces mirror `spec/qvf_manifest.schema.json` at the root
 * and for `Section` and the member specs. They describe a schema-conformant
 * manifest: this package does not run a JSON Schema engine, so an archive that
 * the validator flags may not satisfy them. Kind-specific payloads (structure,
 * spectra, bands, ...) are not typed here; `readJson` returns `unknown`.
 */

/** The binary dtype names of spec § 4.2. */
export type DType =
  | "int8"
  | "int16"
  | "int32"
  | "int64"
  | "uint8"
  | "uint16"
  | "uint32"
  | "uint64"
  | "float32"
  | "float64";

/** Bytes per element of each dtype. */
export const DTYPE_ITEMSIZE: Readonly<Record<DType, number>> = Object.freeze({
  int8: 1,
  int16: 2,
  int32: 4,
  int64: 8,
  uint8: 1,
  uint16: 2,
  uint32: 4,
  uint64: 8,
  float32: 4,
  float64: 8,
});

/** The typed array each dtype decodes to. 64-bit integers decode to BigInt arrays. */
export interface DTypeArrays {
  int8: Int8Array;
  int16: Int16Array;
  int32: Int32Array;
  int64: BigInt64Array;
  uint8: Uint8Array;
  uint16: Uint16Array;
  uint32: Uint32Array;
  uint64: BigUint64Array;
  float32: Float32Array;
  float64: Float64Array;
}

/** Any typed array a binary member can decode to. */
export type TypedArray = DTypeArrays[DType];

/**
 * A decoded binary member. `data` is a flat, C-order (row-major) typed array
 * and `shape` gives its dimensions; narrow on `dtype` to get the array type.
 */
export type BinaryArray = {
  [D in DType]: { dtype: D; shape: number[]; data: DTypeArrays[D] };
}[DType];

/** `{value, units}` quantity (schema `ValueWithUnits`). */
export interface ValueWithUnits {
  value: number;
  /**
   * A unit name of spec § 4.3, or a deprecated legacy spelling (`Eh`, `eV`,
   * `Hartree`); `canonicalUnit` maps either to the unit name.
   */
  units: string;
}

/** A 3-vector. */
export type Vec3 = [number, number, number];

/** Root `source` object (spec § 3.1). */
export interface Source {
  program: string;
  version: string;
  calculation: string;
}

/** A JSON member spec (spec § 4.2). */
export interface JsonMemberSpec {
  path: string;
  format: "json";
  sha256: string;
  /**
   * Uncompressed byte count of the stored member; equals the size its ZIP
   * entry records (optional, spec § 4.2).
   */
  size?: number;
  /** IANA media type of the member's bytes (optional, spec § 4.2); see {@link BinaryMemberSpec.media_type}. */
  media_type?: string;
}

/**
 * A binary member spec (spec § 4.2). `dtype` and `shape` are present on array
 * members and absent on opaque members (`citations.references`, `run.record`
 * `input` / `log` / `attachment.*`, the `preview` `thumbnail` and `image`,
 * and any vendor member written without them).
 */
export interface BinaryMemberSpec {
  path: string;
  format: "binary";
  dtype?: DType;
  shape?: number[];
  sha256: string;
  /**
   * Uncompressed byte count of the stored member; equals the size its ZIP
   * entry records (optional, spec § 4.2).
   */
  size?: number;
  /**
   * IANA media type of the member's bytes, a type and a subtype without
   * parameters such as `image/png` (optional on every member spec, spec
   * § 4.2). It describes the bytes and changes nothing in how they are read;
   * `preview` members require it (spec § 5.15).
   */
  media_type?: string;
}

/** A member spec: the value of a section's `members` map. */
export type MemberSpec = JsonMemberSpec | BinaryMemberSpec;

/**
 * A section (spec § 4.1). Kind-specific peer fields of the section object
 * (`operand_a`, `trajectory_ref`, `program`, `sequence`, ...) are reachable
 * through the index signature as `unknown`.
 */
export interface Section {
  id: string;
  kind: string;
  members: Record<string, MemberSpec>;
  label?: string;
  component?: string;
  critical?: boolean;
  schema_uri?: string;
  /** Id of the `structure` section this section describes (spec § 4.1). */
  structure_ref?: string;
  /** Id of the `run.record` section of the run that produced it (spec § 4.1). */
  run_ref?: string;
  /** Free display label grouping related sections (spec § 4.1). */
  group?: string;
  [peerField: string]: unknown;
}

/** One author in the root `metadata` block (schema `MetadataAuthor`). */
export interface MetadataAuthor {
  name: string;
  orcid?: string;
  /** Personal data; producers do not emit it by default. */
  affiliation?: string;
  /** Personal data; producers do not emit it by default. */
  email?: string;
  [vendorKey: `x_${string}`]: unknown;
}

/** Root `metadata` block (spec § 3.5): describes the archive itself. */
export interface Metadata {
  title?: string;
  description?: string;
  /** ISO 8601 UTC, `YYYY-MM-DDThh:mm:ssZ`. */
  created_utc?: string;
  modified_utc?: string;
  /** RFC 4122 UUID, lowercase. */
  uuid?: string;
  authors?: MetadataAuthor[];
  /** An SPDX identifier is recommended. */
  license?: string;
  doi?: string;
  keywords?: string[];
  /** `uuid`s or DOIs of the sources. */
  derived_from?: string[];
  tags?: string[];
  [vendorKey: `x_${string}`]: unknown;
}

/** One program or library in `provenance.software` (schema `ProvenanceSoftware`). */
export interface ProvenanceSoftware {
  name: string;
  version?: string;
  /** A public address only. */
  url?: string;
  [vendorKey: `x_${string}`]: unknown;
}

/** Calculation-level metadata (spec § 3.2). Open: further keys are allowed. */
export interface Provenance {
  method?: string;
  functional?: string;
  basis?: string;
  charge?: number;
  multiplicity?: number;
  n_electrons?: number;
  scf_converged?: boolean;
  n_scf_iterations?: number;
  scf_energy?: ValueWithUnits;
  fermi_energy?: ValueWithUnits;
  wall_seconds?: number;
  /** Deprecated; consumers must not rely on it. */
  hostname?: string;
  dimensionality?: number;
  run_status?: "pending" | "running" | "converged" | "failed";
  /** The programs and libraries that produced the results. */
  software?: ProvenanceSoftware[];
  /** The producer's own git commit: 7 to 64 hexadecimal characters. */
  git_commit?: string;
  /** Threads per process (>= 1). */
  n_threads?: number;
  /** MPI ranks (>= 1). */
  n_mpi_ranks?: number;
  /** GPUs used (>= 0). */
  n_gpus?: number;
  /** ISO 8601 UTC, `YYYY-MM-DDThh:mm:ssZ`. */
  started_utc?: string;
  finished_utc?: string;
  [key: string]: unknown;
}

/** A camera (schema `Camera`): exactly one of `view_angle` / `parallel_scale`. */
export interface Camera {
  position: Vec3;
  focal_point: Vec3;
  view_up: Vec3;
  view_angle?: number;
  parallel_scale?: number;
}

/** A camera bookmark (schema `Bookmark`). */
export interface Bookmark {
  name: string;
  description?: string;
  camera: Camera;
}

/** The `crossfade` hint of `viewer_defaults` (spec § 3.4), when well-formed. */
export interface CrossfadeHint {
  /** Id of the first volume section; `blend` 0 shows it alone. */
  a: string;
  /** Id of the second volume section; `blend` 1 shows it alone. */
  b: string;
  /** Where the blend starts, 0 to 1; default 0.5. */
  blend?: number;
}

/**
 * Root `viewer_defaults` (spec § 3.4); any other key is a section id. `camera`
 * and `crossfade` are hints the schema reserves but does not check: a
 * consumer verifies the shape (a `Camera`, a `CrossfadeHint`) and ignores a
 * value that does not have it.
 */
export interface ViewerDefaults {
  auto_open?: string[];
  bookmarks?: Bookmark[];
  /** The camera a consumer starts with: a `Camera` when well-formed. */
  camera?: unknown;
  /** Two volume sections to cross-fade between: a `CrossfadeHint` when well-formed. */
  crossfade?: unknown;
  [sectionIdOrHint: string]: unknown;
}

/** Root `thermochemistry` block (Hartree, cal/mol/K, K, atm). */
export interface Thermochemistry {
  zpve_eh?: number;
  enthalpy_eh?: number;
  entropy_cal_mol_k?: number;
  gibbs_free_energy_eh?: number;
  temperature_k?: number;
  pressure_atm?: number;
}

/** Root `dipole_moment` block. */
export interface DipoleMoment {
  total_debye?: number;
  vector_debye?: Vec3;
  origin?: string | Vec3;
}

/** Root `constraints` block. */
export interface Constraints {
  frozen_atoms?: number[];
  distance_constraints?: { atoms: [number, number]; target_angstrom: number }[];
}

/** Named contributions to an energy (spec § 3.6); `x_` keys name further ones. */
export interface EnergyComponents {
  nuclear_repulsion?: ValueWithUnits;
  electronic?: ValueWithUnits;
  one_electron?: ValueWithUnits;
  two_electron?: ValueWithUnits;
  exchange_correlation?: ValueWithUnits;
  exchange?: ValueWithUnits;
  correlation?: ValueWithUnits;
  dispersion?: ValueWithUnits;
  solvation?: ValueWithUnits;
  zpve?: ValueWithUnits;
  thermal?: ValueWithUnits;
  embedding?: ValueWithUnits;
  [vendorComponent: `x_${string}`]: ValueWithUnits;
}

/** The energy of the system by one method (spec § 3.6). */
export interface EnergyByMethod {
  method: string;
  total: ValueWithUnits;
  components?: EnergyComponents;
}

/** Root `energies` block (spec § 3.6); producers write hartree. */
export interface Energies {
  total: ValueWithUnits;
  method?: string;
  components?: EnergyComponents;
  by_method?: EnergyByMethod[];
  units_note?: string;
}

/** One declared vendor extension (spec § 7.4). */
export interface Extension {
  version: string;
  schema_uri?: string;
  critical?: boolean;
}

/** The root of `manifest.json` (spec § 3.1). */
export interface Manifest {
  qvf_version: number;
  source: Source;
  sections: Section[];
  schema_uri?: string;
  /** Byte order of every binary member: `"little"` is the only v1 value (spec § 2.2). */
  byte_order?: "little";
  provenance?: Provenance;
  metadata?: Metadata;
  viewer_defaults?: ViewerDefaults;
  thermochemistry?: Thermochemistry;
  dipole_moment?: DipoleMoment;
  constraints?: Constraints;
  energies?: Energies;
  /** Declared vendor namespaces, keyed `x_<vendor>`. */
  extensions?: Record<string, Extension>;
}
