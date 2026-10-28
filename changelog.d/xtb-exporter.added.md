Add the standalone molecular GFN0/1/2-xTB exporter (`qvf export-xtb` and
`qvf.adapters.xtb.write_xtb`). It packages explicitly selected JSON,
geometry, trajectory, Wiberg bond orders, Molden orbitals, xTB normal modes
and scalar cubes as a validated QVF using existing format contracts.
It checks companion geometry/units/identity, reports missing or unmapped
data, preserves originals and leaves convergence unstated by default.
The exporter works without NumPy or xTB installed; root scalar energy
writing no longer unnecessarily imports NumPy.
