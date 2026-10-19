#!/usr/bin/env python3
"""Write the notebooks a new user finds in ~/notebooks: data/starter/pedigree-tools.ipynb and
data/starter/pedigree-analysis.ipynb.

The first walks through the pedigree packages in Python on the example files, and the second through PedNet, PedGen
and PedInterp, which the workbench loads when they are first used. Every code cell is run by
python/tests/test_starter.py (with the paths changed to this repository's), so they stay correct. Someone who visited
the workbench before a notebook was added is given it on their next visit (page-wb.js).

Run:  python3 build/make_starter.py   (then python3 build/make_page.py)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "data", "starter")

CELLS = [
    ("md", """# The pedigree packages in Python

This notebook uses the workbench's Python packages directly. They are the same packages that the **Tools** tab and
the **Terminal** run. Run the cells in order from the top: click a cell and press **Shift+Enter**. The first code cell
starts Python in your browser, which takes a few seconds the first time.

The example files are in `/data/examples`, and can't be changed. Anything you make goes into your own folder, `~`
(`/home/user`). On your own computer the same code works once you've installed the packages with
`pip install studio2ped studio2ga4gh …`, as the versions on PyPI are the ones that run here."""),
    ("md", """## A Pedigree Studio drawing

A drawing is a JSON file holding the people (with their symbols, fills and positions), the couples, the children, the
twins and the colour key. `studio2ga4gh` reads it into Python objects and works out the pedigree numbers (I-1, II-3 …)
just as the Studio shows them."""),
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

The conditions in the key need ontology terms. Here they come from a terms file, which the **Match conditions to
terms** tool in the Tools tab can make for you. A condition without a term is left out, and a note says so."""),
    ("code", """import os
from studio2ga4gh import convert_file

os.makedirs("/home/user/results", exist_ok=True)
terms = json.load(open("/data/examples/example-terms.json"))
result = convert_file("/data/examples/okafor.studio.json", "okafor-nb", "/home/user/results", terms=terms)
print(result.summary)
for path, _ in result.files:
    print("wrote", path)"""),
    ("md", """## Checking a file against the standard

`pedigree_ga4gh` is the GA4GH implementation that studio2ga4gh, ga4gh2studio and the phenopacket toolkit share.
`validate` applies the checks of the
Phenopackets v2 schema and of phenopacket-tools, and those of the GA4GH Pedigree, such as the KIN relations, the ids
and the parents."""),
    ("code", """import pedigree_ga4gh as pg

doc = pg.load("/home/user/results/okafor-nb_ga4gh-pedigree.json")
findings = pg.validate(doc)
print(pg.render_findings(findings))

old = pg.load("/data/examples/older/studio2ga4gh-0.3_ga4gh-pedigree.json")
n = len(pg.errors(pg.validate(old)))
print(n, "error" if n == 1 else "errors", "in a file from studio2ga4gh 0.3")"""),
    ("md", """## The family as Python objects

`from_document` reads any of the GA4GH forms into a `Kindred`, which holds the family members with their terms and
the relations between them, named with KIN's kinship terms."""),
    ("code", """kindred, notes = pg.from_document(doc)
proband = [m for m in kindred.members if m.index][0]
father, mother, _ = kindred.genetic_parents(proband.id)
print("proband", proband.id, "– father", father, "– mother", mother)
for r in kindred.relations[:5]:
    print(r.individual, pg.kin.get(r.kin).label, r.relative)"""),
    ("md", """## The phenopacket toolkit

`phenopacket_toolkit` reads every form (Phenopacket, Family, Cohort and GA4GH Pedigree) and does the same jobs as
`phenotk`: viewing, statistics, filtering, de-identification and conversion."""),
    ("code", """import phenopacket_toolkit as ptk
from phenopacket_toolkit.ops import render, deidentify

family = ptk.read("/data/examples/okafor_phenopackets-family.json")
print(render(family))

shared = deidentify(family, remap_ids="seq")
print("new ids:", shared.crosswalk)"""),
    ("md", """## PED files

`mpedtools` reads PED files and MPED files, which hold several conditions, each in its own column."""),
    ("code", """import mpedtools

ped = mpedtools.read("/data/examples/okafor.mped")
print(mpedtools.summarise(ped))
print([issue.message for issue in mpedtools.validate(ped)])"""),
    ("md", """## The commands, from a cell

A line that starts with `!` runs a command, as it would in the terminal. The pedigree programs run here in the
notebook's own Python, so a plain `!` line works. For pipes (`|`) and `>`, use the Terminal tab instead."""),
    ("code", """!studio2ped /data/examples/okafor.studio.json -d ~/results -o okafor-nb
!mpedtools info ~/results/okafor-nb.mped"""),
    ("md", """## Next

The notebook `pedigree-analysis.ipynb`, next to this one, goes on to PedNet, PedGen and PedInterp: a family as a
graph, its kinship and loops, the mode of inheritance, candidate variants ranked by co-segregation, simulated
families, and a pedigree read from a picture."""),
]

