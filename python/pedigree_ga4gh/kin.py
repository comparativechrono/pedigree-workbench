"""The Kinship Ontology (KIN): the terms GA4GH Pedigree relationships use.

Every relationship in a GA4GH Pedigree names its relation with a KIN term, for
example ``KIN:027`` *isBiologicalMotherOf*. This module holds the whole of KIN
as published, so that codes and labels are written exactly as the ontology
gives them and can be checked when a file is read.

Source: ``kin.owl`` in https://github.com/GA4GH-Pedigree-Standard/family_history_terminology
at commit 71616ea (16 September 2024), the version behind
http://purl.org/ga4gh/kin.owl. ``KIN:031`` *hasSex* is left out: it links a
person to a sex, not to another person, so it is never a pedigree relationship.

KIN's codes, labels and definitions are from that repository, under the Apache
License, Version 2.0: LICENSE-KIN.txt, beside this file, is its licence.

Earlier drafts of KIN used other codes and labels (for example ``KIN:048``
*isBrokenPartner*, or labels without the final "Of"); :data:`RETIRED` lists the
ones still found in files so that they can be recognised and replaced.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

KIN_IRI = "http://purl.org/ga4gh/kin.owl"
KIN_SOURCE = ("kin.owl, GA4GH-Pedigree-Standard/family_history_terminology "
              "commit 71616ea (2024-09-16)")


@dataclass(frozen=True)
class KinTerm:
    """One KIN relation."""

    id: str                      # "KIN:027"
    label: str                   # "isBiologicalMotherOf"
    parents: Tuple[str, ...]     # broader relations, e.g. ("KIN:003",)
    symmetric: bool              # True when "A rel B" implies "B rel A"
    inverse: Optional[str]       # the KIN code of the inverse relation, if KIN has one
    subject_sex: Optional[str]   # "FEMALE" or "MALE" when the relation implies the subject's sex
    definition: str

    def as_ontology_class(self) -> Dict[str, str]:
        """The ``relation`` object of a GA4GH Pedigree relationship."""
        return {"id": self.id, "label": self.label}


_T = KinTerm

TERMS = {
    'KIN:001': _T('KIN:001', 'isRelativeOf', (), True, None, None,
        'A relation that indicates that a person is connected to another biologically or through a socio-legal relationship.'),
    'KIN:002': _T('KIN:002', 'isBiologicalRelativeOf', ('KIN:001',), True, None, None,
        'A relation that indicates that a person is related to another person biologically.'),
    'KIN:003': _T('KIN:003', 'isBiologicalParentOf', ('KIN:002',), False, 'KIN:032', None,
        'A relation that indicates that a person is the biological parent of another person.'),
    'KIN:004': _T('KIN:004', 'isSpermDonorOf', ('KIN:003',), False, None, 'MALE',
        'A relation between a man who donated his sperm and the child.'),
    'KIN:005': _T('KIN:005', 'isGestationalCarrierOf', ('KIN:001',), False, 'KIN:039', 'FEMALE',
        'A relation between the woman who carried a fertilised egg in her womb and gave birth to a child on behalf of the mother, and the child.'),
    'KIN:006': _T('KIN:006', 'isSurrogateOvumDonorOf', ('KIN:005', 'KIN:038'), False, None, 'FEMALE',
        'A relation between the woman who carried her fertilised egg in her womb and gave birth to a child on behalf of the mother, and the child.'),
    'KIN:007': _T('KIN:007', 'isBiologicalSiblingOf', ('KIN:002',), True, None, None,
        'A relation between two people that have one or both biological parents in common.'),
    'KIN:008': _T('KIN:008', 'isFullsiblingOf', ('KIN:007',), True, None, None,
        'A relation between two people that have both biological parents in common.'),
    'KIN:009': _T('KIN:009', 'isMultipleBirthSiblingOf', ('KIN:008',), True, None, None,
        'A relation between two people born at the same birth.'),
    'KIN:010': _T('KIN:010', 'isMonozygoticMultipleBirthSiblingOf', ('KIN:009',), True, None, None,
        'A relation between two people born at the same birth from a single fertilised ovum that splits.'),
    'KIN:011': _T('KIN:011', 'isPolyzygoticMultipleBirthSiblingOf', ('KIN:009',), True, None, None,
        'A relation between two people born at the same birth from fertilisation of more than two ovums discharged in a single ovarian cycle.'),
    'KIN:012': _T('KIN:012', 'isHalfSiblingOf', ('KIN:007',), True, None, None,
        'A relation between two people that have a single biological parent in common.'),
    'KIN:013': _T('KIN:013', 'isParentalSiblingOf', ('KIN:002',), False, 'KIN:046', None,
        'A relation that indicates that a person is the sibling of a parent of another person.'),
    'KIN:014': _T('KIN:014', 'isCousinOf', ('KIN:002',), True, None, None,
        "A relation between a person and a child of that person's uncle or aunt."),
    'KIN:015': _T('KIN:015', 'isMaternalCousinOf', ('KIN:014',), True, None, None,
        "A relation between a person and a child of that person's mother's sibling."),
    'KIN:016': _T('KIN:016', 'isPaternalCousinOf', ('KIN:014',), True, None, None,
        "A relation between a person and a child of that person's father's sibling."),
    'KIN:017': _T('KIN:017', 'isGrandparentOf', ('KIN:002',), False, 'KIN:036', None,
        "A relation between a person and a child of that person's child."),
    'KIN:018': _T('KIN:018', 'isGreatGrandparentOf', ('KIN:002',), False, 'KIN:047', None,
        "A relation between a person and a child of that person's grandchild."),
    'KIN:019': _T('KIN:019', 'isSocialLegalRelativeOf', ('KIN:001',), True, None, None,
        'A social or legal relationship between two people, for example, an adoptive parent.'),
    'KIN:020': _T('KIN:020', 'isParentFigureOf', ('KIN:019',), False, None, None,
        'A relation between a person who is regarded as having all or some of the characteristics of a parent and the child.'),
    'KIN:021': _T('KIN:021', 'isFosterParentOf', ('KIN:020',), False, None, None,
        "A relation between a person and a child that temporarily enters into his or her family for a period of time, without becoming the child's legal parent."),
    'KIN:022': _T('KIN:022', 'isAdoptiveParentOf', ('KIN:020',), False, None, None,
        'A legal relation between a person and a child that is adopted by that person. The adopted child is given the rights, privileges, and duties of a biological child by the adoptive person.'),
    'KIN:023': _T('KIN:023', 'isStepParentOf', ('KIN:020',), False, None, None,
        "A relation between a person and a child, where the person is married to the father or mother of a child but who is not that child's own father or mother."),
    'KIN:024': _T('KIN:024', 'isSiblingFigureOf', ('KIN:019',), False, None, None,
        'A relation between two people that has all or some of the characteristics of a sibling relationship.'),
    'KIN:025': _T('KIN:025', 'isStepSiblingOf', ('KIN:024',), True, None, None,
        'A relation between children born of two different families who have been joined by marriage, defacto or otherwise, of at least one of their respective parents.'),
    'KIN:026': _T('KIN:026', 'isPartnerOf', ('KIN:019',), True, None, None,
        'A socio-legal relationship between two people who live together and share a common domestic life.'),
    'KIN:027': _T('KIN:027', 'isBiologicalMotherOf', ('KIN:003',), False, None, 'FEMALE',
        'A relation that indicates that a person is the biological mother of another person.'),
    'KIN:028': _T('KIN:028', 'isBiologicalFatherOf', ('KIN:003',), False, None, 'MALE',
        'A relation that indicates that a person is the biological father of another person.'),
    'KIN:029': _T('KIN:029', 'isMitochondrialDonorOf', ('KIN:001',), False, None, 'FEMALE',
        "A relation between a woman that has donated mitochondria and a child. Mitochondrial donation involves removing the nuclear DNA from a woman's ovum containing faulty mitochondria and inserting it into a healthy donor ovum, which has had its nuclear DNA removed."),
    'KIN:030': _T('KIN:030', 'isConsanguineousPartnerOf', ('KIN:002', 'KIN:026'), True, None, None,
        'A socio-legal relationship between two people who live together, share a common domestic life and are closely related biologically (second cousins or closer).'),
    'KIN:032': _T('KIN:032', 'isBiologicalChildOf', ('KIN:002',), False, 'KIN:003', None,
        'A relation that indicates that a person is the biological child of another person.'),
    'KIN:036': _T('KIN:036', 'isGrandchildOf', ('KIN:002',), False, 'KIN:017', None,
        "A relation between a person and a parent of that person's parent."),
    'KIN:038': _T('KIN:038', 'isOvumDonorOf', ('KIN:003',), False, None, 'FEMALE',
        'A relation between a fertile woman who donated an egg to another woman to help her conceive and the child.'),
    'KIN:039': _T('KIN:039', 'hasGestationalCarrier', ('KIN:001',), False, 'KIN:005', None,
        'A relation between the child and a woman who carried a fertilised egg in her womb and gave birth to a child on behalf of the mother.'),
    'KIN:046': _T('KIN:046', 'hasParentalSibling', ('KIN:002',), False, 'KIN:013', None,
        'A relation that indicates that a person has a parental sibling relationship with another person, i.e., the other person is the sibling of a parent.'),
    'KIN:047': _T('KIN:047', 'isGreatGrandchildOf', ('KIN:002',), False, 'KIN:018', None,
        "A relation between a person and a parent of that person's grandparent."),
    'KIN:050': _T('KIN:050', 'isSeparatedPartnerOf', ('KIN:019',), True, None, None,
        'A socio-legal relationship between two people who used to live together and share a common domestic life, but have now separated.'),
    'KIN:051': _T('KIN:051', 'isSeparatedConsanguineousPartnerOf', ('KIN:002', 'KIN:050'), True, None, None,
        'A socio-legal relationship between two people who used to live together, share a common domestic life and are closely related biologically (second cousins or closer), and have now separated.'),
    'KIN:052': _T('KIN:052', 'isMaternalGrandparentOf', ('KIN:017',), False, None, None,
        "A relation between a person and a child of that person's daughter."),
    'KIN:053': _T('KIN:053', 'isPaternalGrandparentOf', ('KIN:017',), False, None, None,
        "A relation between a person and a child of that person's son."),
    'KIN:054': _T('KIN:054', 'isMaternalHalfSiblingOf', ('KIN:012',), True, None, None,
        'A relation between two people that share the same biological mother.'),
    'KIN:055': _T('KIN:055', 'isPaternalHalfSiblingOf', ('KIN:012',), True, None, None,
        'A relation between two people that share the same biological father.'),
    'KIN:056': _T('KIN:056', 'isMaternalStepSiblingOf', ('KIN:025',), False, None, None,
        'A relation between children born of two different families who have been joined by marriage, defacto or otherwise. One is a biological child and the other is a step child of the same woman.'),
    'KIN:057': _T('KIN:057', 'isPaternalStepSiblingOf', ('KIN:025',), False, None, None,
        'A relation between children born of two different families who have been joined by marriage, defacto or otherwise. One is a biological child and the other is a step child of the same man.'),
    'KIN:058': _T('KIN:058', 'isMaternalUncleOf', ('KIN:013',), False, None, 'MALE',
        "A relation between a man and the child of that man's sister."),
    'KIN:059': _T('KIN:059', 'isPaternalUncleOf', ('KIN:013',), False, None, 'MALE',
        "A relation between a man and the child of that man's brother."),
    'KIN:060': _T('KIN:060', 'isMaternalAuntOf', ('KIN:013',), False, None, 'FEMALE',
        "A relation between a woman and the child of that woman's sister."),
    'KIN:061': _T('KIN:061', 'isPaternalAuntOf', ('KIN:013',), False, None, 'FEMALE',
        "A relation between a woman and the child of that woman's brother."),
}


# Labels by which KIN terms are looked up, including skos:altLabel synonyms.
_BY_LABEL: Dict[str, KinTerm] = {t.label.lower(): t for t in TERMS.values()}

# Codes from earlier drafts of KIN that still turn up in files (Open Pedigree
# writes several of them), mapped to (current code, swap). ``swap`` is True when
# the old relation ran the other way, e.g. "child hasBiologicalMother mother"
# becomes "mother isBiologicalMotherOf child". KIN:039 is not here: it is a
# current term (hasGestationalCarrier), even though some tools have used it
# for a sperm donor.
RETIRED: Dict[str, Tuple[str, bool]] = {
    "KIN:033": ("KIN:003", False),  # hasBiologicalChild
    "KIN:034": ("KIN:032", False),  # hasBiologicalParent
    "KIN:035": ("KIN:036", False),  # hasGrandparent
    "KIN:037": ("KIN:017", False),  # hasGrandchild
    "KIN:040": ("KIN:028", True),   # hasBiologicalFather
    "KIN:041": ("KIN:027", True),   # hasBiologicalMother
    "KIN:042": ("KIN:038", True),   # hasOvumDonor
    "KIN:043": ("KIN:006", True),   # hasSurrogateOvumDonor
    "KIN:044": ("KIN:004", True),   # hasSpermDonor
    "KIN:045": ("KIN:047", False),  # hasGreatGrandParent
    "KIN:048": ("KIN:050", False),  # isBrokenPartner
    "KIN:049": ("KIN:051", False),  # isBrokenConsanguineousPartner
}

# Old labels (without "Of", or renamed) mapped to current codes, all in the
# same direction as the current term.
OLD_LABELS: Dict[str, str] = {
    "isrelative": "KIN:001", "isbiologicalrelative": "KIN:002",
    "isbiologicalparent": "KIN:003", "hasbiologicalchild": "KIN:003",
    "isspermdonor": "KIN:004", "isgestationalcarrier": "KIN:005",
    "issurrogateovumdonor": "KIN:006", "isbiologicalsibling": "KIN:007",
    "isfullsibling": "KIN:008", "istwin": "KIN:009", "istwinof": "KIN:009",
    "ismonozygotictwin": "KIN:010", "ismonozygotictwinof": "KIN:010",
    "ispolyzygotictwin": "KIN:011", "ispolyzygotictwinof": "KIN:011",
    "isdizygoticmultiplebirthsiblingof": "KIN:011", "isdizygotictwinof": "KIN:011",
    "ishalfsibling": "KIN:012", "isparentalsibling": "KIN:013",
    "iscousin": "KIN:014", "ismaternalcousin": "KIN:015", "ispaternalcousin": "KIN:016",
    "isgrandparent": "KIN:017", "hasgrandchild": "KIN:017",
    "isgreatgrandparent": "KIN:018", "issociallegalrelative": "KIN:019",
    "isparentfigure": "KIN:020", "isfosterparent": "KIN:021",
    "isadoptiveparent": "KIN:022", "isstepparent": "KIN:023",
    "issiblingfigure": "KIN:024", "isstepsibling": "KIN:025",
    "ispartner": "KIN:026", "isbiologicalmother": "KIN:027",
    "isbiologicalfather": "KIN:028", "ismitochondrialdonor": "KIN:029",
    "isconsanguineouspartner": "KIN:030", "isbiologicalchild": "KIN:032",
    "hasbiologicalparent": "KIN:032", "isgrandchild": "KIN:036",
    "hasgrandparent": "KIN:036", "isovumdonor": "KIN:038",
    "hasgreatgrandparent": "KIN:047",
    "isbrokenpartner": "KIN:050", "isbrokenconsanguineouspartner": "KIN:051",
}

# The terms the converters use, by name.
BIOLOGICAL_PARENT = "KIN:003"
SPERM_DONOR = "KIN:004"
GESTATIONAL_CARRIER = "KIN:005"
SURROGATE_OVUM_DONOR = "KIN:006"
MULTIPLE_BIRTH_SIBLING = "KIN:009"
MONOZYGOTIC_MULTIPLE_BIRTH_SIBLING = "KIN:010"
POLYZYGOTIC_MULTIPLE_BIRTH_SIBLING = "KIN:011"
HALF_SIBLING = "KIN:012"
PARENT_FIGURE = "KIN:020"
FOSTER_PARENT = "KIN:021"
ADOPTIVE_PARENT = "KIN:022"
STEP_PARENT = "KIN:023"
PARTNER = "KIN:026"
BIOLOGICAL_MOTHER = "KIN:027"
BIOLOGICAL_FATHER = "KIN:028"
MITOCHONDRIAL_DONOR = "KIN:029"
CONSANGUINEOUS_PARTNER = "KIN:030"
BIOLOGICAL_CHILD = "KIN:032"
OVUM_DONOR = "KIN:038"
HAS_GESTATIONAL_CARRIER = "KIN:039"
SEPARATED_PARTNER = "KIN:050"
SEPARATED_CONSANGUINEOUS_PARTNER = "KIN:051"


def get(code_or_label: str) -> KinTerm:
    """Return the KIN term for a code (``"KIN:027"``) or a current label.

    Raises ``KeyError`` with an explanation for anything that is not a current
    KIN term, including retired codes and old labels (use :func:`modernise`
    to translate those).
    """
    key = (code_or_label or "").strip()
    if key in TERMS:
        return TERMS[key]
    hit = _BY_LABEL.get(key.lower())
    if hit is not None:
        return hit
    if key in RETIRED:
        new, swap = RETIRED[key]
        raise KeyError("{} is a retired KIN code; the current term is {} ({}){}".format(
            key, new, TERMS[new].label, ", with the two people the other way round" if swap else ""))
    if key.lower() in OLD_LABELS:
        new = TERMS[OLD_LABELS[key.lower()]]
        raise KeyError("{!r} is not a current KIN label; the current term is {} ({})".format(
            key, new.id, new.label))
    raise KeyError("{!r} is not a KIN term".format(code_or_label))


def exists(code: str) -> bool:
    return code in TERMS


def relation(code_or_label: str) -> Dict[str, str]:
    """The ``{"id", "label"}`` object for a relationship's ``relation``."""
    return get(code_or_label).as_ontology_class()


