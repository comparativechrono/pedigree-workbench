"""Tests for pedigree-ga4gh: KIN, the builders, the readers, validation and upgrading."""
import copy
import json
import os

from pedigree_ga4gh import (Kindred, Member, Relation, Term, from_document, identify_legacy, kin,
                            to_ga4gh_pedigree, to_phenopackets_family, upgrade, validate)
from pedigree_ga4gh.validate import errors

DATA = os.path.join(os.path.dirname(__file__), "data")
LEGACY = os.path.join(DATA, "legacy")
CREATED = "2026-10-17T12:00:00Z"


def codes(findings, severity="error"):
    return sorted({f.code for f in findings if f.severity == severity})


def load(name):
    with open(os.path.join(LEGACY, name), encoding="utf-8") as fh:
        return json.load(fh)


# -- KIN -----------------------------------------------------------------------

def test_kin_matches_kin_owl():
    # spot checks against kin.owl (family_history_terminology, 2024-09-16)
    assert kin.get("KIN:027").label == "isBiologicalMotherOf"
    assert kin.get("KIN:028").label == "isBiologicalFatherOf"
    assert kin.get("KIN:010").label == "isMonozygoticMultipleBirthSiblingOf"
    assert kin.get("KIN:011").label == "isPolyzygoticMultipleBirthSiblingOf"
    assert kin.get("KIN:004").label == "isSpermDonorOf"
    assert kin.get("KIN:039").label == "hasGestationalCarrier"
    assert kin.get("KIN:050").label == "isSeparatedPartnerOf"
    assert kin.get("KIN:026").symmetric and not kin.get("KIN:027").symmetric
    assert kin.get("KIN:027").subject_sex == "FEMALE"
    assert kin.is_a("KIN:027", "KIN:003") and kin.is_a("KIN:004", "KIN:003")
    assert not kin.is_a("KIN:005", "KIN:003")      # a gestational carrier is not a biological parent
    assert "KIN:031" not in kin.TERMS                # hasSex is not a relation between people


def test_kin_modernise_old_codes_and_labels():
    assert kin.modernise("KIN:039", "isSpermDonorOf") == (kin.TERMS["KIN:004"], False)
    assert kin.modernise("KIN:011", "isDizygoticMultipleBirthSiblingOf") == (kin.TERMS["KIN:011"], False)
    assert kin.modernise("KIN:041", "hasBiologicalMother") == (kin.TERMS["KIN:027"], True)
    assert kin.modernise("KIN:048", "isBrokenPartner") == (kin.TERMS["KIN:050"], False)
    assert kin.modernise("KIN:999", "") is None


# -- writing ----------------------------------------------------------------------

def trio():
    return Kindred("FAM1", members=[
        Member("MOTHER", sex="FEMALE", vital_status="ALIVE"),
        Member("FATHER", sex="MALE", vital_status="ALIVE"),
        Member("CHILD", index=True, terms=[Term("cystic fibrosis", "MONDO:0009061")])],
        relations=[Relation("MOTHER", "KIN:027", "CHILD"), Relation("FATHER", "KIN:028", "CHILD")],
        versions={"MONDO": "2026-10-06"})


def test_pedigree_has_the_documented_shape():
    """The basic trio of https://pedigree.readthedocs.io/en/latest/examples.html."""
    doc, warnings = to_ga4gh_pedigree(trio(), created_by="test", created=CREATED)
    assert warnings == []
    assert doc["id"] == "FAM1" and doc["indexPatients"] == ["CHILD"]
    subjects = [i["subject"]["id"] for i in doc["individuals"]]
    assert subjects == ["MOTHER", "FATHER", "CHILD"]
    assert all("metaData" in i for i in doc["individuals"])
    rels = [(r["individualId"], r["relation"]["id"], r["relation"]["label"], r["relativeId"])
            for r in doc["relationships"]]
    assert rels == [("MOTHER", "KIN:027", "isBiologicalMotherOf", "CHILD"),
                    ("FATHER", "KIN:028", "isBiologicalFatherOf", "CHILD")]
    child = doc["individuals"][2]
    assert child["diseases"] == [{"term": {"id": "MONDO:0009061", "label": "cystic fibrosis"}}]
    res = child["metaData"]["resources"]
    assert [r["namespacePrefix"] for r in res] == ["MONDO"] and res[0]["version"] == "2026-10-06"
    assert codes(validate(doc)) == []


