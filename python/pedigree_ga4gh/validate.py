"""Check a GA4GH Pedigree, Phenopackets Family, Cohort or Phenopacket.

:func:`validate` returns a list of :class:`Finding` objects. An *error* means
the file breaks the standard and other software may refuse it; a *warning*
means it is valid but probably wrong (a mother recorded as male, a term label
that does not match KIN); *info* is for things worth knowing that are allowed.

The structural checks mirror the JSON schemas and the MetaData check of
phenopacket-tools, the Phenopackets team's validator for Phenopackets v2, so a
file that passes here should pass there. The GA4GH Pedigree checks follow the
standard's conceptual model and its Phenopackets form (see
:mod:`pedigree_ga4gh.pedigree`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import kin, ontology
from .phenopackets import is_iso_duration, is_partial_date, is_timestamp
from .schema import (MESSAGES, MIN_ITEMS, ONEOF_REQUIRED, REQUIRED, camelise, enum_values, field,
                     fields, is_message, ontology_classes, walk)

ERROR, WARNING, INFO = "error", "warning", "info"

_KIND_MESSAGE = {"pedigree": "GA4GHPedigree", "family": "Family", "cohort": "Cohort",
                 "phenopacket": "Phenopacket"}
KIND_NAMES = {"pedigree": "GA4GH Pedigree", "family": "Phenopackets Family",
              "cohort": "Phenopackets Cohort", "phenopacket": "Phenopacket"}


@dataclass
class Finding:
    severity: str        # "error", "warning" or "info"
    code: str            # short, stable identifier, e.g. "undeclared-prefix"
    message: str
    path: str = ""       # where in the file, e.g. "individuals[2].subject"
    fix: str = ""        # what to do about it

    def to_dict(self) -> Dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message,
                "path": self.path, "fix": self.fix}


def errors(findings: List[Finding]) -> List[Finding]:
    return [f for f in findings if f.severity == ERROR]


def is_valid(findings: List[Finding]) -> bool:
    return not errors(findings)


def validate(doc, kind: Optional[str] = None) -> List[Finding]:
    """Check a parsed JSON document. ``kind`` is detected when not given."""
    from .kindred import detect
    from . import legacy

    out: List[Finding] = []
    if not isinstance(doc, dict):
        return [Finding(ERROR, "not-an-object", "the file must hold a JSON object")]
    kind = kind or detect(doc)
    if kind not in _KIND_MESSAGE:
        return [Finding(ERROR, "unknown-kind",
                        "this is not a GA4GH Pedigree, Phenopackets Family, Cohort or Phenopacket")]

    old = legacy.identify(doc)
    if old is not None and not old.upgradable:
        out.append(Finding(ERROR, "draft-form", old.description, "",
                           "ask for the file in the published form, with each individual a Phenopacket"))
        return out
    if old is not None:
        out.append(Finding(ERROR, "legacy-format", old.description, "",
                           "upgrade it: pedigree-ga4gh upgrade FILE (in the Pedigree workbench: Tools > Upgrade a file from an older tool)"))
        if old.unreadable:
            return out

    renamed: List[str] = []
    data = camelise(doc, _KIND_MESSAGE[kind], "", renamed)
    if renamed:
        out.append(Finding(INFO, "proto-names",
                           "{} field name(s) use the proto spelling, e.g. '{}'. Readers accept both "
                           "spellings, but writers use camelCase.".format(len(renamed), renamed[0]),
                           renamed[0], "pedigree-ga4gh upgrade FILE writes them in camelCase"))
    _structure(data, _KIND_MESSAGE[kind], out)
    if kind == "phenopacket":
        _packet(data, "", out)
    elif kind == "family":
        _family(data, out)
    elif kind == "cohort":
        _cohort(data, out)
    else:
        _pedigree(data, out)
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return sorted(out, key=lambda f: order[f.severity])


# -- structure -------------------------------------------------------------------

def _is_int(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, str) and v.strip().lstrip("-").isdigit()


def _scalar_ok(value, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name in ("int32", "uint32", "uint64"):
        return _is_int(value) and (type_name == "int32" or int(value) >= 0)
    if type_name == "double":
        return (isinstance(value, (int, float)) and not isinstance(value, bool)) or (
            isinstance(value, str) and value in ("NaN", "Infinity", "-Infinity"))
    if type_name == "timestamp":
        return is_timestamp(value)
    if type_name == "map":
        return isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
    if type_name == "opaque":
        return isinstance(value, dict)
    if type_name.startswith("enum:"):
        values = enum_values(type_name)
        return value in values or (_is_int(value) and 0 <= int(value) < len(values))
    return True


def _describe(type_name: str) -> str:
    if type_name.startswith("enum:"):
        return "one of " + ", ".join(enum_values(type_name))
    return {"string": "text", "bool": "true or false", "int32": "a whole number",
            "uint32": "a whole number of 0 or more", "uint64": "a whole number of 0 or more",
            "double": "a number", "timestamp": "an RFC 3339 timestamp such as 2024-05-01T10:00:00Z",
            "map": "an object of text values", "opaque": "an object"}.get(type_name, "a " + type_name)


def _default(value, type_name: str) -> bool:
    """True if a value is its type's proto3 default, which JSON writers may leave out."""
    if value is None:
        return True
    if type_name == "string":
        return value == ""
    if type_name == "bool":
        return value is False
    if type_name.startswith("enum:"):
        return value in (enum_values(type_name)[0], 0)
    return False


