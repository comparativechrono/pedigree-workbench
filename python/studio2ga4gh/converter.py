"""Convert a Pedigree Studio drawing to a GA4GH Pedigree and a Phenopackets Family.

The drawing is read into a :class:`pedigree_ga4gh.Kindred` (one per separate
family on the canvas) and written out by pedigree-ga4gh, the one
implementation of GA4GH output that the lab's pedigree tools share. This module
only decides what each symbol and line in the drawing means:

========================================  ==============================================
In Pedigree Studio                        In the GA4GH files
========================================  ==============================================
square, circle, diamond                   sex MALE, FEMALE, UNKNOWN_SEX
slash (deceased)                          vitalStatus DECEASED (otherwise ALIVE)
arrow with a P (proband)                  indexPatients; the Family's proband
arrow alone (consultand)                  noted in the narrative
fill, halves, quarters, shading           a disease or phenotype for each condition named
                                          in the colour key, once it has an ontology term
child line from a couple                  isBiologicalMotherOf / isBiologicalFatherOf
                                          (isBiologicalParentOf if the parent's sex is unknown)
dashed child line                         isAdoptiveParentOf
D in a parent's symbol                    isSpermDonorOf / isOvumDonorOf
G in a parent's symbol (S in older        isGestationalCarrierOf (not a biological parent)
drawings)
identical / non-identical twins           isMonozygotic- / isPolyzygoticMultipleBirthSiblingOf
twins of unknown zygosity (?)             isMultipleBirthSiblingOf
consanguineous couple                     isConsanguineousPartnerOf
separated couple                          isSeparatedPartnerOf
couple without children                   isPartnerOf
pregnancy loss (triangle)                 a member with vitalStatus DECEASED, noted in the narrative
"no children" and "infertility" bars      not people: noted in the narrative
carrier dot, presymptomatic line, P       noted in the narrative (no ontology term exists)
========================================  ==============================================

Names and other notes written under symbols are not exported: Phenopackets
have no field for a name, and such notes are often personal data.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from pedigree_ga4gh import (DISEASE, PHENOTYPE, Kindred, Member, Relation, Term, kin, ontology,
                            to_ga4gh_pedigree, to_phenopackets_family)
from pedigree_ga4gh.io import dumps

from . import __version__
from .session import Session, StudioPerson, parse

CREATED_BY = "studio2ga4gh " + __version__


@dataclass
class ConversionResult:
    files: List[Tuple[str, str]]               # (file name, JSON text)
    kindreds: List[Kindred]
    conditions: List[str]                      # condition names in the colour key
    unmatched: List[str]                       # conditions with no ontology term yet
    warnings: List[str]
    notes: List[str] = field(default_factory=list)
    summary: str = ""

    @property
    def families(self) -> List[Kindred]:       # the name used by version 0.3
        return self.kindreds


def load_terms(obj) -> Dict[str, Dict[str, str]]:
    """Normalise a condition -> term mapping.

    Accepts ``{"Breast cancer": "MONDO:0007254"}``, ``{"Breast cancer": {"id": ...,
    "label": ..., "kind": ...}}`` and decision logs from hponorm, mondonorm or
    phenotk (``{"resolved": {...}}``). Labels are matched without regard to case.
    """
    if isinstance(obj, dict) and isinstance(obj.get("resolved"), dict):
        obj = obj["resolved"]
    out: Dict[str, Dict[str, str]] = {}
    for label, val in (obj or {}).items():
        if isinstance(val, str):
            out[label.strip().lower()] = {"id": val.strip(), "label": label.strip()}
        elif isinstance(val, dict) and (val.get("id") or val.get("curie")):
            out[label.strip().lower()] = {"id": (val.get("id") or val.get("curie")).strip(),
                                          "label": (val.get("label") or label).strip(),
                                          "kind": val.get("kind", ""),
                                          "version": val.get("version", "")}
    return out


_KEY_CURIE = re.compile(r"^(.*?)\s*[\[(]\s*([A-Za-z][A-Za-z0-9.\-]*:[^\s\])]+)\s*[\])]\s*$")


def split_key_label(text: str) -> Tuple[str, Optional[str]]:
    """Split a colour-key entry such as ``"Breast cancer [MONDO:0007254]"`` into
    its name and ontology id. Without an id in brackets the id is ``None``.

    Only an id of an ontology pedigree-ga4gh can declare in a Phenopacket
    counts (the HPO, Mondo, OMIM, Orphanet, SNOMED CT ...): anything else in
    brackets, such as a blood pressure in "Hypertension (BP:160/95)", is part
    of the name.
    """
    m = _KEY_CURIE.match(text or "")
    if m:
        curie = ontology.tidy_curie(m.group(2))
        if ontology.is_curie(curie) and ontology.prefix_of(curie) in ontology.RESOURCES:
            return m.group(1).strip() or curie, curie
    return (text or "").strip(), None


def make_id(label: str) -> str:
    """An identifier made from a label, by the same rule as studio2ped: spaces
    become underscores, and anything but letters, digits, ``_`` and ``-`` is
    dropped ("J. Mensah" -> ``J_Mensah``)."""
    return re.sub(r"[^\w\-]", "", re.sub(r"\s+", "_", (label or "").strip()))


def person_ids(s: Session, ids: str = "numbers") -> Tuple[Dict[str, str], List[str]]:
    """The id each person in the drawing is given, and notes about any that had to change.

    ``ids`` is ``"numbers"`` (pedigree numbers such as II-3), ``"drawing"`` (the
    labels the drawing shows, which may be names) or ``"studio"`` (Pedigree
    Studio's own ids). A label is made into an id by :func:`make_id`. An id that
    would be empty, ``0`` (which a PED-style pedigree reads as "no parent") or
    shared with someone else is replaced by the person's pedigree number, as in
    studio2ped.
    """
    nums = s.numbers()
    if ids not in ("numbers", "drawing", "studio"):
        raise ValueError("ids must be numbers, drawing or studio, not {!r}".format(ids))
    if ids == "numbers":
        return dict(nums), []
    labels = s.drawing_labels() if ids == "drawing" else {pid: pid for pid in s.persons}
    people = [pid for pid, p in s.persons.items() if not p.is_marker]   # (the bars are not people: no id)
    notes: List[str] = []
    out = {}
    for pid in people:
        out[pid] = make_id(labels.get(pid) or "")
        if out[pid] == "0":
            out[pid] = nums[pid]
            notes.append("{} is labelled 0, which a PED-style pedigree reads as 'no parent', so their pedigree "
                         "number is used instead".format(nums[pid]))
        elif not out[pid]:
            out[pid] = nums[pid]
            notes.append("{}'s label has nothing that can go into an id, so their pedigree number is used "
                         "instead".format(nums[pid]))
    while True:
        counts = defaultdict(int)
        for pid in people:
            counts[out[pid]] += 1
        clashes: Dict[str, List[str]] = defaultdict(list)
        for pid in people:
            if counts[out[pid]] > 1 and out[pid] != nums[pid]:
                clashes[out[pid]].append(pid)
        if not clashes:
            break
        for label, pids in clashes.items():
            for pid in pids:
                out[pid] = nums[pid]
            who = [nums[pid] for pid in pids]
            notes.append("'{}' would be the id of more than one person, so {} {} given {} pedigree number{} "
                         "instead".format(label, who[0] if len(who) == 1 else ", ".join(who[:-1]) + " and " + who[-1],
                                          "is" if len(who) == 1 else "are", "their", "" if len(who) == 1 else "s"))
    return out, notes


def _components(s: Session) -> List[List[str]]:
    """Separate families on the canvas: people joined by lines, markers left out."""
    adj: Dict[str, set] = defaultdict(set)
    people = [pid for pid, p in s.persons.items() if not p.is_marker]
    for pr in s.partnerships.values():
        adj[pr.a].add(pr.b)
        adj[pr.b].add(pr.a)
    for cl in s.child_links:
        pr = s.partnerships[cl.partnership]
        for parent in (pr.a, pr.b):
            adj[cl.child].add(parent)
            adj[parent].add(cl.child)
    for t in s.twin_links:
        adj[t.a].add(t.b)
        adj[t.b].add(t.a)
    seen, comps = set(), []
    order = sorted(people, key=lambda pid: (s.persons[pid].y, s.persons[pid].x))
    for start in order:
        if start in seen:
            continue
        comp, stack = [], [start]
        while stack:
            cur = stack.pop()
            if cur in seen or s.persons[cur].is_marker:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj[cur] - seen)
        comps.append(sorted(comp, key=lambda pid: (s.persons[pid].y, s.persons[pid].x)))
    return comps


# G marks a gestational carrier, who carried a child but is not their genetic parent, since the 2025 correction to
# the pedigree nomenclature; drawings from before it mark one S. (A woman who gives the egg and carries the
# pregnancy is a donor, D, and a genetic parent.)
GESTATIONAL_CARRIER_MARKS = ("G", "S")

# Twins' zygosity, and the KIN term for each
_TWIN_KIN = {"identical": kin.MONOZYGOTIC_MULTIPLE_BIRTH_SIBLING, "nonidentical": kin.POLYZYGOTIC_MULTIPLE_BIRTH_SIBLING,
             "unknown": kin.MULTIPLE_BIRTH_SIBLING}


def _twin_chain(a: str, b: str) -> str:
    """The zygosity of X and Z when X and Y are twins of zygosity a, and Y and Z twins of zygosity b.

    An identical twin shares the other's relation; a line of unknown zygosity leaves it unknown; and the
    non-identical twin of a non-identical twin counts as non-identical, which is what a drawing of such a set
    of twins means."""
    if a == "identical":
        return b
    if b == "identical":
        return a
    return "unknown" if "unknown" in (a, b) else "nonidentical"


def _parent_relation(parent: StudioPerson, dashed: bool, warnings: List[str], ids: Dict[str, str]) -> str:
    if dashed:
        return kin.ADOPTIVE_PARENT
    if parent.centre in GESTATIONAL_CARRIER_MARKS:
        return kin.GESTATIONAL_CARRIER
    if parent.centre == "D":
        if parent.sex == "MALE":
            return kin.SPERM_DONOR
        if parent.sex == "FEMALE":
            return kin.OVUM_DONOR
        warnings.append("{} is marked as a donor but their sex is not known; recorded as a biological "
                        "parent".format(ids[parent.id]))
        return kin.BIOLOGICAL_PARENT
    if parent.sex == "MALE":
        return kin.BIOLOGICAL_FATHER
    if parent.sex == "FEMALE":
        return kin.BIOLOGICAL_MOTHER
    return kin.BIOLOGICAL_PARENT


def session_to_kindreds(session_data: dict, *, terms: Optional[dict] = None, kind: str = DISEASE,
                        ids: str = "numbers", family_id: str = "FAM") -> Tuple[List[Kindred], List[str], List[str], List[str]]:
    """Read a Pedigree Studio session into one Kindred per family on the canvas.

    ``terms`` maps condition names in the colour key to ontology terms (see
    :func:`load_terms`); ``kind`` says whether unmatched conditions count as
    diseases or phenotypes; ``ids`` is ``"numbers"`` (pedigree numbers such as
    II-3, the default), ``"drawing"`` (the labels shown in the drawing, which
    may be names) or ``"studio"`` (Pedigree Studio's internal ids).

    Returns ``(kindreds, conditions, warnings, notes)``.
    """
    s = parse(session_data)
    mapping = load_terms(terms or {})
    warnings: List[str] = []
    notes_all: List[str] = []
    idmap, id_notes = person_ids(s, ids)
    warnings.extend(id_notes)
    conditions = [v.strip() for v in s.legend.values() if (v or "").strip()]
    conditions = list(dict.fromkeys(conditions))
    comps = _components(s)
    kids_of = s.couple_children()
    kindreds: List[Kindred] = []
    for n, comp in enumerate(comps, 1):
        fam_id = "{}{}".format(family_id, n) if len(comps) > 1 or family_id == "FAM" else family_id
        k = Kindred(id=fam_id, date=date.today().isoformat())
        notes: List[str] = []
        in_comp = set(comp)
        for pid in comp:
            p = s.persons[pid]
            m = Member(id=idmap[pid], sex=p.sex, index=p.proband)
            if p.is_loss:
                m.vital_status = "DECEASED"
                notes.append("{} is a pregnancy loss".format(m.id))
            elif p.centre == "P":
                m.vital_status = None
                notes.append("{} is a pregnancy".format(m.id))
            else:
                m.vital_status = "DECEASED" if p.deceased else "ALIVE"
            if p.centre == "dot":
                notes.append("{} is a carrier".format(m.id))
            elif p.centre == "line":
                notes.append("{} is a presymptomatic carrier".format(m.id))
            if p.consultand:
                notes.append("{} is a consultand".format(m.id))
            elif re.fullmatch(r"\d+|n", p.centre or "", flags=re.I):
                warnings.append("{} stands for {} people in the drawing but is exported as one person".format(
                    m.id, p.centre))
            names = s.condition_names(p)
            for name in names:
                hit = mapping.get(name.lower())
                if not hit:
                    base, curie = split_key_label(name)
                    hit = mapping.get(base.lower())
                    if not hit and curie:
                        hit = {"id": curie, "label": base}
                if hit:
                    tk = hit.get("kind") or (PHENOTYPE if ontology.prefix_of(hit["id"]) == "HP" else DISEASE)
                    m.terms.append(Term(label=hit.get("label") or name, id=ontology.tidy_curie(hit["id"]), kind=tk))
                    if hit.get("version"):
                        k.versions.setdefault(ontology.prefix_of(ontology.tidy_curie(hit["id"])), hit["version"])
                else:
                    m.terms.append(Term(label=split_key_label(name)[0], kind=kind))
            unnamed = s.unnamed_colours(p)
            if unnamed:
                warnings.append("{} is shaded in {}, which the colour key does not name".format(
                    m.id, ", ".join(unnamed)))
            m.affected = True if p.filled else False
            k.members.append(m)
        # parents and children
        for pr in s.partnerships.values():
            if pr.a not in in_comp and pr.b not in in_comp:
                continue
            links = kids_of.get(pr.id, [])
            real = [cl for cl in links if not s.persons[cl.child].is_marker]
            markers = [cl for cl in links if s.persons[cl.child].is_marker]
            a, b = s.persons[pr.a], s.persons[pr.b]
            # a bar joined to someone by a partner line is not a couple: the bar is not a person, and has no id
            couple = not (a.is_marker or b.is_marker)
            for cl in markers if couple else []:
                notes.append("{} and {}: {}".format(idmap[pr.a], idmap[pr.b], dict(
                    [("no-offspring", "no children"), ("infertile", "infertility")])[s.persons[cl.child].shape]))
            for cl in real:
                for parent in (a, b):
                    if parent.is_marker or parent.is_loss:
                        continue
                    rel = _parent_relation(parent, cl.dashed, warnings, idmap)
                    k.relations.append(Relation(idmap[parent.id], rel, idmap[cl.child]))
            if not couple:
                continue
            if pr.consanguineous:
                code = kin.SEPARATED_CONSANGUINEOUS_PARTNER if pr.separated else kin.CONSANGUINEOUS_PARTNER
            elif pr.separated:
                code = kin.SEPARATED_PARTNER
            elif not real:
                code = kin.PARTNER
            else:
                code = None          # implied by their shared children
            if code:
                k.relations.append(Relation(idmap[pr.a], code, idmap[pr.b]))
        # twins: all relative to the same (leftmost) twin, as the reduced form asks
        root: Dict[str, str] = {}

        def find(x):
            while root.get(x, x) != x:
                x = root[x]
            return x
        comp_twins = [t for t in s.twin_links if t.a in in_comp and t.b in in_comp]
        for t in comp_twins:
            root.setdefault(t.a, t.a)
            root.setdefault(t.b, t.b)
            root[find(t.a)] = find(t.b)
        sets: Dict[str, List[str]] = defaultdict(list)
        for x in root:
            sets[find(x)].append(x)
        for group in sets.values():
            group.sort(key=lambda pid: s.persons[pid].x)
            first = group[0]
            # each twin's zygosity relative to the first: a twin line between them if there is one, else
            # worked out along the shortest chain of twin lines that joins them (see _twin_chain)
            zyg = {first: "identical"}
            queue = [first]
            while queue:
                cur = queue.pop(0)
                for t in comp_twins:
                    if cur in (t.a, t.b):
                        nxt = t.b if t.a == cur else t.a
                        if nxt not in zyg:
                            zyg[nxt] = _twin_chain(zyg[cur], t.zygosity)
                            queue.append(nxt)
            for other in group[1:]:
                k.relations.append(Relation(idmap[first], _TWIN_KIN[zyg.get(other, "unknown")], idmap[other]))
        index = [m.id for m in k.members if m.index]
        conds = sorted({t.label for m in k.members for t in m.terms})
        parts = ["Pedigree drawn in Pedigree Studio: {} people{}.".format(
            len(k.members), "; proband {}".format(", ".join(index)) if index else "")]
        if conds:
            parts.append("Conditions: {}.".format(", ".join(conds)))
        if notes:
            # each note starts with a person's id, which must stay as it is ("i2", not "I2")
            parts.append(" ".join(n + "." for n in notes))
        k.narrative = " ".join(parts)
        notes_all.extend(notes)
        kindreds.append(k)
    return kindreds, conditions, warnings, notes_all


def convert(session_data: dict, output_prefix: str = "pedigree", *, terms: Optional[dict] = None,
            use_phenotypic_features: bool = False, ids: str = "numbers", created_by: str = CREATED_BY,
            created: Optional[str] = None, family_id: str = "FAM", outputs=("pedigree", "family"),
            include_names: Optional[bool] = None) -> ConversionResult:
    """Convert a Pedigree Studio session to GA4GH files.

    Writes ``<prefix>_ga4gh-pedigree.json`` (GA4GH Pedigree) and
    ``<prefix>_phenopackets-family.json`` (Phenopackets Family) for each family
    in the drawing (``_2``, ``_3`` ... are added when there are several).

    ``include_names`` is kept for compatibility with version 0.3: ``True`` is
    the same as ``ids="drawing"``. Names are never written into the files.
    """
    if include_names:
        ids = "drawing"
    kind = PHENOTYPE if use_phenotypic_features else DISEASE
    kindreds, conditions, warnings, notes = session_to_kindreds(
        session_data, terms=terms, kind=kind, ids=ids, family_id=family_id)
    files: List[Tuple[str, str]] = []
    for i, k in enumerate(kindreds):
        suffix = "_{}".format(i + 1) if len(kindreds) > 1 else ""
        if "pedigree" in outputs:
            doc, w = to_ga4gh_pedigree(k, created_by=created_by, created=created)
            warnings.extend(w)
            files.append(("{}{}_ga4gh-pedigree.json".format(output_prefix, suffix), dumps(doc)))
        if "family" in outputs:
            doc, w = to_phenopackets_family(k, created_by=created_by, created=created)
            warnings.extend(w)
            files.append(("{}{}_phenopackets-family.json".format(output_prefix, suffix), dumps(doc)))
    matched = load_terms(terms or {})
    unmatched = [c for c in conditions if c.lower() not in matched
                 and split_key_label(c)[0].lower() not in matched and split_key_label(c)[1] is None]
    warnings = list(dict.fromkeys(warnings))
    people = sum(len(k.members) for k in kindreds)
    summary = "{} famil{} ({} people). Conditions: {}.".format(
        len(kindreds), "y" if len(kindreds) == 1 else "ies", people,
        ", ".join(conditions) if conditions else "none")
    if unmatched:
        summary += " Not yet matched to an ontology term, so left out: {}.".format(", ".join(unmatched))
    return ConversionResult(files=files, kindreds=kindreds, conditions=conditions, unmatched=unmatched,
                            warnings=warnings, notes=notes, summary=summary)


def convert_file(input_path: str, output_prefix: Optional[str] = None, output_dir: Optional[str] = None,
                 **options) -> ConversionResult:
    """Read a session file and write the GA4GH files next to it (or into ``output_dir``)."""
    with open(input_path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if output_prefix is None:
        base = os.path.basename(input_path)
        for ext in (".studio.json", ".json"):
            if base.endswith(ext):
                base = base[: -len(ext)]
                break
        output_prefix = base
    if output_dir is None:
        output_dir = os.path.dirname(input_path) or "."
    result = convert(data, output_prefix, **options)
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for name, text in result.files:
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append((path, text))
    result.files = written
    return result
