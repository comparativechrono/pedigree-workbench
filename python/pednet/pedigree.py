"""Pedigrees: reading PED files, checking them, and the relationships that PedNet needs.

A PED file has one person per line, in six columns: family, person, father, mother, sex
(1 male, 2 female, 0 unknown) and phenotype (2 affected, 1 unaffected, 0 or -9 unknown).
A father or mother of 0 means that parent isn't in the file.
"""
import io
import numbers
import re
from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

MALE, FEMALE, UNKNOWN_SEX = 1, 2, 0
AFFECTED, UNAFFECTED, UNKNOWN = 2, 1, 0

_NO_PARENT = {'', '0', '-9', 'na', 'nan', 'none', '.', '0.0'}
_SEXES = {'1': MALE, '1.0': MALE, 'm': MALE, 'male': MALE, '2': FEMALE, '2.0': FEMALE, 'f': FEMALE,
          'female': FEMALE}
_PHENOTYPES = {'2': AFFECTED, '1': UNAFFECTED, '2.0': AFFECTED, '1.0': UNAFFECTED,
               'affected': AFFECTED, 'unaffected': UNAFFECTED}


def _id(value) -> str:
    """A person's ID as text. A whole number stored as a decimal, as pandas stores the IDs in a column with a blank
    in it (1.0), is written as the whole number (1), so that it matches the same ID in a column of whole numbers."""
    if isinstance(value, numbers.Real) and not isinstance(value, numbers.Integral):
        number = float(value)
        if number == number and number.is_integer():
            return str(int(number))
    return str(value).strip()


def _parent(value) -> Optional[str]:
    """A parent's ID, or None when the parent isn't in the pedigree (0, a blank, or a missing value)"""
    if value is None:
        return None
    text = _id(value)
    if text.lower() in _NO_PARENT:
        return None
    try:
        if float(text) == 0:
            return None
    except ValueError:
        pass
    return text


def _sex(value) -> int:
    return _SEXES.get(str(value).strip().lower(), UNKNOWN_SEX)


def _phenotype(value) -> int:
    return _PHENOTYPES.get(str(value).strip().lower(), UNKNOWN)


@dataclass
class Person:
    """One person in a pedigree. father and mother are IDs, or None for a parent who isn't in the pedigree."""
    id: str
    father: Optional[str] = None
    mother: Optional[str] = None
    sex: int = UNKNOWN_SEX
    phenotype: int = UNKNOWN
    added: bool = False        # put in by PedNet: a parent with no line in the file, or the other parent of someone with only one
    placeholder: bool = False  # added with an ID of PedNet's own (the other parent of someone with only one)

    @property
    def affected(self) -> bool:
        return self.phenotype == AFFECTED

    @property
    def unaffected(self) -> bool:
        return self.phenotype == UNAFFECTED


class PedigreeError(ValueError):
    """A pedigree that can't be used: someone their own ancestor, a person listed twice, or a parent of both sexes"""


