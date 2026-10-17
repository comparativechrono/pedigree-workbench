"""studio2ga4gh: convert Pedigree Studio drawings to GA4GH files.

This is the pedigree workbench's copy (0.4.0). It writes the GA4GH Pedigree
and the Phenopackets Family through pedigree-ga4gh, the workbench's single
implementation of GA4GH output; see that package for what the files contain.
"""
__version__ = "0.4.0"

from .converter import ConversionResult, convert, convert_file, load_terms, session_to_kindreds  # noqa: E402
from .session import parse as parse_session  # noqa: E402

__all__ = ["convert", "convert_file", "load_terms", "session_to_kindreds", "parse_session",
           "ConversionResult", "__version__"]
