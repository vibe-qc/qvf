"""Adapters that write QVF archives from other programs' in-memory results.

Each adapter is a module of its own and imports its program lazily, so
``import qvf.adapters`` and ``import qvf.adapters.pyscf`` work without that
program installed; calling an export function without it raises an
``ImportError`` that names the extra to install.

* ``qvf.adapters.pyscf``: molecular SCF/DFT and closed-shell response results
  of PySCF. From a checkout containing this unreleased adapter, install
  ``python -m pip install 'python/[pyscf,validate]'``.
"""

__all__ = ["pyscf"]