class Pedigree:
    """
    One family. People are kept in the order given. Each person has either both parents in the pedigree or neither:
    when only one parent is given, PedNet adds the other as an unknown person, and a parent with no line of their own
    is added too (with the sex their role gives them), so that the likelihoods can treat everyone alike.

    notes lists anything PedNet changed or found odd while reading the family.
    """

    def __init__(self, people: Iterable[Person], family: str = ''):
        self.family = family
        self.notes: List[str] = []
        self.people: List[Person] = []
        self.index: Dict[str, int] = {}
        for person in people:
            if person.id in self.index:
                raise PedigreeError(f'Family {family}: {person.id} is listed more than once')
            self.index[person.id] = len(self.people)
            self.people.append(person)
        self._complete()
        self._children: Dict[str, List[str]] = {p.id: [] for p in self.people}
        for p in self.people:
            for parent in (p.father, p.mother):
                if parent is not None:
                    self._children[parent].append(p.id)
        self._order = self._topological_order()

    # -- building ---------------------------------------------------------------------------------------------
    def _add(self, person: Person):
        self.index[person.id] = len(self.people)
        self.people.append(person)

    def _complete(self):
        """Add missing parents, give each parent the sex of their role, and check that no one is both a father and a mother"""
        # a parent written as a decimal (1.0), as a file saved from a table with blanks in its parent columns can
        # have them, is the person with the whole-number ID (1), if no one has the decimal ID itself
        renamed = set()
        for p in self.people:
            for role in ('father', 'mother'):
                parent = getattr(p, role)
                if parent is None or parent in self.index:
                    continue
                whole = parent.split('.')[0] if re.fullmatch(r'-?\d+\.0+', parent) else None
                if whole is not None and whole in self.index:
                    setattr(p, role, whole)
                    renamed.add((parent, whole))
        for parent, whole in sorted(renamed):
            self.notes.append(f'the parent {parent} is taken to be {whole}, the same number written without decimals')
        fathers = {p.father for p in self.people if p.father is not None}
        mothers = {p.mother for p in self.people if p.mother is not None}
        both = fathers & mothers
        if both:
            raise PedigreeError(f'Family {self.family}: {", ".join(sorted(both))} listed as both a father and a mother')
        # the children of each parent whose other parent isn't in the file, who share one unknown other parent
        partnerless: Dict[Tuple[str, str], List[Person]] = {}
        for p in list(self.people):
            for role, sex in (('father', MALE), ('mother', FEMALE)):
                parent = getattr(p, role)
                if parent is not None and parent not in self.index:
                    self._add(Person(parent, sex=sex, added=True))
                    self.notes.append(f'{parent}, the {role} of {p.id}, has no line of their own, so was added with an unknown phenotype')
            if (p.father is None) != (p.mother is None):
                missing = 'father' if p.father is None else 'mother'
                partnerless.setdefault((p.mother if missing == 'father' else p.father, missing), []).append(p)
        for (known, missing), children in partnerless.items():
            new_id = f'{known}~partner'
            while new_id in self.index:
                new_id += '~'
            self._add(Person(new_id, sex=MALE if missing == 'father' else FEMALE, added=True, placeholder=True))
            for child in children:
                setattr(child, missing, new_id)
            names = [c.id for c in children]
            who = names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]
            known_role = 'mother' if missing == 'father' else 'father'
            self.notes.append(f'{who} {"has" if len(names) == 1 else "have"} only a {known_role} ({known}) in the file, '
                              f'so an unknown {missing} was added' +
                              ('' if len(names) == 1 else ', the same one for all of them'))
        for p in self.people:
            if p.id in fathers and p.sex != MALE:
                if p.sex == FEMALE:
                    self.notes.append(f'{p.id} is a father but is listed as female, and is taken as male')
                p.sex = MALE
            if p.id in mothers and p.sex != FEMALE:
                if p.sex == MALE:
                    self.notes.append(f'{p.id} is a mother but is listed as male, and is taken as female')
                p.sex = FEMALE

    def _topological_order(self) -> List[str]:
        """Everyone with their parents before them; a PedigreeError if someone is their own ancestor"""
        waiting = {p.id: sum(parent is not None for parent in (p.father, p.mother)) for p in self.people}
        queue = deque(p.id for p in self.people if waiting[p.id] == 0)
        order = []
        while queue:
            n = queue.popleft()
            order.append(n)
            for child in self._children[n]:
                waiting[child] -= 1
                if waiting[child] == 0:
                    queue.append(child)
        if len(order) != len(self.people):
            stuck = sorted(n for n, w in waiting.items() if w > 0)
            raise PedigreeError(f'Family {self.family}: some people are their own ancestors ({", ".join(stuck[:5])})')
        return order

    # -- relationships -----------------------------------------------------------------------------------------
    def __len__(self):
        return len(self.people)

    def __iter__(self):
        return iter(self.people)

    def __getitem__(self, person_id: str) -> Person:
        return self.people[self.index[person_id]]

    def __contains__(self, person_id) -> bool:
        return person_id in self.index

    def __repr__(self):
        return f'Pedigree({self.family!r}, {len(self.people)} people, {len(self.affected())} affected)'

    @property
    def ids(self) -> List[str]:
        return [p.id for p in self.people]

    def children(self, person_id: str) -> List[str]:
        return list(self._children[person_id])

    def parents(self, person_id: str) -> Tuple[Optional[str], Optional[str]]:
        p = self[person_id]
        return p.father, p.mother

    def founders(self) -> List[str]:
        return [p.id for p in self.people if p.father is None]

    def affected(self) -> List[str]:
        return [p.id for p in self.people if p.affected]

    def order(self) -> List[str]:
        """Everyone, each after their parents"""
        return list(self._order)

    def ancestors(self, person_id: str) -> set:
        found, stack = set(), [person_id]
        while stack:
            for parent in self.parents(stack.pop()):
                if parent is not None and parent not in found:
                    found.add(parent)
                    stack.append(parent)
        return found

    def generations(self) -> Dict[str, int]:
        """
        Each person's generation, 0 for the oldest. A child is one generation below its parents, so partners share a
        generation and people who married in are in their partner's. Where that can't hold throughout (people of
        different generations with a child together), each child is one below its lower parent, and each person with no
        parents one above their highest child. The result doesn't depend on the order of the people.
        """
        level: Dict[str, int] = {}
        seen = set()
        for start in self._order:
            if start in seen:
                continue
            comp = {start: 0}
            queue = deque([start])
            consistent = True
            while queue:
                n = queue.popleft()
                p = self[n]
                steps = [(c, 1) for c in self._children[n]] + [(q, -1) for q in (p.father, p.mother) if q is not None]
                for other, step in steps:
                    if other not in comp:
                        comp[other] = comp[n] + step
                        queue.append(other)
                    elif comp[other] != comp[n] + step:
                        consistent = False
            seen.update(comp)
            if not consistent:
                members = [n for n in self._order if n in comp]
                comp = {}
                for n in members:
                    p = self[n]
                    comp[n] = max(comp[p.father], comp[p.mother]) + 1 if p.father is not None else 0
                for n in members:
                    if self[n].father is None and self._children[n]:
                        comp[n] = min(comp[c] for c in self._children[n]) - 1
            oldest = min(comp.values())
            for n, l in comp.items():
                level[n] = l - oldest
        return level

    def consanguineous(self) -> Dict[str, str]:
        """The children of related parents, each with the parents' closest common ancestor"""
        found = {}
        for p in self.people:
            if p.father is None:
                continue
            father_side = self.ancestors(p.father) | {p.father}
            mother_side = self.ancestors(p.mother) | {p.mother}
            common = father_side & mother_side
            if common:
                # the closest: the common ancestor with the fewest steps down to the two parents
                def steps(a):
                    return self._steps_down(a, p.father) + self._steps_down(a, p.mother)
                found[p.id] = min(sorted(common), key=steps)
        return found

    def _steps_down(self, ancestor: str, person: str) -> int:
        """The fewest parent-to-child steps from ancestor down to person"""
        distance = {ancestor: 0}
        queue = deque([ancestor])
        while queue:
            n = queue.popleft()
            if n == person:
                return distance[n]
            for c in self._children[n]:
                if c not in distance:
                    distance[c] = distance[n] + 1
                    queue.append(c)
        return 10 ** 6

    def to_networkx(self, placeholders: bool = False):
        """The pedigree as a networkx DAG, with an edge from each parent to each child (see graph.pedigree_graph)"""
        from .graph import pedigree_graph
        return pedigree_graph(self, placeholders)

    def problems(self) -> List[str]:
        """Things in the family worth checking, besides the notes made while reading it"""
        found = []
        for p in self.people:
            if p.sex == UNKNOWN_SEX and not p.placeholder:
                found.append(f'{p.id} has no sex recorded')
        if not self.affected():
            found.append('no one is affected')
        return found