def test_family_has_ped_pedigree_and_explicit_flags():
    fam, warnings = to_phenopackets_family(trio(), created_by="test", created=CREATED)
    assert fam["proband"]["subject"]["id"] == "CHILD"
    assert fam["consanguinousParents"] is False
    persons = {p["individualId"]: p for p in fam["pedigree"]["persons"]}
    assert persons["CHILD"]["paternalId"] == "FATHER" and persons["CHILD"]["maternalId"] == "MOTHER"
    assert persons["CHILD"]["affectedStatus"] == "AFFECTED"
    assert persons["MOTHER"]["affectedStatus"] == "MISSING"
    assert fam["metaData"]["phenopacketSchemaVersion"] == "2.0"
    assert codes(validate(fam)) == []


def test_unmatched_terms_are_left_out_with_a_warning():
    k = trio()
    k.members[2].terms.append(Term("Something odd"))
    doc, warnings = to_ga4gh_pedigree(k, created_by="test", created=CREATED)
    assert any("Something odd" in w for w in warnings)
    assert len(doc["individuals"][2]["diseases"]) == 1
    assert codes(validate(doc)) == []


def test_symmetric_relations_are_written_once():
    k = trio()
    k.relations += [Relation("MOTHER", "KIN:026", "FATHER"), Relation("FATHER", "KIN:026", "MOTHER")]
    doc, _ = to_ga4gh_pedigree(k, created_by="test", created=CREATED)
    assert sum(r["relation"]["id"] == "KIN:026" for r in doc["relationships"]) == 1


def test_consanguinity_from_shared_ancestor():
    k = Kindred("F", members=[Member(x, sex=s) for x, s in
                              [("GF", "MALE"), ("GM", "FEMALE"), ("A", "MALE"), ("B", "FEMALE"),
                               ("A1", "MALE"), ("B1", "FEMALE"), ("P", "MALE")]])
    k.members[-1].index = True
    for par, code in (("GF", "KIN:028"), ("GM", "KIN:027")):
        k.relations += [Relation(par, code, "A"), Relation(par, code, "B")]
    k.relations += [Relation("A", "KIN:028", "A1"), Relation("B", "KIN:027", "B1"),
                    Relation("A1", "KIN:028", "P"), Relation("B1", "KIN:027", "P")]
    fam, _ = to_phenopackets_family(k, created_by="test", created=CREATED)
    assert fam["consanguinousParents"] is True


def test_consanguinity_is_second_cousins_or_closer():
    """KIN's isConsanguineousPartnerOf, and the usual clinical sense: related as second cousins or closer."""
    k = Kindred("F")
    def child(name, sex, *parents):
        k.members.append(Member(name, sex=sex))
        for p in parents:
            k.relations.append(Relation(p, "KIN:028" if k.member(p).sex == "MALE" else "KIN:027", name))
    child("GGF", "MALE")
    child("GGM", "FEMALE")
    child("A", "MALE", "GGF", "GGM")
    child("B", "FEMALE", "GGF", "GGM")
    child("A1", "MALE", "A")
    child("B1", "FEMALE", "B")          # A1 and B1: first cousins
    child("A2", "MALE", "A1")
    child("B2", "FEMALE", "B1")         # A2 and B2: second cousins
    child("A3", "MALE", "A2")
    child("B3", "FEMALE", "B2")         # A3 and B3: third cousins
    assert k.consanguineous("A1", "B1") and k.consanguineous("A2", "B2")
    assert not k.consanguineous("A3", "B3")
    assert k.consanguineous("A", "B1")                     # uncle and niece
    assert k.consanguineous("GGF", "A2")                   # great-grandfather
    assert not k.consanguineous("GGF", "A3")               # four generations


