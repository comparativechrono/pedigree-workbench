#!/usr/bin/env python3
"""Make the example files of the workbench: data/examples/.

The five drawings are the families of the pedigree practical
(github.com/comparativechrono/pedigree-practical), made into Pedigree Studio
drawings by python/tools/make_examples.py; python/tests/data has the same
files, for the tests. The other examples are made from them here, with the
packages in python/, so that they are always what the current versions write:

    okafor_ga4gh-pedigree.json, okafor_phenopackets-family.json   studio2ga4gh, with example-terms.json
    okafor-later_phenopackets-family.json   the same Family a visit later (the twins' hearing loss found to
                                            be sensorineural), for Compare two files: phenotk's add
    okafor.mped, cf-cousins.mped                                    studio2ped
    lynch.ped (a plain PED file, as other programs write them)      studio2ga4gh, then phenotk's PED export
    older/                       files written by older versions of studio2ga4gh and abusua2ga4gh

Dates in the made files are set to EXAMPLE_DATE, so that making them again gives the same files.

Run:  python3 build/make_example_data.py   (then python3 build/make_page.py)
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "python", "tests", "data")
OUT = os.path.join(ROOT, "data", "examples")
sys.path.insert(0, os.path.join(ROOT, "python"))

EXAMPLE_DATE = "2026-10-17"
CREATED = EXAMPLE_DATE + "T09:00:00Z"
DRAWINGS = ["okafor", "price", "lynch", "cf-cousins", "features"]


def fix_dates(path):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)

    def walk(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k == "created" and isinstance(v, str):
                    o[k] = CREATED
                elif k == "date" and isinstance(v, str) and len(v) == 10:
                    o[k] = EXAMPLE_DATE
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def main():
    from studio2ga4gh import convert_file as to_ga4gh
    from studio2ped import convert_file as to_ped
    os.makedirs(os.path.join(OUT, "older"), exist_ok=True)
    for n in DRAWINGS:
        shutil.copyfile(os.path.join(SRC, n + ".studio.json"), os.path.join(OUT, n + ".studio.json"))
    shutil.copyfile(os.path.join(SRC, "example-terms.json"), os.path.join(OUT, "example-terms.json"))
    # (named so that their kind shows in the name, as the workbench's tools name their files)
    for f in sorted(os.listdir(os.path.join(SRC, "legacy"))):
        name = f.replace("_ga4gh.json", "_ga4gh-pedigree.json").replace("_family.json", "_phenopackets-family.json") \
                .replace("_phenopackets.json", "_phenopackets-family.json")
        shutil.copyfile(os.path.join(SRC, "legacy", f), os.path.join(OUT, "older", name))
    with open(os.path.join(SRC, "example-terms.json"), encoding="utf-8") as fh:
        terms = json.load(fh)
    r = to_ga4gh(os.path.join(OUT, "okafor.studio.json"), "okafor", OUT, terms=terms, created=CREATED)
    for path, _ in r.files:
        fix_dates(path)
    with tempfile.TemporaryDirectory() as tmp:
        for n in ("okafor", "cf-cousins"):
            r = to_ped(os.path.join(OUT, n + ".studio.json"), output_prefix=n, output_dir=tmp)
            for path, _ in r.files:
                shutil.copyfile(path, os.path.join(OUT, os.path.basename(path)))
        # a plain PED file, of the kind other programs write: six columns, pedigree numbers as the ids, no header
        from phenopacket_toolkit import read
        from phenopacket_toolkit.io.writers import to_ped as family_to_ped
        r = to_ga4gh(os.path.join(OUT, "lynch.studio.json"), "lynch", tmp, terms=terms, created=CREATED, outputs=("family",))
        with open(os.path.join(OUT, "lynch.ped"), "w", encoding="utf-8") as fh:
            fh.write(family_to_ped(read(r.files[0][0])))
    # the Okafor Family a visit later, to compare with the first: the twins' hearing loss is sensorineural
    import phenopacket_toolkit as ptk
    from phenopacket_toolkit.ops import add
    doc = ptk.read(os.path.join(OUT, "okafor_phenopackets-family.json"))
    for who in ("IV-3", "IV-4"):
        doc = add(doc, who, phenotypes=[{"id_": "HP:0008527", "label": "Congenital sensorineural hearing impairment"}])
    later = os.path.join(OUT, "okafor-later_phenopackets-family.json")
    ptk.write(doc, later)
    fix_dates(later)
    print("\n".join(sorted(os.path.relpath(os.path.join(dp, f), OUT) for dp, _, fs in os.walk(OUT) for f in fs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
