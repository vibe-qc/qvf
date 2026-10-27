# Convert common files through QVF

The `qvf.convert` Python API and `qvf convert` command started in
toolkit **0.5.0**; XSF and PDB geometry joined in **0.6.0**. The development
checkout also supports the Molden subset below. They use the standard library;
NumPy is optional. Install the `validate` extra for JSON Schema checks as well
as the always-on reference checks.

Every conversion writes a new file, refuses an existing destination and
returns a JSON-compatible report. QVF imports pass the reference validator
before the completed file is published. Exports validate their QVF input and
verify member hashes. Keep the original: text exports select geometry, a
grid or orbitals, not a complete calculation. The report lists unselected
sections and explains the metadata that the text format cannot carry. This is not a
lossless archive edit; use `qvf repack` or `Editor` for that.

## XYZ and geometry-only extended XYZ

```sh
qvf convert molecule.xyz --from xyz --to qvf -o molecule.qvf
qvf convert molecule.qvf --from qvf --to extxyz -o molecule-export.xyz
qvf convert frames.xyz --from extxyz --to qvf -o trajectory.qvf
qvf convert trajectory.qvf --from qvf --to extxyz --section trajectory -o frames-export.xyz
```

Coordinates are angstrom. One frame becomes a canonical `structure`; several
frames also become a `trajectory` referring to the first structure. Atom
count, symbol order and per-axis periodicity must stay constant. Cells may
vary by frame. No molecular charge, multiplicity, energy, job or calculation
status is inferred. A geometry import alone is not a runnable queue job;
add an explicit request as described in the [family workflow](family_workflow.md).

