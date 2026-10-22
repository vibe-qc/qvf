#!/usr/bin/env python3
"""Compatibility entry point for the packaged QVF conformance runner."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from qvf import conformance as _runner

globals().update({name: value for name, value in vars(_runner).items()
                  if not name.startswith("__")})

if __name__ == "__main__":
    raise SystemExit(_runner._main(sys.argv[1:]))
