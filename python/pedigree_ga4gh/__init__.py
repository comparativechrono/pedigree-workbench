"""pedigree-ga4gh: one implementation of GA4GH pedigree and Phenopacket output.

studio2ga4gh, ga4gh2studio, abusua2ga4gh, ga4gh2abusua, the phenopacket toolkit
(phenotk) and the Pedigree workbench all read and write GA4GH files through
this package, so they agree on one form:

* **GA4GH Pedigree** in its Phenopackets form: ``individuals`` are
  Phenopackets, ``relationships`` are ``{individualId, relation, relativeId}``
  with KIN terms (:mod:`pedigree_ga4gh.pedigree`);
* **Phenopackets v2** Phenopackets, Families and Cohorts
  (:mod:`pedigree_ga4gh.phenopackets`).

Typical use::

    from pedigree_ga4gh import Kindred, Member, Relation, Term, to_ga4gh_pedigree, validate
    k = Kindred("FAM1", members=[Member("MOTHER", sex="FEMALE"), Member("CHILD", index=True,
                terms=[Term("cystic fibrosis", "MONDO:0009061")])],
                relations=[Relation("MOTHER", "KIN:027", "CHILD")])
    doc, warnings = to_ga4gh_pedigree(k, created_by="me")
    assert not [f for f in validate(doc) if f.severity == "error"]
"""
from __future__ import annotations

from . import kin, ontology, phenopackets, pedigree, schema
from .io import dump, dumps, load, loads
from .kindred import (DISEASE, PHENOTYPE, Kindred, Member, Relation, Term, detect, from_document,
                      from_ga4gh_pedigree, from_phenopackets_family, to_ga4gh_pedigree,
                      to_phenopackets_family)
from .legacy import identify as identify_legacy, upgrade
from .validate import ERROR, INFO, WARNING, Finding, errors, is_valid, render as render_findings, validate

__version__ = "1.0.0"

__all__ = [
    "__version__", "kin", "ontology", "phenopackets", "pedigree", "schema",
    "Kindred", "Member", "Relation", "Term", "DISEASE", "PHENOTYPE",
    "to_ga4gh_pedigree", "to_phenopackets_family", "from_document", "from_ga4gh_pedigree",
    "from_phenopackets_family", "detect", "identify_legacy", "upgrade",
    "validate", "Finding", "errors", "is_valid", "render_findings", "ERROR", "WARNING", "INFO",
    "load", "loads", "dump", "dumps",
]
