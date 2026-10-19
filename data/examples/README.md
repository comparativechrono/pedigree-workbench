# The example files

Four of the families are those of the Hearn lab's pedigree practical
(github.com/comparativechrono/pedigree-practical), made into Pedigree Studio
drawings by `python/tools/make_examples.py`; the fifth was drawn for the
workbench's tests. **All the families and people are fictional.** The other
files are made from the drawings by the workbench's own packages
(`build/make_example_data.py`), so they are always what the current versions
write.

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
| `lynch.png` | The Lynch family as a picture, in black and white as pedigrees are drawn in papers, with each person where the Studio draws them: for *Picture → PED file* (PedInterp), which reads it as `lynch.ped`. |
| `pednet/` | PedNet's own example families, from its repository (version 2.0.0): `dominant.ped` and `recessive.ped`, each with a VCF file of candidate variants, and `consanguineous.ped`, two affected children of first cousins. |
| `older/` | GA4GH files as studio2ga4gh 0.3 and abusua2ga4gh 0.2 wrote them, which the tools now refuse and upgrade. |

Dates in the made files are fixed (17 October 2026), so that making them again
gives the same files.
