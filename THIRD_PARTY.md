# Third-party software, data and provenance

The Pedigree workbench's own code, help and examples are under the MIT licence
([LICENSE](LICENSE)). What it includes from elsewhere, and what it loads at run
time, keeps its own licence. Keep each component's notices and licence files
when copying or redistributing its files.

## Included in the site

| Component | Version | Licence | Where | Origin |
|---|---|---|---|---|
| Pedigree Studio (Timothy J Hearn) | commit `9e6b524` of 17 October 2026 | MIT | `assets/studio/index.html` | [comparativechrono/PedigreeStudio](https://github.com/comparativechrono/PedigreeStudio); two small changes, recorded in `assets/studio/SOURCE.json` and made by `build/update_studio.py`: the name it keeps its drawing under in the browser, and loading `bridge.js` |
| mpedtools (Tim Hearn) | 0.1.0 | MIT | `python/`, packed into `assets/py/pedigree-tools.zip` | its release on PyPI, unchanged |
| studio2ped, ped2studio, hponorm, mondonorm (Tim Hearn) | 0.2.0, 0.2.2, 1.1.0, 1.1.0 | MIT | the same | the pull requests for their next releases: see `docs/upstream.md` |
| studio2ga4gh, ga4gh2studio, phenopacket-toolkit (Tim Hearn) | 0.4.0 | MIT | the same | changed from their 0.3.0 releases, in the pull requests for 0.4.0: see `docs/upstream.md` |
| pedigree-ga4gh (Tim Hearn) | 1.0.0 | MIT | the same | written for the workbench, now [its own repository](https://github.com/comparativechrono/pedigree-ga4gh) |
| pedwb | 1.0.0 | MIT | the same | written for the workbench |
| PedNet (Tim Hearn and Nick Taylor) | 2.0.0 | MIT | `python/pednet` (with its `LICENSE`), packed into `assets/py/pedigree-analysis.zip` | its wheel on PyPI |
| PedGen (Nick Taylor, with changes by Tim Hearn) | 0.1.4.dev11 | MIT | `python/PedGen` (with its `LICENSE`), the same archive | built from [pedigree-generator#4](https://github.com/comparativechrono/pedigree-generator/pull/4), not yet released |
| PedInterp (Nick Taylor, with changes by Tim Hearn) | 0.1.8.dev12 | MIT | `python/PedInterp` (with its `LICENSE`), the same archive | built from [pedigree-interpreter#5](https://github.com/comparativechrono/pedigree-interpreter/pull/5), not yet released |
| networkx | 3.4.2 | BSD 3-clause | its wheel in `python/vendor`, and in the same archive without its tests, with its `LICENSE.txt` | [PyPI](https://pypi.org/project/networkx/3.4.2/); `python/vendor/SOURCES.json` records the wheel's SHA-256 |
| Mondo, nine terms (ids, names, definitions, synonyms) | release 2026-10-06 | CC BY 4.0 | `python/mondonorm/data/mondo-sample.obo`, mondonorm's offline sample | [Mondo](https://mondo.monarchinitiative.org) |
| HPO ids and names, a small hand-built sample | – | the HPO's own terms of use | `python/hponorm/data/hpo-sample.obo`, hponorm's offline sample | [the HPO](https://hpo.jax.org) |
| KIN, the Kinship Ontology (GA4GH Pedigree Standard): its codes, labels and definitions | `kin.owl`, commit `71616ea` of 16 September 2024 | Apache License 2.0 | `python/pedigree_ga4gh/kin.py`; licence in `python/pedigree_ga4gh/LICENSE-KIN.txt` | [ga4gh/pedigree_family_history_terminology](https://github.com/ga4gh/pedigree_family_history_terminology) (formerly GA4GH-Pedigree-Standard/family_history_terminology) |
| CodeMirror | 5.65.18 | MIT | `assets/vendor/codemirror/` (with its `LICENSE`) | [codemirror/codemirror5](https://github.com/codemirror/codemirror5) |
| marked | 18.0.13 | MIT | `assets/vendor/marked/` (with its `LICENSE`) | [markedjs/marked](https://github.com/markedjs/marked) |
| DOMPurify | 3.4.16 | Apache License 2.0 or Mozilla Public License 2.0 | `assets/vendor/dompurify/` (with its `LICENSE`) | [cure53/DOMPurify](https://github.com/cure53/DOMPurify) |
| JSZip | 3.10.1 | MIT or GNU GPL 3 (used under MIT) | `assets/vendor/jszip/` (with its `LICENSE.markdown`) | [Stuk/jszip](https://github.com/Stuk/jszip) |

The workbench's framework – the page, help, shell, notebook and editor in
`assets/js` and `assets/css` – comes from the Hearn lab's Bioinformatics
workbench.

`python/pedigree_ga4gh/schema.py` lists the messages and fields of the
Phenopackets v2 schema and follows the rules that phenopacket-tools, the
Phenopackets team's validator, applies; it contains no code or schema files of
either. `python/tools/official_check.py` uses phenopacket-tools' JSON schemas
when someone supplies them; they are not included. (phenopacket-tools' licence
is given two ways: its `LICENSE` file is the GNU GPL 3, and its `pom.xml` the
3-clause BSD licence. Ask its maintainers before including any of its files.)

## Loaded when the page runs

| Component | Version | Licence | From |
|---|---|---|---|
| Pyodide (CPython for the browser), with micropip and PyYAML | 0.29.5 | Mozilla Public License 2.0 (CPython: PSF licence; PyYAML: MIT; micropip: MPL 2.0) | cdn.jsdelivr.net, when Python first starts |
| NumPy, pandas (with python-dateutil, pytz and six), OpenCV (opencv-python) and Pillow, as Pyodide builds them | 2.2.5, 2.3.3 (2.9.0.post0, 2025.2, 1.17.0), 4.11.0.86, 11.3.0 | NumPy and pandas: BSD 3-clause; python-dateutil: Apache 2.0 or BSD 3-clause; pytz and six: MIT; OpenCV: Apache 2.0; Pillow: MIT-CMU | cdn.jsdelivr.net, when PedNet, PedGen or PedInterp is first used: NumPy for all three, pandas for PedGen and PedInterp, OpenCV and Pillow for PedInterp |
| The HPO (`hp.obo`) | the latest release | the HPO's own terms of use (see the HPO's web site) | raw.githubusercontent.com, only when a user asks for it in *Match conditions to terms*; it is kept among that user's files, not in the site |

EBI's Ontology Lookup Service is used, when a user chooses it, to search the
HPO and the Mondo Disease Ontology; nothing of it is included.

## Example data

The example families (`data/examples/`) are fictional: four come from the
Hearn lab's pedigree practical, and one was drawn for the tests. The files
made from them are written by the packages themselves (see
`data/examples/README.md`). `data/examples/pednet/` holds PedNet's own
example families, from its repository (MIT), which are fictional too.
