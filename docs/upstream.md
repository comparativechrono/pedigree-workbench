# The changes in the other repositories

The workbench carries its own copies of the Python packages (`python/`). To
give one correct GA4GH implementation, three of them were changed here and one,
`pedigree_ga4gh`, was new. This file records what their own repositories needed
so that `pip install` would give people the same code. Each package
got a pull request making those changes, and all of them were merged and
released on PyPI on 18 October 2026. The copies here are those releases, taken
from their wheels, so `pip install` now gives exactly what the workbench runs.

| Package | On PyPI before | Pull request | Released |
|---|---|---|---|
| pedigree-ga4gh | – | [pedigree-ga4gh#1](https://github.com/comparativechrono/pedigree-ga4gh/pull/1) | **1.0.0**, new: the one GA4GH implementation |
| studio2ga4gh | 0.3.0 | [studio2ga4gh#1](https://github.com/comparativechrono/studio2ga4gh/pull/1) | **0.4.0**, rewritten on pedigree-ga4gh |
| ga4gh2studio | 0.3.0 | [ga4gh2studio#1](https://github.com/comparativechrono/ga4gh2studio/pull/1) | **0.4.0**, reads through pedigree-ga4gh |
| phenopacket-toolkit | 0.3.0 | [phenopacket-toolkit#1](https://github.com/comparativechrono/phenopacket-toolkit/pull/1) | **0.4.0**, “dialects” removed; reads and writes through pedigree-ga4gh; `upgrade` |
| abusua2ga4gh | 0.2.0 | [abusua2ga4gh#1](https://github.com/comparativechrono/abusua2ga4gh/pull/1) | **0.3.0**, writes through pedigree-ga4gh (not in the workbench) |
| ga4gh2abusua | 0.3.0 | [ga4gh2abusua#1](https://github.com/comparativechrono/ga4gh2abusua/pull/1) | **0.4.0**, reads through pedigree-ga4gh (not in the workbench) |
| studio2ped | 0.1.0 | [studio2ped#1](https://github.com/comparativechrono/studio2ped/pull/1) | **0.2.0**, pedigree numbers; markers left out; genetic parents only |
| ped2studio | 0.2.1 | [ped2studio#1](https://github.com/comparativechrono/ped2studio/pull/1) | **0.2.2**, families that reuse ids kept apart |
| hponorm | 1.0.0 | [hponorm#1](https://github.com/comparativechrono/hponorm/pull/1) | **1.1.0**, results scored by how well they match |
| mondonorm | 1.0.0 | [mondonorm#1](https://github.com/comparativechrono/mondonorm/pull/1) | **1.1.0**, the same as hponorm |
| mpedtools | 0.1.0 | – | 0.1.0, unchanged |

`docs/ga4gh.md` says what the correct form is and why.

## Releasing a new version

Every repository that had a pull request now has a workflow, `release.yml`,
that publishes the package to PyPI when a GitHub release is published. It uses PyPI's trusted
publishing, so no token is stored anywhere; PyPI knows each repository as a
trusted publisher (owner `comparativechrono`, the repository's name, workflow
`release.yml`, environment `pypi`). To release a new version, set it in
`pyproject.toml` and in the package's `__version__`, merge, and publish a
GitHub release tagged with the version (`v1.0.1`). The workflow checks the tag
against the version, runs the tests, builds the package and publishes it.

When several packages change together, the order matters, because each
package's tests install what it depends on from PyPI. This is the order the
October 2026 releases followed:

1. pedigree-ga4gh;
2. studio2ga4gh, then ga4gh2studio (whose round-trip test installs
   studio2ga4gh);
3. phenopacket-toolkit;
4. abusua2ga4gh, then ga4gh2abusua (whose round-trip test installs
   abusua2ga4gh).

studio2ped, ped2studio, hponorm and mondonorm depend on none of these and can
be released at any time; phenopacket-toolkit works with hponorm and mondonorm
1.0 or 1.1. If a release's tests run before a package it needs has reached
PyPI, the release stops at the install step. Once that package is out, re-run
the failed job to publish it.

## 1. pedigree-ga4gh: a package of its own

`python/pedigree_ga4gh` is now a repository of its own and a PyPI package,
`pedigree-ga4gh` (pure Python, no dependencies). studio2ga4gh,
ga4gh2studio, phenopacket-toolkit, abusua2ga4gh and ga4gh2abusua depend on it
(`pedigree-ga4gh>=1.0,<2`). Its tests are in its repository, and here in
`python/tests/test_pedigree_ga4gh.py`; with
`PHENOPACKET_TOOLS_SCHEMAS` pointing at phenopacket-tools' JSON schemas they
also check its output against those.

It is also where version 1 of the GA4GH Pedigree Standard will go once it is
approved (the drafts are ga4gh/pedigree pull request 50 and KIN's pull request
55: see `docs/ga4gh.md`), so that the tools change together.

An independent review of all the pull requests found three faults here, now
fixed. A term from an ontology the package did not know (SNOMED CT, the
Disease Ontology, ICD-10-CM) was declared with an empty URL and IRI prefix,
which phenopacket-tools reads as missing: those are declared in full now,
with DrugCentral; any other ontology a file declares in full is kept; a term
whose ontology cannot be declared is left out with a warning; and an empty
resource field is an error. abusua2ga4gh 0.2's usual Family, written without
names, is recognised as an old file. And consanguinity, which meant any
ancestor in common, means what KIN means by it: second cousins or closer.
`validate` also reports a person whose id in a PED-style pedigree is `0`.

## 2. studio2ga4gh → 0.4.0

In its pull request; the workbench's copy is the same. What changed:

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
* Carriers, pregnancies and losses are noted in the narrative. A symbol for
  several people is written as one person, with a note under the result.

The README describes the new output. The command's options are backwards
compatible, except that unmatched conditions are now left out. The notes in
the narrative keep people's ids as they are (0.4.0 at first capitalised their
first letter, which turned Pedigree Studio's ids, such as `p6`, into ids
naming nobody).

After the review: only the id of an ontology pedigree-ga4gh can declare counts
in the colour key (“Hypertension (BP:160/95)” is a name); with `--ids drawing`
or `--ids studio` a label becomes an id by studio2ped's rule (“J. Mensah”
gives `J_Mensah`), and one that would be empty, `0` or shared falls back to
the pedigree number; `-d` makes its folder; and a terms file that is missing
or is not JSON is reported as such.

## 3. ga4gh2studio → 0.4.0

In its pull request. It reads GA4GH Pedigrees and Phenopackets
Families through `pedigree_ga4gh`, so it accepts camelCase and proto names,
draws partnerships (consanguineous, separated), adoption (dashed lines), twins,
markers from the narrative, and puts each condition's term in the colour key.
Files from studio2ga4gh 0.3 and abusua2ga4gh 0.2 are refused with a message
saying to upgrade them first. The command takes one file (`ga4gh2studio FILE
-o OUT`); `-g` and `-p` still work. Without `-o` it writes `<name>.studio.json`
beside the file, which is often the drawing the file was made from, so after
the review it never replaces that file unless given `--force`; a file named
with `-o` is replaced, and the file being read never is.

## 4. phenopacket-toolkit → 0.4.0

In its pull request. The “dialects” for the two older
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

The 0.3.0 release has no repository link on PyPI, and its repository was
empty: 0.4.0's metadata links the repository, which now holds the code, its
first commit being 0.3.0 as released. (ChronomicMedicine pull request 1 adds
the toolkit to the lab's Software page; see section 10.)

One change came from hponorm and mondonorm 1.1, which make their ontology
index available at the top of the package. `filter --include-descendants`
tried that index whenever no file was given for an ontology, and loading it
without a file downloads the whole ontology. It now uses an index only if it
can list a term's descendants (neither can yet) and never downloads one; and
a name that OLS gave no answer for is noted in `normalise`'s decision log.

After the review, `normalise` accepts only exact matches by default. At 0.9 it
filled “Maternal hypothyroidism” with HP:0034778 *Maternal hyperthyroidism*
and “Essential hypotension” with MONDO:0001134 *essential hypertension*,
names spelt almost alike that hponorm and mondonorm 1.0 score 93.6 and 93. The
default `--threshold` is now 0.98, which only a term's label (1) or one of its
synonyms (0.98) reaches; a lower threshold still accepts close names, and the
decision log asks for each of those to be checked. With hponorm and mondonorm
1.0 a result counts as exact only if the name is its label or the synonym it
was found by. The Tools tab's form has the new default.

## 5. abusua2ga4gh → 0.3.0

abusua2ga4gh converts Abusua Pedigree Studio sessions. It is not in the
workbench, but it wrote GA4GH files too, and 0.2.0 had all of the faults
below. Its repository was empty; the pull request's first commit is 0.2.0 as
released, and the second makes it write through pedigree-ga4gh, like
studio2ga4gh, which corrects every one of them. For files 0.2 has already
written, `pedigree-ga4gh upgrade` corrects those it can tell from the file, as
marked.

* `KIN:039` is used for a sperm donor: `KIN:039` is *hasGestationalCarrier*;
  a sperm donor is `KIN:004` *isSpermDonorOf*. (Upgrade: corrected, since the
  relation's label, *isSpermDonorOf*, says which was meant.)
* `KIN:011` is labelled *isDizygoticMultipleBirthSiblingOf*; KIN's label is
  *isPolyzygoticMultipleBirthSiblingOf*. (Upgrade: corrected.)
* Foster and social parents are written as `KIN:022` *isAdoptiveParentOf*;
  KIN has `KIN:021` *isFosterParentOf* and `KIN:020` *isParentFigureOf*, which
  0.3.0 uses. (Upgrade: not corrected, as only the relationship's free-text
  description says which was meant. The upgrade keeps the description in the
  narrative, and lists the relationship to be checked when the description
  says foster or social.)
* Carriers get the phenotypic feature `HP:0032500` “Heterozygous carrier”.
  `HP:0032500` is *Exacerbated by tobacco use*, and the HPO has no carrier
  term. Phenopackets have no field for carrier status: the only structured
  place for it is a genomic interpretation of the variant (heterozygous), when
  the variant is known; otherwise a GA4GH Pedigree's narrative, where 0.3.0
  says it. (Upgrade: corrected. The upgrade removes the feature and says who
  is a carrier in a GA4GH Pedigree's narrative, or lists them to be done for a
  Phenopacket; the check reports the term as an error, `carrier-term`.)
* `name` and `diseases` inside `subject`, a `description` on relationships,
  no `metaData` in the Phenopackets, and resources with an empty `version`.
  (Upgrade: corrected.)
* Conditions with empty ontology ids. 0.3.0 leaves them out and says in the
  narrative who has each; `--terms FILE` matches them. (Upgrade: listed to be
  done. They need terms, which `phenotk normalise` or the workbench's *Fill in
  missing terms* give them.)
* Two ids in its built-in list of conditions were wrong: oculocutaneous
  albinism was `MONDO:0019064` (hereditary spastic paraplegia; it is
  `MONDO:0018910`) and "breast and ovarian cancer" was `MONDO:0003832`
  (complement deficiency). 0.3.0 corrects the first and no longer matches the
  second, which names two cancers rather than one Mondo term.

Whatever the GA4GH structure cannot hold of an Abusua session – reported or
unknown paternity, social fathers, fostering, carriers, who is unaffected – is
said in the narrative in fixed sentences, which ga4gh2abusua reads back. After
the review they come after the narrative's own opening sentence, with each
condition's text quoted, so that nothing a person writes there is read as one;
every social parent is named with their role; and a couple who are second
cousins or closer are consanguineous partners (`KIN:030`) whether or not the
session records a union.

## 6. ga4gh2abusua → 0.4.0

The reverse of abusua2ga4gh, which was on PyPI at 0.3.0 with an empty repository. 0.3.0
read abusua2ga4gh 0.2's non-standard files and could not read the standard
form properly: in a Phenopacket the conditions sit beside `subject`, not
inside it, so a standard GA4GH Pedigree came back without them. It also took
carriers from `HP:0032500`. 0.4.0 reads through pedigree-ga4gh, refuses the
older forms with a message to upgrade them, reads abusua2ga4gh 0.3's
narrative, and writes each condition with its ontology id in brackets, so
that a session converted to GA4GH and back is what it was, apart from names,
and converting it again gives the same files. After the review it reads only
abusua2ga4gh's own notes, and never replaces an existing session of the
default name (often the session the files came from) unless given `-o` or
`--force`.

## 7. studio2ped → 0.2.0

All four are done in its pull request: people are named by pedigree numbers
by default (`--ids numbers|drawing|studio|text`, `text` being 0.1.0's ids),
the markers are left out, the id comes off a condition's column name, and
`.studio.json` comes off the output's name as a whole. It also makes the
output folder when `-d` names one that does not exist, and regenerates its
single-file script from the package. After the review, two more: the father
and mother columns are genetic parents only, so an adopted child (a dashed
line) and a child carried by a surrogate (S) get `0` for those parents, as in
studio2ga4gh's Family; and only an ontology's id comes off a column name
(“Hypertension (BP:160/95)” keeps its brackets). What was wrong:

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

## 8. ped2studio → 0.2.2

Its repository was at 0.1.0 while PyPI had 0.2.1, so the pull request's first
commit brings it up to the release. 0.2.2 then keeps apart families in one
PED file that reuse the same ids (they overwrote each other, so seven people
could come out as four), notes a child whose parent is not in the file, makes
`__version__` say the release (0.2.1's said 0.2.0), and regenerates its
single-file script, which was still 0.1.0 and could not read MPED files.

## 9. hponorm and mondonorm → 1.1.0

All of these are done in their pull requests: mapping files are read in any
case, a failed request says that OLS did not answer (`Suggester.last_error`),
OLS's results are scored by how closely their label or a synonym matches, the
local search shortlists names by their words before difflib, and the purl is
fetched over https. The packages now have an `__init__.py` with their
version, the sample ontologies ship in the wheel, and the workbench needs no
change to use them.

The review found one more fault, now fixed in both: scoring by shared
letters made names spelt almost alike look like the same name, whatever they
meant (“Maternal hypothyroidism” scored about 94 against *Maternal
hyperthyroidism*, “Hypertension” 87 against *Hypotension*, type 1 diabetes 85
against type 2). Names whose words differ by an opposite, added or negating
prefix, or that name different types or numbers, are now scored by the words
they share alone, and such words are not close spellings in the local search;
British and American spellings still match, and a Roman numeral is its number.
What was wrong before 1.1:

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

## 10. PedNet, PedGen and PedInterp

These three came later, from Nick Taylor's repositories, now the lab's
(comparativechrono/PedNet, pedigree-generator and pedigree-interpreter). The
workbench carries them in a second archive (`assets/py/pedigree-analysis.zip`),
which the page loads, with NumPy, pandas, OpenCV and Pillow from Pyodide, only
when one of them is first used. `python/vendor/SOURCES.json` records the wheel
each copy came from.

| Package | On PyPI | The workbench's copy |
|---|---|---|
| PedNet | **2.0.0**, released on 19 October 2026 | its wheel from PyPI |
| PedGen | 0.1.3 (Nick Taylor's) | built from `main`, with #2, #3 and #4 merged: the `pedgen` command; `gen_genotype_export`, which writes everyone's genotypes as a table PedNet reads; matplotlib imported only to draw; and (#4) a rare allele by default, cousins who marry, and a minimum number affected |
| PedInterp | 0.1.7 (Nick Taylor's) | built from [pedigree-interpreter#6](https://github.com/comparativechrono/pedigree-interpreter/pull/6), on top of #3, #4 and #5 (merged): the `pedinterp` command (#3); children drawn straight under their parents read correctly (#4); the enlargement chosen to suit the symbols, and warnings when lines were missed (#5); and (#6) the symbols measured as the reading finds them |

PedInterp's fix came from the workbench's example picture of the Lynch family:
drawn where Pedigree Studio draws it, with each child under a parent and the
generations close together, it gave several children their grandparents.
Hough's line detector joins lines across gaps of up to a tenth of the
picture's width, and the blank left where a symbol is taken out is such a gap.
Pull request #4 cuts lines where they cross a symbol, and follows a line to
the first line it meets on the way up. The picture was also enlarged ten times
whatever its size, which misread pictures much smaller or larger than a few
hundred pixels across, often without a warning: pull request #5 enlarges a
picture so that its symbols are about 200 pixels across, and warns when
someone has only one parent or is joined to no one, when the people read
fall into more than one family, or when no one has parents. #5 looked for
the symbols down to a tenth of the usual size, so as to find the small ones
of a pedigree on a large page, but then the holes in the letters of the
labels were measured as symbols when the lines were thinner than the
strokes of the text, and such a picture was enlarged about three times as
much as it needed. Pull request #6 looks for the symbols as the reading
does, and only if none are found, down to a tenth of the usual size.

Until PedGen and PedInterp are released, `pip install` gives their earlier
versions, without the commands. Their versions come from their git tags,
through hatch-vcs, and unlike PedNet they have no workflow that publishes a
release to PyPI yet. Once Tim Hearn is an owner of the two projects on PyPI,
a `release.yml` like PedNet's, with PyPI's trusted publishing, would let a
GitHub release publish them; until then, an owner uploads them. Then copy the
released wheels into the workbench:

```bash
pip download --no-deps --only-binary=:all: PedGen==VERSION PedInterp==VERSION -d wheels
python3 python/tools/vendor_wheels.py wheels/*.whl
python3 python/build_bundle.py && python3 build/make_page.py
```

PedGen and PedNet used to disagree about the allele: PedGen's partners
carried it at 0.1, so about one in five was a carrier, while PedNet takes a
condition to be rare (1 in 1,000 for an autosomal recessive one). Of 19
simulated recessive families of four generations with two or more people
affected (seeds 1 to 60, at most three children a couple), PedNet called none
autosomal recessive. Pull request #4 makes PedGen's default 0.001. With a
rare allele, a recessive condition almost never turns up again unless
relatives marry, so #4 also lets cousins marry (`CousinLikelihood`,
`--cousins`) and makes families until one has enough people affected
(`min_affected`, `--min-affected`); the workbench's form does both for a
recessive condition. Of 30 such families of four generations, PedNet then
called 16 autosomal recessive, and put that mode first in 25.

## 11. The lab web site

Before this, the Software page on comparativechrono.org listed seven of the
packages.
[ChronomicMedicine pull request 1](https://github.com/comparativechrono/ChronomicMedicine/pull/1)
adds pedigree-ga4gh, abusua2ga4gh, ga4gh2abusua and phenopacket-toolkit, puts
Abusua Pedigree Studio and pedigree-ga4gh on the map of formats, and links the
workbench.
