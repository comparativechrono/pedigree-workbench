"""
mpedtools.ops - Operations on PED and MPED pedigree data.

Provides extract, merge, filter, summarise, split, and conversion functions.
"""

from __future__ import annotations

import os
from typing import Optional

from .core import (
    Individual, Pedigree, ValidationIssue,
    PHENO_UNKNOWN, PHENO_UNAFFECTED, PHENO_AFFECTED, PHENO_CARRIER,
    MISSING_PARENT, validate, format_output, write,
)


# ── Extract single-phenotype PED from MPED ───────────────────────────────

def extract_phenotype(pedigree: Pedigree, phenotype_name: str) -> Pedigree:
    """Extract a single-phenotype PED from an MPED pedigree.

    Creates a new Pedigree with one phenotype column, mapping carrier (3)
    to unaffected (1) for PED compatibility.

    Parameters
    ----------
    pedigree : Pedigree
        Source pedigree (typically MPED with multiple phenotypes).
    phenotype_name : str
        Name of the phenotype column to extract.

    Returns
    -------
    Pedigree
        New single-phenotype pedigree in PED format.

    Raises
    ------
    ValueError
        If the phenotype name is not found.
    """
    if phenotype_name not in pedigree.phenotype_names:
        available = ", ".join(pedigree.phenotype_names)
        raise ValueError(
            f"Phenotype '{phenotype_name}' not found. Available: {available}"
        )

    new_individuals = []
    for ind in pedigree.individuals:
        val = ind.phenotypes.get(phenotype_name, PHENO_UNKNOWN)
        # Collapse carrier to unaffected for standard PED
        if val == PHENO_CARRIER:
            val = PHENO_UNAFFECTED

        new_individuals.append(Individual(
            family_id=ind.family_id,
            ind_id=ind.ind_id,
            father_id=ind.father_id,
            mother_id=ind.mother_id,
            sex=ind.sex,
            phenotypes={phenotype_name: val},
        ))

    return Pedigree(
        phenotype_names=[phenotype_name],
        individuals=new_individuals,
        is_mped=False,
        comments=[f"# Extracted phenotype: {phenotype_name}"],
    )


def extract_all_phenotypes(
    pedigree: Pedigree,
    output_dir: str,
    prefix: Optional[str] = None,
) -> list[str]:
    """Extract each phenotype from an MPED as a separate PED file.

    Parameters
    ----------
    pedigree : Pedigree
        Source MPED pedigree.
    output_dir : str
        Directory to write output files.
    prefix : str, optional
        Filename prefix. Defaults to 'pedigree'.

    Returns
    -------
    list[str]
        Paths to the written files.
    """
    if prefix is None:
        prefix = "pedigree"

    os.makedirs(output_dir, exist_ok=True)
    paths = []

    for pname in pedigree.phenotype_names:
        extracted = extract_phenotype(pedigree, pname)
        # Sanitise filename
        safe_name = pname.replace(" ", "_").replace("/", "_")
        filepath = os.path.join(output_dir, f"{prefix}_{safe_name}.ped")
        write(extracted, filepath, force_format="ped")
        paths.append(filepath)

    return paths


# ── Merge PED files into MPED ────────────────────────────────────────────

