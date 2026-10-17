"""A family as the converters see it, and the two GA4GH files made from it.

A :class:`Kindred` holds the members of a family and the relationships between
them, independently of any file format. Each converter fills one in from its
own input (a Pedigree Studio drawing, a PED file, an Abusua session) and this
module writes it out, so every tool produces exactly the same GA4GH:

* :func:`to_ga4gh_pedigree` writes the GA4GH Pedigree (Phenopackets form):
  one Phenopacket per member plus KIN relationships.
* :func:`to_phenopackets_family` writes a Phenopackets v2 ``Family``: the
  proband's Phenopacket, Phenopackets for relatives with findings, and the
  PED-style pedigree of everyone.

:func:`from_document` reads either file (or a single Phenopacket or a Cohort)
back into a Kindred.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import kin, ontology
from . import pedigree as ped
from . import phenopackets as pp
from .schema import camelise

DISEASE = "disease"
PHENOTYPE = "phenotype"

# Relations through which a person is a child's genetic mother or father, for
# the PED-style pedigree of a Phenopackets Family.
_GENETIC_MOTHER = {kin.BIOLOGICAL_MOTHER, kin.OVUM_DONOR, kin.SURROGATE_OVUM_DONOR}
_GENETIC_FATHER = {kin.BIOLOGICAL_FATHER, kin.SPERM_DONOR}
_FULL_SIBLINGS = {"KIN:008", kin.MULTIPLE_BIRTH_SIBLING, kin.MONOZYGOTIC_MULTIPLE_BIRTH_SIBLING,
                  kin.POLYZYGOTIC_MULTIPLE_BIRTH_SIBLING}


@dataclass
class Term:
    """A disease or phenotype. ``id`` is empty until the term has been matched to an ontology."""

    label: str
    id: str = ""
    kind: str = DISEASE            # DISEASE or PHENOTYPE
    excluded: bool = False         # looked for and found to be absent
    onset: Optional[str] = None    # ISO 8601 age, e.g. "P42Y"
    raw: Optional[Dict] = None     # the Disease or PhenotypicFeature this was read from, if any,
                                   # so that severity, evidence and the like survive a round trip

    @property
    def matched(self) -> bool:
        return ontology.is_curie(ontology.tidy_curie(self.id))


@dataclass
class Member:
    """One person in the family."""

    id: str
    sex: str = "UNKNOWN_SEX"
    vital_status: Optional[str] = None        # ALIVE, DECEASED, UNKNOWN_STATUS or None
    affected: Optional[bool] = None           # True, False, or None for not known
    terms: List[Term] = field(default_factory=list)
    index: bool = False                       # proband, consultand or first person tested
    date_of_birth: Optional[str] = None       # timestamp or full date
    karyotypic_sex: Optional[str] = None
    alternate_ids: List[str] = field(default_factory=list)
    packet_id: Optional[str] = None           # the Phenopacket id, when read from a file
    extra: Dict = field(default_factory=dict)  # other Phenopacket fields kept from a file


@dataclass
class Relation:
    """``individual`` *kin* ``relative``, e.g. ``Relation("MOTHER", "KIN:027", "CHILD")``."""

    individual: str
    kin: str
    relative: str


@dataclass
class Kindred:
    id: str
    members: List[Member] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    narrative: Optional[str] = None
    date: Optional[str] = None                # YYYY, YYYY-MM or YYYY-MM-DD
    status: Optional[str] = None
    versions: Dict[str, str] = field(default_factory=dict)   # ontology prefix -> release
    files: List[Dict] = field(default_factory=list)          # Family-level files, kept on round trips

    # -- lookups --------------------------------------------------------------
    def member(self, member_id: str) -> Optional[Member]:
        for m in self.members:
            if m.id == member_id:
                return m
        return None

    def ids(self) -> List[str]:
        return [m.id for m in self.members]

    def relations_to(self, relative_id: str) -> List[Relation]:
        return [r for r in self.relations if r.relative == relative_id]

    def genetic_parents(self, child_id: str, _via_sibling: bool = True) -> Tuple[Optional[str], Optional[str], List[str]]:
        """``(father, mother, notes)`` for the PED-style pedigree.

        Fathers come from isBiologicalFatherOf and isSpermDonorOf, mothers from
        isBiologicalMotherOf, isOvumDonorOf and isSurrogateOvumDonorOf. A
        parent recorded only as isBiologicalParentOf is placed by sex; if their
        sex is not known they fill whichever place is still empty, and a note
        says so.
        """
        father = mother = None
        notes: List[str] = []
        unplaced: List[str] = []
        for r in self.relations_to(child_id):
            parent = self.member(r.individual)
            if parent is None:
                continue
            if r.kin in _GENETIC_FATHER:
                if father and father != parent.id:
                    notes.append("{} has two fathers ({}, {}); the PED-style pedigree uses {}".format(
                        child_id, father, parent.id, father))
                    continue
                father = parent.id
            elif r.kin in _GENETIC_MOTHER:
                if mother and mother != parent.id:
                    notes.append("{} has two mothers ({}, {}); the PED-style pedigree uses {}".format(
                        child_id, mother, parent.id, mother))
                    continue
                mother = parent.id
            elif r.kin == kin.BIOLOGICAL_PARENT:
                if parent.sex == "MALE" and not father:
                    father = parent.id
                elif parent.sex == "FEMALE" and not mother:
                    mother = parent.id
                else:
                    unplaced.append(parent.id)
        for pid in unplaced:
            if pid in (father, mother):
                continue
            if not father and mother:
                father = pid
                notes.append("{}'s parent {} has no recorded sex; listed as the father because the "
                             "mother is {}".format(child_id, pid, mother))
            elif not mother and father:
                mother = pid
                notes.append("{}'s parent {} has no recorded sex; listed as the mother because the "
                             "father is {}".format(child_id, pid, father))
            else:
                notes.append("{}'s parent {} has no recorded sex, so the PED-style pedigree cannot say "
                             "whether they are the father or the mother; the GA4GH Pedigree records "
                             "them as a biological parent".format(child_id, pid))
        if not father and not mother and _via_sibling:
            # full siblings and twins share parents, so the reduced form may give them only once
            for r in self.relations:
                if r.kin in _FULL_SIBLINGS and child_id in (r.individual, r.relative):
                    other = r.relative if r.individual == child_id else r.individual
                    f, m, _ = self.genetic_parents(other, _via_sibling=False)
                    if f or m:
                        notes.append("{}'s parents taken from their {} {}".format(
                            child_id, "twin" if r.kin != kin.TERMS["KIN:008"].id else "sibling", other))
                        return f, m, notes
        return father, mother, notes

    def ancestors(self, member_id: str) -> Set[str]:
        """Everyone ``member_id`` descends from biologically."""
        out: Set[str] = set()
        stack = [member_id]
        while stack:
            cur = stack.pop()
            for r in self.relations_to(cur):
                if kin.is_a(r.kin, kin.BIOLOGICAL_PARENT) and r.individual not in out:
                    out.add(r.individual)
                    stack.append(r.individual)
        return out

    def consanguineous(self, a: str, b: str) -> bool:
        """True if ``a`` and ``b`` are recorded as consanguineous partners or share an ancestor."""
        for r in self.relations:
            if {r.individual, r.relative} == {a, b} and r.kin in (
                    kin.CONSANGUINEOUS_PARTNER, kin.SEPARATED_CONSANGUINEOUS_PARTNER):
                return True
        anc_a, anc_b = self.ancestors(a), self.ancestors(b)
        return bool(anc_a & anc_b) or a in anc_b or b in anc_a


# -- writing -------------------------------------------------------------------

def _term_entries(member: Member, warnings: List[str]) -> Tuple[List[Dict], List[Dict]]:
    diseases, features = [], []
    seen = set()
    for t in member.terms:
        if not t.matched:
            warnings.append("{}: '{}' was left out because it has no ontology term; match it to "
                            "{} first".format(member.id, t.label or t.id,
                                              "Mondo" if t.kind == DISEASE else "the HPO"))
            continue
        key = (ontology.tidy_curie(t.id), t.kind, t.excluded)
        if key in seen:
            continue
        seen.add(key)
        try:
            if t.kind == PHENOTYPE:
                entry = pp.phenotypic_feature(t.id, t.label, excluded=t.excluded, onset=t.onset)
                term_key = "type"
            else:
                entry = pp.disease(t.id, t.label, excluded=t.excluded, onset=t.onset)
                term_key = "term"
        except ValueError as exc:
            warnings.append("{}: '{}' was left out: {}".format(member.id, t.label or t.id, exc))
            continue
        if t.raw:
            kept = copy.deepcopy(t.raw)
            kept[term_key] = entry[term_key]
            kept.pop("excluded", None)
            if t.excluded:
                kept["excluded"] = True
            if "onset" in entry and "onset" not in kept:
                kept["onset"] = entry["onset"]
            entry = kept
        (features if t.kind == PHENOTYPE else diseases).append(entry)
    return diseases, features


def member_phenopacket(k: Kindred, m: Member, *, created_by: str, created: Optional[str],
                       warnings: List[str]) -> Dict:
    """The Phenopacket for one member."""
    dob = m.date_of_birth
    if dob and pp.date_to_timestamp(dob) is None:
        warnings.append("{}: date of birth '{}' left out; Phenopackets need a full date".format(m.id, dob))
        dob = None
    subject = pp.individual(m.id, sex=m.sex, vital=m.vital_status, date_of_birth=dob,
                           karyotypic_sex=m.karyotypic_sex, alternate_ids=m.alternate_ids)
    kept = m.extra.get("subject") or {}
    for key in ("timeAtLastEncounter", "gender", "taxonomy"):
        if kept.get(key):
            subject[key] = copy.deepcopy(kept[key])
    if kept.get("vitalStatus") and "vitalStatus" in subject:
        # keep the time and cause of death; the status itself comes from the Member
        detail = copy.deepcopy(kept["vitalStatus"])
        detail["status"] = subject["vitalStatus"]["status"]
        subject["vitalStatus"] = detail
    diseases, features = _term_entries(m, warnings)
    packet_id = m.packet_id or "{}-{}".format(k.id, m.id)
    return pp.phenopacket(packet_id, subject, diseases=diseases, phenotypic_features=features,
                          created_by=created_by, versions=k.versions, created=created, extra=m.extra)


def _relationships(k: Kindred, warnings: List[str]) -> List[Dict]:
    ids = set(k.ids())
    out, seen = [], set()
    for r in k.relations:
        if r.individual not in ids or r.relative not in ids:
            warnings.append("relationship {} {} {} left out: both people must be in the pedigree".format(
                r.individual, r.kin, r.relative))
            continue
        try:
            term = kin.get(r.kin)
        except KeyError as exc:
            warnings.append("relationship {} {} {} left out: {}".format(r.individual, r.kin, r.relative, exc))
            continue
        key = (r.individual, term.id, r.relative)
        mirror = (r.relative, term.id, r.individual)
        if key in seen or (term.symmetric and mirror in seen):
            continue
        seen.add(key)
        out.append(ped.relationship(r.individual, term.id, r.relative))
    return out


def to_ga4gh_pedigree(k: Kindred, *, created_by: str, created: Optional[str] = None) -> Tuple[Dict, List[str]]:
    """The GA4GH Pedigree (Phenopackets form) for a Kindred, and any warnings."""
    warnings: List[str] = []
    if not k.members:
        raise ValueError("the family has nobody in it")
    individuals = [member_phenopacket(k, m, created_by=created_by, created=created, warnings=warnings)
                   for m in k.members]
    doc = ped.pedigree(k.id, individuals=individuals, relationships=_relationships(k, warnings),
                       index_patients=[m.id for m in k.members if m.index], narrative=k.narrative,
                       date=k.date or _date.today().isoformat(), status=k.status)
    return doc, _unique(warnings)


def _affected_status(m: Member) -> str:
    if m.affected is True:
        return "AFFECTED"
    if m.affected is False:
        return "UNAFFECTED"
    if any(t.matched and not t.excluded for t in m.terms):
        return "AFFECTED"
    return "MISSING"


def choose_proband(k: Kindred, proband_id: Optional[str] = None) -> Tuple[Member, List[str]]:
    """The Family's proband: the one asked for, else the first index patient,
    else the first affected member, else the first member."""
    notes: List[str] = []
    if proband_id:
        m = k.member(proband_id)
        if m is not None:
            return m, notes
        notes.append("proband {} is not in the family".format(proband_id))
    index = [m for m in k.members if m.index]
    if index:
        if len(index) > 1:
            notes.append("{} index patients are marked; a Phenopackets Family has one proband, so {} "
                         "is used".format(len(index), index[0].id))
        return index[0], notes
    affected = [m for m in k.members if _affected_status(m) == "AFFECTED"]
    if affected:
        notes.append("no proband is marked, so the first affected person, {}, is used".format(affected[0].id))
        return affected[0], notes
    notes.append("no proband is marked and nobody is affected, so {} is used as the proband".format(
        k.members[0].id))
    return k.members[0], notes


def to_phenopackets_family(k: Kindred, *, created_by: str, created: Optional[str] = None,
                           proband_id: Optional[str] = None) -> Tuple[Dict, List[str]]:
    """The Phenopackets v2 Family for a Kindred, and any warnings."""
    warnings: List[str] = []
    if not k.members:
        raise ValueError("the family has nobody in it")
    proband, notes = choose_proband(k, proband_id)
    warnings.extend(notes)
    packets = {m.id: member_phenopacket(k, m, created_by=created_by, created=created, warnings=warnings)
               for m in k.members}
    relatives = []
    for m in k.members:
        if m.id == proband.id:
            continue
        pk = packets[m.id]
        if pk.get("phenotypicFeatures") or pk.get("diseases") or any(
                pk.get(x) for x in ("measurements", "biosamples", "interpretations", "medicalActions", "files")):
            relatives.append(pk)
    persons = []
    for m in k.members:
        father, mother, pnotes = k.genetic_parents(m.id)
        warnings.extend(pnotes)
        persons.append(pp.ped_person(k.id, m.id, paternal_id=father or "0", maternal_id=mother or "0",
                                     sex=m.sex, affected_status=_affected_status(m)))
    father, mother, _ = k.genetic_parents(proband.id)
    consang = bool(father and mother and k.consanguineous(father, mother))
    doc = pp.family(k.id, proband=packets[proband.id], relatives=relatives, persons=persons,
                    consanguineous_parents=consang, created_by=created_by, versions=k.versions,
                    created=created, files=k.files)
    return doc, _unique(warnings)


def _unique(items: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(items))


# -- reading -------------------------------------------------------------------

def detect(doc: Dict) -> str:
    """What a parsed JSON document is: ``"pedigree"`` (GA4GH Pedigree),
    ``"family"``, ``"cohort"``, ``"phenopacket"`` or ``"unknown"``.

    This only looks at the shape; :mod:`pedigree_ga4gh.legacy` recognises the
    older, non-standard files our tools used to write.
    """
    if not isinstance(doc, dict):
        return "unknown"
    if "relationships" in doc or "individuals" in doc or "indexPatients" in doc or "index_patients" in doc:
        return "pedigree"
    if "proband" in doc or "pedigree" in doc or "relatives" in doc:
        return "family"
    if "members" in doc:
        return "cohort"
    if "subject" in doc or "phenotypicFeatures" in doc or "phenotypic_features" in doc or "diseases" in doc:
        return "phenopacket"
    return "unknown"


def _versions_from(metadata: Dict, into: Dict[str, str]) -> None:
    for res in (metadata or {}).get("resources", []) or []:
        p = res.get("namespacePrefix")
        v = res.get("version")
        if p and v and v != ontology.UNKNOWN_VERSION:
            into.setdefault(p, v)


def _member_from_packet(packet: Dict, versions: Dict[str, str]) -> Member:
    subj = packet.get("subject") or {}
    m = Member(id=str(subj.get("id", "")))
    m.packet_id = packet.get("id") or None
    m.sex = subj.get("sex") or "UNKNOWN_SEX"
    vs = subj.get("vitalStatus") or {}
    m.vital_status = vs.get("status") or None
    m.date_of_birth = subj.get("dateOfBirth") or None
    m.karyotypic_sex = subj.get("karyotypicSex") or None
    m.alternate_ids = list(subj.get("alternateIds") or [])
    for d in packet.get("diseases") or []:
        t = d.get("term") or {}
        m.terms.append(Term(label=t.get("label", ""), id=t.get("id", ""), kind=DISEASE,
                            excluded=bool(d.get("excluded")), onset=_age(d.get("onset")),
                            raw=copy.deepcopy(d)))
    for f in packet.get("phenotypicFeatures") or []:
        t = f.get("type") or {}
        m.terms.append(Term(label=t.get("label", ""), id=t.get("id", ""), kind=PHENOTYPE,
                            excluded=bool(f.get("excluded")), onset=_age(f.get("onset")),
                            raw=copy.deepcopy(f)))
    if any(not t.excluded for t in m.terms):
        m.affected = True
    keep = {k: copy.deepcopy(v) for k, v in packet.items()
            if k in ("measurements", "biosamples", "interpretations", "medicalActions", "files") and v}
    md = packet.get("metaData") or {}
    md_keep = {k: copy.deepcopy(md[k]) for k in ("submittedBy", "updates", "externalReferences") if md.get(k)}
    if md_keep:
        keep["metaData"] = md_keep
    subj_keep = {k: copy.deepcopy(subj[k]) for k in ("timeAtLastEncounter", "gender", "taxonomy", "vitalStatus")
                 if subj.get(k)}
    if subj_keep:
        keep["subject"] = subj_keep
    m.extra = keep
    _versions_from(md, versions)
    return m


def _age(time_element) -> Optional[str]:
    if isinstance(time_element, dict):
        age = time_element.get("age")
        if isinstance(age, dict):
            return age.get("iso8601duration")
    return None


def from_ga4gh_pedigree(doc: Dict) -> Tuple[Kindred, List[str]]:
    data = camelise(doc, "GA4GHPedigree")
    warnings: List[str] = []
    k = Kindred(id=str(data.get("id") or "pedigree"), narrative=data.get("narrative"),
                date=data.get("date"), status=data.get("status"))
    for i, packet in enumerate(data.get("individuals") or []):
        if not isinstance(packet, dict):
            continue
        m = _member_from_packet(packet, k.versions)
        if not m.id:
            warnings.append("individuals[{}] has no subject id and was skipped".format(i))
            continue
        if k.member(m.id):
            warnings.append("{} appears twice; the second entry was skipped".format(m.id))
            continue
        k.members.append(m)
    for pid in data.get("indexPatients") or []:
        m = k.member(pid)
        if m is None:
            warnings.append("index patient {} is not among the individuals".format(pid))
        else:
            m.index = True
    for i, r in enumerate(data.get("relationships") or []):
        a, b = r.get("individualId"), r.get("relativeId")
        rel = r.get("relation") or {}
        found = kin.modernise(rel.get("id", ""), rel.get("label", ""))
        if found is None:
            warnings.append("relationships[{}]: {} is not a KIN term and was skipped".format(i, rel))
            continue
        term, swap = found
        if term.id != rel.get("id") or swap:
            warnings.append("relationships[{}]: {} '{}' read as {} '{}'{}".format(
                i, rel.get("id"), rel.get("label"), term.id, term.label,
                " with the two people swapped" if swap else ""))
        if swap:
            a, b = b, a
        k.relations.append(Relation(a, term.id, b))
    return k, warnings


def from_phenopackets_family(doc: Dict) -> Tuple[Kindred, List[str]]:
    data = camelise(doc, "Family")
    warnings: List[str] = []
    k = Kindred(id=str(data.get("id") or "family"))
    _versions_from(data.get("metaData") or {}, k.versions)
    k.files = copy.deepcopy(data.get("files") or [])
    persons = ((data.get("pedigree") or {}).get("persons")) or []
    for p in persons:
        iid = str(p.get("individualId", ""))
        if not iid or k.member(iid):
            continue
        status = p.get("affectedStatus") or "MISSING"
        k.members.append(Member(id=iid, sex=p.get("sex") or "UNKNOWN_SEX",
                                affected=True if status == "AFFECTED" else False if status == "UNAFFECTED" else None))
    for p in persons:
        iid = str(p.get("individualId", ""))
        for key, code in (("paternalId", kin.BIOLOGICAL_FATHER), ("maternalId", kin.BIOLOGICAL_MOTHER)):
            parent = str(p.get(key) or "0")
            if parent in ("0", ""):
                continue
            if k.member(parent) is None:
                warnings.append("{} of {} is {}, who is not in the pedigree".format(key, iid, parent))
                continue
            k.relations.append(Relation(parent, code, iid))
    packets = []
    if isinstance(data.get("proband"), dict):
        packets.append((data["proband"], True))
    for rel in data.get("relatives") or []:
        if isinstance(rel, dict):
            packets.append((rel, False))
    for packet, is_proband in packets:
        m = _member_from_packet(packet, k.versions)
        existing = k.member(m.id)
        if existing is None:
            warnings.append("{} has a Phenopacket but is not in the pedigree".format(m.id))
            k.members.append(m)
            existing = m
        else:
            affected = existing.affected
            existing.terms, existing.extra, existing.packet_id = m.terms, m.extra, m.packet_id
            existing.vital_status, existing.date_of_birth = m.vital_status, m.date_of_birth
            existing.karyotypic_sex, existing.alternate_ids = m.karyotypic_sex, m.alternate_ids
            if m.sex != "UNKNOWN_SEX":
                existing.sex = m.sex
            existing.affected = affected if affected is not None else m.affected
        if is_proband:
            existing.index = True
    if data.get("consanguinousParents"):
        prob = next((m for m in k.members if m.index), None)
        if prob:
            father, mother, _ = k.genetic_parents(prob.id)
            if father and mother and not k.consanguineous(father, mother):
                k.relations.append(Relation(father, kin.CONSANGUINEOUS_PARTNER, mother))
    return k, warnings


def from_phenopackets(packets: Iterable[Dict], kindred_id: str = "cohort") -> Tuple[Kindred, List[str]]:
    """A Kindred of unrelated people, from standalone Phenopackets or a Cohort's members."""
    k = Kindred(id=kindred_id)
    warnings: List[str] = []
    for packet in packets:
        m = _member_from_packet(camelise(packet, "Phenopacket"), k.versions)
        if not m.id or k.member(m.id):
            warnings.append("a Phenopacket with a missing or repeated subject id was skipped")
            continue
        k.members.append(m)
    return k, warnings


def from_document(doc: Dict) -> Tuple[Kindred, List[str]]:
    """Read any of the four document kinds into a Kindred."""
    kind = detect(doc)
    if kind == "pedigree":
        return from_ga4gh_pedigree(doc)
    if kind == "family":
        return from_phenopackets_family(doc)
    if kind == "cohort":
        return from_phenopackets(doc.get("members") or [], str(doc.get("id") or "cohort"))
    if kind == "phenopacket":
        return from_phenopackets([doc], str(doc.get("id") or "phenopacket"))
    raise ValueError("this is not a GA4GH Pedigree, a Phenopackets Family, Cohort or Phenopacket")