def _structure(data: dict, message: str, out: List[Finding]) -> None:
    for path, msg, obj in walk(data, message):
        here = path or "(top level)"
        fdefs = fields(msg)
        for key, value in obj.items():
            f = fdefs.get(key)
            loc = "{}.{}".format(path, key) if path else key
            if f is None:
                out.append(Finding(ERROR, "unknown-field",
                                   "'{}' is not a field of {}; Phenopackets readers reject unknown "
                                   "fields".format(key, _msg_name(msg)), loc,
                                   _unknown_fix(msg, key)))
                continue
            if f.repeated:
                if not isinstance(value, list):
                    out.append(Finding(ERROR, "not-a-list", "'{}' must be a list".format(key), loc))
                    continue
                items = value
            else:
                items = [value]
            for i, item in enumerate(items):
                iloc = "{}[{}]".format(loc, i) if f.repeated else loc
                if is_message(f.type):
                    if not isinstance(item, dict):
                        out.append(Finding(ERROR, "not-an-object", "'{}' must be an object ({})".format(
                            key, _msg_name(f.type)), iloc))
                elif item is not None and not _scalar_ok(item, f.type):
                    out.append(Finding(ERROR, "bad-value", "'{}' must be {}, not {}".format(
                        key, _describe(f.type), json.dumps(item)[:60]), iloc))
        for req in REQUIRED.get(msg, ()):
            f = fdefs[req]
            present = req in obj and not (f.repeated and obj[req] == [])
            if f.type == "string" and present and obj[req] == "":
                present = False
            if not present and (f.type == "bool" or f.type.startswith("enum:")) and not f.repeated:
                continue  # proto3: an absent enum or bool holds its default value
            if msg == "OntologyClass" and req in obj:
                continue  # an empty id or label is reported below, more helpfully
            if not present:
                out.append(Finding(ERROR, "missing-field", "{} is missing '{}', which is required".format(
                    _msg_name(msg), req), here, _missing_fix(msg, req)))
        for (m2, key), n in MIN_ITEMS.items():
            if m2 == msg and isinstance(obj.get(key), list) and 0 < len(obj[key]) < n:
                out.append(Finding(ERROR, "too-few", "'{}' needs at least {} item(s)".format(key, n), here))
        if msg in ONEOF_REQUIRED:
            group = ONEOF_REQUIRED[msg]
            members = [f.json for f in MESSAGES[msg] if f.oneof == group]
            given = [k for k in members if k in obj]
            if len(given) != 1:
                out.append(Finding(ERROR, "oneof", "{} needs exactly one of {} (it has {})".format(
                    _msg_name(msg), ", ".join(members), ", ".join(given) or "none"), here))
        if msg == "OntologyClass":
            _ontology_class(obj, here, out)
        elif msg == "Age":
            v = obj.get("iso8601duration")
            if isinstance(v, str) and v and not is_iso_duration(v):
                out.append(Finding(ERROR, "bad-age", "'{}' is not an ISO 8601 duration such as "
                                   "P34Y or P6M".format(v), here))
        elif msg == "GestationalAge":
            for key in ("weeks", "days"):
                if _is_int(obj.get(key)) and int(obj[key]) < 0:
                    out.append(Finding(ERROR, "bad-value", "{} cannot be negative".format(key), here))
        elif msg == "Resource":
            for key in ("url", "iriPrefix", "name"):
                if key in obj and isinstance(obj[key], str) and not obj[key].strip():
                    out.append(Finding(WARNING, "empty-resource-field",
                                       "resource {} has an empty {}".format(obj.get("namespacePrefix", "?"), key),
                                       here))
            if obj.get("version") == ontology.UNKNOWN_VERSION:
                out.append(Finding(INFO, "unknown-version",
                                   "the release of {} that the terms came from is not recorded".format(
                                       obj.get("namespacePrefix", "?")), here))
        elif msg == "MetaData":
            v = obj.get("phenopacketSchemaVersion")
            if isinstance(v, str) and v and not v.startswith("2"):
                out.append(Finding(ERROR, "schema-version",
                                   "phenopacketSchemaVersion is {}; these checks are for version 2.0".format(v),
                                   here))


