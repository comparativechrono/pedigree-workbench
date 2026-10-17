"""mpedtools — Tools for working with PED and MPED pedigree files."""

__version__ = "0.1.0"

from .core import (
    Individual, Pedigree, ValidationIssue,
    read, parse, write, format_output, validate,
    PHENO_UNKNOWN, PHENO_UNAFFECTED, PHENO_AFFECTED, PHENO_CARRIER,
)
from .ops import (
    extract_phenotype, extract_all_phenotypes, merge,
    split_families, filter_family, filter_phenotype_status,
    to_ped, to_mped, add_phenotype, remove_phenotype, summarise,
)

__all__ = [
    "Individual", "Pedigree", "ValidationIssue",
    "read", "parse", "write", "format_output", "validate",
    "extract_phenotype", "extract_all_phenotypes", "merge",
    "split_families", "filter_family", "filter_phenotype_status",
    "to_ped", "to_mped", "add_phenotype", "remove_phenotype", "summarise",
    "PHENO_UNKNOWN", "PHENO_UNAFFECTED", "PHENO_AFFECTED", "PHENO_CARRIER",
]
