try:
    from ._version import version as __version__
except ImportError:
    #_version.py is written when the package is built, so it is missing from a copy of the source, as in a browser
    __version__ = 'unknown'
from .core import pedigree_processing, PED_export

__all__ = [
    "pedigree_processing",
    "PED_export",
]