def _ontology_class(obj: dict, here: str, out: List[Finding]) -> None:
    cid, label = obj.get("id"), obj.get("label")
    if isinstance(cid, str):
        if not cid.strip():
            out.append(Finding(ERROR, "empty-term-id",
                               "the term '{}' has no ontology id".format(label or "?"), here,
                               "give it its ontology id: phenotk normalise FILE --mapping terms.json (in the Pedigree workbench: Tools > Fill in missing terms)"))
        elif not ontology.is_curie(cid):
            out.append(Finding(ERROR, "bad-curie", "'{}' is not a CURIE such as HP:0001626".format(cid), here))
        elif ontology.tidy_curie(cid) != cid:
            out.append(Finding(WARNING, "curie-case", "'{}' is usually written '{}'".format(
                cid, ontology.tidy_curie(cid)), here))
    if isinstance(label, str) and not label.strip():
        out.append(Finding(ERROR, "empty-label", "the term {} has an empty label".format(cid or "?"), here))
    from .legacy import CARRIER_MISTAKE, is_carrier_mistake
    if is_carrier_mistake(obj):
        out.append(Finding(ERROR, "carrier-term",
                           "{} '{}' is not a carrier term: {} is 'Exacerbated by tobacco use', and the HPO has no "
                           "term for a carrier".format(CARRIER_MISTAKE, label, CARRIER_MISTAKE), here,
                           "pedigree-ga4gh upgrade removes it (in the Pedigree workbench: Tools > Upgrade a file "
                           "from an older tool), and a GA4GH Pedigree's narrative then says who is a carrier"))


def _msg_name(msg: str) -> str:
    return {"GA4GHPedigree": "the pedigree", "Person": "a pedigree person"}.get(msg, msg)


def _unknown_fix(msg: str, key: str) -> str:
    if msg == "Individual" and key in ("diseases", "phenotypicFeatures"):
        return "move it up to the Phenopacket that holds this subject"
    if msg == "Individual" and key == "name":
        return "remove it; Phenopackets keep no names (use an id or alternateIds)"
    if msg == "Relationship":
        return "remove it; a relationship has only individualId, relation and relativeId"
    return "remove it or correct its spelling"


def _missing_fix(msg: str, key: str) -> str:
    if key == "metaData":
        return "add metaData (created, createdBy, phenopacketSchemaVersion, resources)"
    if msg == "MetaData" and key == "phenopacketSchemaVersion":
        return 'add "phenopacketSchemaVersion": "2.0"'
    return ""


