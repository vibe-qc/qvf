"""Compatibility import; use the qvf package for new code."""
import sys
import warnings
warnings.warn("qvf_reader is deprecated; use qvf.reader", DeprecationWarning, stacklevel=2)
from qvf import validate as _implementation
if __name__ == "__main__":
    raise SystemExit(_implementation._main_entrypoint())
sys.modules[__name__] = _implementation
