"""Builders for Phenopacket schema v2 objects, in canonical JSON form.

Everything here returns plain dicts with lowerCamelCase keys, the proto3 JSON
form every Phenopackets tool reads. The builders refuse to make an invalid
object: an ontology term without a CURIE or a label, an unknown enum value or a
malformed timestamp raises ``ValueError``. Fields that phenopacket-tools always
prints, such as ``sex`` and ``affectedStatus`` and the ``consanguinousParents``
flag, are always written, even when they hold the default value.

Reference: https://phenopacket-schema.readthedocs.io (schema version 2.0).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from . import ontology
from .schema import ENUMS

SCHEMA_VERSION = "2.0"

SEXES = ENUMS["Sex"]                                  # UNKNOWN_SEX, FEMALE, MALE, OTHER_SEX
VITAL_STATUSES = ENUMS["VitalStatus.Status"]          # UNKNOWN_STATUS, ALIVE, DECEASED
AFFECTED_STATUSES = ENUMS["Pedigree.Person.AffectedStatus"]  # MISSING, UNAFFECTED, AFFECTED
KARYOTYPIC_SEXES = ENUMS["KaryotypicSex"]

# The ISO 8601 duration pattern phenopacket-tools checks Age against.
_ISO_DURATION = re.compile(r"^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d+[HMS])(\d+H)?(\d+M)?(\d+S)?)?$")
# RFC 3339 date-time, as JSON Schema's "date-time" format requires.
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")
# Partial dates the GA4GH Pedigree allows for its own ``date``.
_PARTIAL_DATE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")


def now() -> str:
    """The current time as an RFC 3339 UTC timestamp, to the second."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_timestamp(value: str) -> bool:
    if not isinstance(value, str) or not _TIMESTAMP.match(value):
        return False
    try:
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def is_iso_duration(value: str) -> bool:
    return isinstance(value, str) and bool(_ISO_DURATION.match(value))


def is_partial_date(value: str) -> bool:
    return isinstance(value, str) and bool(_PARTIAL_DATE.match(value))


def date_to_timestamp(value: str) -> Optional[str]:
    """Turn a full date (``YYYY-MM-DD``) into a timestamp; ``None`` for anything less.

    Phenopackets store ``dateOfBirth`` as a timestamp, so a year on its own
    cannot be written there without inventing a month and day.
    """
    v = (value or "").strip()
    if is_timestamp(v):
        return v
    if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            return None
        return v + "T00:00:00Z"
    return None


def _choice(value: str, allowed: Sequence[str], what: str) -> str:
    v = (value or "").strip().upper()
    if v not in allowed:
        raise ValueError("{} must be one of {}, not {!r}".format(what, ", ".join(allowed), value))
    return v


def time_element_age(iso8601duration: str) -> Dict:
    """A ``TimeElement`` holding an age such as ``P49Y``."""
    if not is_iso_duration(iso8601duration):
        raise ValueError("{!r} is not an ISO 8601 duration such as P49Y or P3M".format(iso8601duration))
    return {"age": {"iso8601duration": iso8601duration}}


def vital_status(status: str) -> Dict:
    return {"status": _choice(status, VITAL_STATUSES, "vital status")}


def individual(subject_id: str, *, sex: str = "UNKNOWN_SEX", vital: Optional[str] = None,
               date_of_birth: Optional[str] = None, karyotypic_sex: Optional[str] = None,
               alternate_ids: Iterable[str] = (), time_at_last_encounter: Optional[str] = None) -> Dict:
    """The ``subject`` of a Phenopacket.

    ``date_of_birth`` must be a timestamp or a full date. ``time_at_last_encounter``
    is an ISO 8601 age such as ``P34Y``.
    """
    if not subject_id or not str(subject_id).strip():
        raise ValueError("an individual needs an id")
    out: Dict = {"id": str(subject_id)}
    alts = [a for a in alternate_ids if a]
    if alts:
        out["alternateIds"] = list(dict.fromkeys(alts))
    if date_of_birth:
        ts = date_to_timestamp(date_of_birth)
        if ts is None:
            raise ValueError("date of birth {!r} must be a full date (YYYY-MM-DD)".format(date_of_birth))
        out["dateOfBirth"] = ts
    if time_at_last_encounter:
        out["timeAtLastEncounter"] = time_element_age(time_at_last_encounter)
    if vital:
        out["vitalStatus"] = vital_status(vital)
    out["sex"] = _choice(sex or "UNKNOWN_SEX", SEXES, "sex")
    if karyotypic_sex:
        out["karyotypicSex"] = _choice(karyotypic_sex, KARYOTYPIC_SEXES, "karyotypic sex")
    return out


def disease(curie: str, label: str, *, excluded: bool = False, onset: Optional[str] = None) -> Dict:
    out: Dict = {"term": ontology.ontology_class(curie, label)}
    if excluded:
        out["excluded"] = True
    if onset:
        out["onset"] = time_element_age(onset)
    return out


