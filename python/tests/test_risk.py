"""pedwb.risk: the Risk tab's reader of GA4GH Pedigrees and Phenopackets Families.

(The tab's sums and its readers of drawings and PED files are in the page, and are tested by tests/risk.)
"""
import json
import os
import tempfile

from pedwb import risk

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
EXAMPLES = os.path.join(REPO, "data", "examples")


def _raises(fn, *words):
    try:
        fn()
    except ValueError as e:
        for w in words:
            assert w in str(e), (w, str(e))
        return
    raise AssertionError("no ValueError")


def test_pedigree():
    fam = risk.family(os.path.join(EXAMPLES, "okafor_ga4gh-pedigree.json"))
    assert fam["kind"] == "pedigree"
    assert len(fam["people"]) == 16
    by = {p["id"]: p for p in fam["people"]}
    keys = [c["key"] for c in fam["conditions"]]
    assert "HP:0000365" in keys and risk.FAMILY_STATUS not in keys
    # the twins with hearing loss: their parents, the cousins III-2 and III-3, and one genotype for both
    for twin in ("IV-3", "IV-4"):
        assert (by[twin]["father"], by[twin]["mother"]) == ("III-2", "III-3")
        assert by[twin]["status"]["HP:0000365"] == "affected"
    assert by["IV-4"]["twin"] == "IV-3" and by["IV-3"]["twin"] is None
    assert fam["partners"] == [["III-2", "III-3"]]
    # no one is recorded as not having it, so the tab takes people with no record as unaffected (as PedNet does)
    assert fam["unrecorded"] == "auto"
    assert not any(p["status"].get("HP:0000365") == "unaffected" for p in fam["people"])
    assert by["IV-3"]["index"] is True
    assert by["III-1"]["sex"] == "M" and by["IV-5"]["sex"] == "U"


def test_family():
    fam = risk.family(os.path.join(EXAMPLES, "okafor_phenopackets-family.json"))
    assert fam["kind"] == "family"
    # the Family's own record of who is affected comes first, and people with no record of it aren't unaffected
    assert fam["conditions"][0]["key"] == risk.FAMILY_STATUS
    assert fam["unrecordedFor"][risk.FAMILY_STATUS] == "unknown"
    by = {p["id"]: p for p in fam["people"]}
    assert by["IV-3"]["status"][risk.FAMILY_STATUS] == "affected"
    assert by["IV-1"]["status"][risk.FAMILY_STATUS] == "unaffected"
    assert by["II-3"]["status"]["MONDO:0007254"] == "affected"


def test_refused():
    # an older form of the files, to be upgraded first
    _raises(lambda: risk.family(os.path.join(EXAMPLES, "older", "studio2ga4gh-0.3_ga4gh-pedigree.json")), "Upgrade it first")
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        _raises(lambda: risk.family(bad), "not a JSON file")
        one = os.path.join(d, "one.json")
        with open(one, "w", encoding="utf-8") as fh:
            json.dump({"id": "p1", "subject": {"id": "s1"}, "phenotypicFeatures": [], "metaData": {"created": "2026-10-17T09:00:00Z", "createdBy": "test", "phenopacketSchemaVersion": "2.0", "resources": []}}, fh)
        _raises(lambda: risk.family(one), "which has no pedigree")
