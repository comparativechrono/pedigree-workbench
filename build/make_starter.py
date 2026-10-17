#!/usr/bin/env python3
"""Write the notebook a new user finds in ~/notebooks: data/starter/pedigree-tools.ipynb.

It walks through the pedigree packages in Python on the example files. Every code cell is run by
python/tests/test_starter.py (with the paths changed to this repository's), so it stays correct.

Run:  python3 build/make_starter.py   (then python3 build/make_page.py)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "data", "starter", "pedigree-tools.ipynb")

CELLS = [
    ("md", """# The pedigree packages in Python

This notebook uses the workbench's Python packages directly – the same packages that the **Tools** tab and the
**Terminal** run. Run the cells from the top: click a cell and press **Shift+Enter**. The first one starts Python in
your browser, which takes a few seconds the first time.

The example files are in `/data/examples` (read-only); what you make goes into your own folder, `~` (`/home/user`).
On your own computer the same code works after `pip install studio2ped studio2ga4gh …` – with the versions noted in
the help (Reference → Versions)."""),
    ("md", """## A Pedigree Studio drawing

A drawing is a JSON file: the people (with their symbols, fills and positions), the couples, the children, twins and the
colour key. `studio2ga4gh` reads it into Python objects and works out the pedigree numbers (I-1, II-3 …) as the Studio
shows them."""),
    ("code", """import json
from studio2ga4gh import parse_session

data = json.load(open("/data/examples/okafor.studio.json"))
drawing = parse_session(data)
numbers = drawing.numbers()
people = [p for p in drawing.persons.values() if not p.is_marker]
print(len(people), "people; the colour key:", drawing.legend)
for p in sorted(people, key=lambda p: numbers[p.id])[:6]:
    print(numbers[p.id], p.sex, "affected" if p.filled else "", drawing.condition_names(p))"""),
    ("md", """## Drawing → GA4GH Pedigree and Phenopackets Family

The conditions in the key need ontology terms: here they come from a terms file (the **Match conditions to terms** tool
in the Tools tab makes one). A condition without a term is left out, with a note."""),
    ("code", """import os
from studio2ga4gh import convert_file

os.makedirs("/home/user/results", exist_ok=True)
terms = json.load(open("/data/examples/example-terms.json"))
result = convert_file("/data/examples/okafor.studio.json", "okafor-nb", "/home/user/results", terms=terms)
print(result.summary)
for path, _ in result.files:
    print("wrote", path)"""),
    ("md", """## Checking a file against the standard

`pedigree_ga4gh` is the one GA4GH implementation the other packages share. `validate` applies the checks of the
Phenopackets v2 schema and of phenopacket-tools, and those of the GA4GH Pedigree (KIN relations, ids, parents)."""),
    ("code", """import pedigree_ga4gh as pg

doc = pg.load("/home/user/results/okafor-nb_ga4gh-pedigree.json")
findings = pg.validate(doc)
print(pg.render_findings(findings))

old = pg.load("/data/examples/older/studio2ga4gh-0.3_ga4gh-pedigree.json")
n = len(pg.errors(pg.validate(old)))
print(n, "error" if n == 1 else "errors", "in a file from studio2ga4gh 0.3")"""),
    ("md", """## The family as Python objects

`from_document` reads any of the GA4GH forms into a `Kindred`: members with their terms, and the relations between
them, named with the KIN kinship terms."""),
    ("code", """kindred, notes = pg.from_document(doc)
proband = [m for m in kindred.members if m.index][0]
father, mother, _ = kindred.genetic_parents(proband.id)
print("proband", proband.id, "– father", father, "– mother", mother)
for r in kindred.relations[:5]:
    print(r.individual, pg.kin.get(r.kin).label, r.relative)"""),
    ("md", """## The phenopacket toolkit

`phenopacket_toolkit` reads every form (Phenopacket, Family, Cohort, GA4GH Pedigree) and does the jobs of `phenotk`:
view, statistics, filtering, de-identification, conversion."""),
    ("code", """import phenopacket_toolkit as ptk
from phenopacket_toolkit.ops import render, deidentify

family = ptk.read("/data/examples/okafor_phenopackets-family.json")
print(render(family))

shared = deidentify(family, remap_ids="seq")
print("new ids:", shared.crosswalk)"""),
    ("md", """## PED files

`mpedtools` reads PED files and MPED files (several conditions, one column each)."""),
    ("code", """import mpedtools

ped = mpedtools.read("/data/examples/okafor.mped")
print(mpedtools.summarise(ped))
print([issue.message for issue in mpedtools.validate(ped)])"""),
    ("md", """## The commands, from a cell

A line that starts with `!` runs a command, as in the terminal. The pedigree programs run here, in this notebook's
Python, so a plain `!` line works; for pipes (`|`) and `>`, use the Terminal tab."""),
    ("code", """!studio2ped /data/examples/okafor.studio.json -d ~/results -o okafor-nb
!mpedtools info ~/results/okafor-nb.mped"""),
]


def main():
    cells = []
    for kind, src in CELLS:
        lines = src.split("\n")
        source = [l + "\n" for l in lines[:-1]] + [lines[-1]]
        if kind == "md":
            cells.append({"cell_type": "markdown", "id": "c%02d" % len(cells), "metadata": {}, "source": source})
        else:
            cells.append({"cell_type": "code", "id": "c%02d" % len(cells), "metadata": {}, "source": source,
                          "execution_count": None, "outputs": []})
    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3 (ipykernel)", "language": "python"},
            "language_info": {"name": "python", "file_extension": ".py", "mimetype": "text/x-python"},
            "workbench": {"made_with": "Pedigree workbench (in the browser)"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(nb, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("data/starter/pedigree-tools.ipynb: {} cells".format(len(cells)))


if __name__ == "__main__":
    main()
