"""ped2studio — Convert PED pedigree files to Pedigree Studio session JSON."""

__version__ = "0.2.2"

from .converter import convert, convert_file, parse_ped  # noqa: E402

__all__ = ["convert", "convert_file", "parse_ped", "__version__"]
