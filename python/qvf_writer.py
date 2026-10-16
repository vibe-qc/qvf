"""Compatibility import; use the qvf package for new code."""
import sys
import warnings
warnings.warn("qvf_writer is deprecated; use qvf.writer", DeprecationWarning, stacklevel=2)
from qvf import _legacy_writer as _implementation
sys.modules[__name__] = _implementation
