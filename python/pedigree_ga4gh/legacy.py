"""Recognise and upgrade files written by earlier versions of our tools.

Before this package existed, studio2ga4gh (up to 0.3) and abusua2ga4gh (up to
0.2) each wrote GA4GH files their own way, and neither was correct. Those
files can still be opened: :func:`upgrade` rewrites one in the standard form
and lists every change it made. Nothing is guessed: a condition stored with an
empty ontology id keeps its label and empty id, and is listed in ``todo`` so
that it can be matched to an ontology term.

What each older form got wrong:

studio2ga4gh up to 0.3, GA4GH Pedigree
    The conceptual model written straight out as JSON: people with ``sex``,
    ``deceased`` and ``affected`` on them and relationships with ``individual``
    and ``relative``. Neither GA4GH implementation looks like this.
abusua2ga4gh up to 0.2, GA4GH Pedigree
    Diseases inside ``subject``, ``name`` in ``subject``, a ``description`` on
    relationships, no ``metaData`` in the Phenopackets, and ``KIN:039`` for a
    sperm donor (KIN:039 is *hasGestationalCarrier*; a sperm donor is KIN:004).
Both, Phenopackets
    Conditions with an empty ontology id; studio2ga4gh also left ``metaData``
    out of the embedded Phenopackets and ``phenopacketSchemaVersion`` out of
    ``metaData``, and abusua2ga4gh put ``name`` in ``subject``.
Both
    ``KIN:011`` labelled *isDizygoticMultipleBirthSiblingOf*; KIN calls it
    *isPolyzygoticMultipleBirthSiblingOf*.
abusua2ga4gh up to 0.2, carriers
    A phenotypic feature ``HP:0032500`` labelled "Heterozygous carrier".
    ``HP:0032500`` is *Exacerbated by tobacco use*, and the HPO has no term for
    a carrier: being a carrier is not a phenotype. The upgrade removes the
    feature; in a GA4GH Pedigree the narrative then says who is a carrier (as
    studio2ga4gh writes it), and for a Phenopacket it is listed in ``todo``:
    Phenopackets have no field for carrier status, and the only structured
    place for it, a genomic interpretation of the variant, needs a person who
    knows the variant.

The draft of version 1 of the standard is recognised too, so that it is not
taken for one of the forms above, but it cannot be upgraded: it is not yet
approved (ga4gh/pedigree pull request 50, 2026). Its people are Individuals of
its own rather than Phenopackets, and its relationships have lists of
biological and social KIN terms instead of one ``relation``.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import kin, ontology
from . import phenopackets as pp
from .kindred import DISEASE, Kindred, Member, Relation, Term, detect, to_ga4gh_pedigree
from .schema import camelise

UPGRADED_BY = "pedigree-ga4gh upgrade"

# abusua2ga4gh 0.2 wrote carriers as this phenotypic feature, labelled "Heterozygous carrier"; it is the HPO's
# "Exacerbated by tobacco use", and the HPO has no term for a carrier (checked in the release of 2026-09-01)
CARRIER_MISTAKE = "HP:0032500"


def is_carrier_mistake(term: Dict) -> bool:
    """A phenotypic feature's type that is abusua2ga4gh's carrier mistake (HP:0032500 labelled as a carrier)."""
    return (isinstance(term, dict) and ontology.tidy_curie(str(term.get("id") or "")) == CARRIER_MISTAKE
            and "carrier" in str(term.get("label") or "").lower())


def _who(ids: List[str]) -> str:
    return ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


@dataclass
class Legacy:
    form: str            # "studio2ga4gh-pedigree", "abusua2ga4gh-pedigree", "phenopackets", "pedigree-v1-draft"
    description: str
    unreadable: bool     # True if the standard reader cannot make sense of it at all
    upgradable: bool = True   # False if upgrade() cannot rewrite it (the draft of version 1)


# Fields of the draft of version 1 of the standard (ga4gh/pedigree pull request 50), in JSON and proto spelling,
# that no form the workbench reads has: on its Individuals, and on its Relationships
V1_DRAFT_INDIVIDUAL = ("sexAssignedAtBirth", "sex_assigned_at_birth", "genderIdentity", "gender_identity",
                       "eggParentId", "egg_parent_id", "spermParentId", "sperm_parent_id", "egg_parent",
                       "sperm_parent", "externalIdentifiers", "external_identifiers", "populationDescriptors",
                       "population_descriptors")
V1_DRAFT_RELATIONSHIP = ("biologicalRelationship", "biological_relationship", "socialRelationship",
                         "social_relationship", "twinGroup", "twin_group", "consanguinity", "consanguinityNote",
                         "consanguinity_note")
V1_DRAFT = ("This GA4GH Pedigree is in the form of the draft of version 1 of the standard (ga4gh/pedigree pull "
            "request 50), which is not yet approved: its people are not Phenopackets, and its relationships have "
            "lists of biological and social KIN terms. The workbench reads and writes the published form, and "
            "cannot read or convert this one yet.")


def _individuals(doc: Dict) -> List[Dict]:
    return [i for i in (doc.get("individuals") or []) if isinstance(i, dict)]


def identify(doc: Dict) -> Optional[Legacy]:
    """Say whether ``doc`` is one of the older, non-standard forms, or the draft of version 1."""
    if not isinstance(doc, dict):
        return None
    kind = detect(doc)
    if kind == "pedigree":
        inds = _individuals(doc)
        rels = [r for r in (doc.get("relationships") or []) if isinstance(r, dict)]
        if any(k in i for i in inds for k in V1_DRAFT_INDIVIDUAL) or any(
                k in r for r in rels for k in V1_DRAFT_RELATIONSHIP):
            return Legacy("pedigree-v1-draft", V1_DRAFT, True, False)
        flat = inds and all("subject" not in i for i in inds) and any(
            k in i for i in inds for k in ("sex", "deceased", "affected"))
        if flat or any("individual" in r or "relative" in r for r in rels):
            return Legacy("studio2ga4gh-pedigree",
                          "This GA4GH Pedigree was written by studio2ga4gh 0.3 or earlier, which wrote the "
                          "conceptual model straight out as JSON. It is not in a form other software reads.",
                          True)
        subj_problems = any(isinstance(i.get("subject"), dict) and (
            "diseases" in i["subject"] or "phenotypicFeatures" in i["subject"] or "name" in i["subject"])
            for i in inds)
        rel_problems = any("description" in r for r in rels)
        no_md = inds and all("metaData" not in i and "meta_data" not in i for i in inds)
        if subj_problems or rel_problems or (no_md and any(
                "vital_status" in (i.get("subject") or {}) for i in inds)):
            return Legacy("abusua2ga4gh-pedigree",
                          "This GA4GH Pedigree looks like the output of abusua2ga4gh 0.2 or earlier: it "
                          "puts diseases or names inside 'subject', or extra fields on relationships, "
                          "which the standard does not allow.", False)
        return None
    if kind in ("family", "phenopacket", "cohort"):
        packets = _packets(doc, kind)
        md = doc.get("metaData") or doc.get("meta_data") or {}
        studio = (md.get("createdBy") == "studio2ga4gh" and "phenopacketSchemaVersion" not in md)
        abusua = any("name" in (p.get("subject") or {}) for p in packets)
        if studio or abusua:
            return Legacy("phenopackets",
                          "This file was written by an older version of {} and does not meet the "
                          "Phenopackets v2 schema.".format("studio2ga4gh" if studio else "abusua2ga4gh"),
                          False)
    return None


def _packets(doc: Dict, kind: str) -> List[Dict]:
    if kind == "family":
        out = [doc["proband"]] if isinstance(doc.get("proband"), dict) else []
        return out + [r for r in doc.get("relatives") or [] if isinstance(r, dict)]
    if kind == "cohort":
        return [m for m in doc.get("members") or [] if isinstance(m, dict)]
    if kind == "pedigree":
        return _individuals(doc)
    return [doc]


def upgrade(doc: Dict, *, created_by: str = UPGRADED_BY, created: Optional[str] = None,
            versions: Optional[Dict[str, str]] = None) -> Tuple[Dict, List[str], List[str]]:
    """Rewrite an older or non-standard file in the standard form.

    Returns ``(new_document, changes, todo)``. ``changes`` says what was done;
    ``todo`` lists what still needs a person, such as conditions with no
    ontology term. A file that is already standard comes back with its proto
    field names in camelCase and its KIN labels checked, and nothing else changed.
    """
    kind = detect(doc)
    old = identify(doc)
    if old is not None and not old.upgradable:
        raise ValueError(old.description)
    if old is not None and old.form == "studio2ga4gh-pedigree":
        return _upgrade_flat_pedigree(doc, created_by, created)
    message = {"pedigree": "GA4GHPedigree", "family": "Family", "cohort": "Cohort",
               "phenopacket": "Phenopacket"}.get(kind)
    if message is None:
        raise ValueError("this is not a GA4GH Pedigree, Phenopackets Family, Cohort or Phenopacket")
    changes: List[str] = []
    todo: List[str] = []
    renamed: List[str] = []
    data = camelise(copy.deepcopy(doc), message, "", renamed)
    if renamed:
        changes.append("renamed {} field(s) from proto spelling to JSON spelling (e.g. {})".format(
            len(renamed), renamed[0]))
    notes: List[str] = []
    carriers: List[str] = []
    for path, packet in _packet_paths(data, kind):
        _fix_packet(packet, path, changes, notes, carriers)
    if kind == "pedigree":
        _fix_relationships(data, changes, notes, todo)
        if carriers:
            notes.append("{} {} a carrier.".format(_who(carriers), "is" if len(carriers) == 1 else "are each"))
        if notes:
            narrative = data.get("narrative") or ""
            extra = " ".join(notes)
            data["narrative"] = (narrative + " " + extra).strip() if narrative else extra
            changes.append("kept {} note(s) in the narrative".format(len(notes)))
    else:
        for who in carriers:
            todo.append("{}: was recorded as a carrier. Phenopackets have no field for carrier status: the only "
                        "structured place for it is a genomic interpretation of the variant (heterozygous), if the "
                        "variant is known; a GA4GH Pedigree can say it in its narrative".format(who))
    family_md = data.get("metaData") if kind in ("family", "cohort") else None
    for path, packet in _packet_paths(data, kind):
        _fix_metadata(packet, path, family_md, created_by, created, changes, versions)
    if kind in ("family", "cohort"):
        _fix_metadata(data, "the " + kind, None, created_by, created, changes, versions)
    if kind == "family" and "consanguinousParents" not in data:
        data["consanguinousParents"] = False
        changes.append("wrote consanguinousParents: false explicitly")
    if kind == "family":
        data = _reorder(data, ("id", "proband", "relatives", "consanguinousParents", "pedigree", "files", "metaData"))
    for path, packet in _packet_paths(data, kind):
        for key, label in _empty_terms(packet):
            todo.append("{}: '{}' needs an ontology term ({} id is empty)".format(
                (packet.get("subject") or {}).get("id") or path, label, key))
    return data, changes, todo


def _reorder(d: Dict, order) -> Dict:
    out = {k: d[k] for k in order if k in d}
    out.update({k: v for k, v in d.items() if k not in out})
    return out


def _packet_paths(data: Dict, kind: str):
    if kind == "phenopacket":
        yield "the Phenopacket", data
    elif kind == "family":
        if isinstance(data.get("proband"), dict):
            yield "proband", data["proband"]
        for i, r in enumerate(data.get("relatives") or []):
            if isinstance(r, dict):
                yield "relatives[{}]".format(i), r
    elif kind == "cohort":
        for i, m in enumerate(data.get("members") or []):
            if isinstance(m, dict):
                yield "members[{}]".format(i), m
    elif kind == "pedigree":
        for i, m in enumerate(data.get("individuals") or []):
            if isinstance(m, dict):
                yield "individuals[{}]".format(i), m


def _fix_packet(packet: Dict, path: str, changes: List[str], notes: List[str], carriers: List[str]) -> None:
    subj = packet.get("subject")
    if not isinstance(subj, dict):
        return
    who = subj.get("id") or path
    for key in ("diseases", "phenotypicFeatures", "phenotypic_features"):
        if key in subj:
            target = "phenotypicFeatures" if key != "diseases" else "diseases"
            moved = subj.pop(key) or []
            packet.setdefault(target, []).extend(moved)
            changes.append("{}: moved {} out of subject to the Phenopacket".format(who, target))
    if "vital_status" in subj:
        subj.setdefault("vitalStatus", subj.pop("vital_status"))
        changes.append("{}: renamed vital_status to vitalStatus".format(who))
    if "alternate_ids" in subj:
        subj.setdefault("alternateIds", subj.pop("alternate_ids"))
    if "name" in subj:
        name = subj.pop("name")
        alts = [a for a in subj.get("alternateIds") or [] if a != name]
        if alts:
            subj["alternateIds"] = alts
        else:
            subj.pop("alternateIds", None)
        changes.append("{}: removed the name (Phenopackets have no name field; names are personal "
                       "data)".format(who))
    if "sex" not in subj:
        subj["sex"] = "UNKNOWN_SEX"
    feats = packet.get("phenotypicFeatures")
    if isinstance(feats, list) and any(is_carrier_mistake((f or {}).get("type")) for f in feats if isinstance(f, dict)):
        keep = [f for f in feats if not (isinstance(f, dict) and is_carrier_mistake(f.get("type")))]
        if keep:
            packet["phenotypicFeatures"] = keep
        else:
            packet.pop("phenotypicFeatures")
        carriers.append(who)
        changes.append("{}: removed the phenotypic feature {} 'Heterozygous carrier': {} is 'Exacerbated by "
                       "tobacco use', and the HPO has no term for a carrier".format(who, CARRIER_MISTAKE, CARRIER_MISTAKE))
    for key in ("diseases", "phenotypicFeatures"):
        for entry in packet.get(key) or []:
            term = entry.get("term" if key == "diseases" else "type")
            if isinstance(term, dict) and term.get("id") and term["id"] != ontology.tidy_curie(term["id"]):
                changes.append("{}: wrote {} as {}".format(who, term["id"], ontology.tidy_curie(term["id"])))
                term["id"] = ontology.tidy_curie(term["id"])


def _fix_relationships(data: Dict, changes: List[str], notes: List[str], todo: List[str]) -> None:
    for i, r in enumerate(data.get("relationships") or []):
        if not isinstance(r, dict):
            continue
        desc = r.pop("description", None)
        if desc:
            notes.append("{} and {}: {}.".format(r.get("individualId"), r.get("relativeId"), desc))
        rel = r.get("relation") or {}
        # abusua2ga4gh 0.2 wrote foster and social parents as adoptive parents: only its note says which was meant
        if desc and rel.get("id") == kin.ADOPTIVE_PARENT and any(w in str(desc).lower() for w in ("foster", "social")):
            todo.append("relationships[{}]: {} is written as an adoptive parent of {} (KIN:022), but the note says "
                        "'{}'. If that is what was meant, KIN has KIN:021 isFosterParentOf and KIN:020 "
                        "isParentFigureOf".format(i, r.get("individualId"), r.get("relativeId"), desc))
        found = kin.modernise(rel.get("id", ""), rel.get("label", ""))
        if found is None:
            continue
        term, swap = found
        if swap:
            r["individualId"], r["relativeId"] = r.get("relativeId"), r.get("individualId")
        if rel.get("id") != term.id or rel.get("label") != term.label or swap:
            changes.append("relationships[{}]: {} '{}' became {} '{}'{}".format(
                i, rel.get("id"), rel.get("label"), term.id, term.label,
                " with the two people swapped" if swap else ""))
            r["relation"] = term.as_ontology_class()
        data["relationships"][i] = _reorder(r, ("individualId", "relation", "relativeId"))


def _fix_metadata(container: Dict, path: str, inherit: Optional[Dict], created_by: str,
                  created: Optional[str], changes: List[str], given: Optional[Dict[str, str]] = None) -> None:
    md = container.get("metaData")
    versions: Dict[str, str] = {}
    for src in (md, inherit):
        for res in (src or {}).get("resources") or []:
            if res.get("namespacePrefix") and res.get("version"):
                versions.setdefault(res["namespacePrefix"], res["version"])
    for p, v in (given or {}).items():
        if v and versions.get(p) in (None, "", ontology.UNKNOWN_VERSION):
            versions[p] = v
    if not isinstance(md, dict):
        base = copy.deepcopy(inherit) if isinstance(inherit, dict) else {}
        md = {"created": base.get("created") or created or pp.now(),
              "createdBy": base.get("createdBy") or created_by}
        container["metaData"] = md
        changes.append("{}: added metaData{}".format(path, " (copied from the Family)" if inherit else ""))
    if not md.get("created") or not pp.is_timestamp(md.get("created", "")):
        md["created"] = created or pp.now()
        changes.append("{}: set metaData.created".format(path))
    if not md.get("createdBy"):
        md["createdBy"] = created_by
        changes.append("{}: set metaData.createdBy".format(path))
    if md.get("phenopacketSchemaVersion") != pp.SCHEMA_VERSION:
        if not str(md.get("phenopacketSchemaVersion", "")).startswith("2"):
            changes.append("{}: set phenopacketSchemaVersion to 2.0".format(path))
            md["phenopacketSchemaVersion"] = pp.SCHEMA_VERSION
    used = pp.prefixes_used(container)
    have = {r.get("namespacePrefix"): r for r in md.get("resources") or [] if isinstance(r, dict)}
    new_res = []
    for p in sorted(set(used) | {k for k in have if k}):
        r = have.get(p)
        complete = r and all(r.get(f) for f in ("id", "name", "url", "version", "namespacePrefix", "iriPrefix"))
        if complete and r.get("version") == ontology.UNKNOWN_VERSION and versions.get(p) not in (
                None, "", ontology.UNKNOWN_VERSION):
            r = dict(r, version=versions[p])
            changes.append("{}: recorded {} release {}".format(path, p, versions[p]))
        if complete:
            new_res.append(r)
            continue
        fresh = ontology.resource(p, (r or {}).get("version") or versions.get(p))
        if r:
            for f in ("id", "name", "url", "iriPrefix"):
                if r.get(f):
                    fresh[f] = r[f]
            changes.append("{}: filled in the {} resource".format(path, p))
        else:
            changes.append("{}: declared the {} resource".format(path, p))
        new_res.append(fresh)
    if new_res:
        md["resources"] = new_res
    elif "resources" in md:
        md.pop("resources")
        changes.append("{}: removed an empty resources list".format(path))
    container["metaData"] = _reorder(md, ("created", "createdBy", "submittedBy", "resources", "updates",
                                          "phenopacketSchemaVersion", "externalReferences"))


def _empty_terms(packet: Dict):
    for d in packet.get("diseases") or []:
        t = d.get("term") or {}
        if not (t.get("id") or "").strip():
            yield "the disease", t.get("label", "")
    for f in packet.get("phenotypicFeatures") or []:
        t = f.get("type") or {}
        if not (t.get("id") or "").strip():
            yield "the phenotype", t.get("label", "")


def _upgrade_flat_pedigree(doc: Dict, created_by: str, created: Optional[str]) -> Tuple[Dict, List[str], List[str]]:
    """studio2ga4gh 0.3's conceptual-model JSON -> the Phenopackets form."""
    changes = ["rewrote the conceptual-model JSON of studio2ga4gh 0.3 in the Phenopackets form: one "
               "Phenopacket per person, relationships as individualId, relation, relativeId"]
    todo: List[str] = []
    k = Kindred(id=str(doc.get("id") or "pedigree"), narrative=doc.get("narrative"),
                date=doc.get("date"), status=doc.get("status"))
    index = set(doc.get("indexPatients") or doc.get("index_patients") or [])
    named = 0
    affected = []
    for ind in _individuals(doc):
        mid = str(ind.get("id", ""))
        if not mid:
            continue
        sex = ind.get("sex")
        if isinstance(sex, dict):          # the 2021 draft wrote sex as a Concept
            sex = (sex.get("label") or sex.get("id") or "").upper()
        sex = {"M": "MALE", "F": "FEMALE", "UNKNOWN": "UNKNOWN_SEX", "OTHER": "OTHER_SEX"}.get(sex, sex)
        if sex not in pp.SEXES:
            sex = "UNKNOWN_SEX"
        m = Member(id=mid, sex=sex, index=mid in index,
                   vital_status="DECEASED" if ind.get("deceased") else "ALIVE",
                   affected=bool(ind.get("affected")) if "affected" in ind else None)
        if ind.get("name"):
            named += 1
        dob = ind.get("dateOfBirth")
        if dob:
            if pp.date_to_timestamp(dob):
                m.date_of_birth = dob
            else:
                changes.append("{}: dropped the date of birth '{}'; Phenopackets need a full date".format(mid, dob))
        if ind.get("affected"):
            affected.append(mid)
        k.members.append(m)
    if named:
        changes.append("removed {} name(s); Phenopackets have no name field".format(named))
    for r in doc.get("relationships") or []:
        a = r.get("individual", r.get("individualId"))
        b = r.get("relative", r.get("relativeId"))
        rel = r.get("relation") or {}
        found = kin.modernise(rel.get("id", ""), rel.get("label", ""))
        if not (a and b and found):
            changes.append("skipped a relationship that could not be read: {}".format(r))
            continue
        term, swap = found
        if term.id != rel.get("id") or term.label != rel.get("label"):
            changes.append("{} '{}' became {} '{}'".format(rel.get("id"), rel.get("label"), term.id, term.label))
        if swap:
            a, b = b, a
        k.relations.append(Relation(str(a), term.id, str(b)))
    out, _ = to_ga4gh_pedigree(k, created_by=created_by, created=created)
    if affected:
        todo.append("{} {} marked as affected, but the file does not say by what. Open the matching "
                    "*_phenopackets.json from the same conversion, or convert the Studio drawing again, "
                    "to get the conditions: {}".format(
                        len(affected), "person is" if len(affected) == 1 else "people are", ", ".join(affected)))
    return out, changes, todo