def is_a(code: str, ancestor: str) -> bool:
    """True if ``code`` is ``ancestor`` or a narrower relation beneath it."""
    seen = set()
    stack = [code]
    while stack:
        c = stack.pop()
        if c == ancestor:
            return True
        if c in seen or c not in TERMS:
            continue
        seen.add(c)
        stack.extend(TERMS[c].parents)
    return False


def modernise(code: str, label: str = "") -> Optional[Tuple[KinTerm, bool]]:
    """Best current term for a code and label found in an older file.

    Returns ``(term, swap)``, where ``swap`` means the two people must change
    places, or ``None`` when neither the code nor the label can be placed.
    A current code wins when its label agrees (or there is no label);
    otherwise the label decides, so a relationship written as ``KIN:039``
    with the label *isSpermDonorOf* becomes ``KIN:004``.
    """
    code = (code or "").strip()
    norm = (label or "").strip().lower()
    by_label = _BY_LABEL.get(norm) or (TERMS.get(OLD_LABELS[norm]) if norm in OLD_LABELS else None)
    if code in TERMS:
        current = TERMS[code]
        if not norm or by_label is None or by_label.id == current.id:
            return current, False
        return by_label, False
    if code in RETIRED:
        new, swap = RETIRED[code]
        return TERMS[new], swap
    if by_label is not None:
        return by_label, False
    return None
