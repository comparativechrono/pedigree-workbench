"""GA4GH families for the Risk tab.

The Risk tab reads drawings, PED and MPED files in the page (assets/js/risk-read.js). A GA4GH Pedigree or a
Phenopackets Family is read here, with pedigree-ga4gh, so that the family's parents are found exactly as PedNet,
phenopacket-toolkit and the converters find them, into the same shape:

    {"id", "kind": "pedigree" or "family", "people", "conditions", "notes", "unrecorded", "partners"}

with "partners" the couples the file records as partners, with each person as {"id", "label", "name", "sex": "M",
"F" or "U", "father", "mother", "twin", "status", "index"},
where status gives each condition the person has a record of as "affected" or "unaffected". A GA4GH Pedigree records
the affected by their conditions, and the unaffected only by a condition marked as excluded, so people with no record
of a condition are taken as PedNet takes them ("unrecorded": "auto"). A Family's own affected status is a condition
of its own, the first, with the key "family".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

FAMILY_STATUS = "family"
_SEXES = {"MALE": "M", "FEMALE": "F"}


def _read(path: str) -> Dict[str, Any]:
    import pedigree_ga4gh
    import os
    with open(os.path.expanduser(path), encoding="utf-8-sig") as fh:
        text = fh.read()
    try:
        doc = pedigree_ga4gh.loads(text)
    except ValueError as e:
        raise ValueError(f"This is not a JSON file: {e}")
    if not isinstance(doc, dict):
        raise ValueError("This is not a GA4GH Pedigree or a Phenopackets Family, each of which is a JSON object")
    return doc


def family(path: str) -> Dict[str, Any]:
    """The family in a GA4GH Pedigree or Phenopackets Family, as the Risk tab reads it (see above). An older form of
    the files, or a file with no pedigree in it, is refused with a ValueError that says what to do."""
    import pedigree_ga4gh
    from pedigree_ga4gh import kin
    doc = _read(path)
    old = pedigree_ga4gh.identify_legacy(doc)
    if old is not None:
        how = ("Upgrade it first (Tools: Upgrade an older GA4GH file, or pedigree-ga4gh upgrade in the terminal)"
               if old.upgradable else "It can’t be upgraded, as it is a draft that no tool writes any more")
        raise ValueError(f"This is {old.description}, not a GA4GH Pedigree or Phenopackets Family as the standard "
                         f"has them. {how}.")
    kind = pedigree_ga4gh.detect(doc)
    if kind not in ("pedigree", "family"):
        if kind in ("cohort", "phenopacket"):
            raise ValueError(f"This is a Phenopackets {kind}, which has no pedigree: the Risk tab reads a GA4GH "
                             "Pedigree or a Phenopackets Family")
        raise ValueError("This is not a GA4GH Pedigree or a Phenopackets Family")
    kindred, notes = pedigree_ga4gh.from_document(doc)
    notes = list(notes)

    conditions: List[Dict[str, Any]] = []
    if kind == "family":
        conditions.append({"key": FAMILY_STATUS, "label": "affected, as the Family records it"})
    seen = set()
    for member in kindred.members:
        for term in member.terms:
            key = (term.id or term.label or "").strip()
            if key and key not in seen:
                seen.add(key)
                conditions.append({"key": key, "label": term.label or term.id, "id": term.id or None})

    twins, partners = {}, []
    ids = set(kindred.ids())
    for r in kindred.relations:
        if r.kin == kin.TERMS["KIN:010"].id:     # isMonozygoticMultipleBirthSiblingOf
            twins.setdefault(r.relative, r.individual)
        elif kin.is_a(r.kin, kin.PARTNER) and r.individual in ids and r.relative in ids:
            partners.append([r.individual, r.relative])
    people = []
    for member in kindred.members:
        father, mother, more = kindred.genetic_parents(member.id)
        notes.extend(n for n in more if n not in notes)
        status: Dict[str, str] = {}
        if kind == "family" and member.affected is not None:
            status[FAMILY_STATUS] = "affected" if member.affected else "unaffected"
        for term in member.terms:
            key = (term.id or term.label or "").strip()
            if not key:
                continue
            if not term.excluded:
                status[key] = "affected"
            elif status.get(key) != "affected":
                status[key] = "unaffected"
        people.append({
            "id": member.id, "label": member.id, "name": "", "sex": _SEXES.get(member.sex, "U"),
            "father": father, "mother": mother, "twin": twins.get(member.id) if twins.get(member.id) != member.id else None,
            "status": status, "index": bool(member.index), "deceased": member.vital_status == "DECEASED",
        })
    if not people:
        raise ValueError("There is no one in this file")
    return {"id": str(kindred.id or "family"), "kind": kind, "people": people, "conditions": conditions,
            "notes": notes, "unrecorded": "auto", "unrecordedFor": {FAMILY_STATUS: "unknown"}, "partners": partners}
