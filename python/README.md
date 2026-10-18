# The Python packages of the Pedigree workbench

These are the packages that the workbench runs in the browser – in the Tools
tab, the Notebook and the Terminal. `build_bundle.py` packs them into
`assets/py/pedigree-tools.zip`, which the page unpacks into its Python
(Pyodide) when Python starts. The same archive runs on any computer with
Python 3.9 or later: unzip it, put the folder on `PYTHONPATH`, and run
`python -m pedwb PROGRAM …` (`PROGRAM` being any of the programs below).

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
| `pedwb` | 1.0.0 | new: runs the programs for the terminal (`python -m pedwb NAME …`), and holds the small functions the Tools tab calls (`pedwb.gui`) |

The versions in bold were released on PyPI on 18 October 2026, from the pull
requests listed in `docs/upstream.md`. The copies here are taken from those
releases' wheels, so they are exactly what `pip install` gives.

The packages are by Tim Hearn, under the MIT licence (`LICENSE`).
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

## Also here

- `tests/` and `run_tests.py`: the tests (`python3 python/run_tests.py`). With
  `PHENOPACKET_TOOLS_SCHEMAS` set to phenopacket-tools' v2 JSON schemas they
  also check the packages' output against those.
- `tools/make_examples.py`: makes the example drawings from the pedigree
  practical's families.
- `tools/official_check.py`: checks files the way phenopacket-tools does,
  with its own schemas (which need the Python packages jsonschema and
  referencing).
- `build_bundle.py`: makes the archive for the page.
