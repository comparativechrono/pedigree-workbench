'''
Pedigree Studio drawings of the pedigrees PedInterp reads.

Studio_export writes a pedigree read by pedigree_processing as a Pedigree Studio file, <FamilyID>.studio.json, which
the Studio opens (Open, in its menu) as a drawing to carry on with: a pedigree sketched by hand, or a picture of one,
becomes a Studio drawing. It holds what a PED file can't: the twins, identical or not, the couples who have no children,
and where each person was drawn, so the drawing is laid out as the picture was, a row of symbols to a generation. The
Studio's Tidy lays it out afresh.

The file is in the form the Studio saves (version 5), which ped2studio and ga4gh2studio write too, so that studio2ped
and studio2ga4gh read it back.
'''
import json
import os
import re
from statistics import median

#: Pedigree Studio's symbols are 52 pixels across, and it draws each generation two and a half symbols below the one
#: before, with partners two symbols apart
SHAPE = 52
ROW_GAP = 2.5*SHAPE
PARTNER_GAP = 2*SHAPE
#: the drawing's top left corner, as ga4gh2studio lays drawings out
MARGIN = 100
#: the closest two people in a row are drawn, from the left of one symbol to the left of the next
CLOSEST = 1.5*SHAPE
#: what the affected are filled with, as ped2studio fills them: the colour the Studio draws its lines in
AFFECTED_COLOUR = '#1a2332'
#: the Studio's symbol for each shape PedInterp reads, and for each sex in a table without them
STUDIO_SHAPES = {'square': 'male', 'circle': 'female', 'diamond': 'unknown', 'triangle': 'miscarriage'}
SEX_SHAPES = {1: 'male', 2: 'female'}
#: the numbers the Studio gives people itself, which it shows without them being written as text
_NUMBERED = re.compile(r'[IVXLCDM]+-\d+')


def _id(value):
    '''An id as text: 3, not 3.0'''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _generations(people, parents):
    '''Each person's generation, from 0 for those without parents in the drawing, for a table without a layout'''
    found = {}

    def generation(person, seen=()):
        if person not in found:
            above = [generation(p, seen + (person,)) + 1 for p in parents.get(person, ()) if p in people and p not in seen]
            found[person] = max(above, default=0)
        return found[person]
    for person in people:
        generation(person)
    return found


def _positions(people, parents, layout):
    '''
    Where each person is drawn, as (x, y), the top left corner of their symbol in the Studio's pixels: where the picture
    has them, the picture made the size of the Studio's drawings (its symbols as large as the Studio's, and no closer
    together on the whole), with each row of symbols a generation at the Studio's spacing; or, for a table without a
    layout, by generation and in the order of the table. No two people in a row are closer than CLOSEST, and the
    drawing starts MARGIN from the top left
    '''
    if all(person in layout and layout[person].get('box') for person in people):
        rows = {row: k for k, row in enumerate(sorted({layout[person]['row'] for person in people}))}
        row = {person: rows[layout[person]['row']] for person in people}
        middle = {person: layout[person]['box'][0] + layout[person]['box'][2]/2 for person in people}
        # (the picture made the size of the Studio's drawings, by its symbols; or by how far apart they are, if they
        # are drawn closer together than the Studio draws them, as they often are in a sketch, so that their numbers
        # have room)
        size = median(max(layout[person]['box'][2], layout[person]['box'][3]) for person in people) or 1.0
        apart = []
        for k in set(row.values()):
            line = sorted(middle[person] for person in people if row[person] == k)
            apart += [b - a for a, b in zip(line, line[1:]) if b > a]
        scale = max(SHAPE/size, PARTNER_GAP/median(apart) if apart else 0)
        x = {person: middle[person]*scale - SHAPE/2 for person in people}
    else:
        row = _generations(people, parents)
        x, count = {}, {}
        for person in people:
            x[person] = count.get(row[person], 0)*PARTNER_GAP
            count[row[person]] = count.get(row[person], 0) + 1
    for k in set(row.values()):
        line = sorted((person for person in people if row[person] == k), key=lambda person: x[person])
        for left, right in zip(line, line[1:]):
            x[right] = max(x[right], x[left] + CLOSEST)
    shift = MARGIN - min(x.values(), default=MARGIN)
    return {person: (round(x[person] + shift, 1), round(MARGIN + row[person]*ROW_GAP, 1)) for person in people}