ANALYSIS = [
    ("md", """# Analysing pedigrees: PedNet, PedGen and PedInterp

This notebook works with three more packages: **PedNet**, which analyses a pedigree as a graph and weighs up the mode
of inheritance and candidate variants; **PedGen**, which simulates families; and **PedInterp**, which reads a picture
of a pedigree. They need NumPy, and PedGen and PedInterp need pandas too, and PedInterp OpenCV, so the workbench loads
them only when they are first used. The first cell that imports one of them takes longer, because it downloads it,
with what it needs: about 4 MB for PedNet, and about 21 MB in all once PedGen and PedInterp are loaded too. Your
browser keeps them for next time.

Run the cells in order from the top: click a cell and press **Shift+Enter**. The same work is in the **Tools** tab,
under *Analyse and simulate*, and in the terminal, as the commands `pednet`, `pedgen` and `pedinterp`."""),
    ("md", """## A family as a graph

PedNet reads a PED file into a pedigree for each family. A pedigree is a directed acyclic graph, with an edge from
each parent to each child, and a marriage between relatives closes a loop in it. In the Okafor family, the parents of
the twin boys with hearing loss are first cousins. (From an MPED file, PedNet takes the first condition.)"""),
    ("code", """import pednet

okafor = pednet.read_ped("/data/examples/okafor.mped")["FAM1"]
print(len(okafor.people), "people; affected:", okafor.affected())
for loop in pednet.loops(okafor):
    print("a loop, from", loop.kind + ":", ", ".join(loop.people))"""),
    ("md", """## Kinship and inbreeding

The kinship coefficient of two people is the chance that a copy of a gene taken at random from one of them and a copy
taken from the other are the same copy, inherited from an ancestor they share. A child's inbreeding coefficient is
the kinship of their parents, so the children of first cousins have 1/16."""),
    ("code", """inbred = {pid: f for pid, f in pednet.inbreeding(okafor).items() if f > 0}
print("inbred:", inbred)
for a, b in [("IV-3", "IV-4"), ("IV-3", "II-3"), ("III-2", "III-3")]:
    r = pednet.relationship(okafor, a, b)
    print(f"{b} is the {r.name} of {a}: a relative of degree {r.degree}, kinship {r.kinship:.4f}")
# everyone's, as a matrix: a person's kinship with themself is (1 + F)/2
ids, phi = pednet.kinship_matrix(okafor)
print("IV-3 with himself:", phi[ids.index("IV-3"), ids.index("IV-3")])"""),
    ("md", """## The mode of inheritance

`infer_mode` works out the likelihood of who is affected under each mode of inheritance exactly, by treating the
pedigree as a Bayesian network of genotypes, and turns the likelihoods into probabilities. In the Lynch family, bowel
cancer passes from father to son, and the answer is clear. Two affected brothers whose parents are cousins point to a
recessive condition, but not to whether it is autosomal or X-linked."""),
    ("code", """lynch = pednet.read_ped("/data/examples/lynch.ped")["FAM1"]
print(pednet.infer_mode(lynch))
print()
print(pednet.infer_mode(okafor))"""),
    ("md", """## Candidate variants

`rank_variants` scores each candidate variant by how well it co-segregates with the condition. The score is a Bayes
factor, and its strength is given as evidence for co-segregation (PP1) or against it (BS4), under the ACMG/AMP
guidelines. These are PedNet's own examples: a family with a dominant condition, and six variants found by
sequencing some of them."""),
    ("code", """family = pednet.read_ped("/data/examples/pednet/dominant.ped")["FAM1"]
variants = pednet.read_vcf("/data/examples/pednet/dominant.vcf", samples=family.ids)
for s in pednet.rank_variants(family, variants):
    print(s.rank, s.id, round(s.log10_bf, 2), s.evidence, s.best_mode, s.notes)"""),
    ("md", """## Simulating families with PedGen

PedGen makes up a family by Mendelian inheritance from an affected founder, as a table, and with a seed it makes the
same family each time. PedNet reads the table as it is."""),
    ("code", """from PedGen import pedigree_generator, gen_PED_export

sim = pedigree_generator(max_children=3, FamilyID="SIM1", mode="AD", generation_count=4, seed=4)
print(len(sim), "people,", (sim["Phenotype"] == 2).sum(), "affected")
print(pednet.infer_mode(pednet.pedigree_from_rows(sim)))
print("wrote", gen_PED_export(sim, "/home/user/results"))"""),
    ("md", """PedNet takes a condition to be rare: its recessive model gives the allele a frequency of 1 in 1,000. The partners
who marry into a family that PedGen simulates carry the allele at the frequency you give, 0.1 unless you say
otherwise, so about one in five of them is a carrier. In a recessive family that PedGen makes, the affected children
of carriers who married in are very unlikely under PedNet's model, and it may favour another mode. Given PedGen's
frequency, it weighs the family up as PedGen made it."""),
    ("code", """rec = pednet.pedigree_from_rows(pedigree_generator(max_children=3, FamilyID="SIM2", mode="AR", generation_count=4, seed=34))
print("a rare allele:", pednet.infer_mode(rec).call)
print("PedGen's frequency:", pednet.infer_mode(rec, allele_frequency={"AR": 0.1}).call)"""),
    ("md", """## Reading a picture with PedInterp

PedInterp reads a pedigree from a picture of one, drawn in black on white. The labels can't be read in a browser,
which has no Tesseract, so the people are numbered by generation instead (I-1, I-2, II-1 …), as Pedigree Studio
numbers them. The picture of the Lynch family was drawn where the Studio draws it, so the numbers are the ones in the
Lynch PED file, and the two tables are the same."""),
    ("code", """import pandas as pd
from PedInterp import pedigree_processing

read = pedigree_processing("LYNCH", image_path="/data/examples/lynch.png", ocr=None)
print(read.head(6).to_string(index=False))
columns = ["FamilyID", "IndividualID", "PaternalID", "MaternalID", "Sex", "Phenotype"]
ped = pd.read_csv("/data/examples/lynch.ped", sep="\\t", header=None, names=columns, dtype=str)
print("the same as lynch.ped:", read[columns[1:]].astype(str).values.tolist() == ped[columns[1:]].values.tolist())"""),
    ("md", """## The commands, from a cell

The same work as commands: a line that starts with `!` runs one, as the terminal would."""),
    ("code", """!pednet mode /data/examples/okafor.mped --method patterns
!pedgen --mode AD --generations 3 --seed 5 --family SIM3 -d ~/results
!pedinterp /data/examples/lynch.png --labels none -q -d ~/results"""),
]

NOTEBOOKS = {"pedigree-tools.ipynb": CELLS, "pedigree-analysis.ipynb": ANALYSIS}


def write(name, cell_list):
    cells = []
    for kind, src in cell_list:
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
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as fh:
        json.dump(nb, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("data/starter/{}: {} cells".format(name, len(cells)))


def main():
    for name, cell_list in NOTEBOOKS.items():
        write(name, cell_list)


if __name__ == "__main__":
    main()