def merge(pedigrees: list[Pedigree], phenotype_names: Optional[list[str]] = None) -> Pedigree:
    """Merge multiple single-phenotype PED pedigrees into one MPED.

    All pedigrees must have the same individuals (same FamID+IndID sets with
    matching pedigree structure). Each contributes one phenotype column.

    Parameters
    ----------
    pedigrees : list[Pedigree]
        List of single-phenotype pedigrees to merge.
    phenotype_names : list[str], optional
        Names for the phenotype columns. If None, uses the phenotype names
        from each pedigree.

    Returns
    -------
    Pedigree
        Merged MPED pedigree.

    Raises
    ------
    ValueError
        If pedigrees have mismatched individuals.
    """
    if not pedigrees:
        raise ValueError("No pedigrees to merge")

    if phenotype_names is None:
        phenotype_names = []
        for i, ped in enumerate(pedigrees):
            if ped.phenotype_names:
                name = ped.phenotype_names[0]
            else:
                name = f"Phenotype_{i + 1}"
            # Ensure uniqueness
            base = name
            counter = 2
            while name in phenotype_names:
                name = f"{base}_{counter}"
                counter += 1
            phenotype_names.append(name)

    if len(phenotype_names) != len(pedigrees):
        raise ValueError(
            f"Got {len(phenotype_names)} phenotype names for {len(pedigrees)} pedigrees"
        )

    # Use the first pedigree as the structural template
    base = pedigrees[0]

    # Build lookup for each additional pedigree
    lookups: list[dict[tuple[str, str], Individual]] = []
    for ped in pedigrees:
        lookup = {}
        for ind in ped.individuals:
            lookup[(ind.family_id, ind.ind_id)] = ind
        lookups.append(lookup)

    # Build merged individuals
    merged_individuals = []
    for ind in base.individuals:
        key = (ind.family_id, ind.ind_id)
        pheno_dict: dict[str, int] = {}

        for j, pname in enumerate(phenotype_names):
            other_ind = lookups[j].get(key)
            if other_ind and other_ind.phenotypes:
                # Get the first (usually only) phenotype value
                first_pheno = list(other_ind.phenotypes.values())[0]
                pheno_dict[pname] = first_pheno
            else:
                pheno_dict[pname] = PHENO_UNKNOWN

        merged_individuals.append(Individual(
            family_id=ind.family_id,
            ind_id=ind.ind_id,
            father_id=ind.father_id,
            mother_id=ind.mother_id,
            sex=ind.sex,
            phenotypes=pheno_dict,
        ))

    return Pedigree(
        phenotype_names=phenotype_names,
        individuals=merged_individuals,
        is_mped=True,
        version="1",
        comments=[f"# Merged from {len(pedigrees)} pedigrees"],
    )


# ── Split by family ──────────────────────────────────────────────────────

def split_families(pedigree: Pedigree) -> list[Pedigree]:
    """Split a multi-family PED/MPED into separate pedigrees, one per family.

    Parameters
    ----------
    pedigree : Pedigree
        Source pedigree with one or more families.

    Returns
    -------
    list[Pedigree]
        One Pedigree per family, preserving format and phenotype columns.
    """
    families_dict: dict[str, list[Individual]] = {}
    for ind in pedigree.individuals:
        families_dict.setdefault(ind.family_id, []).append(ind)

    result = []
    for fam_id in pedigree.families:
        result.append(Pedigree(
            phenotype_names=list(pedigree.phenotype_names),
            individuals=families_dict[fam_id],
            is_mped=pedigree.is_mped,
            version=pedigree.version,
            comments=[f"# Family: {fam_id}"],
        ))
    return result


# ── Filter ────────────────────────────────────────────────────────────────

def filter_family(pedigree: Pedigree, family_id: str) -> Pedigree:
    """Extract a single family from a multi-family pedigree.

    Parameters
    ----------
    pedigree : Pedigree
        Source pedigree.
    family_id : str
        Family ID to extract.

    Returns
    -------
    Pedigree
        Pedigree containing only the specified family.

    Raises
    ------
    ValueError
        If the family ID is not found.
    """
    inds = [ind for ind in pedigree.individuals if ind.family_id == family_id]
    if not inds:
        available = ", ".join(pedigree.families)
        raise ValueError(f"Family '{family_id}' not found. Available: {available}")

    return Pedigree(
        phenotype_names=list(pedigree.phenotype_names),
        individuals=inds,
        is_mped=pedigree.is_mped,
        version=pedigree.version,
        comments=[f"# Family: {family_id}"],
    )


