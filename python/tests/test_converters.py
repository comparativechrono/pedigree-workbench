"""Tests for the workbench's copies of studio2ga4gh and ga4gh2studio."""
import json
import os
from collections import Counter

import ga4gh2studio
import studio2ga4gh
from pedigree_ga4gh import from_document, kin, loads, validate
from studio2ga4gh.session import parse

DATA = os.path.join(os.path.dirname(__file__), "data")
CREATED = "2026-10-17T12:00:00Z"
EXAMPLES = ["okafor", "price", "lynch", "cf-cousins"]


def session(name):
    with open(os.path.join(DATA, name + ".studio.json"), encoding="utf-8") as fh:
        return json.load(fh)


def terms():
    with open(os.path.join(DATA, "example-terms.json"), encoding="utf-8") as fh:
        return json.load(fh)


def errors(doc):
    return [f for f in validate(doc) if f.severity == "error"]


def convert(name, **kw):
    r = studio2ga4gh.convert(session(name), name, terms=terms(), created=CREATED, **kw)
    return r, loads(r.files[0][1]), loads(r.files[1][1])


def rels(doc):
    return {(r["individualId"], r["relation"]["label"], r["relativeId"]) for r in doc["relationships"]}


def test_examples_convert_to_valid_files():
    for name in EXAMPLES:
        r, ped, fam = convert(name)
        assert r.unmatched == [], name
        assert errors(ped) == [] and errors(fam) == [], name
        assert ped["individuals"] and fam["pedigree"]["persons"]


def test_ids_are_the_pedigree_numbers_studio_shows():
    s = parse(session("okafor"))
    nums = s.numbers()
    assert sorted(set(v.split("-")[0] for v in nums.values())) == ["I", "II", "III", "IV"]
    r, ped, fam = convert("okafor")
    assert all(i["subject"]["id"].count("-") == 1 for i in ped["individuals"])


def test_features_drawing():
    r = studio2ga4gh.convert(session("features"), "features", created=CREATED)
    ped, fam = loads(r.files[0][1]), loads(r.files[1][1])
    assert errors(ped) == [] and errors(fam) == []
    got = rels(ped)
    labels = Counter(lab for _, lab, _ in got)
    # surrogate and donor marks
    assert labels["isGestationalCarrierOf"] == 1 and labels["isSpermDonorOf"] == 1
    # dashed line and the adopted symbol
    assert labels["isAdoptiveParentOf"] == 2
    # separated, consanguineous-separated, and couples whose only "children" are markers
    assert labels["isSeparatedPartnerOf"] == 1 and labels["isSeparatedConsanguineousPartnerOf"] == 1
    assert labels["isPartnerOf"] == 2
    # parent of unknown sex
    assert labels["isBiologicalParentOf"] == 2
    # triplets: c2-c3 identical, c3-c4 non-identical, all given relative to the leftmost
    twins = [(a, lab, b) for a, lab, b in got if "MultipleBirth" in lab]
    assert len(twins) == 2 and len({a for a, _, _ in twins}) == 1
    assert {lab for _, lab, _ in twins} == {"isMonozygoticMultipleBirthSiblingOf",
                                            "isPolyzygoticMultipleBirthSiblingOf"}
    # markers are not people
    assert len(ped["individuals"]) == 27
    narrative = ped["narrative"]
    for words in ("no children", "infertility", "pregnancy loss", "is a carrier", "presymptomatic carrier",
                  "is a pregnancy"):
        assert words in narrative, words
    # the CURIE written in the colour key is used; unnamed conditions are reported
    assert "Condition X [MONDO:0009061]" not in r.unmatched
    assert set(r.unmatched) == {"Condition Y", "Condition Z"}
    proband = fam["proband"]
    assert proband["diseases"][0]["term"]["id"] == "MONDO:0009061"
    # the gestational carrier is not the child's mother in the PED-style pedigree
    persons = {p["individualId"]: p for p in fam["pedigree"]["persons"]}
    carried = [b for a, lab, b in got if lab == "isGestationalCarrierOf"][0]
    carrier = [a for a, lab, b in got if lab == "isGestationalCarrierOf"][0]
    assert persons[carried]["maternalId"] != carrier
    assert any("stands for 3 people" in w for w in r.warnings)
    assert any("does not name" in w for w in r.warnings)


def test_notes_keep_ids_as_they_are():
    """Pedigree Studio's own ids are in lower case (p6, c1): a note about one must not capitalise it."""
    data = session("features")
    carriers = [p["id"] for p in data["persons"] if p.get("centerText") == "dot"]
    r = studio2ga4gh.convert(data, "features", ids="studio", created=CREATED)
    narrative = loads(r.files[0][1])["narrative"]
    assert carriers and all("{} is a carrier.".format(c) in narrative for c in carriers)
    assert all(c.upper() not in narrative.split() for c in carriers)


def test_round_trip_studio_ga4gh_studio():
    def signature(doc):
        k, _ = from_document(doc)
        sex = {m.id: m.sex for m in k.members}

        def key(r):
            a, b = sex[r.individual], sex[r.relative]
            if kin.TERMS[r.kin].symmetric:      # the direction of a symmetric relation does not matter
                a, b = sorted((a, b))
            return a, r.kin, b
        return (len(k.members), Counter(key(r) for r in k.relations),
                Counter(t.id for m in k.members for t in m.terms), sum(m.index for m in k.members))
    for name in EXAMPLES + ["features"]:
        r1 = studio2ga4gh.convert(session(name), name, terms=terms(), created=CREATED)
        ped1 = loads(r1.files[0][1])
        drawn = ga4gh2studio.convert(ped1)
        r2 = studio2ga4gh.convert(drawn.session, name, terms=terms(), created=CREATED)
        ped2 = loads(r2.files[0][1])
        assert signature(ped1) == signature(ped2), name


def test_ga4gh2studio_refuses_old_files_with_a_clear_message():
    with open(os.path.join(DATA, "legacy", "studio2ga4gh-0.3_ga4gh.json"), encoding="utf-8") as fh:
        old = json.load(fh)
    try:
        ga4gh2studio.convert(old)
    except ga4gh2studio.LegacyFileError as exc:
        assert "upgrade" in str(exc).lower()
    else:
        raise AssertionError("an old file was accepted")


def test_ga4gh2studio_draws_a_family_file():
    r, ped, fam = convert("price")
    drawn = ga4gh2studio.convert(None, fam).session
    shapes = Counter(p["shape"] for p in drawn["persons"])
    assert drawn["childLinks"] and drawn["partnerships"]
    assert sum(shapes.values()) >= len(fam["pedigree"]["persons"])