def _ancestors(person, parents, seen=None):
    seen = set() if seen is None else seen
    for parent in parents.get(person, ()):
        if parent not in seen:
            seen.add(parent)
            _ancestors(parent, parents, seen)
    return seen


def studio_drawing(PED_df, condition=None):
    '''
    A pedigree read by pedigree_processing as a Pedigree Studio drawing: the dict that Studio_export writes as JSON.

    Each person is a symbol, filled in if they are affected, with a colour key naming condition (an ontology term and
    its label, as GA4GH_export takes it) or saying "Affected"; a triangle, for a pregnancy lost, is the Studio's
    symbol for one. Couples are joined, those with no children too (from attrs['partners']), and their children hang
    from the line between them; twins (attrs['twins']) are joined to one point, with a bar if they are identical. A
    child with only one parent in the table is given an unknown parent for the line to come from, as ga4gh2studio
    gives one. People numbered as the Studio numbers them (I-1, II-3) have no text of their own, as the Studio shows
    its numbers, and anyone else's ID is written under their symbol. The marks of a dataframe read with marks=True are
    drawn as the Studio draws them: a slash through the symbol of someone who has died, the proband's arrow, and a
    carrier's dot.
    '''
    from .core import _marked, ga4gh_condition, has_marks, twin_groups
    layout = PED_df.attrs.get('layout') or {}
    people, sex, affected, parents = [], {}, {}, {}
    marked = has_marks(PED_df)
    deceased, proband, carrier = {}, {}, {}
    for row in PED_df.itertuples(index=False):
        person = _id(row.IndividualID)
        people.append(person)
        sex[person] = int(row.Sex)
        affected[person] = int(row.Phenotype) == 2
        if marked:
            deceased[person] = _marked(row, 'Deceased')
            proband[person] = _marked(row, 'Proband')
            carrier[person] = _marked(row, 'Carrier')
        parents[person] = tuple(p for p in (_id(row.PaternalID), _id(row.MaternalID)) if p not in ('0', ''))
    known = set(people)
    father_mother = {}
    for row in PED_df.itertuples(index=False):
        father, mother = _id(row.PaternalID), _id(row.MaternalID)
        father_mother[_id(row.IndividualID)] = (father if father in known else None, mother if mother in known else None)
    position = _positions(people, parents, layout)

    # a child with one parent in the table: an unknown parent beside that one, for the line to come from
    unknown = {}
    for person in people:
        father, mother = father_mother[person]
        if bool(father) != bool(mother):
            one = father or mother
            if one not in unknown:
                unknown[one] = f'{one}-partner'
                x, y = position[one]
                position[unknown[one]] = (round(x + PARTNER_GAP, 1), y)
            father_mother[person] = (father, unknown[father]) if father else (unknown[mother], mother)
    if unknown:
        # (no closer to the people beside them than anyone else)
        for y in {position[u][1] for u in unknown.values()}:
            line = sorted((p for p in position if position[p][1] == y), key=lambda p: position[p][0])
            for left, right in zip(line, line[1:]):
                if position[right][0] < position[left][0] + CLOSEST:
                    position[right] = (round(position[left][0] + CLOSEST, 1), y)

    if condition is not None:
        cid, label = ga4gh_condition(condition)
        key_text = f'{label} [{cid}]'
    else:
        key_text = 'Affected'
    numbers = {person: f'person-{k + 1}' for k, person in enumerate(people + list(unknown.values()))}
    persons = []
    for person in people + list(unknown.values()):
        placeholder = person not in known
        shape = STUDIO_SHAPES.get((layout.get(person) or {}).get('shape')) if not placeholder else None
        shape = shape or SEX_SHAPES.get(sex.get(person), 'unknown')
        x, y = position[person]
        persons.append({
            'id': numbers[person], 'shape': shape, 'x': x, 'y': y,
            'text': 'unknown parent' if placeholder else ('' if _NUMBERED.fullmatch(person) else person),
            'deceased': deceased.get(person, False), 'proband': proband.get(person, False),
            'fillMode': 'solid' if affected.get(person) else 'none', 'fillColor': AFFECTED_COLOUR,
            'quarters': [None]*4, 'halves': [None, None], 'shadingPattern': 'stripes', 'shadingCoverage': 'full',
            'centerText': 'dot' if carrier.get(person) else '',
            'miscarriageSex': {1: 'male', 2: 'female'}.get(sex.get(person), 'unknown') if shape == 'miscarriage'
            else 'unknown',
            'noSnap': False, 'siblingFixed': False, 'customLabel': 'Lbl'})

    lines = 0
    partnerships, child_links, twin_links = [], [], []
    couples = {}
    ancestors = {}

    def couple(a, b):
        nonlocal lines
        key = tuple(sorted((a, b)))
        if key not in couples:
            for p in key:
                if p not in ancestors:
                    ancestors[p] = _ancestors(p, parents)
            related = bool((ancestors[a] | {a}) & (ancestors[b] | {b}))
            lines += 1
            couples[key] = f'pship-{lines}'
            left, right = sorted(key, key=lambda p: position[p][0])
            partnerships.append({'id': couples[key], 'fromId': numbers[left], 'toId': numbers[right],
                                 'type': 'consanguineous' if related else 'normal'})
        return couples[key]

    for a, b in PED_df.attrs.get('partners') or []:
        a, b = _id(a), _id(b)
        if a in known and b in known and a != b:
            couple(a, b)
    for person in people:
        father, mother = father_mother[person]
        if father and mother:
            pship = couple(father, mother)
            lines += 1
            child_links.append({'id': f'child-{lines}', 'partnershipId': pship, 'childId': numbers[person],
                                'branchYOffset': 0, 'dashed': False})
    partnership_of = {link['childId']: link['partnershipId'] for link in child_links}
    for first, others in twin_groups(PED_df):
        for other, identical in others:
            pship = partnership_of.get(numbers.get(first))
            if pship and pship == partnership_of.get(numbers.get(other)):
                lines += 1
                twin_links.append({'id': f'twin-{lines}', 'child1Id': numbers[first], 'child2Id': numbers[other],
                                   'type': 'identical' if identical else 'nonidentical', 'partnershipId': pship})

    legend = {AFFECTED_COLOUR: key_text} if any(affected.values()) else {}
    right = max((p['x'] for p in persons), default=MARGIN)
    return {
        'version': 5, 'personIdCounter': len(persons), 'labelIdCounter': 0, 'lineIdCounter': lines,
        'persons': persons, 'labels': [], 'partnerships': partnerships, 'childLinks': child_links,
        'twinLinks': twin_links, 'legendLabels': legend, 'legendVisible': bool(legend),
        # (the colour key to the right of the drawing)
        'legendX': round(right + SHAPE + 60, 1), 'legendY': MARGIN,
        'zoom': 1, 'panX': 0, 'panY': 0, 'numberingMode': 'numbers',
        'partnerGapMultiplier': PARTNER_GAP/SHAPE, 'childHeightMultiplier': ROW_GAP/SHAPE, 'drawStrokes': [],
    }


def Studio_export(PED_df, output_dir='.', condition=None):
    '''
    Writes a pedigree read by pedigree_processing as a Pedigree Studio drawing, output_dir/<FamilyID>.studio.json
    (see studio_drawing), and returns the file's path. Open it in Pedigree Studio to carry on with the drawing.
    '''
    family = _id(PED_df['FamilyID'].iloc[0])
    drawing = studio_drawing(PED_df, condition=condition)
    os.makedirs(output_dir, exist_ok=True)
    path = f'{output_dir}/{family}.studio.json'
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(drawing, fh, indent=2)
        fh.write('\n')
    return path
