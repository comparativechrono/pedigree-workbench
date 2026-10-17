# Changes the other repositories need

The workbench carries its own copies of the Python packages (`python/`). Five
are unchanged copies of their releases on PyPI; three were changed here so that
there is one correct GA4GH implementation, and one, `pedigree_ga4gh`, is new.
Nothing has been changed in the packages' own repositories: this file lists
what should be changed there, so that `pip install` gives people what the
workbench runs.

| Package | Release on PyPI | In the workbench | State |
|---|---|---|---|
| studio2ped | 0.1.0 | 0.1.0 | unchanged copy |
| ped2studio | 0.2.1 | 0.2.0 in its `__init__` (the 0.2.1 release's code) | unchanged copy |
| mpedtools | 0.1.0 | 0.1.0 | unchanged copy |
| hponorm | 1.0.0 | 1.0.0 | unchanged copy |
| mondonorm | 1.0.0 | 1.0.0 | unchanged copy |
| studio2ga4gh | 0.3.0 | **0.4.0** | rewritten on `pedigree_ga4gh` |
| ga4gh2studio | 0.3.0 | **0.4.0** | reads through `pedigree_ga4gh` |
| phenopacket-toolkit | 0.3.0 | **0.4.0** | “dialects” removed; reads and writes through `pedigree_ga4gh`; `upgrade` command |
| pedigree-ga4gh | – | **1.0.0** | new: the one GA4GH implementation |

`docs/ga4gh.md` says what the correct form is and why.

## 1. pedigree-ga4gh: a package of its own

Make `python/pedigree_ga4gh` a repository and a PyPI package (`pedigree-ga4gh`,
pure Python, no dependencies), and make studio2ga4gh, ga4gh2studio,
phenopacket-toolkit and abusua2ga4gh depend on it (`pedigree-ga4gh>=1.0,<2`).
Its tests are in `python/tests/test_pedigree_ga4gh.py`; with
`PHENOPACKET_TOOLS_SCHEMAS` pointing at phenopacket-tools' JSON schemas they
also check its output against those.

It is also where version 1 of the GA4GH Pedigree Standard will go once it is
approved (the drafts are ga4gh/pedigree pull request 50 and KIN's pull request
55: see `docs/ga4gh.md`), so that the four tools change together.

## 2. studio2ga4gh → 0.4.0

Replace the package with the workbench's copy (`python/studio2ga4gh`). What changed:

* The GA4GH Pedigree is the Phenopackets form (individuals are Phenopackets v2,
  relationships with KIN terms), not the conceptual model as JSON.
* Conditions are matched to terms with `--terms FILE` (or an id in the colour
  key: “Breast cancer [MONDO:0007254]”); a condition without a term is left out
  with a note, instead of being written with an empty id.
* People are named by their pedigree numbers by default (`--ids
  numbers|drawing|studio`); names in the drawing are never written unless
  asked for.
* Each Phenopacket has `metaData` with `phenopacketSchemaVersion` and a
  resource, with its release, for each ontology used.
* `--only pedigree|family`, `--family-id`, `--created-by`.
* `--phenotypes` is kept so that version 0.3's commands still run, but it
  changes nothing: it decided how a condition without a term was written, and
  such conditions are now left out. Whether a matched condition is a disease
  or a phenotype follows its term (Mondo or HPO).
* Carriers, pregnancies, losses and symbols for several people go into the
  narrative.

The README's description of the output should be updated to match; the
command's options are backwards compatible except that unmatched conditions
are now left out.

## 3. ga4gh2studio → 0.4.0

Replace with `python/ga4gh2studio`. It reads GA4GH Pedigrees and Phenopackets
Families through `pedigree_ga4gh`, so it accepts camelCase and proto names,
draws partnerships (consanguineous, separated), adoption (dashed lines), twins,
markers from the narrative, and puts each condition's term in the colour key.
Files from studio2ga4gh 0.3 and abusua2ga4gh 0.2 are refused with a message
saying to upgrade them first. The command takes one file (`ga4gh2studio FILE
-o OUT`); `-g` and `-p` still work.

## 4. phenopacket-toolkit → 0.4.0

Replace with `python/phenopacket_toolkit`. The “dialects” for the two older
forms are gone: a file in an older form is refused with a message, and `phenotk
upgrade` rewrites it once. GA4GH Pedigrees are handled as documents of their
own (view, stats, filter, de-identify, sort, convert to a Family and back, PED
export). Normalising records the ontology releases used (from OBO files and
from OLS). De-identifying a GA4GH Pedigree replaces the people's ids in its
narrative too ("proband IV-3"), as whole words, and warns that the narrative is
free text to be read before the file is shared.

One fault of 0.3.0 is fixed as well: `phenotk normalise` with EBI's Ontology
Lookup Service accepted the first result for every name, however poor a
match. hponorm's and mondonorm's OLS clients score their results by rank (100,
96, 92 …), so the first always looked like an exact match. 0.4.0 scores OLS's
results by how closely their labels match the name, so the threshold means
what it says; a terms file whose entries carry a `version` also has that
release recorded in the resources; and a name filled in with a term of the
other kind (a "disease" given an HPO term, as in studio2ga4gh 0.3's files) is
moved to where its term belongs, phenotypic features or diseases.

`phenotk merge` is corrected too. In 0.3.0 a merged Family gave everyone in
it no parents, whatever the inputs said, and the merged metaData was the first
input's, so the releases of the other inputs' ontologies were lost. In 0.4.0
the Family's pedigree comes from the Families and GA4GH Pedigrees among the
inputs, the metaData declares every ontology the inputs declare, with its
release, and repeated ids are dealt with: in a Family the first Phenopacket
for a person is kept; in a Cohort the later person is renamed after their
file's id (`FAM2-IV-3`), since pedigree numbers recur from family to family.
Both are reported.

`phenotk filter --prune-pedigree` on a Family kept in its pedigree only the
people with a Phenopacket, so the relatives with nothing recorded – most of a
family – went too, and the parents of those who were left were then missing:
the file was invalid even when only terms had been filtered. 0.4.0 takes out
of the pedigree only the people whose Phenopackets the filters left out, and
clears the lines to them.

`phenotk deidentify --drop-provenance` removed `created` and `createdBy`,
which metaData requires, so the file it wrote was invalid. 0.4.0 puts the
de-identification in their place (`phenotk deidentify`, and its time) and
removes the record of updates.

`phenotk add` wrote invalid files in three ways, all fixed in 0.4.0: a term
from an ontology the file did not use yet was not declared in `metaData`; a
variant (`--variant`) was always given the proband's id, whoever it was added
to, and a diagnosis without a disease when `--diagnosis` was left out (now
refused with a message, since `Diagnosis.disease` is required); and a
zygosity given as its GENO id had no label. `phenotk filter` on a Family now
refuses filters that would leave out the proband, which a Family must have,
instead of writing a Family without one.

The package has no repository link on PyPI: add one (the lab's software page
does not list the toolkit either).

## 5. abusua2ga4gh

It should write through `pedigree-ga4gh` like studio2ga4gh. Until then, its
output has these faults. `pedigree-ga4gh upgrade` corrects those it can tell
from the file, as marked; the others need abusua2ga4gh itself to change.

* `KIN:039` is used for a sperm donor: `KIN:039` is *hasGestationalCarrier*;
  a sperm donor is `KIN:004` *isSpermDonorOf*. (Corrected: the relation's
  label, *isSpermDonorOf*, says which was meant.)
* `KIN:011` is labelled *isDizygoticMultipleBirthSiblingOf*; KIN's label is
  *isPolyzygoticMultipleBirthSiblingOf*. (Corrected.)
* Foster and social parents are written as `KIN:022` *isAdoptiveParentOf*;
  KIN has `KIN:021` *isFosterParentOf* and `KIN:020` *isParentFigureOf*.
  (Not corrected: only the relationship's free-text description says which
  was meant. The upgrade keeps the description in the narrative, and lists
  the relationship to be checked when the description says foster or social.)
* Carriers get the phenotypic feature `HP:0032500` “Heterozygous carrier”.
  `HP:0032500` is *Exacerbated by tobacco use*, and the HPO has no carrier
  term. Phenopackets have no field for carrier status: the only structured
  place for it is a genomic interpretation of the variant (heterozygous), when
  the variant is known; otherwise a GA4GH Pedigree's narrative. (Corrected:
  the upgrade removes the feature and says who is a carrier in a GA4GH
  Pedigree's narrative, or lists them to be done for a Phenopacket; the check
  reports the term as an error, `carrier-term`.)
* `name` and `diseases` inside `subject`, a `description` on relationships,
  no `metaData` in the Phenopackets, and resources with an empty `version`.
  (Corrected.)
* Conditions with empty ontology ids. (Listed to be done: they need terms,
  which `phenotk normalise` or the workbench's *Fill in missing terms* give
  them.)

## 6. studio2ped

* People are named by the text under their symbol (or the Studio's own id). In
  the examples this gives ids such as `Alice_50` and `Bowel_cancer`, and two
  people labelled `26` in the Lynch family get the same id, which `mpedtools
  validate` reports as an error. Offer pedigree numbers (II-3) as the default,
  as studio2ga4gh 0.4 does, and never write names unless asked for.
* The “no children” and “infertile” symbols, which Pedigree Studio stores as
  children of a couple, are written as people (in `features.studio.json`, 29
  “individuals” for 27 people). Leave them out (studio2ga4gh 0.4 does, and
  notes them in the narrative).
* A condition named with its id in the key (“Condition X [MONDO:0009061]”)
  becomes the column `Condition_X_MONDO0009061`: take the id off the name.
* Without `-o`, the output is named after the input with only `.json` taken
  off: `okafor.studio.json` gives `okafor.studio.mped`. Take `.studio.json`
  off as a whole, as studio2ga4gh does.

## 7. hponorm and mondonorm

* `--mapping` looks a label up as it is lower-cased, so a mapping file must
  have lower-case keys; studio2ga4gh's and phenotk's terms files are matched
  without regard to case. Matching without regard to case (lower-casing the
  file's keys when it is read) would let one terms file serve all of them.
* The `Suggester` turns a failed request into “no suggestions”, so an
  unreachable OLS looks like a name with no match. Say that OLS did not answer.
* The OLS client scores results by their rank (`100 - 4 × rank`), which looks
  like a match score but is not one; anything that compares it with a
  threshold (as phenopacket-toolkit 0.3 did) accepts the first result
  whatever it is. Score by how closely the label or a synonym matches the
  query, and keep the synonyms OLS returns, so that “Deafness” can be matched
  to *Hearing impairment*.
* Without rapidfuzz (which Pyodide does not have) the local search scores every
  name with difflib: a few seconds per name for the HPO, and weak ranking
  (“learning disability” puts *Dyslexia* before *Specific learning
  disability*). A token-based shortlist before difflib would be faster and
  better.
* The HPO is downloaded from `http://purl.obolibrary.org/obo/hp.obo`, which a
  web page cannot fetch (plain http, and a redirect to a host without CORS).
  The workbench downloads `hp.obo` from raw.githubusercontent.com instead.

## 8. The lab web site

The Software page lists seven of the packages; add phenopacket-toolkit and
pedigree-ga4gh (with the map of formats), and link the workbench.
