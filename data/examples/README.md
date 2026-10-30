# The example files

Four of the families are those of the Hearn lab's pedigree practical
(github.com/comparativechrono/pedigree-practical), made into Pedigree Studio
drawings by `python/tools/make_examples.py`; the fifth was drawn for the
workbench's tests. **All the families and people are fictional.** The other
files are made from the drawings by the workbench's own packages
(`build/make_example_data.py`), so they are always what the current versions
write, except the two pictures of the Okafor family, which Pedigree Studio
itself draws (`build/make_example_pictures.py`): the sketch's strokes are made
by a program that imitates a hand, from where the people are in the drawing.

| File | What it is |
|---|---|
| `okafor.studio.json` | Four generations: twin boys with hearing loss from birth, whose parents are cousins, and a grandmother with breast cancer. |
| `price.studio.json` | Breast, ovarian and prostate cancer across three generations. |
| `lynch.studio.json` | Bowel and pancreatic cancer over four generations: the practical's Lynch syndrome scenario. |
| `cf-cousins.studio.json` | Cystic fibrosis in a family whose grandparents are related, with a carrier who has been tested. |
| `features.studio.json` | Every kind of symbol and line Pedigree Studio draws, for testing the converters. |
| `example-terms.json` | Terms for the conditions of the four practical families: Mondo for the diseases, the HPO for hearing loss, with each ontology's release. |
| `okafor_ga4gh-pedigree.json`, `okafor_phenopackets-family.json` | The Okafor family as a GA4GH Pedigree and a Phenopackets Family (studio2ga4gh). |
| `okafor-later_phenopackets-family.json` | The same Family a visit later: the twins' hearing loss is found to be sensorineural (for *Compare two files*). |
| `okafor.mped`, `cf-cousins.mped` | MPED files made by studio2ped: their ids are the people's pedigree numbers. |
| `lynch.ped` | A plain PED file of the Lynch family, as other programs write them: pedigree numbers as ids, one status column. |
| `lynch.png` | The Lynch family as a picture, in black and white as pedigrees are drawn in papers, with each person where the Studio draws them: for *Picture → PED file and drawing* (PedInterp), which reads it as `lynch.ped`, apart from the family's id. |
| `okafor.png` | The Okafor family as Pedigree Studio saves it as a picture (its *Save as image*), numbers, names and colour key and all. PedInterp reads it as the people, parents and sexes of `okafor.mped`, with those who have either condition affected, and finds the identical twins. |
| `okafor-sketch.png` | The same family sketched roughly with the Studio's Draw tool, with the pen it starts with (black, 4 pixels wide), as testers in a clinic sketch: symbols of unequal sizes, some scribbled in, slashes for those who have died, an arrow at the proband, and wobbly lines that stop short or run on. PedInterp reads it as it reads `okafor.png`, with *Drawn by hand*, and turns it into a Studio drawing, twins and all; with *Read who has died, the proband and carriers*, it reads the five who have died and the proband too, as it does in `okafor.png`. |
| `pednet/` | PedNet's own example families, from its repository (version 2.0.0): `dominant.ped` and `recessive.ped`, each with a VCF file of candidate variants, and `consanguineous.ped`, two affected children of first cousins. |
| `older/` | GA4GH files as studio2ga4gh 0.3 and abusua2ga4gh 0.2 wrote them, which the tools now refuse and upgrade. |
| `workflows/` | The example workflows of the Tools tab, made with the workflow engine by `build/make_example_workflows.js`: `share-a-drawing` (a drawing → the GA4GH files, checked, and the Family de-identified), `sketch-to-drawing` (`okafor-sketch.png` → a PED file, a drawing and a GA4GH Pedigree, which is checked, and the family's mode of inheritance), `simulate-and-test` (a family simulated by PedGen, its mode of inheritance and candidate variants weighed by PedNet, and a drawing of it), and `update-an-old-file` (a file from `older/` upgraded, its missing terms filled in from a terms file, and checked). |

Dates in the made files are fixed (17 October 2026), so that making them again
gives the same files.
