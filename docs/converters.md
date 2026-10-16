# Convert common files through QVF

The `qvf.convert` Python API and `qvf convert` command are included in
toolkit **0.5.0**. They use the standard library; NumPy is optional. Install
the `validate` extra for JSON Schema checks as well as the always-on
reference checks.

Every conversion writes a new file, refuses an existing destination and
returns a JSON-compatible report. QVF imports pass the reference validator
before the completed file is published. Exports validate their QVF input and
verify member hashes. Keep the original: text exports select geometry or a
grid, not a complete calculation, and the report lists unselected sections
and explains the metadata that the text format cannot carry. This is not a
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

## Python API and limits

```python
from qvf.convert import import_xyz, export_xyz, import_cube, export_cube

report = import_xyz("molecule.xyz", "molecule.qvf")
report = export_xyz("molecule.qvf", "geometry.xyz", extended=True)
report = import_cube("field.cube", "field.qvf", kind="volume.generic")
report = export_cube("field.qvf", "field-export.cube", section="volume")
```

Import text is capped at 64 MiB and five million coordinate/scalar values.
These initial converters parse bounded inputs in memory; they are not a
replacement for the streaming QVF reader/writer for large datasets. QVF
reader limits also apply on export. Unsupported formats remain in WP-48:
Molden, XSF, POSCAR/CHGCAR, PDB and CIF; richer extXYZ property mappings also
remain future work. No QVF schema, canonical kind or finding code changes.