def filter_phenotype_status(
    pedigree: Pedigree,
    phenotype_name: str,
    status: int,
) -> list[Individual]:
    """Find all individuals with a specific status for a phenotype.

    Parameters
    ----------
    pedigree : Pedigree
        Source pedigree.
    phenotype_name : str
        Phenotype column to query.
    status : int
        Status code to match (0=unknown, 1=unaffected, 2=affected, 3=carrier).

    Returns
    -------
    list[Individual]
        Matching individuals.
    """
    return [
        ind for ind in pedigree.individuals
        if ind.phenotypes.get(phenotype_name, PHENO_UNKNOWN) == status
    ]


# ── Convert between formats ──────────────────────────────────────────────

def to_ped(pedigree: Pedigree, phenotype_name: Optional[str] = None) -> Pedigree:
    """Convert an MPED pedigree to standard PED format.

    If the MPED has multiple phenotypes, you must specify which one to use.
    Carrier status (3) is collapsed to unaffected (1).

    Parameters
    ----------
    pedigree : Pedigree
        Source pedigree.
    phenotype_name : str, optional
        Which phenotype to use. Required if multiple phenotypes exist.
        Defaults to the first phenotype if only one exists.

    Returns
    -------
    Pedigree
        Standard PED-format pedigree.
    """
    if pedigree.num_phenotypes == 0:
        raise ValueError("Pedigree has no phenotype columns")

    if phenotype_name is None:
        if pedigree.num_phenotypes > 1:
            available = ", ".join(pedigree.phenotype_names)
            raise ValueError(
                f"Multiple phenotypes found ({available}). "
                f"Specify which one with phenotype_name="
            )
        phenotype_name = pedigree.phenotype_names[0]

    return extract_phenotype(pedigree, phenotype_name)


def to_mped(pedigree: Pedigree, phenotype_name: Optional[str] = None) -> Pedigree:
    """Convert a standard PED pedigree to MPED format.

    Parameters
    ----------
    pedigree : Pedigree
        Source PED pedigree.
    phenotype_name : str, optional
        Name for the phenotype column. Defaults to current name or 'Phenotype'.

    Returns
    -------
    Pedigree
        MPED-format pedigree.
    """
    if phenotype_name is None:
        phenotype_name = pedigree.phenotype_names[0] if pedigree.phenotype_names else "Phenotype"

    new_individuals = []
    for ind in pedigree.individuals:
        val = list(ind.phenotypes.values())[0] if ind.phenotypes else PHENO_UNKNOWN
        new_individuals.append(Individual(
            family_id=ind.family_id,
            ind_id=ind.ind_id,
            father_id=ind.father_id,
            mother_id=ind.mother_id,
            sex=ind.sex,
            phenotypes={phenotype_name: val},
        ))

    return Pedigree(
        phenotype_names=[phenotype_name],
        individuals=new_individuals,
        is_mped=True,
        version="1",
    )


# ── Add / remove phenotype columns ───────────────────────────────────────

def add_phenotype(
    pedigree: Pedigree,
    name: str,
    default_value: int = PHENO_UNKNOWN,
) -> Pedigree:
    """Add a new phenotype column to a pedigree.

    Parameters
    ----------
    pedigree : Pedigree
        Source pedigree.
    name : str
        Name for the new phenotype column.
    default_value : int
        Default value for all individuals (0=unknown).

    Returns
    -------
    Pedigree
        New pedigree with the additional column.
    """
    if name in pedigree.phenotype_names:
        raise ValueError(f"Phenotype '{name}' already exists")

    new_names = list(pedigree.phenotype_names) + [name]
    new_individuals = []
    for ind in pedigree.individuals:
        new_phenos = dict(ind.phenotypes)
        new_phenos[name] = default_value
        new_individuals.append(Individual(
            family_id=ind.family_id, ind_id=ind.ind_id,
            father_id=ind.father_id, mother_id=ind.mother_id,
            sex=ind.sex, phenotypes=new_phenos,
        ))

    return Pedigree(
        phenotype_names=new_names,
        individuals=new_individuals,
        is_mped=True if len(new_names) > 1 else pedigree.is_mped,
        version=pedigree.version or "1",
        comments=list(pedigree.comments),
    )


