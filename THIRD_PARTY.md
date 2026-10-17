# Third-party software, data and provenance

The Pedigree workbench's own code, help and examples are under the MIT licence
([LICENSE](LICENSE)). What it includes from elsewhere, and what it loads at run
time, keeps its own licence. Keep each component's notices and licence files
when copying or redistributing its files.

## Included in the site

| Component | Version | Licence | Where | Origin |
|---|---|---|---|---|
| Pedigree Studio (Timothy J Hearn) | commit `9e6b524` of 17 October 2026 | MIT | `assets/studio/index.html` | [comparativechrono/PedigreeStudio](https://github.com/comparativechrono/PedigreeStudio); two small changes, recorded in `assets/studio/SOURCE.json` and made by `build/update_studio.py`: the name it keeps its drawing under in the browser, and loading `bridge.js` |
| studio2ped, ped2studio, mpedtools, hponorm, mondonorm (Tim Hearn) | 0.1.0, 0.2.1, 0.1.0, 1.0.0, 1.0.0 | MIT | `python/`, packed into `assets/py/pedigree-tools.zip` | their releases on PyPI, unchanged |
| studio2ga4gh, ga4gh2studio, phenopacket-toolkit (Tim Hearn) | 0.4.0 | MIT | the same | changed from their 0.3.0 releases: see `docs/upstream.md` |
| pedigree-ga4gh, pedwb | 1.0.0 | MIT | the same | written for the workbench |
| KIN, the Kinship Ontology (GA4GH Pedigree Standard): its codes, labels and definitions | `kin.owl`, commit `71616ea` of 16 September 2024 | Apache License 2.0 | `python/pedigree_ga4gh/kin.py`; licence in `python/pedigree_ga4gh/LICENSE-KIN.txt` | [GA4GH-Pedigree-Standard/family_history_terminology](https://github.com/GA4GH-Pedigree-Standard/family_history_terminology) |
| CodeMirror | 5.65.18 | MIT | `assets/vendor/codemirror/` (with its `LICENSE`) | [codemirror/codemirror5](https://github.com/codemirror/codemirror5) |
| marked | 18.0.13 | MIT | `assets/vendor/marked/` (with its `LICENSE`) | [markedjs/marked](https://github.com/markedjs/marked) |
| DOMPurify | 3.4.16 | Apache License 2.0 or Mozilla Public License 2.0 | `assets/vendor/dompurify/` (with its `LICENSE`) | [cure53/DOMPurify](https://github.com/cure53/DOMPurify) |
| JSZip | 3.10.1 | MIT or GNU GPL 3 (used under MIT) | `assets/vendor/jszip/` (with its `LICENSE.markdown`) | [Stuk/jszip](https://github.com/Stuk/jszip) |

The workbench's framework – the page, help, shell, notebook and editor in
`assets/js` and `assets/css` – comes from the Hearn lab's Bioinformatics
workbench.

`python/pedigree_ga4gh/schema.py` lists the messages and fields of the
Phenopackets v2 schema and follows the rules that phenopacket-tools, the
GA4GH's validator, applies; it contains no code or schema files of either.
`python/tools/official_check.py` uses phenopacket-tools' JSON schemas when
someone supplies them; they are not included.

## Loaded when the page runs

| Component | Version | Licence | From |
|---|---|---|---|
| Pyodide (CPython for the browser), with micropip and PyYAML | 0.29.5 | Mozilla Public License 2.0 (CPython: PSF licence; PyYAML: MIT; micropip: MPL 2.0) | cdn.jsdelivr.net, when Python first starts |
| The HPO (`hp.obo`) | the latest release | the HPO's own terms of use (see the HPO's web site) | raw.githubusercontent.com, only when a user asks for it in *Match conditions to terms*; it is kept among that user's files, not in the site |

EBI's Ontology Lookup Service is used, when a user chooses it, to search the
HPO and the Mondo Disease Ontology; nothing of it is included.

## Example data

The example families (`data/examples/`) are fictional: four come from the
Hearn lab's pedigree practical, and one was drawn for the tests. The files
made from them are written by the packages themselves (see
`data/examples/README.md`).