def read_ped(source, family: Optional[str] = None) -> Dict[str, Pedigree]:
    """
    Reads a PED file into a pedigree for each family, keyed by family ID.

    source is a path, an open file, or the text itself. Columns are separated by tabs or spaces; lines starting
    with # are skipped, as are any columns after the sixth. family, if given, keeps only that family.
    """
    if hasattr(source, 'read'):
        text = source.read()
    elif isinstance(source, str) and '\n' in source:
        text = source
    else:
        with open(source, encoding='utf-8-sig') as handle:
            text = handle.read()
    rows: Dict[str, List[Person]] = {}
    for number, line in enumerate(io.StringIO(text), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split()
        if len(fields) < 6:
            raise PedigreeError(f'Line {number} has {len(fields)} columns, not the six of a PED file: {line}')
        fam, pid, father, mother, sex, phenotype = fields[:6]
        if family is not None and fam != family:
            continue
        rows.setdefault(fam, []).append(Person(pid, _parent(father), _parent(mother), _sex(sex), _phenotype(phenotype)))
    if family is not None and family not in rows:
        raise PedigreeError(f'There is no family {family} in the PED file')
    return {fam: Pedigree(people, fam) for fam, people in rows.items()}


def pedigree_from_rows(rows, family: str = '') -> Pedigree:
    """
    A pedigree from rows of (person, father, mother, sex, phenotype), or of dicts or pandas rows with the PED column
    names (IndividualID, PaternalID, MaternalID, Sex, Phenotype), as PedGen and PedInterp make them
    """
    people = []
    if hasattr(rows, 'iterrows'):
        rows = [row for _, row in rows.iterrows()]
    for row in rows:
        if not isinstance(row, (tuple, list)):
            pid, father, mother = row['IndividualID'], row['PaternalID'], row['MaternalID']
            sex, phenotype = row['Sex'], row['Phenotype']
            if not family and 'FamilyID' in row:
                family = _id(row['FamilyID'])
        else:
            pid, father, mother, sex, phenotype = row
        people.append(Person(_id(pid), _parent(father), _parent(mother), _sex(_id(sex)), _phenotype(_id(phenotype))))
    return Pedigree(people, family)


def write_ped(pedigree: Pedigree, path_or_file=None) -> str:
    """
    The pedigree as PED text, written to path_or_file too if one is given. Parents PedNet added because they had no line
    in the file get a line of their own; the unknown parents it made up for people with only one parent are left out.
    """
    lines = []
    for p in pedigree.people:
        if p.placeholder:
            continue
        father = p.father if p.father is not None and not pedigree[p.father].placeholder else '0'
        mother = p.mother if p.mother is not None and not pedigree[p.mother].placeholder else '0'
        lines.append('\t'.join([pedigree.family or '0', p.id, father, mother, str(p.sex), str(p.phenotype)]))
    text = '\n'.join(lines) + '\n'
    if path_or_file is not None:
        if hasattr(path_or_file, 'write'):
            path_or_file.write(text)
        else:
            with open(path_or_file, 'w') as handle:
                handle.write(text)
    return text
