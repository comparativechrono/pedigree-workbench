"""Convert GA4GH files to a Pedigree Studio drawing.

Reads a GA4GH Pedigree (Phenopackets form) or a Phenopackets Family through
pedigree-ga4gh, the workbench's single GA4GH implementation, and draws it as a
Pedigree Studio session. The layout here is a simple one; the workbench runs
Pedigree Studio's Tidy on the drawing as soon as it opens.

How relationships are drawn:

* biological, sperm-donor and ovum-donor parents: a couple with a solid line
  to the child (donors get a D in their symbol);
* a gestational carrier with no genetic mother recorded: drawn in the mother's
  place with an S in her symbol;
* adoptive parents: a dashed line, and the child's symbol in brackets;
* twins: identical (KIN:010) or non-identical (KIN:009, KIN:011);
* partners, consanguineous and separated partners: the matching partnership line.

A child with only one parent recorded gets an "unknown parent" partner so the
Studio can draw the line of descent. Relations the Studio cannot draw directly
(cousins, grandparents and so on, without the people in between) are listed in
the warnings.

Files written by studio2ga4gh 0.3 or abusua2ga4gh 0.2 must be upgraded first
(``pedigree-ga4gh upgrade``), so that only one form of GA4GH is ever read.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pedigree_ga4gh import Kindred, from_document, identify_legacy, kin
from pedigree_ga4gh.io import loads

# Pedigree Studio layout constants
SHAPE_SIZE = 52
SHAPE_HALF = 26
PARTNER_GAP = SHAPE_SIZE * 2
CHILD_HEIGHT = SHAPE_SIZE * 2.5
CHILD_SPACING = 104
MIN_BLOCK_GAP = 60
STROKE_COLOR = "#1a2332"

# Colours for conditions, in order
DISEASE_PALETTE = ["#c0392b", "#2980b9", "#27ae60", "#e67e22", "#8e44ad", "#f1c40f", "#16a085", "#d35400",
                   "#7f8c8d"]

SEX_TO_CODE = {"MALE": 1, "FEMALE": 2}
CODE_TO_SHAPE = {1: "male", 2: "female", 0: "unknown"}

_ADOPTIVE = {kin.ADOPTIVE_PARENT, kin.FOSTER_PARENT}
_PARTNER = {kin.PARTNER: "normal", kin.CONSANGUINEOUS_PARTNER: "consanguineous",
            kin.SEPARATED_PARTNER: "separated", kin.SEPARATED_CONSANGUINEOUS_PARTNER: "consanguineous-separated"}
_TWINS = {kin.MONOZYGOTIC_MULTIPLE_BIRTH_SIBLING: "identical",
          kin.POLYZYGOTIC_MULTIPLE_BIRTH_SIBLING: "nonidentical",
          kin.MULTIPLE_BIRTH_SIBLING: "nonidentical"}
_DRAWN = ({kin.BIOLOGICAL_MOTHER, kin.BIOLOGICAL_FATHER, kin.BIOLOGICAL_PARENT, kin.SPERM_DONOR,
           kin.OVUM_DONOR, kin.SURROGATE_OVUM_DONOR, kin.GESTATIONAL_CARRIER} | _ADOPTIVE | set(_PARTNER)
          | set(_TWINS))


@dataclass
class Individual:
    id: str
    sex: int                         # 1 male, 2 female, 0 unknown
    deceased: bool = False
    proband: bool = False
    diseases: List[str] = field(default_factory=list)   # condition labels
    father_id: Optional[str] = None
    mother_id: Optional[str] = None
    adoptive: Tuple[Optional[str], Optional[str]] = (None, None)   # adoptive father, mother
    is_adopted: bool = False
    centre: str = ""                 # "D", "S", "dot", "line", "P"
    loss: bool = False
    placeholder: bool = False
    generation: int = -1
    x: float = 0.0
    y: float = 0.0
    partners: List[str] = field(default_factory=list)
    mating_units: List[str] = field(default_factory=list)


@dataclass
class MatingUnit:
    key: str
    father_id: str
    mother_id: str
    child_ids: List[str] = field(default_factory=list)


# -- Layout (from ped2studio and ga4gh2studio 0.3) ----------------------------------

def build_mating_units(inds: dict[str, Individual]) -> dict[str, MatingUnit]:
    units: dict[str, MatingUnit] = {}
    for ind in inds.values():
        if ind.father_id and ind.mother_id:
            key = f"{ind.father_id}+{ind.mother_id}"
            if key not in units:
                units[key] = MatingUnit(key=key, father_id=ind.father_id, mother_id=ind.mother_id)
            units[key].child_ids.append(ind.id)
            if ind.father_id in inds:
                if ind.mother_id not in inds[ind.father_id].partners:
                    inds[ind.father_id].partners.append(ind.mother_id)
                if key not in inds[ind.father_id].mating_units:
                    inds[ind.father_id].mating_units.append(key)
            if ind.mother_id in inds:
                if ind.father_id not in inds[ind.mother_id].partners:
                    inds[ind.mother_id].partners.append(ind.father_id)
                if key not in inds[ind.mother_id].mating_units:
                    inds[ind.mother_id].mating_units.append(key)
    return units


def assign_generations(inds: dict[str, Individual]) -> int:
    for ind in inds.values():
        has_f = ind.father_id and ind.father_id in inds
        has_m = ind.mother_id and ind.mother_id in inds
        if not has_f and not has_m:
            ind.generation = 0

    changed = True
    while changed:
        changed = False
        for ind in inds.values():
            if ind.generation >= 0:
                continue
            fg = inds[ind.father_id].generation if (ind.father_id and ind.father_id in inds) else -1
            mg = inds[ind.mother_id].generation if (ind.mother_id and ind.mother_id in inds) else -1
            if fg >= 0 and mg >= 0:
                ind.generation = max(fg, mg) + 1; changed = True
            elif fg >= 0 and not (ind.mother_id and ind.mother_id in inds):
                ind.generation = fg + 1; changed = True
            elif mg >= 0 and not (ind.father_id and ind.father_id in inds):
                ind.generation = mg + 1; changed = True

    for ind in inds.values():
        if ind.generation >= 0 and ind.partners:
            has_parent = (ind.father_id and ind.father_id in inds) or (ind.mother_id and ind.mother_id in inds)
            if has_parent:
                continue
            for pid in ind.partners:
                if pid in inds and inds[pid].generation > ind.generation:
                    ind.generation = inds[pid].generation; break

    for ind in inds.values():
        if ind.generation < 0:
            ind.generation = 0

    return max(ind.generation for ind in inds.values()) + 1 if inds else 0


def get_ancestors(inds, ind_id):
    ancestors = set()
    stack = [ind_id]
    visited = set()
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        ind = inds.get(current)
        if not ind:
            continue
        for p in (ind.father_id, ind.mother_id):
            if p and p in inds and p not in ancestors:
                ancestors.add(p)
                stack.append(p)
    return ancestors


def is_consanguineous(inds, id1, id2):
    return bool(get_ancestors(inds, id1) & get_ancestors(inds, id2))


def get_mating_unit_for_child(units, child_id):
    for mk, mu in units.items():
        if child_id in mu.child_ids:
            return mk
    return None




def compute_layout(inds, units, num_gens):
    gen_members = defaultdict(list)
    for ind in inds.values():
        gen_members[ind.generation].append(ind.id)

    placed = set()

    # Gen 0
    y0 = 100.0
    cursor = 200.0
    gen0_couples = []
    gen0_coupled = set()
    for mu in units.values():
        f, m = mu.father_id, mu.mother_id
        if f in inds and m in inds:
            if inds[f].generation == 0 and inds[m].generation == 0:
                pair = (min(f, m), max(f, m))
                if pair[0] not in gen0_coupled:
                    gen0_couples.append((f, m))
                    gen0_coupled.add(f); gen0_coupled.add(m)

    for f, m in gen0_couples:
        inds[f].x, inds[f].y = cursor, y0; cursor += PARTNER_GAP
        inds[m].x, inds[m].y = cursor, y0; cursor += SHAPE_SIZE + MIN_BLOCK_GAP
        placed.add(f); placed.add(m)

    for iid in gen_members.get(0, []):
        if iid not in placed:
            inds[iid].x, inds[iid].y = cursor, y0
            cursor += SHAPE_SIZE + MIN_BLOCK_GAP; placed.add(iid)

    # Gen 1+
    for gen in range(1, num_gens):
        y = 100 + gen * CHILD_HEIGHT
        mu_children = {}
        orphans = []
        for iid in gen_members.get(gen, []):
            found = get_mating_unit_for_child(units, iid)
            if found:
                mu_children.setdefault(found, []).append(iid)
            else:
                orphans.append(iid)

        consang_pairs = set()
        all_children = set()
        for clist in mu_children.values():
            all_children.update(clist)
        for iid in all_children:
            for pid in inds[iid].partners:
                if pid in all_children:
                    consang_pairs.add((min(iid, pid), max(iid, pid)))

        def mu_sort_key(mk):
            mu = units[mk]
            xs = []
            if mu.father_id in inds and inds[mu.father_id].generation < gen: xs.append(inds[mu.father_id].x)
            if mu.mother_id in inds and inds[mu.mother_id].generation < gen: xs.append(inds[mu.mother_id].x)
            return (sum(xs) / len(xs)) if xs else 0

        mu_order = sorted(mu_children.keys(), key=mu_sort_key)
        used_ranges = []

        for mk in mu_order:
            mu = units[mk]
            children = mu_children[mk]
            if not children:
                continue
            fx = (inds[mu.father_id].x + SHAPE_HALF) if mu.father_id in inds else 0
            mx = (inds[mu.mother_id].x + SHAPE_HALF) if mu.mother_id in inds else 0
            parent_mid = (fx + mx) / 2

            child_infos = []
            for cid in children:
                partner_id = None
                partner_is_consang = False
                for pid in inds[cid].partners:
                    if pid in inds and inds[pid].generation == gen and pid not in children:
                        partner_id = pid
                        partner_is_consang = (min(cid, pid), max(cid, pid)) in consang_pairs
                        break
                child_infos.append((cid, partner_id is not None, partner_id, partner_is_consang))

            partnered = [e for e in child_infos if e[1]]
            unpartnered = [e for e in child_infos if not e[1]]
            left_p, right_p = [], []
            for entry in partnered:
                cid, p, pid, pc = entry
                if pc and pid and pid in placed:
                    (left_p if inds[pid].x < parent_mid else right_p).append(entry)
                elif pc:
                    right_p.append(entry)
                else:
                    right_p.append(entry)
            marry_ins = [e for e in right_p if not e[3]]
            consang_right = [e for e in right_p if e[3]]
            if len(marry_ins) > 1:
                half = len(marry_ins) // 2
                left_p = left_p + marry_ins[:half]; right_p = consang_right + marry_ins[half:]
            else:
                right_p = consang_right + marry_ins

            ordered = left_p + unpartnered + right_p
            n_slots = len(ordered)
            total_width = (n_slots - 1) * CHILD_SPACING if n_slots > 1 else 0
            start_x = parent_mid - total_width / 2 - SHAPE_HALF
            positions = []
            for i, (cid, has_partner, partner_id, partner_is_consang) in enumerate(ordered):
                cx = start_x + i * CHILD_SPACING
                if has_partner and partner_id:
                    if partner_is_consang:
                        positions.append((cid, cx))
                    else:
                        child_centre = cx + SHAPE_HALF
                        if child_centre <= parent_mid:
                            positions.append((partner_id, cx - PARTNER_GAP)); positions.append((cid, cx))
                        else:
                            positions.append((cid, cx)); positions.append((partner_id, cx + PARTNER_GAP))
                else:
                    positions.append((cid, cx))

            if positions:
                min_x = min(px for _, px in positions); max_x = max(px for _, px in positions) + SHAPE_SIZE
                for rng_min, rng_max in used_ranges:
                    if min_x < rng_max + MIN_BLOCK_GAP and max_x > rng_min - MIN_BLOCK_GAP:
                        shift = rng_max + MIN_BLOCK_GAP - min_x
                        positions = [(pid, px + shift) for pid, px in positions]
                        min_x += shift; max_x += shift
                used_ranges.append((min_x, max_x))
                for pid, px in positions:
                    if pid and pid in inds:
                        inds[pid].x = px; inds[pid].y = y; placed.add(pid)

        orphan_cursor = (used_ranges[-1][1] + MIN_BLOCK_GAP) if used_ranges else 100.0
        for iid in orphans:
            if iid not in placed:
                inds[iid].x = orphan_cursor; inds[iid].y = y
                orphan_cursor += SHAPE_SIZE + MIN_BLOCK_GAP; placed.add(iid)

    if inds:
        min_x_global = min(ind.x for ind in inds.values())
        if min_x_global < 100:
            shift = 100 - min_x_global
            for ind in inds.values():
                ind.x += shift




# -- GA4GH -> drawing ----------------------------------------------------------------

_NOTE_PATTERNS = [
    (re.compile(r"(\S+) is a pregnancy loss"), "loss"),
    (re.compile(r"(\S+) is a presymptomatic carrier"), "line"),
    (re.compile(r"(\S+) is a carrier"), "dot"),
    (re.compile(r"(\S+) is a pregnancy(?! loss)"), "P"),
]
_COUPLE_NOTE = re.compile(r"(\S+) and (\S+): (no children|infertility)")


def _notes(narrative: str):
    """Marks that studio2ga4gh records in the narrative, so that a round trip keeps them."""
    marks, couples = {}, []
    text = narrative or ""
    for pattern, mark in _NOTE_PATTERNS:
        for m in pattern.finditer(text):
            marks.setdefault(m.group(1), mark)
    for m in _COUPLE_NOTE.finditer(text):
        couples.append((m.group(1), m.group(2), m.group(3)))
    return marks, couples


def key_label(term) -> str:
    """The colour-key text for a condition: its label, then its ontology id in brackets,
    which studio2ga4gh reads back so that a round trip keeps the term."""
    if term.matched:
        return "{} [{}]".format(term.label or term.id, term.id)
    return term.label or term.id


def kindred_to_individuals(k: Kindred, warnings: List[str]):
    """The people to draw, with the parents to draw each one from."""
    inds: Dict[str, Individual] = {}
    marks, couple_notes = _notes(k.narrative or "")
    for m in k.members:
        ind = Individual(id=m.id, sex=SEX_TO_CODE.get(m.sex, 0),
                         deceased=(m.vital_status == "DECEASED"), proband=m.index,
                         diseases=[key_label(t) for t in m.terms if not t.excluded])
        mark = marks.get(m.id)
        if mark == "loss":
            ind.loss = True
            ind.deceased = False
        elif mark:
            ind.centre = mark
        if m.affected and not ind.diseases:
            ind.diseases = ["Affected"]
        inds[m.id] = ind
    skipped = defaultdict(int)
    for r in k.relations:
        if r.kin not in _DRAWN:
            skipped[kin.TERMS[r.kin].label if r.kin in kin.TERMS else r.kin] += 1
    for label, n in skipped.items():
        warnings.append("{} '{}' relationship{} cannot be drawn directly and {} left out".format(
            n, label, "" if n == 1 else "s", "was" if n == 1 else "were"))
    for m in k.members:
        child = inds[m.id]
        father, mother, notes = k.genetic_parents(m.id)
        for rel in k.relations_to(m.id):
            parent = inds.get(rel.individual)
            if parent is None:
                continue
            if rel.kin in (kin.SPERM_DONOR, kin.OVUM_DONOR, kin.SURROGATE_OVUM_DONOR):
                parent.centre = parent.centre or ("S" if rel.kin == kin.SURROGATE_OVUM_DONOR else "D")
            if rel.kin == kin.GESTATIONAL_CARRIER:
                if not mother:
                    mother = rel.individual
                    parent.centre = "S"
                else:
                    warnings.append("{} carried {} for {}; a drawing has room for one mother, so the "
                                    "gestational carrier is not linked".format(rel.individual, m.id, mother))
        child.father_id, child.mother_id = father, mother
        adoptive = [r.individual for r in k.relations_to(m.id) if r.kin in _ADOPTIVE and r.individual in inds]
        if adoptive:
            child.is_adopted = True
            af = next((a for a in adoptive if inds[a].sex == 1), None)
            am = next((a for a in adoptive if a != af and inds[a].sex != 1), None)
            if af is None and len(adoptive) > 1:
                af = next(a for a in adoptive if a != am)
            child.adoptive = (af, am)
    return inds, couple_notes


def _placeholders(inds: Dict[str, Individual], warnings: List[str]) -> None:
    """Give children with one recorded parent an unknown partner for that parent."""
    extra: Dict[str, Individual] = {}
    for ind in list(inds.values()):
        for attr in ("bio", "adoptive"):
            if attr == "bio":
                f, m = ind.father_id, ind.mother_id
            else:
                f, m = ind.adoptive
            if bool(f) == bool(m):
                continue
            known = f or m
            key = "{}-partner".format(known) if attr == "bio" else "{}-adoptive-partner".format(known)
            if key not in extra:
                extra[key] = Individual(id=key, sex=0, placeholder=True)
                warnings.append("added an unknown partner for {} so the Studio can draw the line to {}".format(
                    known, ind.id))
            if attr == "bio":
                if f:
                    ind.mother_id = key
                else:
                    ind.father_id = key
            else:
                ind.adoptive = (f, key) if f else (key, m)
    inds.update(extra)


def build_session(inds: Dict[str, Individual], couple_notes, partner_rels, twins, conditions) -> dict:
    persons, partnerships, child_links, twin_links = [], [], [], []
    colours = {c: DISEASE_PALETTE[i % len(DISEASE_PALETTE)] for i, c in enumerate(conditions)}
    ps_id = {iid: "person-{}".format(i + 1) for i, iid in enumerate(inds)}
    for iid, ind in inds.items():
        shape = CODE_TO_SHAPE.get(ind.sex, "unknown")
        if ind.loss:
            shape = "miscarriage"
        elif ind.is_adopted:
            shape = "adopted-" + shape
        cols = [colours[d] for d in ind.diseases if d in colours]
        fill = {"fillMode": "none", "fillColor": STROKE_COLOR, "quarters": [None] * 4, "halves": [None, None]}
        if len(cols) == 1:
            fill.update(fillMode="solid", fillColor=cols[0])
        elif len(cols) == 2:
            fill.update(fillMode="half", halves=cols[:2])
        elif len(cols) > 2:
            fill.update(fillMode="quartered", quarters=(cols + [None] * 4)[:4])
        text = "" if (ind.placeholder or re.fullmatch(r"[IVXL]+-\d+", iid)) else iid
        if ind.placeholder:
            text = "unknown parent"
        persons.append(dict({
            "id": ps_id[iid], "shape": shape, "x": round(ind.x, 1), "y": round(ind.y, 1),
            "text": text, "deceased": ind.deceased, "proband": ind.proband,
            "shadingPattern": "stripes", "shadingCoverage": "full",
            "centerText": ind.centre if ind.centre in ("D", "S", "dot", "line", "P") else "",
            "miscarriageSex": {1: "male", 2: "female"}.get(ind.sex, "unknown") if ind.loss else "unknown",
            "noSnap": False, "siblingFixed": False, "customLabel": "Lbl"}, **fill))
    n = 0
    pship: Dict[Tuple[str, str], str] = {}

    def couple(a, b, typ="normal"):
        nonlocal n
        key = tuple(sorted((a, b)))
        if key in pship:
            return pship[key]
        n += 1
        pid = "pship-{}".format(n)
        pship[key] = pid
        partnerships.append({"id": pid, "fromId": ps_id[a], "toId": ps_id[b], "type": typ})
        return pid

    for (a, b), typ in partner_rels.items():
        if a in ps_id and b in ps_id:
            couple(a, b, typ)
    for iid, ind in inds.items():
        for (f, m), dashed in (((ind.father_id, ind.mother_id), False), (ind.adoptive, True)):
            if f and m and f in ps_id and m in ps_id:
                typ = "consanguineous" if (not dashed and is_consanguineous(inds, f, m)) else "normal"
                pid = couple(f, m, partner_rels.get(tuple(sorted((f, m))), typ))
                n += 1
                child_links.append({"id": "child-{}".format(n), "partnershipId": pid, "childId": ps_id[iid],
                                    "branchYOffset": 0, "dashed": dashed})
    for a, b, what in couple_notes:
        if a in ps_id and b in ps_id:
            pid = couple(a, b)
            n += 1
            mid = "person-{}".format(len(persons) + 1)
            ax, ay = inds[a].x, inds[a].y
            persons.append({"id": mid, "shape": "no-offspring" if what == "no children" else "infertile",
                            "x": round(ax + SHAPE_SIZE, 1), "y": round(ay + CHILD_HEIGHT, 1), "text": "",
                            "deceased": False, "proband": False, "fillMode": "none", "fillColor": STROKE_COLOR,
                            "quarters": [None] * 4, "halves": [None, None], "shadingPattern": "stripes",
                            "shadingCoverage": "full", "centerText": "", "miscarriageSex": "unknown",
                            "noSnap": False, "siblingFixed": False, "customLabel": "Lbl"})
            child_links.append({"id": "child-{}".format(n), "partnershipId": pid, "childId": mid,
                                "branchYOffset": 0, "dashed": False})
    for a, b, typ in twins:
        if a in ps_id and b in ps_id:
            pid = ""
            for cl in child_links:
                if cl["childId"] == ps_id[a] and not cl["dashed"]:
                    pid = cl["partnershipId"]
            n += 1
            twin_links.append({"id": "twin-{}".format(n), "child1Id": ps_id[a], "child2Id": ps_id[b],
                               "type": typ, "partnershipId": pid})
    legend = {colours[c]: c for c in conditions if any(c in ind.diseases for ind in inds.values())}
    return {
        "version": 5, "personIdCounter": len(persons), "labelIdCounter": 0, "lineIdCounter": n,
        "persons": persons, "labels": [], "partnerships": partnerships, "childLinks": child_links,
        "twinLinks": twin_links, "legendLabels": legend, "legendVisible": bool(legend),
        "legendX": 50, "legendY": 80, "zoom": 1, "panX": 0, "panY": 0, "numberingMode": "numbers",
        "partnerGapMultiplier": 2, "childHeightMultiplier": 2.5, "drawStrokes": [],
    }


@dataclass
class ConversionResult:
    session: dict
    summary: str
    warnings: List[str] = field(default_factory=list)


class LegacyFileError(ValueError):
    """The file is in one of the older, non-standard forms and must be upgraded first."""


def kindred_to_session(k: Kindred) -> Tuple[dict, List[str]]:
    warnings: List[str] = []
    inds, couple_notes = kindred_to_individuals(k, warnings)
    _placeholders(inds, warnings)
    partner_rels: Dict[Tuple[str, str], str] = {}
    twins = []
    for r in k.relations:
        if r.kin in _PARTNER:
            partner_rels[tuple(sorted((r.individual, r.relative)))] = _PARTNER[r.kin]
        elif r.kin in _TWINS:
            twins.append((r.individual, r.relative, _TWINS[r.kin]))
    # layout: draw adopted children under the adoptive couple when no biological parents are known
    layout_inds = {iid: ind for iid, ind in inds.items()}
    saved = {}
    for iid, ind in inds.items():
        if not (ind.father_id and ind.mother_id) and all(ind.adoptive):
            saved[iid] = (ind.father_id, ind.mother_id)
            ind.father_id, ind.mother_id = ind.adoptive
    units = build_mating_units(layout_inds)
    num_gens = assign_generations(layout_inds)
    compute_layout(layout_inds, units, num_gens)
    for iid, (f, m) in saved.items():
        inds[iid].father_id, inds[iid].mother_id = f, m
    conditions = []
    for ind in inds.values():
        for d in ind.diseases:
            if d not in conditions:
                conditions.append(d)
    session = build_session(inds, couple_notes, partner_rels, twins, conditions)
    return session, warnings


def convert(ga4gh_data: Optional[dict] = None, phenopackets_data: Optional[dict] = None) -> ConversionResult:
    """Draw a GA4GH Pedigree or a Phenopackets Family as a Pedigree Studio session.

    Give either document. If both are given (as version 0.3 needed), the GA4GH
    Pedigree is used: it already holds everything the Family does.
    """
    doc = ga4gh_data or phenopackets_data
    if not doc:
        return ConversionResult(session={}, summary="Nothing to convert.")
    for d in (ga4gh_data, phenopackets_data):
        if d is not None:
            old = identify_legacy(d)
            if old is not None and not old.upgradable:
                raise LegacyFileError(old.description)
            if old is not None:
                raise LegacyFileError(old.description + " Upgrade it first: pedigree-ga4gh upgrade FILE "
                                      "(in the Pedigree workbench: Tools > Upgrade a file from an older tool).")
    k, warnings = from_document(doc)
    if ga4gh_data and phenopackets_data:
        warnings.append("both files were given; the GA4GH Pedigree was used, as it holds everything the "
                        "Family does")
    session, w = kindred_to_session(k)
    warnings.extend(w)
    n_people = sum(1 for p in session["persons"] if p["shape"] not in ("no-offspring", "infertile"))
    summary = "{} people, {} couples, {} twin pairs. Conditions: {}.".format(
        n_people, len(session["partnerships"]), len(session["twinLinks"]),
        ", ".join(session["legendLabels"].values()) or "none")
    return ConversionResult(session=session, summary=summary, warnings=warnings)


def convert_file(ga4gh_path: Optional[str] = None, phenopackets_path: Optional[str] = None,
                 output_path: str = "pedigree_session.json") -> ConversionResult:
    def read(path):
        with open(path, encoding="utf-8-sig") as fh:
            return loads(fh.read())
    result = convert(read(ga4gh_path) if ga4gh_path else None,
                     read(phenopackets_path) if phenopackets_path else None)
    if result.session:
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(result.session, fh, indent=2)
            fh.write("\n")
    return result
