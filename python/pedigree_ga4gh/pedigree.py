"""Builders for the GA4GH Pedigree in its Phenopackets form.

The GA4GH Pedigree Standard is a conceptual model: a pedigree is a set of
individuals and the relationships between them, each relationship naming its
relation with a KIN term. It is carried by another standard rather than being
a file format of its own. In the Phenopackets form, which the standard's own
examples use (https://pedigree.readthedocs.io/en/latest/examples.html):

* ``individuals`` is a list of Phenopackets, one per member of the family;
* each relationship is ``{individualId, relation, relativeId}``, where the two
  ids are the ``subject.id`` of Phenopackets in ``individuals`` and
  ``relation`` is a KIN term, read as "individual *relation* relative";
* ``indexPatients`` lists the subject ids of the proband(s) or consultand(s).

This follows the proposed ``org.ga4gh.pedigree.v1.Pedigree`` message
(phenopacket-schema pull request #364, 2022). That proposal was closed without
being merged in September 2025 because the GA4GH pedigree group had not
settled on a form, so the standard has no approved file format yet. Every part
of the output that does have an approved schema is valid: each individual is a
valid Phenopacket v2 and each relation a current KIN term. If GA4GH settles on
a different form, this module is the one place to change.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from . import kin
from .phenopackets import is_partial_date


def relationship(individual_id: str, relation: str, relative_id: str) -> Dict:
    """``individual`` *relation* ``relative``, e.g. ``("MOTHER", "KIN:027", "CHILD")``."""
    if not individual_id or not relative_id:
        raise ValueError("a relationship needs two individuals")
    if individual_id == relative_id:
        raise ValueError("{} cannot be related to themselves".format(individual_id))
    return {"individualId": individual_id, "relation": kin.relation(relation), "relativeId": relative_id}


def pedigree(pedigree_id: str, *, individuals: Sequence[Dict], relationships: Sequence[Dict],
             index_patients: Iterable[str] = (), narrative: Optional[str] = None,
             date: Optional[str] = None, status: Optional[str] = None) -> Dict:
    """A GA4GH Pedigree, with its fields in the order of the proposed proto."""
    if not pedigree_id:
        raise ValueError("a pedigree needs an id")
    if date and not is_partial_date(date):
        raise ValueError("date {!r} must be YYYY, YYYY-MM or YYYY-MM-DD".format(date))
    out: Dict = {"id": pedigree_id}
    if narrative:
        out["narrative"] = narrative
    if date:
        out["date"] = date
    if status:
        out["status"] = status
    idx: List[str] = list(dict.fromkeys(i for i in index_patients if i))
    if idx:
        out["indexPatients"] = idx
    out["individuals"] = list(individuals)
    if relationships:
        out["relationships"] = list(relationships)
    return out
