"""Compatibility import; use the qvf package for new code."""
import sys
from qvf import model as _implementation
sys.modules[__name__] = _implementation