def phenotypic_feature(curie: str, label: str, *, excluded: bool = False,
                       onset: Optional[str] = None, description: Optional[str] = None) -> Dict:
    out: Dict = {}
    if description:
        out["description"] = description
    out["type"] = ontology.ontology_class(curie, label)
    if excluded:
        out["excluded"] = True
    if onset:
        out["onset"] = time_element_age(onset)
    return out


def metadata(*, created_by: str, prefixes: Iterable[str] = (), versions: Optional[Dict[str, str]] = None,
             created: Optional[str] = None, submitted_by: Optional[str] = None) -> Dict:
    """``MetaData`` declaring a resource for each ontology prefix used.

    ``versions`` maps a prefix to the release its terms came from (for example
    ``{"HP": "2025-05-06"}``); prefixes without one are recorded as "unknown".
    ``resources`` is left out when no ontology is used, as an empty list is not
    allowed.
    """
    if not created_by or not created_by.strip():
        raise ValueError("metaData needs createdBy (who or what made the file)")
    ts = created or now()
    if not is_timestamp(ts):
        raise ValueError("created {!r} is not an RFC 3339 timestamp".format(ts))
    out: Dict = {"created": ts, "createdBy": created_by.strip()}
    if submitted_by:
        out["submittedBy"] = submitted_by
    res = ontology.resources_for(prefixes, versions)
    if res:
        out["resources"] = res
    out["phenopacketSchemaVersion"] = SCHEMA_VERSION
    return out


def prefixes_used(packet: Dict) -> List[str]:
    """The ontology prefixes a Phenopacket (or Family, or Cohort) uses."""
    from .schema import ontology_classes
    message = "Family" if "proband" in packet or "pedigree" in packet else (
        "Cohort" if "members" in packet else "Phenopacket")
    seen = []
    for _, oc in ontology_classes(packet, message):
        p = ontology.prefix_of(oc.get("id", ""))
        if p and p not in seen:
            seen.append(p)
    return seen


def phenopacket(packet_id: str, subject: Dict, *, diseases: Sequence[Dict] = (),
                phenotypic_features: Sequence[Dict] = (), created_by: str,
                versions: Optional[Dict[str, str]] = None, created: Optional[str] = None,
                extra: Optional[Dict] = None) -> Dict:
    """A complete Phenopacket with its own ``metaData``.

    ``extra`` carries other Phenopacket fields (measurements, interpretations,
    files...) through unchanged, for example when a file is read and written
    again.
    """
    out: Dict = {"id": packet_id, "subject": subject}
    if phenotypic_features:
        out["phenotypicFeatures"] = list(phenotypic_features)
    if diseases:
        out["diseases"] = list(diseases)
    for key in ("measurements", "biosamples", "interpretations", "medicalActions", "files"):
        if extra and extra.get(key):
            out[key] = extra[key]
    md_extra = (extra or {}).get("metaData") or {}
    out["metaData"] = metadata(created_by=created_by, prefixes=prefixes_used(out), versions=versions,
                               created=created, submitted_by=md_extra.get("submittedBy"))
    for key in ("updates", "externalReferences"):
        if md_extra.get(key):
            out["metaData"][key] = md_extra[key]
    return out


def ped_person(family_id: str, individual_id: str, *, paternal_id: str = "0", maternal_id: str = "0",
               sex: str = "UNKNOWN_SEX", affected_status: str = "MISSING") -> Dict:
    """One row of a Phenopackets ``Pedigree`` (the PED-style pedigree of a Family)."""
    return {
        "familyId": family_id,
        "individualId": individual_id,
        "paternalId": paternal_id or "0",
        "maternalId": maternal_id or "0",
        "sex": _choice(sex or "UNKNOWN_SEX", SEXES, "sex"),
        "affectedStatus": _choice(affected_status or "MISSING", AFFECTED_STATUSES, "affected status"),
    }


def family(family_id: str, *, proband: Dict, relatives: Sequence[Dict], persons: Sequence[Dict],
           consanguineous_parents: bool, created_by: str, versions: Optional[Dict[str, str]] = None,
           created: Optional[str] = None, files: Sequence[Dict] = ()) -> Dict:
    """A Phenopackets ``Family``.

    The Family's ``metaData`` declares every ontology used anywhere in it, as
    phenopacket-tools checks the whole Family against that one list.
    """
    if not persons:
        raise ValueError("a Family's pedigree needs at least one person")
    out: Dict = {"id": family_id, "proband": proband}
    if relatives:
        out["relatives"] = list(relatives)
    out["consanguinousParents"] = bool(consanguineous_parents)
    out["pedigree"] = {"persons": list(persons)}
    if files:
        out["files"] = list(files)
    out["metaData"] = metadata(created_by=created_by, prefixes=prefixes_used(out), versions=versions,
                               created=created)
    return out
