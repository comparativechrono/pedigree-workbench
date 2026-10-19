"""GA4GH pedigrees, read into the same pedigrees as PED files: the GA4GH Pedigree, in which each person is a Phenopacket
and the family is given by KIN relationships (as studio2ga4gh, PedGen and PedInterp write it), and the Phenopackets
Family, whose pedigree is a PED file in JSON. They are read with pedigree-ga4gh, the GA4GH implementation the lab's
tools share, so parents are found as they are everywhere else: a sperm donor counts as a father, an ovum donor as a
mother, and an adoptive parent as neither.

A GA4GH Pedigree says who is affected only through each person's conditions (their diseases and phenotypic features).
Someone with the condition is affected, and someone with it marked as excluded (looked for, and not found) is
unaffected. Everyone else has no record of it. They are taken as unaffected if no one in the file is marked as not
having the condition, as in the files that studio2ga4gh writes from drawings, which record only the affected; and as
of unknown phenotype if anyone is, as in the files that PedGen and PedInterp write, which record both. The pedigree's
notes say which; unrecorded overrides it.
"""
from typing import Dict, List, Optional, Tuple

from .pedigree import AFFECTED, FEMALE, MALE, UNAFFECTED, UNKNOWN, UNKNOWN_SEX, Pedigree, PedigreeError, Person

_SEXES = {'MALE': MALE, 'FEMALE': FEMALE}
UNRECORDED = ('unaffected', 'unknown')


def _document(source):
    """The parsed JSON document from a path, an open file, its text, or the document itself"""
    import pedigree_ga4gh
    if isinstance(source, dict):
        return source
    if hasattr(source, 'read'):
        text = source.read()
    elif isinstance(source, str) and source.lstrip().startswith('{'):
        text = source
    else:
        with open(source, encoding='utf-8-sig') as handle:
            text = handle.read()
    try:
        doc = pedigree_ga4gh.loads(text)
    except ValueError as error:
        raise PedigreeError(f'This is not a JSON file: {error}')
    if not isinstance(doc, dict):
        raise PedigreeError('This is not a GA4GH Pedigree or a Phenopackets Family, each of which is a JSON object')
    return doc


def _condition_key(term) -> str:
    return (term.id or term.label or '').strip()


def conditions(source) -> List[Tuple[str, str]]:
    """The conditions named in a GA4GH Pedigree or Phenopackets Family, as (id, label), in the order first met"""
    import pedigree_ga4gh
    kindred, _ = pedigree_ga4gh.from_document(_document(source))
    found = {}
    for member in kindred.members:
        for term in member.terms:
            found.setdefault(_condition_key(term), (term.id, term.label))
    return list(found.values())


def read_ga4gh(source, family: Optional[str] = None, condition: Optional[str] = None,
               unrecorded: Optional[str] = None) -> Dict[str, Pedigree]:
    """
    Reads a GA4GH Pedigree or a Phenopackets Family into a pedigree, keyed by its family ID, as read_ped reads a PED
    file. Older forms of these files, and the draft of version 1 of the standard, are refused, with how to upgrade.

    source is a path, an open file, the JSON text, or the document already parsed. family, if given, must be the
    document's ID. condition chooses the condition that makes someone affected, by its ontology ID or its label, when
    the file names more than one; if it names one, that is the one, and if it names several and none is chosen,
    having any of them makes someone affected (and a note says so). unrecorded, 'unaffected' or 'unknown', is what
    to take the people with no record of the condition to be (see the module's description for the default). A
    Phenopackets Family's own affected status is used, unless a condition is chosen.
    """
    import pedigree_ga4gh
    if unrecorded is not None and unrecorded not in UNRECORDED:
        raise PedigreeError(f"unrecorded must be 'unaffected' or 'unknown', not {unrecorded!r}")
    doc = _document(source)
    old = pedigree_ga4gh.identify_legacy(doc)
    if old is not None:
        how = ('Upgrade it first with: pedigree-ga4gh upgrade FILE' if old.upgradable
               else 'It cannot be upgraded, as it is a draft no tool writes any more')
        raise PedigreeError(f'This is {old.description}, not a GA4GH Pedigree or Phenopackets Family as the standard '
                            f'has them. {how}')
    kind = pedigree_ga4gh.detect(doc)
    if kind not in ('pedigree', 'family'):
        raise PedigreeError(f'This is a Phenopackets {kind}, which has no pedigree: PedNet reads a GA4GH Pedigree or '
                            'a Phenopackets Family' if kind in ('cohort', 'phenopacket')
                            else 'This is not a GA4GH Pedigree or a Phenopackets Family')
    kindred, read_notes = pedigree_ga4gh.from_document(doc)
    name = str(kindred.id or '')
    if family is not None and family != name:
        raise PedigreeError(f'There is no family {family} in the file: its family is {name}')
    notes: List[str] = list(read_notes)

    # which condition makes someone affected
    named = {}
    for member in kindred.members:
        for term in member.terms:
            named.setdefault(_condition_key(term), term.label or term.id)
    chosen = None
    if condition is not None:
        want = condition.strip().lower()
        chosen = {key for key, label in named.items() if want in (key.lower(), (label or '').lower())}
        if not chosen:
            names = '; '.join(f'{label} ({key})' if key != label else key for key, label in named.items()) or 'none'
            raise PedigreeError(f'No one in the file has the condition {condition}. The conditions it names: {names}')
    elif len(named) > 1:
        listed = ', '.join(named.values())
        if kind == 'pedigree':
            notes.append(f'The file names several conditions ({listed}): anyone with any of them is taken as '
                         'affected. Choose one with --condition to look at it alone')
        else:
            notes.append(f"The Family's own affected status is used. Its people's conditions ({listed}) can be "
                         'looked at one at a time with --condition')
    by_terms = kind == 'pedigree' or condition is not None

    def recorded(member) -> Optional[int]:
        terms = [t for t in member.terms if chosen is None or _condition_key(t) in chosen]
        if any(not t.excluded for t in terms):
            return AFFECTED
        if terms:
            return UNAFFECTED
        return None

    statuses = {m.id: recorded(m) for m in kindred.members} if by_terms else {}
    if by_terms:
        explicit = any(s == UNAFFECTED for s in statuses.values())
        taken = unrecorded or ('unknown' if explicit else 'unaffected')
        missing = [pid for pid, s in statuses.items() if s is None]
        what = ' or '.join(named[k] for k in chosen) if chosen else 'the condition'
        if missing:
            if unrecorded:
                why = 'as asked'
            elif explicit:
                why = 'as the file marks others as not having it'
            else:
                why = 'as the file records only the affected'
            notes.append(f'{len(missing)} people with no record of {what} are taken as '
                         f'{"unaffected" if taken == "unaffected" else "of unknown phenotype"}, {why}')
        fill = UNAFFECTED if taken == 'unaffected' else UNKNOWN
        statuses = {pid: (fill if s is None else s) for pid, s in statuses.items()}

    people = []
    for member in kindred.members:
        father, mother, parent_notes = kindred.genetic_parents(member.id)
        notes.extend(n for n in parent_notes if n not in notes)
        if by_terms:
            phenotype = statuses[member.id]
        else:
            phenotype = {True: AFFECTED, False: UNAFFECTED}.get(member.affected, UNKNOWN)
        people.append(Person(str(member.id), father, mother, _SEXES.get(member.sex, UNKNOWN_SEX), phenotype))
    if not people:
        raise PedigreeError('There are no people in the file')
    pedigree = Pedigree(people, name)
    pedigree.notes[:0] = notes
    return {name: pedigree}
