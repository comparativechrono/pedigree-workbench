"""ga4gh2studio: draw GA4GH Pedigree and Phenopackets Family files in Pedigree Studio.

It reads GA4GH files through pedigree-ga4gh, the one GA4GH implementation that
the lab's pedigree tools share.
"""
__version__ = "0.4.1"

from .converter import ConversionResult, LegacyFileError, convert, convert_file, kindred_to_session  # noqa: E402

__all__ = ["convert", "convert_file", "kindred_to_session", "ConversionResult", "LegacyFileError", "__version__"]
