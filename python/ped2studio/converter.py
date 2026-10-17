"""
ped2studio - Convert PED/MPED pedigree files to Pedigree Studio session JSON.

Core converter module: parses PED and MPED formats, builds the family graph,
computes a layered layout, and emits a Pedigree Studio v4 session.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# ── Pedigree Studio default constants ──────────────────────────────────────
SHAPE_SIZE = 52
SHAPE_HALF = 26
PARTNER_GAP = SHAPE_SIZE * 2       # 104 px between partner left-edges
CHILD_HEIGHT = SHAPE_SIZE * 2.5    # 130 px between generation rows
CHILD_SPACING = 104                # horizontal spacing between siblings
MIN_BLOCK_GAP = 60                 # minimum gap between unrelated blocks in same generation
AFFECTED_COLOR = "#1a2332"         # default fill colour for affected individuals
STROKE_COLOR = "#1a2332"

# Colour palette for multi-phenotype MPED files (matches Pedigree Studio FILL_COLORS)
PHENOTYPE_PALETTE = [
    '#c0392b', '#2980b9', '#27ae60', '#e67e22',
    '#8e44ad', '#f1c40f', '#16a085', '#d35400', '#7f8c8d',
]

SEX_MAP = {1: "male", 2: "female"}
DEFAULT_SEX = "unknown"


# ── Data models ────────────────────────────────────────────────────────────

@dataclass
class Individual:
    """One row of a PED or MPED file."""
    family_id: str
    ind_id: str
    father_id: Optional[str]     # None means unknown/missing
    mother_id: Optional[str]
    sex: int                      # 1=male, 2=female, other=unknown
    phenotype: int                # primary phenotype: 2=affected, 1=unaffected, 0=unknown
    phenotypes: dict[str, int] = field(default_factory=dict)
    # Named phenotypes: {column_name: code} where code is 0-3 (0=unknown, 1=unaffected, 2=affected, 3=carrier)
    generation: int = -1
    x: float = 0.0
    y: float = 0.0
    partners: list[str] = field(default_factory=list)
    mating_units: list[str] = field(default_factory=list)


@dataclass
class MatingUnit:
    """A couple and their children."""
    key: str                      # "father_id+mother_id"
    father_id: str
    mother_id: str
    child_ids: list[str] = field(default_factory=list)


# ── PED parser ─────────────────────────────────────────────────────────────

def parse_ped(text: str) -> tuple[dict[str, Individual], list[str]]:
    """Parse PED or MPED format text into individuals.

    Detects MPED format automatically by looking for the '# MPED v' header line.
    For standard PED, creates a single phenotype named 'Phenotype'.

    Returns
    -------
    tuple of (dict[str, Individual], list[str])
        The individuals dict keyed by ind_id, and the ordered list of
        phenotype column names.
    """
    individuals: dict[str, Individual] = {}
    missing = {"0", "-9", ""}

    # Detect MPED format
    is_mped = False
    phenotype_names: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("# MPED v"):
            is_mped = True
            parts = line.split("\t")
            phenotype_names = [p.strip() for p in parts[1:] if p.strip()]
            break

    if not is_mped:
        phenotype_names = ["Phenotype"]

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if is_mped else line.split()
        if len(parts) < 6:
            continue

        fam_id = parts[0]
        ind_id = parts[1]
        father = parts[2] if parts[2] not in missing else None
        mother = parts[3] if parts[3] not in missing else None
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
                    pheno_dict[pname] = 0
            else:
                pheno_dict[pname] = 0

        # Primary phenotype: affected (2) if any phenotype is 2
        primary = 0
        for v in pheno_dict.values():
            if v == 2:
                primary = 2
                break
        if primary == 0:
            for v in pheno_dict.values():
                if v == 1:
                    primary = 1
                    break

        individuals[ind_id] = Individual(
            family_id=fam_id,
            ind_id=ind_id,
            father_id=father,
            mother_id=mother,
            sex=sex,
            phenotype=primary,
            phenotypes=pheno_dict,
        )

    return individuals, phenotype_names


# ── Graph analysis ─────────────────────────────────────────────────────────

def build_mating_units(inds: dict[str, Individual]) -> dict[str, MatingUnit]:
    """Extract all mating units from the pedigree.  Each unique (father, mother)
    pair found in child records becomes a MatingUnit."""
    units: dict[str, MatingUnit] = {}
    for ind in inds.values():
        if ind.father_id and ind.mother_id:
            # both parents present
            key = f"{ind.father_id}+{ind.mother_id}"
            if key not in units:
                units[key] = MatingUnit(key=key, father_id=ind.father_id, mother_id=ind.mother_id)
            units[key].child_ids.append(ind.ind_id)
            # record partnerships on the parents
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


def get_ancestors(inds: dict[str, Individual], ind_id: str) -> set[str]:
    """Return the set of all ancestor IDs for a given individual."""
    ancestors: set[str] = set()
    stack = [ind_id]
    while stack:
        current = stack.pop()
        ind = inds.get(current)
        if not ind:
            continue
        for parent_id in (ind.father_id, ind.mother_id):
            if parent_id and parent_id in inds and parent_id not in ancestors:
                ancestors.add(parent_id)
                stack.append(parent_id)
    return ancestors


def is_consanguineous(inds: dict[str, Individual], id1: str, id2: str) -> bool:
    """Return True if two individuals share at least one common ancestor."""
    anc1 = get_ancestors(inds, id1)
    anc2 = get_ancestors(inds, id2)
    return bool(anc1 & anc2)


def get_mating_unit_for_child(units: dict[str, MatingUnit], child_id: str) -> Optional[str]:
    """Return the mating-unit key that lists child_id, or None."""
    for mk, mu in units.items():
        if child_id in mu.child_ids:
            return mk
    return None


def assign_generations(inds: dict[str, Individual]) -> int:
    """Assign generation numbers (0 = founders). Returns the total number of
    generations. Uses iterative propagation to handle arbitrary depth."""
    # Founders: individuals whose parents are not in the pedigree
    for ind in inds.values():
        has_father = ind.father_id and ind.father_id in inds
        has_mother = ind.mother_id and ind.mother_id in inds
        if not has_father and not has_mother:
            ind.generation = 0

    changed = True
    while changed:
        changed = False
        for ind in inds.values():
            if ind.generation >= 0:
                continue
            father_gen = inds[ind.father_id].generation if (ind.father_id and ind.father_id in inds) else -1
            mother_gen = inds[ind.mother_id].generation if (ind.mother_id and ind.mother_id in inds) else -1
            if father_gen >= 0 and mother_gen >= 0:
                new_gen = max(father_gen, mother_gen) + 1
                ind.generation = new_gen
                changed = True
            elif father_gen >= 0 and not (ind.mother_id and ind.mother_id in inds):
                ind.generation = father_gen + 1
                changed = True
            elif mother_gen >= 0 and not (ind.father_id and ind.father_id in inds):
                ind.generation = mother_gen + 1
                changed = True

    # Marry-in partners: founders who have no parents themselves but are
    # partnered with someone at a later generation.  Move them to match
    # their partner so they appear on the same row.
    for ind in inds.values():
        if ind.generation >= 0 and ind.partners:
            has_parent = (ind.father_id and ind.father_id in inds) or (ind.mother_id and ind.mother_id in inds)
            if has_parent:
                continue  # not a marry-in — has own parents
            for pid in ind.partners:
                if pid in inds and inds[pid].generation > ind.generation:
                    ind.generation = inds[pid].generation
                    break

    # Fallback: anything still unassigned goes to generation 0
    for ind in inds.values():
        if ind.generation < 0:
            ind.generation = 0

    return max(ind.generation for ind in inds.values()) + 1 if inds else 0


# ── Layout engine ──────────────────────────────────────────────────────────

def compute_layout(inds: dict[str, Individual], units: dict[str, MatingUnit], num_gens: int):
    """Assign (x, y) positions to every individual.

    Strategy — process one generation at a time, top-down:
      Gen 0:  Place founder couples and singletons left-to-right.
      Gen 1+: For each parent mating unit, centre its children below the parent
              midpoint.  Partnered children get their marry-in partner placed on
              the outer edge.  Unpartnered singletons fill the inner positions.
              An overlap-avoidance pass shifts groups that would collide.
    """
    gen_members: dict[int, list[str]] = defaultdict(list)
    for ind in inds.values():
        gen_members[ind.generation].append(ind.ind_id)

    placed: set[str] = set()  # track who has been positioned

    # ── Gen 0: founders ───────────────────────────────────────────────
    y0 = 100.0
    cursor = 200.0  # start with some left margin

    # Identify Gen-0 couples
    gen0_couples: list[tuple[str, str]] = []
    gen0_coupled: set[str] = set()
    for mu in units.values():
        f, m = mu.father_id, mu.mother_id
        if f in inds and m in inds:
            if inds[f].generation == 0 and inds[m].generation == 0:
                pair = (min(f, m), max(f, m))
                if pair[0] not in gen0_coupled:
                    gen0_couples.append((f, m))
                    gen0_coupled.add(f)
                    gen0_coupled.add(m)

    for f, m in gen0_couples:
        inds[f].x, inds[f].y = cursor, y0
        cursor += PARTNER_GAP
        inds[m].x, inds[m].y = cursor, y0
        cursor += SHAPE_SIZE + MIN_BLOCK_GAP
        placed.add(f)
        placed.add(m)

    # Gen-0 singletons (founders with no partner in this gen)
    for iid in gen_members.get(0, []):
        if iid not in placed:
            inds[iid].x, inds[iid].y = cursor, y0
            cursor += SHAPE_SIZE + MIN_BLOCK_GAP
            placed.add(iid)

    # ── Gen 1+: children under parents ────────────────────────────────
    for gen in range(1, num_gens):
        y = 100 + gen * CHILD_HEIGHT

        # Collect children grouped by parent mating unit
        mu_children: dict[str, list[str]] = {}
        orphans: list[str] = []

        for iid in gen_members.get(gen, []):
            found_mu = get_mating_unit_for_child(units, iid)
            if found_mu:
                mu_children.setdefault(found_mu, []).append(iid)
            else:
                orphans.append(iid)

        # Pre-identify consanguineous pairs in this generation:
        # couples where BOTH partners are children of mating units.
        consang_pairs: set[tuple[str, str]] = set()
        all_children_this_gen: set[str] = set()
        for clist in mu_children.values():
            all_children_this_gen.update(clist)

        for iid in all_children_this_gen:
            for pid in inds[iid].partners:
                if pid in all_children_this_gen:
                    pair = (min(iid, pid), max(iid, pid))
                    consang_pairs.add(pair)

        # Sort mating-unit groups by parent x-midpoint (left families first)
        def mu_sort_key(mk):
            mu = units[mk]
            xs = []
            if mu.father_id in inds and inds[mu.father_id].generation < gen:
                xs.append(inds[mu.father_id].x)
            if mu.mother_id in inds and inds[mu.mother_id].generation < gen:
                xs.append(inds[mu.mother_id].x)
            return (sum(xs) / len(xs)) if xs else 0

        mu_order = sorted(mu_children.keys(), key=mu_sort_key)

        used_ranges: list[tuple[float, float]] = []

        for mk in mu_order:
            mu = units[mk]
            children = mu_children[mk]
            if not children:
                continue

            # Parent midpoint
            fx = (inds[mu.father_id].x + SHAPE_HALF) if mu.father_id in inds else 0
            mx = (inds[mu.mother_id].x + SHAPE_HALF) if mu.mother_id in inds else 0
            parent_mid = (fx + mx) / 2

            # Classify children's partners
            child_infos: list[tuple[str, bool, Optional[str], bool]] = []
            # (child_id, has_partner, partner_id, partner_is_consanguineous)
            for cid in children:
                partner_id = None
                partner_is_consang = False
                for pid in inds[cid].partners:
                    if pid in inds and inds[pid].generation == gen and pid not in children:
                        partner_id = pid
                        pair = (min(cid, pid), max(cid, pid))
                        partner_is_consang = pair in consang_pairs
                        break
                child_infos.append((cid, partner_id is not None, partner_id, partner_is_consang))

            # Sort: partnered children at edges, unpartnered in centre.
            partnered = [(cid, p, pid, pc) for cid, p, pid, pc in child_infos if p]
            unpartnered = [(cid, p, pid, pc) for cid, p, pid, pc in child_infos if not p]

            # Distribute partnered children to edges.
            # For consanguineous partners already placed, put the child on
            # the side closest to the placed partner.
            left_partnered: list = []
            right_partnered: list = []

            for entry in partnered:
                cid, p, pid, pc = entry
                if pc and pid and pid in placed:
                    # Consanguineous partner already placed — child goes to that side
                    if inds[pid].x < parent_mid:
                        left_partnered.append(entry)
                    else:
                        right_partnered.append(entry)
                elif pc and pid and pid not in placed:
                    # Consanguineous partner not yet placed — child goes right
                    # (their sibling group will be processed later, further right)
                    right_partnered.append(entry)
                else:
                    # Marry-in: default to right
                    right_partnered.append(entry)

            # If multiple marry-in partners, split evenly across edges
            marry_ins = [e for e in right_partnered if not e[3]]
            consang_right = [e for e in right_partnered if e[3]]
            if len(marry_ins) > 1:
                half = len(marry_ins) // 2
                left_partnered = left_partnered + marry_ins[:half]
                right_partnered = consang_right + marry_ins[half:]
            else:
                right_partnered = consang_right + marry_ins

            ordered = left_partnered + unpartnered + right_partnered

            # Compute positions
            n_slots = len(ordered)
            total_width = (n_slots - 1) * CHILD_SPACING if n_slots > 1 else 0
            start_x = parent_mid - total_width / 2 - SHAPE_HALF

            positions: list[tuple[str, float]] = []
            for i, (cid, has_partner, partner_id, partner_is_consang) in enumerate(ordered):
                cx = start_x + i * CHILD_SPACING
                if has_partner and partner_id:
                    if partner_is_consang:
                        # Consanguineous partner: only place the child here.
                        # The partner will be placed by their own mating unit group.
                        positions.append((cid, cx))
                    else:
                        # Marry-in partner: place both child and partner.
                        child_centre = cx + SHAPE_HALF
                        if child_centre <= parent_mid:
                            positions.append((partner_id, cx - PARTNER_GAP))
                            positions.append((cid, cx))
                        else:
                            positions.append((cid, cx))
                            positions.append((partner_id, cx + PARTNER_GAP))
                else:
                    positions.append((cid, cx))

            # Overlap avoidance
            if positions:
                min_x = min(px for _, px in positions)
                max_x = max(px for _, px in positions) + SHAPE_SIZE
                for rng_min, rng_max in used_ranges:
                    if min_x < rng_max + MIN_BLOCK_GAP and max_x > rng_min - MIN_BLOCK_GAP:
                        shift = rng_max + MIN_BLOCK_GAP - min_x
                        positions = [(pid, px + shift) for pid, px in positions]
                        min_x += shift
                        max_x += shift
                used_ranges.append((min_x, max_x))

                for pid, px in positions:
                    if pid and pid in inds:
                        inds[pid].x = px
                        inds[pid].y = y
                        placed.add(pid)

        # Place orphans
        orphan_cursor = (used_ranges[-1][1] + MIN_BLOCK_GAP) if used_ranges else 100.0
        for iid in orphans:
            if iid not in placed:
                inds[iid].x = orphan_cursor
                inds[iid].y = y
                orphan_cursor += SHAPE_SIZE + MIN_BLOCK_GAP
                placed.add(iid)

    # ── Final pass: normalise coordinates ──────────────────────────────
    # Shift everything right so all positions are ≥ 100
    if inds:
        min_x_global = min(ind.x for ind in inds.values())
        if min_x_global < 100:
            shift = 100 - min_x_global
            for ind in inds.values():
                ind.x += shift


# ── Session builder ────────────────────────────────────────────────────────

def build_session(
    inds: dict[str, Individual],
    units: dict[str, MatingUnit],
    phenotype_names: list[str],
    affected_color: str = AFFECTED_COLOR,
    use_shading: bool = False,
    shading_pattern: str = "stripes",
    fill_type: str = "full",
) -> dict:
    """Build a Pedigree Studio v4 session dict.

    Handles both single-phenotype PED and multi-phenotype MPED data.
    For multi-phenotype, assigns a colour per phenotype from the palette.
    """
    persons = []
    partnerships = []
    child_links = []
    legend_labels = {}

    pid_counter = 0
    pship_counter = 0
    cl_counter = 0

    # Determine if this is multi-phenotype
    # Filter out "Carrier" column — it maps to centre dot, not a colour
    visual_phenotypes = [n for n in phenotype_names if n.lower() != "carrier"]
    carrier_column = next((n for n in phenotype_names if n.lower() == "carrier"), None)
    is_multi = len(visual_phenotypes) > 1

    # Assign colours to phenotypes
    pheno_colors: dict[str, str] = {}
    if is_multi:
        for i, pname in enumerate(visual_phenotypes):
            pheno_colors[pname] = PHENOTYPE_PALETTE[i % len(PHENOTYPE_PALETTE)]
    elif visual_phenotypes:
        pheno_colors[visual_phenotypes[0]] = affected_color

    # Map individual IDs to Pedigree Studio person IDs
    id_map: dict[str, str] = {}
    for ind in inds.values():
        pid_counter += 1
        ps_id = f"person-{pid_counter}"
        id_map[ind.ind_id] = ps_id

        shape = SEX_MAP.get(ind.sex, DEFAULT_SEX)

        fill_mode = "none"
        fill_color = affected_color
        halves = [None, None]
        quarters = [None, None, None, None]
        shading_pat = "stripes"
        shading_cov = "full"
        center_text = ""

        if is_multi:
            # Multi-phenotype: determine which phenotypes this person has
            affected_phenos = [pn for pn in visual_phenotypes if ind.phenotypes.get(pn) == 2]
            carrier_phenos = [pn for pn in visual_phenotypes if ind.phenotypes.get(pn) == 3]

            if len(affected_phenos) >= 4:
                # 4+ affected: quartered fill with first four colours
                fill_mode = "quartered"
                for qi in range(min(4, len(affected_phenos))):
                    quarters[qi] = pheno_colors[affected_phenos[qi]]
            elif len(affected_phenos) >= 2:
                # 2-3 affected: quartered fill
                fill_mode = "quartered"
                for qi, pn in enumerate(affected_phenos[:4]):
                    quarters[qi] = pheno_colors[pn]
            elif len(affected_phenos) == 1:
                # 1 affected: solid fill
                fill_mode = "solid"
                fill_color = pheno_colors[affected_phenos[0]]
            elif len(carrier_phenos) >= 2:
                # Multiple carrier: quartered with lighter treatment
                fill_mode = "quartered"
                for qi, pn in enumerate(carrier_phenos[:4]):
                    quarters[qi] = pheno_colors[pn]
            elif len(carrier_phenos) == 1:
                # 1 carrier: half fill
                fill_mode = "half"
                halves = [pheno_colors[carrier_phenos[0]], None]

            # Carrier column → centre dot (independent of colour-based carrier)
            if carrier_column and ind.phenotypes.get(carrier_column) == 3:
                center_text = "dot"

        else:
            # Single phenotype: use the existing styling options
            pname = visual_phenotypes[0] if visual_phenotypes else None
            pheno_val = ind.phenotypes.get(pname, ind.phenotype) if pname else ind.phenotype

            if pheno_val == 2:
                if use_shading:
                    fill_mode = "shading"
                    shading_pat = shading_pattern
                    shading_cov = "half-left" if fill_type == "half" else "full"
                elif fill_type == "half":
                    fill_mode = "half"
                    halves = [affected_color, None]
                else:
                    fill_mode = "solid"
                    fill_color = affected_color
            elif pheno_val == 3:
                # Carrier in single-phenotype mode: half fill or dot
                if fill_type == "half" or use_shading:
                    center_text = "dot"
                else:
                    fill_mode = "half"
                    halves = [affected_color, None]

            # Carrier column → centre dot
            if carrier_column and ind.phenotypes.get(carrier_column) == 3:
                center_text = "dot"

        persons.append({
            "id": ps_id,
            "shape": shape,
            "x": round(ind.x, 1),
            "y": round(ind.y, 1),
            "text": ind.ind_id,
            "deceased": False,
            "proband": False,
            "fillMode": fill_mode,
            "fillColor": fill_color,
            "quarters": quarters,
            "halves": halves,
            "shadingPattern": shading_pat,
            "shadingCoverage": shading_cov,
            "centerText": center_text,
            "miscarriageSex": "unknown",
            "noSnap": False,
            "siblingFixed": False,
            "customLabel": "Lbl",
        })

    # Partnerships (one per mating unit)
    pship_id_map: dict[str, str] = {}
    for mk, mu in units.items():
        if mu.father_id in id_map and mu.mother_id in id_map:
            pship_counter += 1
            ps_id = f"pship-{pship_counter}"
            pship_id_map[mk] = ps_id
            ptype = "consanguineous" if is_consanguineous(inds, mu.father_id, mu.mother_id) else "normal"
            partnerships.append({
                "id": ps_id,
                "fromId": id_map[mu.father_id],
                "toId": id_map[mu.mother_id],
                "type": ptype,
            })

    # Child links
    for mk, mu in units.items():
        if mk not in pship_id_map:
            continue
        for cid in mu.child_ids:
            if cid in id_map:
                cl_counter += 1
                child_links.append({
                    "id": f"child-{cl_counter}",
                    "partnershipId": pship_id_map[mk],
                    "childId": id_map[cid],
                    "branchYOffset": 0,
                    "dashed": False,
                })

    # Legend
    if is_multi:
        for pname in visual_phenotypes:
            if any(ind.phenotypes.get(pname, 0) >= 2 for ind in inds.values()):
                legend_labels[pheno_colors[pname]] = pname
    elif use_shading:
        cov = "half-left" if fill_type == "half" else "full"
        key = f"shading:{shading_pattern}:{cov}"
        legend_labels[key] = "Affected"
    else:
        any_affected = any(ind.phenotype == 2 for ind in inds.values())
        if any_affected:
            legend_labels[affected_color] = "Affected"

    return {
        "version": 4,
        "personIdCounter": pid_counter,
        "labelIdCounter": 0,
        "lineIdCounter": max(pship_counter, cl_counter) if pship_counter or cl_counter else 0,
        "persons": persons,
        "labels": [],
        "partnerships": partnerships,
        "childLinks": child_links,
        "twinLinks": [],
        "legendLabels": legend_labels,
        "legendVisible": bool(legend_labels),
        "legendX": 50,
        "legendY": 80,
        "zoom": 1,
        "panX": 0,
        "panY": 0,
        "numberingMode": "numbers",
        "partnerGapMultiplier": 2,
        "childHeightMultiplier": 2.5,
    }


# ── Public API ─────────────────────────────────────────────────────────────

def convert(
    ped_text: str,
    affected_color: str = AFFECTED_COLOR,
    use_shading: bool = False,
    shading_pattern: str = "stripes",
    fill_type: str = "full",
) -> dict:
    """Convert PED or MPED format text to a Pedigree Studio session dict.

    Automatically detects MPED format (by looking for '# MPED v' header).
    For MPED with multiple phenotypes, each phenotype gets a distinct colour
    from the palette and the affected_color/use_shading/fill_type options
    are ignored. For single-phenotype files (standard PED or single-column
    MPED), the styling options apply as before.

    Parameters
    ----------
    ped_text : str
        Contents of a PED or MPED file.
    affected_color : str
        Hex colour for affected individuals (single-phenotype only).
    use_shading : bool
        If True, use shading fill mode (single-phenotype only).
    shading_pattern : str
        'stripes' or 'dots' (single-phenotype, shading only).
    fill_type : str
        'full' or 'half' (single-phenotype only).

    Returns
    -------
    dict
        A Pedigree Studio v4 session object, ready for JSON serialisation.
    """
    inds, phenotype_names = parse_ped(ped_text)
    if not inds:
        return build_session({}, {}, phenotype_names, affected_color, use_shading, shading_pattern, fill_type)

    units = build_mating_units(inds)
    num_gens = assign_generations(inds)
    compute_layout(inds, units, num_gens)
    return build_session(inds, units, phenotype_names, affected_color, use_shading, shading_pattern, fill_type)


def convert_file(
    input_path: str,
    output_path: str,
    **kwargs,
) -> dict:
    """Read a PED or MPED file and write the Pedigree Studio session JSON.

    Parameters
    ----------
    input_path : str
        Path to the input .ped or .mped file.
    output_path : str
        Path to the output .json file.
    **kwargs
        Passed to convert().

    Returns
    -------
    dict
        The session dict that was written.
    """
    with open(input_path, "r") as f:
        ped_text = f.read()

    session = convert(ped_text, **kwargs)

    with open(output_path, "w") as f:
        json.dump(session, f, indent=2)

    return session