def test_terms_from_other_vocabularies():
    k = trio()
    k.member("CHILD").terms += [Term("breast cancer", "SNOMEDCT:254837009"), Term("asthma", "DOID:2841"),
                                Term("something", "FOO:123")]
    doc, warnings = to_ga4gh_pedigree(k, created_by="test", created=CREATED)
    child = doc["individuals"][2]
    assert [d["term"]["id"] for d in child["diseases"]] == ["MONDO:0009061", "SNOMEDCT:254837009", "DOID:2841"]
    assert all(r["url"] and r["iriPrefix"] for r in child["metaData"]["resources"])
    assert codes(validate(doc)) == []
    # FOO cannot be declared in metaData, so it is left out rather than making the file invalid
    assert any("FOO:123" in w and "left out" in w for w in warnings)
    # unless the file it came from declared it in full: then it is kept, and declared the same way
    child["diseases"].append({"term": {"id": "FOO:123", "label": "something"}})
    child["metaData"]["resources"].append({"id": "foo", "name": "Foo", "url": "https://foo.example",
                                           "version": "1", "namespacePrefix": "FOO",
                                           "iriPrefix": "https://foo.example/"})
    again, _ = to_ga4gh_pedigree(from_document(doc)[0], created_by="test", created=CREATED)
    foo = [r for r in again["individuals"][2]["metaData"]["resources"] if r["namespacePrefix"] == "FOO"]
    assert foo and foo[0]["url"] == "https://foo.example" and codes(validate(again)) == []
    # an empty field in a resource is an error: phenopacket-tools reads it as missing
    bad = copy.deepcopy(doc)
    bad["individuals"][2]["metaData"]["resources"][0]["iriPrefix"] = ""
    assert "empty-resource-field" in codes(validate(bad))


def test_a_person_whose_id_is_zero_is_reported():
    k = trio()
    k.members[0].id = "0"
    k.relations[0].individual = "0"
    fam, _ = to_phenopackets_family(k, created_by="test", created=CREATED)
    assert "zero-id" in codes(validate(fam))


def test_round_trip_through_both_files():
    k = trio()
    ped, _ = to_ga4gh_pedigree(k, created_by="test", created=CREATED)
    fam, _ = to_phenopackets_family(k, created_by="test", created=CREATED)
    for doc in (ped, fam):
        k2, warnings = from_document(doc)
        assert warnings == []
        assert {m.id for m in k2.members} == {"MOTHER", "FATHER", "CHILD"}
        assert {(r.individual, r.kin, r.relative) for r in k2.relations} >= {
            ("MOTHER", "KIN:027", "CHILD"), ("FATHER", "KIN:028", "CHILD")}
        assert [t.id for t in k2.member("CHILD").terms] == ["MONDO:0009061"]
        assert k2.member("CHILD").index


def test_proto_field_names_are_read():
    doc, _ = to_ga4gh_pedigree(trio(), created_by="test", created=CREATED)
    text = json.dumps(doc).replace('"individualId"', '"individual_id"').replace('"relativeId"', '"relative_id"') \
        .replace('"indexPatients"', '"index_patients"').replace('"metaData"', '"meta_data"')
    snake = json.loads(text)
    assert codes(validate(snake)) == []
    assert "proto-names" in codes(validate(snake), "info")
    k, _ = from_document(snake)
    assert len(k.relations) == 2 and k.member("CHILD").index


# -- validation ---------------------------------------------------------------------

def test_validation_catches_the_usual_mistakes():
    doc, _ = to_ga4gh_pedigree(trio(), created_by="test", created=CREATED)
    bad = copy.deepcopy(doc)
    bad["individuals"][0]["subject"]["name"] = "Jane"                  # not a field
    bad["individuals"][2]["diseases"][0]["term"]["id"] = ""             # empty id
    bad["individuals"][2]["phenotypicFeatures"] = [{"type": {"id": "HP:0000365", "label": "Hearing impairment"}}]
    bad["relationships"][0]["relation"]["label"] = "isBiologicalMother"  # not KIN's label
    bad["relationships"][1]["relativeId"] = "NOBODY"
    bad["relationships"].append({"individualId": "FATHER", "relation": {"id": "KIN:027",
                                 "label": "isBiologicalMotherOf"}, "relativeId": "CHILD"})
    found = validate(bad)
    assert {"unknown-field", "empty-term-id", "undeclared-prefix", "unknown-person"} <= set(codes(found))
    assert {"kin-label", "relation-sex"} <= set(codes(found, "warning"))


def test_validation_of_a_family():
    fam, _ = to_phenopackets_family(trio(), created_by="test", created=CREATED)
    bad = copy.deepcopy(fam)
    del bad["proband"]["metaData"]
    bad["pedigree"]["persons"][2]["maternalId"] = "ELSEWHERE"
    bad["metaData"].pop("phenopacketSchemaVersion")
    found = codes(validate(bad))
    assert {"missing-field", "missing-parent"} <= set(found)


