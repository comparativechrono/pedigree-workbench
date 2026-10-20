# The Python packages of the Pedigree workbench

These are the packages that the workbench runs in the browser – in the Tools
tab, the Notebook and the Terminal, and in the Risk tab, to read GA4GH files.
`build_bundle.py` packs them into `assets/py/pedigree-tools.zip`, which the
page unpacks into its Python (Pyodide) when Python starts. The same archive runs on any computer with
Python 3.9 or later: unzip it, put the folder on `PYTHONPATH`, and run
`python -m pedwb PROGRAM …` (`PROGRAM` being any of the programs below).

PedNet, PedGen and PedInterp, with networkx, go in a second archive,
`assets/py/pedigree-analysis.zip`. They need NumPy, pandas, OpenCV and Pillow,
which Pyodide has, so the page loads that archive and those packages only when
one of the three is first used (`pedwb.cli.NEEDS` says what each program
needs). On your own computer, unzip it into the same folder, and install
NumPy, pandas, OpenCV and Pillow with pip.

| Package | Version | Where it comes from |
|---|---|---|
| `studio2ped` | **0.2.0** | on PyPI (was 0.1.0); people named by pedigree numbers, the markers left out, and only genetic parents in the parent columns |
| `ped2studio` | **0.2.2** | on PyPI (was 0.2.1); families that reuse ids kept apart |
| `mpedtools` | 0.1.0 | the release on PyPI, unchanged |
| `hponorm` | **1.1.0** | on PyPI (was 1.0.0); results scored by how well they match, opposites (hypo- and hyper-) and different subtypes never scored as close spellings, and a faster local search |
| `mondonorm` | **1.1.0** | on PyPI (was 1.0.0); the same changes as hponorm |
| `studio2ga4gh` | **0.4.0** | on PyPI (was 0.3.0); rewritten to write through `pedigree_ga4gh` |
| `ga4gh2studio` | **0.4.0** | on PyPI (was 0.3.0); changed to read through `pedigree_ga4gh` |
| `phenopacket_toolkit` (phenotk) | **0.4.0** | on PyPI (was 0.3.0); without its “dialects”, reading and writing through `pedigree_ga4gh`, with faults fixed, and accepting only exact matches by default when it looks terms up |
| `pedigree_ga4gh` | **1.0.0** | on PyPI, new: the one GA4GH implementation the others share |
| `pedwb` | 1.0.0 | new: runs the programs for the terminal (`python -m pedwb NAME …`), and holds the small functions the Tools tab calls (`pedwb.gui`) and the Risk tab's reader of GA4GH files (`pedwb.risk`) |

In the second archive:

| Package | Version | Where it comes from |
|---|---|---|
| `pednet` (PedNet) | **2.1.0** | on PyPI since 19 October 2026 (from [PedNet#6](https://github.com/comparativechrono/PedNet/pull/6)), after 2.0.0 that morning, which has pedigrees as graphs, the mode of inheritance, and the co-segregation of candidate variants: GA4GH Pedigrees and Phenopackets Families read as well as PED files |
| `PedGen` | 0.1.4.dev13 | built from [pedigree-generator#5](https://github.com/comparativechrono/pedigree-generator/pull/5), not released yet: the `pedgen` command, a table of genotypes for PedNet, matplotlib imported only to draw, a rare allele by default, cousins who marry, and a minimum number affected (merged); a GA4GH Pedigree as well as a PED file (#5) |
| `PedInterp` | 0.1.8.dev19 | built from [pedigree-interpreter#8](https://github.com/comparativechrono/pedigree-interpreter/pull/8), not released yet: the `pedinterp` command, children drawn straight under their parents read correctly, the enlargement chosen to suit the symbols, warnings when lines were missed, the symbols measured as the reading finds them, and a GA4GH Pedigree as well as a PED file (merged); twins, and pedigrees sketched by hand (#8) |
| `networkx` | 3.4.2 | its wheel from PyPI, in `vendor/`; the archive has it without its tests |

`tools/vendor_wheels.py` copies the four from their wheels, and records each
wheel's name and SHA-256 in `vendor/SOURCES.json`. When PedGen and PedInterp
are released on PyPI, copy them again from the released wheels.
PedNet is by
Tim Hearn and Nick Taylor, and PedGen and PedInterp by Nick Taylor, under the
MIT licence (each package's `LICENSE`); networkx is under the 3-clause BSD
licence (in its wheel, and in the archive as `networkx/LICENSE.txt`).

The versions in bold in the first table were released on PyPI on 18 October
2026, from the pull requests listed in `docs/upstream.md`. The copies here are
taken from those releases' wheels, so they are exactly what `pip install`
gives.

The other packages are by Tim Hearn, under the MIT licence (`LICENSE`).
`pedigree_ga4gh/kin.py` holds the terms of KIN, the Kinship Ontology of the
GA4GH Pedigree Standard, under the Apache License 2.0
(`pedigree_ga4gh/LICENSE-KIN.txt`).

What changed in each package, and the pull requests that made the changes,
are in `docs/upstream.md`. Why the GA4GH files are written as they are is
explained in `docs/ga4gh.md`.

## The programs

| Program | Package |
|---|---|
| `studio2ped`, `ped2studio`, `studio2ga4gh`, `ga4gh2studio`, `mpedtools`, `hponorm`, `mondonorm` | their packages |
| `phenotk` | `phenopacket_toolkit` |
| `pedigree-ga4gh` | `pedigree_ga4gh` |
| `pednet`, `pedgen`, `pedinterp` | `pednet`, `PedGen`, `PedInterp` (in the second archive) |

## Also here

- `tests/` and `run_tests.py`: the tests (`python3 python/run_tests.py`). With
  `PHENOPACKET_TOOLS_SCHEMAS` set to phenopacket-tools' v2 JSON schemas they
  also check the packages' output against those. The tests of PedNet, PedGen
  and PedInterp need NumPy, pandas, OpenCV and Pillow, and are skipped without
  them.
- `tools/vendor_wheels.py`: copies PedNet, PedGen, PedInterp and networkx from
  their wheels (see above).
- `tools/make_examples.py`: makes the example drawings from the pedigree
  practical's families.
- `tools/official_check.py`: checks files the way phenopacket-tools does,
  with its own schemas (which need the Python packages jsonschema and
  referencing).
- `build_bundle.py`: makes the archive for the page.
