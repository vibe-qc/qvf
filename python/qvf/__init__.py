"""QVF: pure Python streaming archives, lazy readers, editing and validation.

Install ``qvf-writer[numpy]`` for numeric convenience writers and NumPy array
views, or ``qvf-writer[validate]`` for full JSON Schema checks. The package,
raw-buffer writer, reader and editor require only the standard library.
"""
from .model import Manifest, Section, MemberSpec, Source, Lattice, GridSpec
from .reader import Reader, Tensor, Limits
from .writer import Writer
from .editor import Editor
from . import validate
from .validate import validate_qvf, FINDING_CODES
from ._legacy_writer import QvfWriter, TOOLKIT_VERSION as __version__
from .validate import QvfReader

__all__ = ["Writer", "Reader", "Editor", "Tensor", "Limits", "Manifest", "Section",
           "MemberSpec", "Source", "Lattice", "GridSpec", "validate", "validate_qvf",
           "FINDING_CODES", "QvfWriter", "QvfReader", "__version__"]