The supported extXYZ geometry subset has `Properties=species:S:1:pos:R:3`
(or the two property groups reversed), optional `Lattice` with nine quoted,
space-separated row-vector components in angstrom, and optional `pbc` with
three booleans. With a cell and no `pbc`, all axes are periodic; with neither,
all are nonperiodic. This follows the [extXYZ geometry conventions](https://github.com/libAtoms/extxyz#reading-aseatomsatoms-from-this-format).
Other header properties, atom columns and array syntaxes are refused. Plain
XYZ comments are counted as omitted, not copied into archive metadata.
Unknown/ghost symbols, nonfinite values and degenerate periodic cells are
refused. Plain XYZ export refuses cells or periodicity; extXYZ retains them.

An archive with more than one structure/trajectory candidate requires
`--section ID`, including an imported multi-frame archive. This avoids
silently exporting its initial structure in place of its full trajectory.

## Scalar Gaussian cube

```sh
qvf convert density.cube --from cube --to qvf --kind volume.density -o density.qvf
qvf convert density.qvf --from qvf --to cube --section volume -o density-export.cube
```

The supported cube subset has a positive atom count, positive grid counts,
one scalar per voxel, bohr atom/origin/voxel coordinates and X/Y/Z loop order
(Z fastest). Fortran `D` exponents are accepted. Grid vectors can be skewed.
The implementation follows the scalar layout used by
[ASE's cube reader/writer](https://docs.ase-lib.org/_modules/ase/io/cube.html).
Atom positions convert to QVF angstrom; grid coordinates remain bohr and
scalar values are unchanged. The two comment lines and atom-charge column
are reported as omitted. A cube's atom-charge column is not assumed to be a
population analysis. Cube export writes that column as zero.

Cube does not reliably specify the field's physical meaning or periodicity.
The default is `volume.generic` and a nonperiodic structure. `--kind` is an
explicit assertion that the values already use the selected canonical
kind's units; it does not rescale the data. Multi-orbital cubes, multiple
values per voxel, negative grid counts and nonstandard loop orders are
refused rather than guessed.

For a known periodic grid, declare the axes explicitly:

```sh
qvf convert cell.cube --from cube --to qvf --periodic true true true -o cell.qvf
```

The default QVF cube endpoint convention is `includes_endpoint: true`: the
cell row is the voxel vector times `n - 1`. Add `--no-endpoint` for grids that
span the cell in `n` steps. No slab is dropped or duplicated. Export retains
voxel values and vectors verbatim and reports kind, periodic flags and the
endpoint choice, which must be supplied again on import because cube cannot
carry those QVF declarations. Never infer a crystal cell just from a cube's
bounding box.

## Static XSF geometry and scalar grids (toolkit 0.6.0)

```sh
qvf convert crystal.xsf --from xsf --to qvf -o crystal.qvf
qvf convert field.xsf --from xsf --to qvf --kind volume.density --periodic true true true -o field.qvf
qvf convert field.qvf --from qvf --to xsf --section volume -o field-export.xsf
```

The static subset follows the [XCrySDen XSF specification](https://web.mit.edu/xcrysden_v1.5.60/www/XCRYSDEN/doc/XSF.html).
It accepts one primitive geometry (`PRIMVEC`/`PRIMCOORD`) with `CRYSTAL`,
`SLAB` or `POLYMER`, or a molecular `ATOMS` geometry, optionally preceded by
`MOLECULE`. Periodic structure axes must be the leading cell axes (three,
two or one respectively); the converter never permutes axes. Atom identities
may be symbols or atomic numbers. Positions and cell rows remain angstrom.

One named scalar `DATAGRID_3D` in one block is supported. Grid origin and
spanning vectors convert from angstrom to bohr. Each voxel row is its span
divided by `n - 1`, so both boundary planes remain present. Values move from
XSF's X-fastest order to QVF's Z-fastest order without changing samples.
No plane is added, removed or resampled. Grid shape needs at least two
points per axis. A periodic QVF grid without endpoint planes is refused on
export; it must first be explicitly transformed by the caller.

A periodic structure does not prove that a particular scalar field repeats.
Import defaults to a finite grid, even with `CRYSTAL`; `--periodic` explicitly
asserts the **field's** repeating axes, which must match the structure axes
and cell spans. The default kind is `volume.generic`. `--kind` asserts the
values already use that kind's canonical units, with no scalar rescaling.
Export reports kind and field periodicity because XSF cannot encode those
QVF declarations; supply them again when reimporting. On nonperiodic axes,
QVF's endpoint flag has no effect; XSF always retains the sampled extent.

Animation, forces, conventional-cell sections, multiple grids/blocks, 2D
and band grids, degenerate boxes and unknown records are refused. Comments
between sections and grid labels are reported as omitted. A nonperiodic
structure with a cell cannot be exported by this molecular subset. As with
other converters, a file containing both a structure and a grid requires
`--section` on export. No charge, multiplicity or job is inferred.

## PDB geometry (toolkit 0.6.0)

```sh
qvf convert molecule.pdb --from pdb --to qvf -o geometry.qvf
qvf convert geometry.qvf --from qvf --to pdb -o geometry-export.pdb
```

This bounded subset follows the [wwPDB coordinate records](https://www.wwpdb.org/documentation/file-format-content/format33/sect9.html)
and [fixed-column conventions](https://www.wwpdb.org/documentation/file-format-content/format33/sect1.html).
Import retains only explicit elements (columns 77–78) and Cartesian angstrom
coordinates (columns 31–54, `Real(8.3)`) from `ATOM` and `HETATM`, in source
order. Names such as `CA` never determine the element. ASCII records, unique
positive decimal serials and recognized element symbols are required;
isotope labels such as `D`, hybrid-36 serials and missing elements are refused.

One geometry is accepted, optionally enclosed in one `MODEL`/`ENDMDL` pair.
Every nonblank alternate-location indicator and every multi-model ensemble
is refused; prepare a deliberately selected conformation/model externally.
No highest-occupancy or first-model choice occurs. Occupancy does not filter
atoms. The report counts omitted metadata records and atom-charge fields;
it also lists dropped atom/residue/chain names, occupancy and temperature
factors. Standard metadata such as `CONECT`, `CRYST1` and symmetry records
is reported but not interpreted. Unknown records fail. Output is nonperiodic:
no cell, bonds, assembly, protonation, charge, multiplicity or job is inferred.
Keep the original PDB for biomolecular and crystallographic information.

Export selects one structure, with `--section` required if a trajectory or
another structure is also present. Trajectories, cells and periodicity are
refused. It writes up to 9,999 atoms as synthetic `HETATM` records: one `UNL`
residue per atom, element-based names, occupancy 1.00 and temperature factor
0.00. These are placeholders, not biological or experimental metadata.
Coordinates round to 0.001 angstrom; the report gives the maximum rounding
error. Values that overflow the eight-column fields are refused. This is a
geometry interchange file, not a deposition-ready PDB or a metadata round trip.

## Molecular Molden orbitals (Unreleased)

```sh
qvf convert orbitals.molden --from molden --to qvf --spin restricted -o orbitals.qvf
qvf convert orbitals.qvf --from qvf --to molden --section wavefunction -o orbitals-export.molden
```

This subset follows the [Molden format description](https://www.theochem.ru.nl/molden/molden_format.html)
for molecular geometry, atom-centered Gaussian contractions and real orbitals.
It supports `s`, `p`, combined `sp`, spherical `5D` and Cartesian `6D` shells.
The default d convention is Cartesian; explicit spherical flags are honored.
Atoms need sequential indices and matching element/nuclear-charge values.
Coordinates require `AU` or `Angs`; basis exponents and orbital energies use
atomic units. Every orbital needs `Sym`, `Ene`, `Spin`, `Occup` and one real
coefficient for every AO. Sparse or repeated AO indices are refused.

Import requires `--spin restricted`, `restricted_open` or `unrestricted`.
An Alpha-only file cannot distinguish the first two; the caller must choose.
Unrestricted import requires both Alpha and Beta sets and occupations in
0–1; a single set uses 0–2. The resulting `structure` and `wavefunction.gto`
use existing QVF v1 members. Orbital kind is `custom`: Molden does not prove
that orbitals are canonical, localized or natural. No method, charge,
multiplicity, electron count or job is inferred.

The normalized-AO convention is checked independently with
[PySCF's Molden reader/writer](https://pyscf.org/_modules/pyscf/tools/molden.html).
Input contractions must have squared norm within `1e-5` of one; small text
rounding drift is normalized and the original norms are reported. Ordering
and Cartesian component scaling convert to QVF Appendix A. Export normalizes
contractions and compensates MO coefficients so orbital values are preserved;
it does not orthogonalize orbitals or claim a wavefunction is physically valid.
Export writes coordinates in bohr to avoid a second angstrom conversion.

ECP/core sections, ghosts, Slater functions, f and higher shells, complex or
spinor coefficients, periodic geometry, transition-weight occupations and
unknown sections are refused. Non-unit shell scale factors and unnormalized
input contractions are refused instead of guessing a producer's dialect.
Export requires a basis for every atom, contiguous shells per atom and one
d convention. More than one wavefunction requires `--section`.

Import reports omitted comments/title text. Export reports its selected spin,
contraction norms, omitted sections/members and generated `A` symmetry labels
when labels were absent. It retains geometry, basis, real coefficients,
energies, occupations and labels; QVF identities, bonds, method metadata,
jobs and overlap/density matrices are not retained. Supply the reported spin
on reimport and keep the original archive.

## Python API and limits

```python
from qvf.convert import import_xyz, export_xyz, import_cube, export_cube
# Since toolkit 0.6.0:
from qvf.convert import import_xsf, export_xsf, import_pdb, export_pdb
# In the development checkout (Unreleased):
from qvf.convert import import_molden, export_molden

report = import_xyz("molecule.xyz", "molecule.qvf")
report = export_xyz("molecule.qvf", "geometry.xyz", extended=True)
report = import_cube("field.cube", "field.qvf", kind="volume.generic")
report = export_cube("field.qvf", "field-export.cube", section="volume")
report = import_molden("orbitals.molden", "orbitals.qvf", spin="restricted")
```

Import text is capped at 64 MiB. Geometry/grid importers limit coordinate/scalar
values to five million; Molden limits coefficient matrices to five million
entries and contractions to 512 primitives each.
These initial converters parse bounded inputs in memory; they are not a
replacement for the streaming QVF reader/writer for large datasets. QVF
reader limits also apply on export. Unsupported formats remain in WP-48:
POSCAR/CHGCAR and CIF; broader Molden dialects, richer extXYZ properties and
biomolecular PDB metadata mappings also remain future work. No QVF schema, canonical kind or
finding code changes.
