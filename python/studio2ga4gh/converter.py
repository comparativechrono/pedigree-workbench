"""Convert a Pedigree Studio drawing to a GA4GH Pedigree and a Phenopackets Family.

The drawing is read into a :class:`pedigree_ga4gh.Kindred` (one per separate
family on the canvas) and written out by pedigree-ga4gh, the workbench's one
implementation of GA4GH output. This module only decides what each symbol and
line in the drawing means:

========================================  ==============================================
In Pedigree Studio                        In the GA4GH files
========================================  ==============================================
square, circle, diamond                   sex MALE, FEMALE, UNKNOWN_SEX
slash (deceased)                          vitalStatus DECEASED (otherwise ALIVE)
arrow (proband)                           indexPatients; the Family's proband
fill, halves, quarters, shading           a disease or phenotype for each condition named
                                          in the colour key, once it has an ontology term
child line from a couple                  isBiologicalMotherOf / isBiologicalFatherOf
                                          (isBiologicalParentOf if the parent's sex is unknown)
dashed child line                         isAdoptiveParentOf
D in a parent's symbol                    isSpermDonorOf / isOvumDonorOf
S in a parent's symbol                    isGestationalCarrierOf (not a biological parent)
identical / non-identical twins           isMonozygotic- / isPolyzygoticMultipleBirthSiblingOf
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
    its name and ontology id. Without an id in brackets the id is ``None``."""
    m = _KEY_CURIE.match(text or "")
    if m and ontology.is_curie(ontology.tidy_curie(m.group(2))):
        return m.group(1).strip() or m.group(2), ontology.tidy_curie(m.group(2))
    return (text or "").strip(), None


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


def _parent_relation(parent: StudioPerson, dashed: bool, warnings: List[str], ids: Dict[str, str]) -> str:
    if dashed:
        return kin.ADOPTIVE_PARENT
    if parent.centre == "S":
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
    if ids == "drawing":
        labels = s.drawing_labels()
    elif ids == "studio":
        labels = {pid: pid for pid in s.persons}
    else:
        labels = s.numbers()
    # ids must be unique; fall back to pedigree numbers for any clash
    counts: Dict[str, int] = defaultdict(int)
    for pid, p in s.persons.items():
        if not p.is_marker:
            counts[labels[pid]] += 1
    nums = s.numbers()
    idmap = {}
    for pid in s.persons:
        lab = re.sub(r"\s+", "_", (labels.get(pid) or "").strip()) or nums[pid]
        if counts[labels.get(pid)] > 1:
            lab = nums[pid]
        idmap[pid] = lab
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
            for cl in markers:
                notes.append("{} and {}: {}".format(idmap[pr.a], idmap[pr.b], dict(
                    [("no-offspring", "no children"), ("infertile", "infertility")])[s.persons[cl.child].shape]))
            for cl in real:
                for parent in (a, b):
                    if parent.is_marker or parent.is_loss:
                        continue
                    rel = _parent_relation(parent, cl.dashed, warnings, idmap)
                    k.relations.append(Relation(idmap[parent.id], rel, idmap[cl.child]))
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
            links = [t for t in comp_twins if t.a in group]
            for other in group[1:]:
                direct = [t for t in links if {t.a, t.b} == {first, other}]
                # twins joined only through a third count as identical only if every link is
                identical = direct[0].identical if direct else all(t.identical for t in links)
                code = kin.MONOZYGOTIC_MULTIPLE_BIRTH_SIBLING if identical else kin.POLYZYGOTIC_MULTIPLE_BIRTH_SIBLING
                k.relations.append(Relation(idmap[first], code, idmap[other]))
        index = [m.id for m in k.members if m.index]
        conds = sorted({t.label for m in k.members for t in m.terms})
        parts = ["Pedigree drawn in Pedigree Studio: {} people{}.".format(
            len(k.members), "; proband {}".format(", ".join(index)) if index else "")]
        if conds:
            parts.append("Conditions: {}.".format(", ".join(conds)))
        if notes:
            parts.append(" ".join(n[0].upper() + n[1:] + "." for n in notes))
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
    written = []
    for name, text in result.files:
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append((path, text))
    result.files = written
    return result
