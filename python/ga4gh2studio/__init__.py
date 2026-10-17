"""ga4gh2studio: draw GA4GH Pedigree and Phenopackets Family files in Pedigree Studio.

This is the pedigree workbench's copy (0.4.0), which reads GA4GH through
pedigree-ga4gh, the workbench's single GA4GH implementation.
"""
__version__ = "0.4.0"

from .converter import ConversionResult, LegacyFileError, convert, convert_file, kindred_to_session  # noqa: E402

__all__ = ["convert", "convert_file", "kindred_to_session", "ConversionResult", "LegacyFileError", "__version__"]