def remove_phenotype(pedigree: Pedigree, name: str) -> Pedigree:
    """Remove a phenotype column from a pedigree.

    Parameters
    ----------
    pedigree : Pedigree
        Source pedigree.
    name : str
        Name of the phenotype column to remove.

    Returns
    -------
    Pedigree
        New pedigree without the specified column.
    """
    if name not in pedigree.phenotype_names:
        raise ValueError(f"Phenotype '{name}' not found")

    new_names = [n for n in pedigree.phenotype_names if n != name]
    new_individuals = []
    for ind in pedigree.individuals:
        new_phenos = {k: v for k, v in ind.phenotypes.items() if k != name}
        new_individuals.append(Individual(
            family_id=ind.family_id, ind_id=ind.ind_id,
            father_id=ind.father_id, mother_id=ind.mother_id,
            sex=ind.sex, phenotypes=new_phenos,
        ))

    is_mped = pedigree.is_mped if len(new_names) > 1 else False
    return Pedigree(
        phenotype_names=new_names,
        individuals=new_individuals,
        is_mped=is_mped,
        version=pedigree.version,
        comments=list(pedigree.comments),
    )


# ── Summary ──────────────────────────────────────────────────────────────

def summarise(pedigree: Pedigree) -> str:
    """Generate a human-readable summary of a pedigree.

    Parameters
    ----------
    pedigree : Pedigree
        The pedigree to summarise.

    Returns
    -------
    str
        Multi-line summary text.
    """
    lines = []
    fmt = "MPED v" + (pedigree.version or "1") if pedigree.is_mped else "PED"
    lines.append(f"Format: {fmt}")
    if pedigree.source_path:
        lines.append(f"Source: {pedigree.source_path}")

    lines.append(f"Individuals: {len(pedigree.individuals)}")
    lines.append(f"Families: {len(pedigree.families)} ({', '.join(pedigree.families)})")

    founders = sum(1 for ind in pedigree.individuals if not ind.has_parents)
    non_founders = len(pedigree.individuals) - founders
    lines.append(f"Founders: {founders}, Non-founders: {non_founders}")

    males = sum(1 for ind in pedigree.individuals if ind.sex == 1)
    females = sum(1 for ind in pedigree.individuals if ind.sex == 2)
    unknown = sum(1 for ind in pedigree.individuals if ind.sex == 0)
    lines.append(f"Sex: {males} male, {females} female, {unknown} unknown")

    lines.append(f"Phenotype columns: {pedigree.num_phenotypes}")
    for pname in pedigree.phenotype_names:
        counts = {PHENO_UNKNOWN: 0, PHENO_UNAFFECTED: 0, PHENO_AFFECTED: 0, PHENO_CARRIER: 0}
        for ind in pedigree.individuals:
            val = ind.phenotypes.get(pname, PHENO_UNKNOWN)
            counts[val] = counts.get(val, 0) + 1

        parts = []
        if counts[PHENO_AFFECTED] > 0:
            parts.append(f"{counts[PHENO_AFFECTED]} affected")
        if counts[PHENO_CARRIER] > 0:
            parts.append(f"{counts[PHENO_CARRIER]} carrier")
        if counts[PHENO_UNAFFECTED] > 0:
            parts.append(f"{counts[PHENO_UNAFFECTED]} unaffected")
        if counts[PHENO_UNKNOWN] > 0:
            parts.append(f"{counts[PHENO_UNKNOWN]} unknown")

        lines.append(f"  {pname}: {', '.join(parts)}")

    # Validation
    issues = validate(pedigree)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    if issues:
        lines.append(f"Validation: {len(errors)} error(s), {len(warnings)} warning(s)")
        for issue in issues[:10]:
            lines.append(f"  [{issue.level}] {issue.message}")
        if len(issues) > 10:
            lines.append(f"  ... and {len(issues) - 10} more")
    else:
        lines.append("Validation: OK")

    return "\n".join(lines)