# -- meaning -----------------------------------------------------------------------

def _prefix_coverage(container: dict, message: str, path: str, out: List[Finding],
                     skip_relations: bool = False) -> None:
    md = container.get("metaData")
    if not isinstance(md, dict):
        return
    declared = {r.get("namespacePrefix") for r in md.get("resources") or [] if isinstance(r, dict)}
    seen = set()
    for p, oc in ontology_classes(container, message, path):
        if skip_relations and p.endswith(".relation"):
            continue
        cid = oc.get("id") if isinstance(oc.get("id"), str) else ""
        pre = ontology.prefix_of(cid)
        if pre and ontology.is_curie(cid) and pre not in declared and pre not in seen:
            seen.add(pre)
            out.append(Finding(ERROR, "undeclared-prefix",
                               "{} terms are used but metaData has no resource for {}".format(pre, pre),
                               "{}.metaData".format(path) if path else "metaData",
                               "add a resource for {}: pedigree-ga4gh upgrade does this (in the Pedigree workbench: Tools > Upgrade a file from an older tool)".format(pre)))
    prefixes = [r.get("namespacePrefix") for r in md.get("resources") or [] if isinstance(r, dict)]
    dups = {p for p in prefixes if p and prefixes.count(p) > 1}
    for d in sorted(dups):
        out.append(Finding(WARNING, "duplicate-resource", "{} is declared more than once".format(d),
                           "{}.metaData".format(path) if path else "metaData"))


def _packet(packet: dict, path: str, out: List[Finding]) -> None:
    _prefix_coverage(packet, "Phenopacket", path, out)
    if not isinstance(packet.get("subject"), dict):
        out.append(Finding(WARNING, "no-subject", "the Phenopacket has no subject", path or "(top level)"))


def _family(fam: dict, out: List[Finding]) -> None:
    _prefix_coverage(fam, "Family", "", out)
    packets = []
    if isinstance(fam.get("proband"), dict):
        packets.append(("proband", fam["proband"]))
    for i, r in enumerate(fam.get("relatives") or []):
        if isinstance(r, dict):
            packets.append(("relatives[{}]".format(i), r))
    for p, packet in packets:
        _packet(packet, p, out)
    persons = ((fam.get("pedigree") or {}).get("persons")) or []
    _ped_persons(persons, out)
    ids = {p.get("individualId") for p in persons if isinstance(p, dict)}
    for p, packet in packets:
        sid = (packet.get("subject") or {}).get("id")
        if sid and sid not in ids:
            out.append(Finding(ERROR, "subject-not-in-pedigree",
                               "{} has a Phenopacket but is not in the pedigree".format(sid), p,
                               "a pedigree person's individualId must match each subject id"))
    sids = [(packet.get("subject") or {}).get("id") for _, packet in packets]
    for s in {x for x in sids if x and sids.count(x) > 1}:
        out.append(Finding(ERROR, "duplicate-subject", "{} has more than one Phenopacket".format(s)))


def _ped_persons(persons: list, out: List[Finding]) -> None:
    by_id: Dict[str, dict] = {}
    fam_ids = set()
    for i, p in enumerate(persons):
        if not isinstance(p, dict):
            continue
        iid = p.get("individualId")
        fam_ids.add(p.get("familyId"))
        if iid in by_id:
            out.append(Finding(ERROR, "duplicate-person", "{} is in the pedigree twice".format(iid),
                               "pedigree.persons[{}]".format(i)))
        by_id[iid] = p
    if len(fam_ids) > 1:
        out.append(Finding(INFO, "several-families", "the pedigree mixes family ids: {}".format(
            ", ".join(sorted(str(x) for x in fam_ids)))))
    for i, p in enumerate(persons):
        if not isinstance(p, dict):
            continue
        loc = "pedigree.persons[{}]".format(i)
        for key, want in (("paternalId", "MALE"), ("maternalId", "FEMALE")):
            pid = p.get(key)
            if pid in (None, "", "0"):
                continue
            if pid not in by_id:
                out.append(Finding(ERROR, "missing-parent", "{} of {} is {}, who is not in the pedigree".format(
                    key, p.get("individualId"), pid), loc))
                continue
            sex = by_id[pid].get("sex") or "UNKNOWN_SEX"
            if sex not in (want, "UNKNOWN_SEX"):
                out.append(Finding(WARNING, "parent-sex", "{} is the {} of {} but is recorded as {}".format(
                    pid, "father" if want == "MALE" else "mother", p.get("individualId"), sex), loc))
        if p.get("paternalId") not in (None, "", "0") and p.get("paternalId") == p.get("maternalId"):
            out.append(Finding(ERROR, "same-parents", "{} has the same person as father and mother".format(
                p.get("individualId")), loc))
    parents = {iid: [x for x in (p.get("paternalId"), p.get("maternalId")) if x not in (None, "", "0")]
               for iid, p in by_id.items()}
    _cycles(parents, out)


