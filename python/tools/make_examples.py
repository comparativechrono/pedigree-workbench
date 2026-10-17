"""Make the example Pedigree Studio files in examples/ from the pedigree practical's families.

The families come from https://github.com/comparativechrono/pedigree-practical
(data/pedigrees/*.json). This is a Python port of that practical's
``toSession()`` (assets/js/pedigree.js), which turns one of its family files
into a Pedigree Studio session.

    python python/tools/make_examples.py PATH/TO/pedigree-practical/data/pedigrees examples/
"""
import json
import sys
from pathlib import Path

UNIT, ROW, X0, Y0 = 52, 130, 200, 160
BLACK = "#1a2332"


def shape_of(p):
    if p.get("line") == "none":
        return "no-offspring"
    if p.get("line") == "infertile":
        return "infertile"
    if p.get("loss"):
        return "miscarriage"
    s = {"M": "male", "F": "female"}.get(p.get("sex"), "unknown")
    return "adopted-" + s if p.get("adopted") else s


def fill_of(p, colours):
    def colour(key):
        if key is True:
            return BLACK
        return (colours or {}).get(key) or key or BLACK
    out = {"fillMode": "none", "fillColor": BLACK, "quarters": [None] * 4, "halves": [None, None],
           "shadingPattern": "stripes", "shadingCoverage": "full"}
    a = p.get("affected")
    if not a:
        return out
    if isinstance(a, list):
        cs = [colour(x) for x in a]
        if len(cs) == 1:
            out.update(fillMode="solid", fillColor=cs[0])
        elif len(cs) == 2:
            out.update(fillMode="half", halves=[cs[0], cs[1]])
        else:
            out.update(fillMode="quartered", quarters=(cs + [None] * 4)[:4])
        return out
    out.update(fillMode="solid", fillColor=colour(a))
    return out


def centre_of(p):
    if p.get("carrier"):
        return "dot"
    if p.get("pregnancy"):
        return "P"
    if p.get("donor"):
        return "D"
    if p.get("multiple") is not None:
        return str(p["multiple"])
    return ""


def to_session(scn):
    unit, row = scn.get("unit", UNIT), scn.get("row", ROW)
    persons = []
    for p in scn.get("people", []):
        d = {"id": "p-" + p["id"], "shape": shape_of(p),
             "x": X0 + (p.get("x") or 0) * unit, "y": Y0 + (p.get("gen") or 0) * row + (p.get("dy") or 0),
             "text": p.get("text", ""), "deceased": bool(p.get("deceased")), "proband": bool(p.get("proband")),
             "centerText": centre_of(p),
             "miscarriageSex": ({"M": "male", "F": "female"}.get(p.get("sex"), "unknown") if p.get("loss") else "unknown"),
             "noSnap": bool(p.get("noSnap")), "siblingFixed": False, "customLabel": p.get("tag") or "Lbl"}
        d.update(fill_of(p, scn.get("colours")))
        persons.append(d)
    n = 0
    partnerships, couple_id = [], {}
    for c in scn.get("couples", []):
        a, b = (c[0], c[1]) if isinstance(c, list) else (c["a"], c["b"])
        typ = (c.get("type") if isinstance(c, dict) else None) or "normal"
        n += 1
        pid = "pship-{}".format(n)
        partnerships.append({"id": pid, "fromId": "p-" + a, "toId": "p-" + b, "type": typ})
        couple_id[a + "+" + b] = couple_id[b + "+" + a] = pid
    child_links, twin_links = [], []
    for f in scn.get("children", []):
        pid = couple_id[f["of"][0] + "+" + f["of"][1]]
        for k in f["kids"]:
            n += 1
            child_links.append({"id": "child-{}".format(n), "partnershipId": pid, "childId": "p-" + k,
                                "branchYOffset": 0, "dashed": k in (f.get("adoptedIn") or [])})
    for t in scn.get("twins", []):
        cl = next((c for c in child_links if c["childId"] == "p-" + t["a"]), None)
        n += 1
        twin_links.append({"id": "twin-{}".format(n), "child1Id": "p-" + t["a"], "child2Id": "p-" + t["b"],
                           "type": t.get("type") or "identical", "partnershipId": cl["partnershipId"] if cl else None})
    legend = {}
    for k, label in (scn.get("key") or {}).items():
        legend[(scn.get("colours") or {}).get(k) or k] = label
    key_at = scn.get("keyAt") or [0, 0]
    return {
        "version": 4, "personIdCounter": 0, "labelIdCounter": 0, "lineIdCounter": n,
        "persons": persons,
        "labels": [{"id": "label-{}".format(i + 1), "x": X0 + l["x"] * unit, "y": Y0 + l["gen"] * row,
                    "text": l["text"], "size": l.get("size", 13), "bordered": bool(l.get("bordered"))}
                   for i, l in enumerate(scn.get("labels", []))],
        "partnerships": partnerships, "childLinks": child_links, "twinLinks": twin_links,
        "legendLabels": legend, "legendVisible": bool(scn.get("key")),
        "legendX": X0 + key_at[0] * unit, "legendY": Y0 + key_at[1] * row,
        "numberingMode": scn.get("numbering", "numbers"),
        "partnerGapMultiplier": 2, "childHeightMultiplier": 2.5, "drawStrokes": [],
    }


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    for name in sys.argv[3:] or [p.stem for p in sorted(src.glob("*.json"))]:
        scn = json.loads((src / (name + ".json")).read_text(encoding="utf-8"))
        out = dst / "{}.studio.json".format(name)
        out.write_text(json.dumps(to_session(scn), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", out)


if __name__ == "__main__":
    main()