# -- older files ------------------------------------------------------------------------

def test_old_studio2ga4gh_pedigree_is_recognised_and_upgraded():
    old = load("studio2ga4gh-0.3_ga4gh.json")
    assert identify_legacy(old).form == "studio2ga4gh-pedigree"
    assert codes(validate(old)) == ["legacy-format"]
    new, changes, todo = upgrade(old, created=CREATED)
    assert identify_legacy(new) is None
    assert codes(validate(new)) == []
    assert any("Phenopackets form" in c for c in changes)
    assert todo and "affected" in todo[0]
    assert new["relationships"] and all(r["relation"]["id"] in kin.TERMS for r in new["relationships"])
    labels = {r["relation"]["label"] for r in new["relationships"]}
    assert "isDizygoticMultipleBirthSiblingOf" not in labels


def test_old_studio2ga4gh_family_is_upgraded_except_for_terms():
    old = load("studio2ga4gh-0.3_phenopackets.json")
    assert identify_legacy(old) is not None
    new, changes, todo = upgrade(old, created=CREATED)
    remaining = codes(validate(new))
    assert remaining == ["empty-term-id"]          # only the conditions still need ontology terms
    assert len(todo) == 3
    assert all("metaData" in p for p in [new["proband"]] + new["relatives"])


def test_old_abusua_pedigree_is_upgraded():
    old = load("abusua2ga4gh-0.2_ga4gh.json")
    assert identify_legacy(old).form == "abusua2ga4gh-pedigree"
    new, changes, todo = upgrade(old, created=CREATED)
    for ind in new["individuals"]:
        assert "name" not in ind["subject"] and "diseases" not in ind["subject"]
        assert "metaData" in ind and "vitalStatus" in ind["subject"]
    assert all(set(r) == {"individualId", "relation", "relativeId"} for r in new["relationships"])
    assert new["narrative"].startswith("Asante family. i1 and i3: paternity reported, not confirmed.")
    assert codes(validate(new)) == ["empty-term-id"]
    # foster and social parents were written as adoptive ones: listed to be checked, not changed
    assert sum("KIN:021 isFosterParentOf" in t for t in todo) == 2
    assert all(r["relation"]["id"] != "KIN:021" for r in new["relationships"])


def test_old_abusua_family_names_are_removed():
    old = load("abusua2ga4gh-0.2_family.json")
    new, changes, todo = upgrade(old, created=CREATED)
    for p in [new["proband"]] + new.get("relatives", []):
        assert "name" not in p["subject"] and "alternate_ids" not in p["subject"]
        for r in p["metaData"].get("resources", []):
            assert r["version"]
    assert any("removed the name" in c for c in changes)


def test_old_abusua_family_without_names_is_recognised():
    """abusua2ga4gh 0.2 put names in subject only with --include-names; its Family without them is old too."""
    old = load("abusua2ga4gh-0.2_family_no-names.json")
    assert "name" not in json.dumps([p["subject"] for p in [old["proband"]] + old["relatives"]])
    found = identify_legacy(old)
    assert found is not None and found.form == "phenopackets" and found.upgradable
    new, changes, todo = upgrade(old, created=CREATED)
    assert "HP:0032500" not in json.dumps(new)
    assert any("carrier" in t for t in todo)


def test_the_carrier_mistake_is_found_and_removed():
    # abusua2ga4gh 0.2 wrote carriers as HP:0032500, which is "Exacerbated by tobacco use"
    old = load("abusua2ga4gh-0.2_family.json")
    assert "HP:0032500" in json.dumps(old)
    assert "carrier-term" in codes(validate(old))
    new, changes, todo = upgrade(old, created=CREATED)
    assert "HP:0032500" not in json.dumps(new)
    assert "carrier-term" not in codes(validate(new))
    assert any("was recorded as a carrier" in t for t in todo)
    # in a GA4GH Pedigree, the narrative says who is a carrier, as studio2ga4gh writes it
    ped, _ = to_ga4gh_pedigree(trio(), created_by="test", created=CREATED)
    child = ped["individuals"][-1]
    child.setdefault("phenotypicFeatures", []).append({"type": {"id": "HP:0032500", "label": "Heterozygous carrier"}})
    assert "carrier-term" in codes(validate(ped))
    new, changes, todo = upgrade(ped, created=CREATED)
    assert "HP:0032500" not in json.dumps(new)
    assert "{} is a carrier.".format(child["subject"]["id"]) in new["narrative"]
    assert not errors(validate(new))
    # the real term, with its own label, is left alone
    ped2, _ = to_ga4gh_pedigree(trio(), created_by="test", created=CREATED)
    ped2["individuals"][-1].setdefault("phenotypicFeatures", []).append(
        {"type": {"id": "HP:0032500", "label": "Exacerbated by tobacco use"}})
    assert "carrier-term" not in codes(validate(ped2))