def _cycles(parents: Dict[str, List[str]], out: List[Finding]) -> None:
    state: Dict[str, int] = {}

    def visit(node, chain):
        state[node] = 1
        for par in parents.get(node, []):
            if state.get(par) == 1:
                out.append(Finding(ERROR, "ancestry-loop", "{} is their own ancestor".format(par)))
                return True
            if state.get(par) is None and par in parents and visit(par, chain + [par]):
                return True
        state[node] = 2
        return False

    for n in list(parents):
        if state.get(n) is None and visit(n, [n]):
            break


def _cohort(cohort: dict, out: List[Finding]) -> None:
    _prefix_coverage(cohort, "Cohort", "", out)
    for i, m in enumerate(cohort.get("members") or []):
        if isinstance(m, dict):
            _packet(m, "members[{}]".format(i), out)


def _pedigree(doc: dict, out: List[Finding]) -> None:
    if "date" in doc and isinstance(doc["date"], str) and not is_partial_date(doc["date"]):
        out.append(Finding(ERROR, "bad-date", "date '{}' must be YYYY, YYYY-MM or YYYY-MM-DD".format(doc["date"]),
                           "date"))
    subjects: Dict[str, dict] = {}
    for i, packet in enumerate(doc.get("individuals") or []):
        if not isinstance(packet, dict):
            continue
        p = "individuals[{}]".format(i)
        _packet(packet, p, out)
        sid = (packet.get("subject") or {}).get("id") if isinstance(packet.get("subject"), dict) else None
        if not sid:
            out.append(Finding(ERROR, "no-subject-id", "an individual has no subject id, so no relationship "
                               "can refer to them", p))
            continue
        if sid in subjects:
            out.append(Finding(ERROR, "duplicate-subject", "{} is in the pedigree twice".format(sid), p))
        subjects[sid] = packet
    if not subjects:
        out.append(Finding(WARNING, "no-individuals", "the pedigree has nobody in it"))
    for i, pid in enumerate(doc.get("indexPatients") or []):
        if pid not in subjects:
            out.append(Finding(ERROR, "unknown-index-patient",
                               "index patient {} is not one of the individuals".format(pid),
                               "indexPatients[{}]".format(i)))

    def sex(pid):
        return ((subjects.get(pid) or {}).get("subject") or {}).get("sex") or "UNKNOWN_SEX"

    seen = set()
    parents: Dict[str, List[str]] = {s: [] for s in subjects}
    mothers: Dict[str, List[str]] = {}
    fathers: Dict[str, List[str]] = {}
    for i, r in enumerate(doc.get("relationships") or []):
        if not isinstance(r, dict):
            continue
        loc = "relationships[{}]".format(i)
        a, b = r.get("individualId"), r.get("relativeId")
        rel = r.get("relation") if isinstance(r.get("relation"), dict) else {}
        code, label = rel.get("id", ""), rel.get("label", "")
        for who in (a, b):
            if who and who not in subjects:
                out.append(Finding(ERROR, "unknown-person",
                                   "{} is not one of the individuals; relationship ids must be subject "
                                   "ids".format(who), loc))
        if a and a == b:
            out.append(Finding(ERROR, "self-relation", "{} is related to themselves".format(a), loc))
        if code not in kin.TERMS:
            found = kin.modernise(code, label)
            if found:
                term, swap = found
                out.append(Finding(ERROR, "old-kin-term",
                                   "{} '{}' is not a current KIN term; it means {} '{}'{}".format(
                                       code, label, term.id, term.label,
                                       ", with the two people the other way round" if swap else ""),
                                   loc + ".relation", "upgrade the file"))
            else:
                out.append(Finding(ERROR, "unknown-kin-term", "{} is not a KIN term".format(code or "(empty)"),
                                   loc + ".relation"))
            continue
        term = kin.TERMS[code]
        if label != term.label:
            hint = kin.modernise("", label)
            msg = "KIN calls {} '{}', not '{}'".format(code, term.label, label)
            if hint and hint[0].id != code:
                msg += " (the label '{}' means {})".format(label, hint[0].id)
                out.append(Finding(ERROR, "kin-mismatch", msg, loc + ".relation",
                                   "check which relation was meant, then correct the code or the label"))
            else:
                out.append(Finding(WARNING, "kin-label", msg, loc + ".relation",
                                   "use KIN's label: pedigree-ga4gh upgrade does this (in the Pedigree workbench: Tools > Upgrade a file from an older tool)"))
        if term.subject_sex and a in subjects and sex(a) not in (term.subject_sex, "UNKNOWN_SEX"):
            out.append(Finding(WARNING, "relation-sex", "{} is recorded as {} but '{}' is for a {} subject".format(
                a, sex(a), term.label, "male" if term.subject_sex == "MALE" else "female"), loc))
        key = (a, code, b)
        if key in seen:
            out.append(Finding(WARNING, "duplicate-relationship", "{} {} {} is listed twice".format(
                a, term.label, b), loc))
        elif term.symmetric and (b, code, a) in seen:
            out.append(Finding(INFO, "both-directions", "{} is symmetric, so {} {} {} need only be given "
                               "once".format(term.label, b, term.label, a), loc))
        seen.add(key)
        if a in subjects and b in subjects and kin.is_a(code, kin.BIOLOGICAL_PARENT):
            if a not in parents.setdefault(b, []):
                parents[b].append(a)
            if code in (kin.BIOLOGICAL_MOTHER, kin.OVUM_DONOR, kin.SURROGATE_OVUM_DONOR):
                mothers.setdefault(b, []).append(a)
            if code in (kin.BIOLOGICAL_FATHER, kin.SPERM_DONOR):
                fathers.setdefault(b, []).append(a)
    for child, ps in parents.items():
        if len(ps) > 2:
            out.append(Finding(WARNING, "too-many-parents", "{} has {} biological parents: {}".format(
                child, len(ps), ", ".join(ps))))
    for child, ms in mothers.items():
        if len(set(ms)) > 1:
            out.append(Finding(WARNING, "two-mothers", "{} has more than one genetic mother: {}".format(
                child, ", ".join(sorted(set(ms))))))
    for child, fs in fathers.items():
        if len(set(fs)) > 1:
            out.append(Finding(WARNING, "two-fathers", "{} has more than one genetic father: {}".format(
                child, ", ".join(sorted(set(fs))))))
    _cycles(parents, out)


def render(findings: List[Finding]) -> str:
    """The findings as plain text, one per line."""
    if not findings:
        return "No problems found."
    mark = {ERROR: "error  ", WARNING: "warning", INFO: "info   "}
    lines = []
    for f in findings:
        where = " [{}]".format(f.path) if f.path else ""
        lines.append("{} {}{}".format(mark[f.severity], f.message, where))
        if f.fix:
            lines.append("        fix: {}".format(f.fix))
    n_e, n_w = len(errors(findings)), len([f for f in findings if f.severity == WARNING])
    lines.append("")
    lines.append("{} error{}, {} warning{}".format(n_e, "" if n_e == 1 else "s", n_w, "" if n_w == 1 else "s"))
    return "\n".join(lines)
