"""
mpedtools - Tools for working with PED and MPED pedigree files.

Core module: data models, PED/MPED parser, and file I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────

PHENO_UNKNOWN = 0
PHENO_UNAFFECTED = 1
PHENO_AFFECTED = 2
PHENO_CARRIER = 3

VALID_PHENO_CODES = {0, 1, 2, 3}
VALID_SEX_CODES = {0, 1, 2}
MISSING_PARENT = "0"

COLUMN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


# ── Data models ───────────────────────────────────────────────────────────

@dataclass
class Individual:
    """One individual in a pedigree."""
    family_id: str
    ind_id: str
    father_id: str        # "0" if unknown
    mother_id: str        # "0" if unknown
    sex: int              # 1=male, 2=female, 0=unknown
    phenotypes: dict[str, int] = field(default_factory=dict)
    # phenotype_name -> code (0-3)

    @property
    def has_parents(self) -> bool:
        return self.father_id != MISSING_PARENT or self.mother_id != MISSING_PARENT

    def get_phenotype(self, name: str) -> int:
        """Get phenotype code for a named phenotype. Returns 0 if not found."""
        return self.phenotypes.get(name, PHENO_UNKNOWN)

    def is_affected(self, name: Optional[str] = None) -> bool:
        """Check if individual is affected for a given (or any) phenotype."""
        if name:
            return self.get_phenotype(name) == PHENO_AFFECTED
        return any(v == PHENO_AFFECTED for v in self.phenotypes.values())

    def is_carrier(self, name: Optional[str] = None) -> bool:
        """Check if individual is a carrier for a given (or any) phenotype."""
        if name:
            return self.get_phenotype(name) == PHENO_CARRIER
        return any(v == PHENO_CARRIER for v in self.phenotypes.values())


@dataclass
class Pedigree:
    """A parsed PED or MPED file."""
    phenotype_names: list[str]           # ordered list of phenotype column names
    individuals: list[Individual]        # all individuals in order
    is_mped: bool                        # True if parsed from MPED format
    version: Optional[str] = None        # MPED version string (e.g. "1") or None for PED
    comments: list[str] = field(default_factory=list)  # non-header comment lines
    source_path: Optional[str] = None    # original file path if loaded from file

    @property
    def families(self) -> list[str]:
        """List of unique family IDs in order of first appearance."""
        seen = set()
        result = []
        for ind in self.individuals:
            if ind.family_id not in seen:
                seen.add(ind.family_id)
                result.append(ind.family_id)
        return result

    @property
    def num_phenotypes(self) -> int:
        return len(self.phenotype_names)

    def get_family(self, family_id: str) -> list[Individual]:
        """Get all individuals in a specific family."""
        return [ind for ind in self.individuals if ind.family_id == family_id]

    def get_individual(self, family_id: str, ind_id: str) -> Optional[Individual]:
        """Find a specific individual by family and individual ID."""
        for ind in self.individuals:
            if ind.family_id == family_id and ind.ind_id == ind_id:
                return ind
        return None

    def get_affected(self, phenotype: Optional[str] = None) -> list[Individual]:
        """Get all affected individuals, optionally filtered by phenotype name."""
        return [ind for ind in self.individuals if ind.is_affected(phenotype)]

    def get_carriers(self, phenotype: Optional[str] = None) -> list[Individual]:
        """Get all carriers, optionally filtered by phenotype name."""
        return [ind for ind in self.individuals if ind.is_carrier(phenotype)]


# ── Validation ────────────────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    """A single validation issue found in a PED/MPED file."""
    level: str      # 'error' or 'warning'
    line: int       # line number (1-based), 0 for file-level issues
    message: str


def validate(pedigree: Pedigree) -> list[ValidationIssue]:
    """Validate a parsed pedigree for structural correctness.

    Returns a list of ValidationIssue objects. An empty list means the file
    is valid.
    """
    issues: list[ValidationIssue] = []

    if not pedigree.phenotype_names:
        issues.append(ValidationIssue("error", 0, "No phenotype columns defined"))

    # Check for duplicate column names
    seen_cols = set()
    for name in pedigree.phenotype_names:
        if name in seen_cols:
            issues.append(ValidationIssue("error", 0, f"Duplicate phenotype column name: {name}"))
        seen_cols.add(name)
        if not COLUMN_NAME_PATTERN.match(name):
            issues.append(ValidationIssue("error", 0,
                f"Invalid phenotype column name: '{name}' (must be alphanumeric, underscore, or hyphen)"))

    # Build ID lookup per family
    family_ids: dict[str, dict[str, int]] = {}  # family -> {ind_id -> line_number}

    for i, ind in enumerate(pedigree.individuals, start=1):
        fam = ind.family_id
        if fam not in family_ids:
            family_ids[fam] = {}

        # Duplicate individual ID within family
        if ind.ind_id in family_ids[fam]:
            issues.append(ValidationIssue("error", i,
                f"Duplicate individual ID '{ind.ind_id}' in family '{fam}'"))
        family_ids[fam][ind.ind_id] = i

        # Sex code
        if ind.sex not in VALID_SEX_CODES:
            issues.append(ValidationIssue("warning", i,
                f"Invalid sex code {ind.sex} for {ind.ind_id}"))

        # Phenotype codes
        for pname, pval in ind.phenotypes.items():
            if pval not in VALID_PHENO_CODES:
                issues.append(ValidationIssue("warning", i,
                    f"Invalid phenotype code {pval} for {ind.ind_id} phenotype '{pname}'"))

        # Phenotype count
        if len(ind.phenotypes) != len(pedigree.phenotype_names):
            issues.append(ValidationIssue("error", i,
                f"Individual {ind.ind_id} has {len(ind.phenotypes)} phenotype values, "
                f"expected {len(pedigree.phenotype_names)}"))

        # Single parent
        has_father = ind.father_id != MISSING_PARENT
        has_mother = ind.mother_id != MISSING_PARENT
        if has_father != has_mother:
            issues.append(ValidationIssue("warning", i,
                f"Individual {ind.ind_id} has only one parent specified"))

    # Check parent references exist and have correct sex
    for ind in pedigree.individuals:
        fam = ind.family_id
        if ind.father_id != MISSING_PARENT:
            if ind.father_id not in family_ids.get(fam, {}):
                issues.append(ValidationIssue("error", 0,
                    f"Father '{ind.father_id}' of '{ind.ind_id}' not found in family '{fam}'"))
            else:
                father = pedigree.get_individual(fam, ind.father_id)
                if father and father.sex == 2:
                    issues.append(ValidationIssue("warning", 0,
                        f"Father '{ind.father_id}' of '{ind.ind_id}' has sex=2 (female)"))

        if ind.mother_id != MISSING_PARENT:
            if ind.mother_id not in family_ids.get(fam, {}):
                issues.append(ValidationIssue("error", 0,
                    f"Mother '{ind.mother_id}' of '{ind.ind_id}' not found in family '{fam}'"))
            else:
                mother = pedigree.get_individual(fam, ind.mother_id)
                if mother and mother.sex == 1:
                    issues.append(ValidationIssue("warning", 0,
                        f"Mother '{ind.mother_id}' of '{ind.ind_id}' has sex=1 (male)"))

    return issues


# ── PED/MPED parser ──────────────────────────────────────────────────────

def read(filepath: str) -> Pedigree:
    """Read a PED or MPED file. Detects format automatically.

    Parameters
    ----------
    filepath : str
        Path to the .ped or .mped file.

    Returns
    -------
    Pedigree
        Parsed pedigree data.
    """
    with open(filepath, "r") as f:
        text = f.read()

    pedigree = parse(text)
    pedigree.source_path = filepath
    return pedigree


def parse(text: str) -> Pedigree:
    """Parse PED or MPED format text. Detects format automatically.

    Parameters
    ----------
    text : str
        File contents.

    Returns
    -------
    Pedigree
        Parsed pedigree data.
    """
    lines = text.splitlines()

    # Detect format: look for MPED header
    format_line = None
    header_line = None
    is_mped = False
    version = None
    phenotype_names: list[str] = []
    comments: list[str] = []
    data_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# MPED v"):
            is_mped = True
            # Parse version and column names
            parts = stripped.split("\t")
            version_part = parts[0]  # "# MPED v1"
            version_match = re.search(r"v(\d+)", version_part)
            version = version_match.group(1) if version_match else "1"
            phenotype_names = [p.strip() for p in parts[1:] if p.strip()]
            format_line = i
            continue
        if stripped.startswith("# FamID"):
            header_line = i
            continue
        if stripped.startswith("#"):
            comments.append(stripped)
            continue
        # First non-comment, non-header line = data start
        data_start = i
        break

    # Parse data lines
    individuals: list[Individual] = []

    if not is_mped and not phenotype_names:
        # Standard PED: single phenotype column named "Phenotype"
        phenotype_names = ["Phenotype"]

    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if stripped.startswith("#") and not stripped.startswith("# MPED") and not stripped.startswith("# FamID"):
                comments.append(stripped)
            continue

        parts = stripped.split("\t")
        # Also try space-delimited for standard PED compatibility
        if len(parts) < 6:
            parts = stripped.split()
        if len(parts) < 6:
            continue

        fam_id = parts[0]
        ind_id = parts[1]
        father_id = parts[2] if parts[2] not in ("0", "-9") else MISSING_PARENT
        mother_id = parts[3] if parts[3] not in ("0", "-9") else MISSING_PARENT

        try:
            sex = int(parts[4])
        except ValueError:
            sex = 0

        # Parse phenotype columns
        pheno_dict: dict[str, int] = {}
        for j, pname in enumerate(phenotype_names):
            col_idx = 5 + j
            if col_idx < len(parts):
                try:
                    pheno_dict[pname] = int(parts[col_idx])
                except ValueError:
                    pheno_dict[pname] = PHENO_UNKNOWN
            else:
                pheno_dict[pname] = PHENO_UNKNOWN

        individuals.append(Individual(
            family_id=fam_id,
            ind_id=ind_id,
            father_id=father_id,
            mother_id=mother_id,
            sex=sex,
            phenotypes=pheno_dict,
        ))

    return Pedigree(
        phenotype_names=phenotype_names,
        individuals=individuals,
        is_mped=is_mped,
        version=version,
        comments=comments,
    )


# ── PED/MPED writer ─────────────────────────────────────────────────────

def write(pedigree: Pedigree, filepath: str, force_format: Optional[str] = None):
    """Write a pedigree to a PED or MPED file.

    Parameters
    ----------
    pedigree : Pedigree
        The pedigree data to write.
    filepath : str
        Output file path.
    force_format : str, optional
        'ped' or 'mped'. If None, inferred from pedigree.is_mped.
    """
    text = format_output(pedigree, force_format)
    with open(filepath, "w") as f:
        f.write(text)


def format_output(pedigree: Pedigree, force_format: Optional[str] = None) -> str:
    """Format a pedigree as PED or MPED text.

    Parameters
    ----------
    pedigree : Pedigree
        The pedigree data.
    force_format : str, optional
        'ped' or 'mped'. If None, inferred from pedigree.is_mped.

    Returns
    -------
    str
        Formatted file contents.
    """
    use_mped = pedigree.is_mped
    if force_format == "ped":
        use_mped = False
    elif force_format == "mped":
        use_mped = True

    lines: list[str] = []

    if use_mped:
        # Format line
        lines.append("# MPED v1\t" + "\t".join(pedigree.phenotype_names))
        # Header line
        lines.append("# FamID\tIndID\tFatherID\tMotherID\tSex\t" +
                     "\t".join(pedigree.phenotype_names))
    else:
        lines.append("# FamID\tIndID\tFatherID\tMotherID\tSex\tPhenotype")

    # Comments
    for c in pedigree.comments:
        if not c.startswith("# MPED") and not c.startswith("# FamID"):
            lines.append(c)

    # Data
    for ind in pedigree.individuals:
        parts = [ind.family_id, ind.ind_id, ind.father_id, ind.mother_id, str(ind.sex)]

        if use_mped:
            for pname in pedigree.phenotype_names:
                parts.append(str(ind.phenotypes.get(pname, PHENO_UNKNOWN)))
        else:
            # Standard PED: use first phenotype, collapse carrier to unaffected
            if pedigree.phenotype_names:
                val = ind.phenotypes.get(pedigree.phenotype_names[0], PHENO_UNKNOWN)
                if val == PHENO_CARRIER:
                    val = PHENO_UNAFFECTED  # PED has no carrier code
                parts.append(str(val))
            else:
                parts.append(str(PHENO_UNKNOWN))

        lines.append("\t".join(parts))

    return "\n".join(lines) + "\n"