# the trio of the draft of version 1 of the standard (ga4gh/pedigree pull request 50, 2026, not approved), as
# proto3 JSON writes it, and as the draft's own examples spell it
V1_DRAFT_TRIO = {
    "id": "FAM1",
    "narrative": "A GA4GH Pedigree of a trio with an affected child",
    "indexPatients": ["CHILD"],
    "individuals": [
        {"id": "MOTHER", "sexAssignedAtBirth": "ASSIGNED_FEMALE"},
        {"id": "FATHER", "sexAssignedAtBirth": "ASSIGNED_MALE"},
        {"id": "CHILD", "eggParentId": "MOTHER", "spermParentId": "FATHER"},
    ],
    "relationships": [
        {"individual": "MOTHER", "relative": "CHILD",
         "biologicalRelationship": [{"id": "KIN:027", "label": "isBiologicalMotherOf"}]},
        {"individual": "FATHER", "relative": "CHILD",
         "biologicalRelationship": [{"id": "KIN:028", "label": "isBiologicalFatherOf"}]},
    ],
}
V1_DRAFT_TRIO_AS_IN_ITS_EXAMPLES = {
    "id": "FAM1",
    "individuals": [
        {"id": "MOTHER", "sex_assigned_at_birth": "assigned female"},
        {"id": "FATHER", "sex_assigned_at_birth": "assigned male"},
        {"id": "CHILD", "egg_parent": "MOTHER", "sperm_parent": "FATHER"},
    ],
    "relationships": [
        {"individual": "MOTHER", "relative": "CHILD", "biological_relationship": [{"id": "KIN:027"}]},
    ],
    "index_patients": ["CHILD"],
}


def test_the_draft_of_version_1_is_recognised_and_not_upgraded():
    from ga4gh2studio.converter import LegacyFileError as StudioError, convert
    from phenopacket_toolkit.io.readers import LegacyFileError, from_dict
    for doc in (V1_DRAFT_TRIO, V1_DRAFT_TRIO_AS_IN_ITS_EXAMPLES):
        old = identify_legacy(doc)
        assert old.form == "pedigree-v1-draft" and not old.upgradable
        assert codes(validate(doc)) == ["draft-form"]
        for read in (upgrade, from_dict, convert):
            try:
                read(doc)
            except (ValueError, LegacyFileError, StudioError) as exc:
                assert "draft of version 1" in str(exc) and "upgrade" not in str(exc)
            else:
                raise AssertionError("{} should refuse the draft form".format(read.__name__))
    # studio2ga4gh 0.3's relationships also have 'individual' and 'relative': it is still told apart
    assert identify_legacy(load("studio2ga4gh-0.3_ga4gh.json")).form == "studio2ga4gh-pedigree"
    assert identify_legacy(load("studio2ga4gh-0.3_ga4gh.json")).upgradable


def test_upgrading_a_standard_file_changes_nothing_that_matters():
    doc, _ = to_ga4gh_pedigree(trio(), created_by="test", created=CREATED)
    new, changes, todo = upgrade(doc, created=CREATED)
    assert new == doc and changes == [] and todo == []


def test_against_phenopacket_tools_schemas():
    """Runs only when PHENOPACKET_TOOLS_SCHEMAS names a folder of phenopacket-tools' v2 JSON schemas."""
    folder = os.environ.get("PHENOPACKET_TOOLS_SCHEMAS")
    if not folder:
        return
    import sys
    from pathlib import Path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    import official_check
    reg = official_check.registry(Path(folder))
    ped, _ = to_ga4gh_pedigree(trio(), created_by="test", created=CREATED)
    fam, _ = to_phenopackets_family(trio(), created_by="test", created=CREATED)
    for doc in (ped, fam):
        kind, problems = official_check.check(doc, Path(folder), reg)
        assert problems == [], problems
