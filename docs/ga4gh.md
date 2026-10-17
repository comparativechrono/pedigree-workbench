# The GA4GH form the workbench writes, and why

This note records how the workbench writes GA4GH files, what was wrong with the
files our tools wrote before, and the sources behind each decision. It is for
whoever maintains the packages; the help in the workbench (Files and standards →
The GA4GH Pedigree) explains the same for people using it.

## In short

* There is now **one implementation** of GA4GH output, `pedigree_ga4gh`
  (`python/pedigree_ga4gh`). studio2ga4gh, ga4gh2studio and the phenopacket
  toolkit all read and write GA4GH files through it, so they cannot disagree
  again.
* A **GA4GH Pedigree** is written in the Phenopackets form proposed for the
  standard: `individuals` are full Phenopackets v2, `relationships` are
  `{individualId, relation, relativeId}` with a current KIN term as the
  relation, and `indexPatients` lists the proband.
* A **Phenopackets Family** is written exactly to the Phenopackets v2 schema.
* Every file passes the checks of the Phenopackets v2 JSON schemas and of
  phenopacket-tools, the GA4GH's own validator, wherever they apply.
  `pedigree_ga4gh.validate` applies the same checks (and those of the pedigree:
  KIN terms, people named in relationships, parents' sexes, loops of
  ancestry), so the workbench can check a file without Java.
