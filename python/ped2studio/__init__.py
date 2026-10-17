"""ped2studio — Convert PED pedigree files to Pedigree Studio session JSON."""

__version__ = "0.2.0"

from .converter import convert, convert_file, parse_ped

__all__ = ["convert", "convert_file", "parse_ped"]
