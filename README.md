# Pedigree workbench

A web page for working with family pedigrees: draw a family in **Pedigree
Studio**, then turn the drawing into the files other people and programs need
– PED files for linkage programs, and the GA4GH Pedigree and Phenopackets
files for sharing a family's pedigree and findings – with the lab's Python
packages, which run in the browser. Nothing is installed and nothing is
uploaded: the drawings, the files and Python all stay on the computer of the
person using it.

The packages are studio2ped, ped2studio, studio2ga4gh, ga4gh2studio,
mpedtools, hponorm, mondonorm and the phenopacket toolkit (phenotk), with
pedigree-ga4gh, the one GA4GH implementation that the others now share. With
them are three packages for analysing pedigrees: **PedNet**, which analyses a
family as a graph and weighs up its mode of inheritance and how well candidate
variants co-segregate with its condition; **PedGen**, which simulates
families; and **PedInterp**, which reads a pedigree from a picture of one.
They need NumPy, pandas, OpenCV and Pillow, so the page loads them only when
one of them is first used.

## Contents

1. [What is in it](#what-is-in-it)
2. [The GA4GH files](#the-ga4gh-files)
3. [Put it on GitHub Pages](#put-it-on-github-pages)
4. [Try it on your own computer](#try-it-on-your-own-computer)
5. [How it is made](#how-it-is-made)
6. [Tests](#tests)
7. [Changes the other repositories need](#changes-the-other-repositories-need)
8. [Files](#files)
9. [Credits and licences](#credits-and-licences)

## What is in it

One page, `index.html`. On the left is the **help**, which can be hidden: a
first session, walkthroughs of the common jobs, a page for every tool, and
pages on the file formats and standards. Its buttons do what they say – open
an example in the Studio, open a tool with a file chosen, run a command in the
terminal – and its map of the formats, from the lab's Software page, opens a
tool when an arrow is clicked. On the right is the **workbench**, with five
tabs:

| Tab | What it is for |
|---|---|
| **Studio** | Pedigree Studio itself, with a bar that keeps the drawing among the user's files: New, Open, Save, Save as, Tidy, and *Convert or check…*, which takes the drawing to the Tools tab. |
| **Tools** | The packages behind forms, for people who would rather point and click: each tool runs one command of one package, exactly as the terminal would, and shows that command, and the same work in Python, so that it can be done again without the form. The first page is the map and the common tasks. |
| **Files** | The user's files and the examples: look at them, edit them, upload and download. |
| **Notebook** | Python notebooks (Jupyter's `.ipynb`), with all the packages, starting with a welcome notebook that walks through them. |
| **Terminal** | A bash-like shell with the packages' programs as commands (`studio2ga4gh`, `phenotk`, `mpedtools` …), text tools, `python` and `pip`. |

The tools in the Tools tab:

| Group | Tools |
|---|---|
| Convert | Drawing → GA4GH Pedigree and Phenopackets (studio2ga4gh) · GA4GH or Phenopackets → drawing (ga4gh2studio) · Drawing → PED or MPED (studio2ped) · PED or MPED → drawing (ped2studio) · GA4GH Pedigree ⇄ Phenopackets Family · GA4GH → PED, table or YAML (phenotk) |
| Ontology terms | Match conditions to terms (hponorm, mondonorm) · Fill in missing terms (phenotk normalise) |
| Check and look inside | Check against the standard · Upgrade a file from an older tool (pedigree-ga4gh) · Look inside a GA4GH file · Compare two files (phenotk) |
| Prepare to share | De-identify · Keep some people or terms · One file for each person · Put files together · Add findings to people (phenotk) |
| PED and MPED files | Summary and check · Take one condition out · Put PED files together · One file for each family · PED ⇄ MPED, and columns (mpedtools) |
| Analyse and simulate | The pedigree as a graph · Mode of inheritance · Rank candidate variants (PedNet) · Simulate a family (PedGen) |

*Picture → PED file* (PedInterp) is with the conversions. A browser can't run
Tesseract, which PedInterp uses to read the labels under the symbols, so in
the workbench it numbers the people by generation (I-1, I-2, II-1 …), as
Pedigree Studio does.

*Match conditions to terms* finds the HPO or Mondo term for each condition in
a drawing's colour key, searching EBI's Ontology Lookup Service or copies of
the ontologies in the browser, and keeps the choices in a terms file. It and
*Fill in missing terms* are the only places where anything leaves the
computer: if the user chooses EBI's service, the words searched for go to EBI.

## The GA4GH files

There is now **one GA4GH implementation**, the new package `pedigree_ga4gh`
(`python/pedigree_ga4gh`), through which studio2ga4gh, ga4gh2studio and the
phenopacket toolkit all read and write. The GA4GH Pedigree Standard is still in
development, and neither of the forms it is carried in is approved; the
workbench writes a GA4GH Pedigree in the Phenopackets form proposed for it
(every individual a Phenopacket version 2, relationships named with current KIN
terms), and a Phenopackets Family exactly to the Phenopackets v2 schema. Files
from the older versions of studio2ga4gh and abusua2ga4gh, which were not
correct, are recognised and upgraded once.

A draft of version 1 of the standard, under review since June 2026, would
change the form: people would be records of the standard's own, linked to
their Phenopackets, and KIN would be revised. It is not approved, so the
workbench follows the published version, and recognises files in the draft's
form without trying to convert them. **[docs/ga4gh.md](docs/ga4gh.md)**
records the decision, what was wrong before, what the draft would change, and
the sources.

## Put it on GitHub Pages

The site is the repository as it is: `index.html` at the top, with `assets/`
and `data/` beside it. It needs no build step and no server-side code.

1. In the repository's **Settings → Pages**, choose *Deploy from a branch*,
   the branch `main` and the folder `/ (root)`.
2. After a minute the workbench is at
   `https://comparativechrono.github.io/pedigree-workbench/`.

The empty file `.nojekyll` stops GitHub processing the site. Python
(Pyodide 0.29.5, about 10 MB the first time) is loaded from jsDelivr when a
user first runs a tool; everything else comes from the site itself. Pyodide
0.29.5 (September 2026) is a maintenance release of the 0.29 series, with
Python 3.13; Pyodide's newer series, numbered 314, has Python 3.14, and the
workbench has not been tried with it.

Users' files are kept by their browser for the site's address (IndexedDB, under
the prefix `pedwb`), so they stay when the site is updated, and are not shared
with the lab's other workbenches on the same address.

## Try it on your own computer

Browsers do not run the workbench from a file opened directly (`file://…`):
they block the web worker that runs Python and the Studio's frame. Serve the
folder instead:

```bash
python3 serve.py          # then open http://localhost:8000/
```

## How it is made

`index.html` is built from `build/template.html` and the help pages in
`build/help/`. After changing any of the sources, rebuild what depends on them:

| You changed | Run |
|---|---|
| the Python packages (`python/`) | `python3 python/build_bundle.py` (makes `assets/py/pedigree-tools.zip` and `pedigree-analysis.zip`), then `python3 build/make_page.py` |
| PedNet, PedGen, PedInterp or networkx | `python3 python/tools/vendor_wheels.py WHEEL …` (copies them from their wheels into `python/`), then the line above |
| the help (`build/help/*.html`), the template, `build/citations.json` | `python3 build/make_page.py` |
| the notebooks to start from | `python3 build/make_starter.py` |
| the example files | `python3 build/make_example_data.py`, then `python3 build/make_page.py` |
| Pedigree Studio | `python3 build/update_studio.py --git ../PedigreeStudio`, then `python3 build/make_page.py` |

- **Pedigree Studio** is a copy of `index.html` from the PedigreeStudio
  repository (`assets/studio/`), changed in two small ways that
  `build/update_studio.py` makes and `assets/studio/SOURCE.json` records: it
  keeps its drawing in the browser under a name of its own, and it loads
  `bridge.js`, through which the bar above it opens and saves drawings.
- **The Python packages** in `python/` are the workbench's copies;
  [python/README.md](python/README.md) says where each comes from and which
  are changed. They are zipped into `assets/py/pedigree-tools.zip`, which the
  page unpacks into Pyodide when Python starts. PedNet, PedGen and PedInterp,
  with networkx, are in a second archive, `assets/py/pedigree-analysis.zip`,
  which the page loads with the packages of Pyodide's they need (NumPy,
  pandas, OpenCV, Pillow) the first time one of them is used: by its command,
  its tools, or an import in a notebook or script (`py-worker.js`, from what
  `pedwb.cli.NEEDS` says each needs). OpenCV alone is a download of about
  11 MB, so loading them every time Python starts would slow every first
  visit.
- **The framework** – the page, the help, the shell, the notebook and the
  editor – comes from the lab's Bioinformatics workbench (`assets/js`,
  `assets/css`), with what this workbench does not need taken out. The Studio
  tab (`studio-tab.js`), the Tools tab (`tools.js`), the map (`schematic.js`),
  the text tools of the terminal (`shell-text.js`) and the page's set-up
  (`page-wb.js`) are its own. `pedwb` (`python/pedwb`) runs the programs for
  the terminal and holds the small functions the Tools tab calls.

## Tests

```bash
python3 python/run_tests.py           # the packages: conversions, validation, upgrading, the toolkit, PedNet, PedGen,
                                      # PedInterp, and the notebooks to start from
python3 tests/help_code.py            # every code box of the help, run as a reader would
node tests/equivalence/gen.js assets/js/tools.js > /tmp/cases.jsonl && \
  python3 tests/equivalence/run_equiv.py /tmp/cases.jsonl
                                      # each tool's command and its Python write the same files
python3 tests/browser_smoke.py        # the page in headless Chromium (needs Playwright)
```

The tests of PedNet, PedGen and PedInterp, and their help boxes, need NumPy,
pandas, OpenCV and Pillow (`pip install numpy pandas opencv-python-headless
pillow`), and are skipped, with a note, without them. With
`PHENOPACKET_TOOLS_SCHEMAS` pointing at phenopacket-tools' v2 JSON
schemas, `run_tests.py` also checks the packages' output against them, and
`python/tools/official_check.py` checks any file the way phenopacket-tools
does. The tests never contact EBI's Ontology Lookup Service.

## The packages' own repositories

Each package the workbench changed had a pull request in its own repository
making the same changes. The pull requests were merged, and the packages were
released on PyPI on 18 October 2026, so `pip install` gives exactly what the
workbench runs. The copies in
`python/` are taken from those releases' wheels.
**[docs/upstream.md](docs/upstream.md)** lists the pull requests with what each
changed, and how to release new versions. They cover:

- pedigree-ga4gh, as a package of its own;
- new versions of studio2ga4gh, ga4gh2studio and phenopacket-toolkit;
- abusua2ga4gh and ga4gh2abusua, rewritten on pedigree-ga4gh;
- studio2ped, ped2studio, hponorm and mondonorm.

PedNet 2.0.0 is on PyPI, and the workbench's copy is its wheel. The commands
the workbench runs from PedGen and PedInterp, and PedInterp's reading of
children drawn straight under their parents, are merged but not yet released,
so the workbench's copies are built from GitHub: PedGen's from
[pedigree-generator#4](https://github.com/comparativechrono/pedigree-generator/pull/4), which simulates a rare allele by default and
lets cousins marry, and PedInterp's from
[pedigree-interpreter#5](https://github.com/comparativechrono/pedigree-interpreter/pull/5), which chooses how much to enlarge a picture
and warns when lines were missed.

## Files

```
index.html                 the page (built: see above)
assets/
  js/  css/                the workbench
  studio/                  Pedigree Studio, and bridge.js
  py/                      the Python packages, zipped for the page: pedigree-tools.zip, and
                           pedigree-analysis.zip (PedNet, PedGen, PedInterp), loaded when first used
  vendor/                  CodeMirror, marked, DOMPurify, JSZip
data/
  examples/                example families, and files made from them (README.md)
  starter/                 the notebooks to start from
build/                     what builds index.html, the examples, the notebook and the Studio copy
  help/                    the help pages
python/                    the packages, their tests, and tools for the examples and checks
  vendor/                  networkx's wheel, and SOURCES.json: where PedNet, PedGen, PedInterp and networkx come from
docs/                      ga4gh.md (the GA4GH decision), upstream.md (the packages' pull requests)
tests/                     the help's code, command/Python equivalence, a browser test
serve.py                   a small web server for trying it locally
```

## Credits and licences

The workbench, Pedigree Studio and the packages are the Hearn lab's, under
the MIT licence ([LICENSE](LICENSE)); PedNet is by Tim Hearn and Nick Taylor,
and PedGen and PedInterp by Nick Taylor, also under the MIT licence, with their
licences beside them in `python/`. networkx is under the 3-clause BSD
licence. KIN's terms in `pedigree_ga4gh` are from
the GA4GH Pedigree Standard's `kin.owl` (Apache 2.0). The libraries of the page
and Pyodide keep their own licences: **[THIRD_PARTY.md](THIRD_PARTY.md)** lists
them. The example families are the fictional families of the lab's pedigree
practical.