* Files from the older versions are recognised, refused by the readers with a
  clear message, and converted once with `pedigree-ga4gh upgrade` (or
  `phenotk upgrade`, or the Tools tab's *Upgrade a file from an older tool*).

## What the GA4GH Pedigree standard is

The GA4GH Pedigree Standard is still being written. The GA4GH's page for it
says it is “Currently in development”, with a call for pilots in March 2024.
Its documentation describes it as a conceptual model – a pedigree is a set of
individuals and the relationships between them, each relationship coded with
the Kinship Ontology (KIN) – with implementation guides in other standards and
some tooling. It is not a file format of its own: it is carried either by
Phenopackets or by HL7 FHIR.

* **The Phenopackets form** was proposed as a new message,
  `org.ga4gh.pedigree.v1.Pedigree`, in phenopacket-schema pull request #364
  (Jules Jacobsen, 24 November 2022): an `id`, a `narrative`, a `date`, a
  `status`, `index_patients`, `individuals` (each a Phenopacket) and
  `relationships` (`individual_id`, `relation` as an ontology class,
  `relative_id`). The pull request was closed without being merged on
  26 September 2025 with the comment “The Pedigree group still hasn't decided
  on anything, so I'm closing this.” The message is therefore in no release of
  the schema.
* **The FHIR form** is a draft implementation guide (version 0.1.0) using
  FamilyMemberHistory resources; Open Pedigree and a REDCap plug-in use it,
  with older KIN codes.

Neither form is approved. The only approved GA4GH format our tools write is
**Phenopackets v2** (Phenopacket, Family, Cohort).

## Why the Phenopackets form

* Our users work with Phenopackets: the Family file is already Phenopackets v2,
  and the phenopacket toolkit is built around them.
* In this form every individual is a Phenopacket, so everything about a
  person – diseases, phenotypes, vital status – is in an approved, validated
  structure. Only the wrapper (the list of individuals and the relationships)
  comes from the proposal.
* The standard's own examples use this form
  (pedigree.readthedocs.io, *Examples*).
* JSON is written as proto3 JSON is: field names in camelCase
  (`indexPatients`, `individualId`, `relativeId`). Readers also accept the
  proto names (`index_patients` …), as proto3 JSON parsers must.

If the GA4GH settles on a different form, `pedigree_ga4gh/pedigree.py` is the
one place to change, and `upgrade` can rewrite files from this form.

## What a GA4GH Pedigree from the workbench contains

```json
{
  "id": "FAM1",
  "narrative": "Pedigree drawn in Pedigree Studio: 16 people; proband IV-3. …",
  "date": "2026-10-17",
  "indexPatients": ["IV-3"],
  "individuals": [
    {
      "id": "FAM1-II-3",
      "subject": {"id": "II-3", "vitalStatus": {"status": "ALIVE"}, "sex": "FEMALE"},
      "diseases": [{"term": {"id": "MONDO:0007254", "label": "breast cancer"}}],
      "metaData": {
        "created": "2026-10-17T09:00:00Z",
        "createdBy": "studio2ga4gh 0.4.0",
        "resources": [{"id": "mondo", "name": "Mondo Disease Ontology", "url": "http://purl.obolibrary.org/obo/mondo.obo",
                       "version": "2026-10-06", "namespacePrefix": "MONDO", "iriPrefix": "http://purl.obolibrary.org/obo/MONDO_"}],
        "phenopacketSchemaVersion": "2.0"
      }
    }
  ],
  "relationships": [
    {"individualId": "I-1", "relation": {"id": "KIN:028", "label": "isBiologicalFatherOf"}, "relativeId": "II-3"}
  ]
}
```

* People are named by their pedigree numbers (II-3), as Pedigree Studio
  numbers them, unless the person converting chooses the labels in the drawing
  (which may be names) or the Studio's own ids.
* Each Phenopacket has its own `metaData`, with a `resource` for every ontology
  prefix its terms use and the release of that ontology when it is known (from
  the terms file, the ontology file searched, or EBI's Ontology Lookup
  Service), and `"unknown"` when it is not.
* A condition with no ontology term is **left out**, with a note: a disease or
  phenotypic feature without an id is invalid. The workbench's *Match
  conditions to terms* tool gives conditions their terms first.
* Relationships use the 48 current KIN terms (`KIN:031` *hasSex* is not a
  relationship between people and is never used). Each relation is written
  once: symmetric ones (partners, twins) in one direction only.
* Things the standard has no field for – a carrier, a pregnancy, a symbol that
  stands for several people – go into the `narrative`, so they are not lost.

### KIN

KIN is read from `kin.owl` in GA4GH-Pedigree-Standard/family_history_terminology
(commit 71616ea, 16 September 2024), the file behind `http://purl.org/ga4gh/kin.owl`.
Codes and labels are written exactly as KIN gives them. Codes from earlier drafts
of KIN that turn up in files are recognised and replaced by `upgrade`
(`KIN:033`→`KIN:003`, `KIN:048`→`KIN:050`, and so on; for five of them the
direction is reversed as well – see `pedigree_ga4gh/kin.py`, `RETIRED`).

## The Phenopackets Family

* `proband` is the index patient's Phenopacket; `relatives` are the other
  members who have findings (a relative with nothing to record is in the
  pedigree but has no Phenopacket).
* `pedigree.persons` is the PED-style pedigree of the whole family: family id,
  individual id, paternal and maternal ids, sex and affected status. Parents
  come from the biological relations (and sperm and egg donors); adoptive,
  foster and step-parents are not genetic parents and are not written there.
* `consanguinousParents` (spelt as the schema spells it) says whether the
  proband's parents are related, worked out from the relationships.
* The Family has its own `metaData`, and so does each Phenopacket in it.

## The checks

`pedigree_ga4gh.validate` reports errors (the file is invalid), warnings (worth
fixing) and notes, each with where in the file and how to fix it. They follow:

* the Phenopackets v2 JSON schemas in phenopacket-tools (required fields,
  types, enumerations, `oneof` groups, minimum lengths and counts);
* phenopacket-tools' MetaDataValidator: every ontology id must be a CURIE whose
  prefix is declared in the `metaData.resources` of the top-level message;
* the GA4GH Pedigree: every id in `relationships` and `indexPatients` must be
  the `subject.id` of an individual; relations must be current KIN terms with
  their own labels; no one is related to themselves; a biological mother is
  female and a father male; no one has more than two genetic parents; nobody
  is their own ancestor;
* one mistake of the older files that is valid in form but wrong in meaning:
  `HP:0032500` used for a carrier (`carrier-term`).

phenopacket-tools prints enum and boolean defaults and drops empty strings and
empty lists, so a missing `consanguinousParents` (false) or an empty
`resources` list is accepted; an empty id is not (it disappears and the field
is then missing).

## What was wrong before

| Tool and version | What it wrote | Why it was wrong |
|---|---|---|
| studio2ga4gh 0.3, GA4GH Pedigree | People with `sex`, `deceased` and `affected` on them; relationships with `individual` and `relative` | The conceptual model written straight out as JSON. Neither GA4GH form looks like this, and no other software reads it. |
| studio2ga4gh 0.3, Phenopackets Family | Phenopackets without `metaData`; `metaData` without `phenopacketSchemaVersion`; conditions with an empty ontology id | Each is invalid Phenopackets v2. |
| abusua2ga4gh 0.2, GA4GH Pedigree | Diseases and a `name` inside `subject`; a `description` on relationships; no `metaData` in the Phenopackets; resource versions of `""` | Unknown fields are rejected by Phenopackets readers; diseases belong to the Phenopacket, not the subject; `metaData` is required. |
| abusua2ga4gh 0.2, KIN | `KIN:039` for a sperm donor; `KIN:011` labelled *isDizygoticMultipleBirthSiblingOf*; `KIN:022` (adoptive parent) for foster and social parents | `KIN:039` is *hasGestationalCarrier*; a sperm donor is `KIN:004`. KIN's label for `KIN:011` is *isPolyzygoticMultipleBirthSiblingOf*. KIN has `KIN:021` *isFosterParentOf* and `KIN:020` *isParentFigureOf*. |
| abusua2ga4gh 0.2, carriers | A phenotypic feature `HP:0032500` “Heterozygous carrier” | `HP:0032500` is *Exacerbated by tobacco use*. The HPO has no carrier term: carrier status is not a phenotype, and Phenopackets have no field for it. The only structured place for it is a genomic interpretation of the variant (heterozygous), when the variant is known; otherwise a GA4GH Pedigree's narrative, as studio2ga4gh writes it. |
| phenopacket-toolkit 0.3 | “Dialects” that accepted both of the forms above | Being able to read two incorrect forms kept them alive. 0.4 reads one form, refuses the old ones with a message, and converts them with `phenotk upgrade`. |
| ga4gh2studio 0.3 | Read only studio2ga4gh 0.3's form | 0.4 reads the standard forms through `pedigree_ga4gh`. |

## A correction

An earlier message said that leaving out `consanguinousParents` when it is
false was an error. It is not: proto3 JSON may leave out default values, and
phenopacket-tools accepts the field either way. The workbench writes it
always, which is also valid. Likewise an empty `resources` list is not itself
an error in the JSON (the printer drops it); what is required is a resource for
every prefix that is used.

## Sources

* GA4GH, *Pedigree* (product page): https://ga4gh.org/product/pedigree – “Currently in development”.
* GA4GH Pedigree Standard documentation: https://pedigree.readthedocs.io/ (Introduction; Examples; KIN).
* phenopacket-schema pull request #364, *Pedigree*: https://github.com/phenopackets/phenopacket-schema/pull/364 (opened 24 November 2022, closed unmerged 26 September 2025).
* Phenopackets v2 schema: https://github.com/phenopackets/phenopacket-schema and https://phenopacket-schema.readthedocs.io/
* phenopacket-tools (validator and JSON schemas): https://github.com/phenopackets/phenopacket-tools
* KIN: https://github.com/GA4GH-Pedigree-Standard/family_history_terminology (`kin.owl`, commit 71616ea)
* Pedigree FHIR implementation guide (draft 0.1.0): https://github.com/GA4GH-Pedigree-Standard/pedigree-fhir-ig
* Jacobsen JOB, Baudis M, Baynam GS, et al. The GA4GH Phenopacket schema defines a computable representation of clinical data. *Nat Biotechnol* 2022;40(6):817–820. doi:10.1038/s41587-022-01357-4
* Danis D, Jacobsen JOB, Wagner AH, et al. Phenopacket-tools: building and validating GA4GH Phenopackets. *PLoS ONE* 2023;18(5):e0285433. doi:10.1371/journal.pone.0285433
* Human Phenotype Ontology: Gargano MA, Matentzoglu N, Coleman B, et al. The Human Phenotype Ontology in 2024: phenotypes around the world. *Nucleic Acids Res* 2024;52(D1):D1333–D1346. doi:10.1093/nar/gkad1005 – `HP:0032500` checked in the release of 2026-09-01.
