"""Ontology terms: CURIEs, OntologyClass objects and MetaData resources.

Phenopackets name every disease, phenotype and other coded value with an
``OntologyClass``: ``{"id": "MONDO:0007254", "label": "breast cancer"}``. The
``id`` is required and must be a CURIE (prefix, colon, local id). The label is
required too and must not be empty. Every prefix used in a Phenopacket must be
declared as a ``Resource`` in its ``metaData``, with all six resource fields
filled in.

The resource details below follow the values used by phenopacket-tools, the
GA4GH reference implementation, so that files from the two agree.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

# PREFIX:LOCAL. The prefix starts with a letter. Neither part may contain a
# space, a second colon or an underscore: phenopacket-tools splits ids on ':'
# and '_' and rejects any id that gives more than two pieces.
_CURIE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9.\-]*):([^\s:_]+)$")

# Prefixes written in a different case by some tools, mapped to the usual form.
_PREFIX_CASE = {
    "hp": "HP", "hpo": "HP", "mondo": "MONDO", "omim": "OMIM", "mim": "OMIM",
    "orpha": "ORPHA", "orphanet": "ORPHA", "ncit": "NCIT", "uberon": "UBERON",
    "hgnc": "HGNC", "geno": "GENO", "so": "SO", "eco": "ECO", "efo": "EFO",
    "loinc": "LOINC", "ucum": "UCUM", "chebi": "CHEBI", "ncbitaxon": "NCBITaxon",
    "hancestro": "HANCESTRO", "pato": "PATO", "uo": "UO", "cl": "CL", "maxo": "MAXO",
    "snomedct": "SNOMEDCT", "kin": "KIN",
}

RESOURCES: Dict[str, Dict[str, str]] = {
    "HP": {"id": "hp", "name": "human phenotype ontology",
           "url": "http://purl.obolibrary.org/obo/hp.owl",
           "iriPrefix": "http://purl.obolibrary.org/obo/HP_"},
    "MONDO": {"id": "mondo", "name": "Mondo Disease Ontology",
              "url": "http://purl.obolibrary.org/obo/mondo.obo",
              "iriPrefix": "http://purl.obolibrary.org/obo/MONDO_"},
    "OMIM": {"id": "omim", "name": "An Online Catalog of Human Genes and Genetic Disorders",
             "url": "https://www.omim.org", "iriPrefix": "https://www.omim.org/entry/"},
    "ORPHA": {"id": "ordo", "name": "Orphanet Rare Disease Ontology",
              "url": "http://www.orpha.net/ontology/orphanet.owl",
              "iriPrefix": "http://www.orpha.net/ORDO/Orphanet_"},
    "NCIT": {"id": "ncit", "name": "NCI Thesaurus",
             "url": "http://purl.obolibrary.org/obo/ncit.owl",
             "iriPrefix": "http://purl.obolibrary.org/obo/NCIT_"},
    "GENO": {"id": "geno", "name": "Genotype Ontology",
             "url": "http://purl.obolibrary.org/obo/geno.owl",
             "iriPrefix": "http://purl.obolibrary.org/obo/GENO_"},
    "HGNC": {"id": "hgnc", "name": "HUGO Gene Nomenclature Committee",
             "url": "https://www.genenames.org",
             "iriPrefix": "https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/"},
    "UBERON": {"id": "uberon", "name": "Uber-anatomy ontology",
               "url": "http://purl.obolibrary.org/obo/uberon.owl",
               "iriPrefix": "http://purl.obolibrary.org/obo/UBERON_"},
    "SO": {"id": "so", "name": "Sequence types and features ontology",
           "url": "http://purl.obolibrary.org/obo/so.owl",
           "iriPrefix": "http://purl.obolibrary.org/obo/SO_"},
    "ECO": {"id": "eco", "name": "Evidence & Conclusion Ontology (ECO)",
            "url": "http://purl.obolibrary.org/obo/eco.owl",
            "iriPrefix": "http://purl.obolibrary.org/obo/ECO_"},
    "EFO": {"id": "efo", "name": "Experimental Factor Ontology",
            "url": "http://www.ebi.ac.uk/efo/efo.owl",
            "iriPrefix": "http://purl.obolibrary.org/obo/EFO_"},
    "PATO": {"id": "pato", "name": "PhenotypicFeature And Trait Ontology",
             "url": "http://purl.obolibrary.org/obo/pato.owl",
             "iriPrefix": "http://purl.obolibrary.org/obo/PATO_"},
    "UO": {"id": "uo", "name": "Units of measurement ontology",
           "url": "http://purl.obolibrary.org/obo/uo.owl",
           "iriPrefix": "http://purl.obolibrary.org/obo/UO_"},
    "CL": {"id": "cl", "name": "Cell Ontology",
           "url": "http://purl.obolibrary.org/obo/cl.owl",
           "iriPrefix": "http://purl.obolibrary.org/obo/CL_"},
    "NCBITaxon": {"id": "ncbitaxon", "name": "NCBI organismal classification",
                  "url": "http://purl.obolibrary.org/obo/ncbitaxon.owl",
                  "iriPrefix": "http://purl.obolibrary.org/obo/NCBITaxon_"},
    "UCUM": {"id": "ucum", "name": "Unified Code for Units of Measure",
             "url": "https://ucum.org", "iriPrefix": "https://units-of-measurement.org/"},
    "LOINC": {"id": "loinc", "name": "Logical Observation Identifiers Names and Codes",
              "url": "https://loinc.org", "iriPrefix": "https://loinc.org/"},
    "CHEBI": {"id": "chebi", "name": "Chemical Entities of Biological Interest",
              "url": "https://www.ebi.ac.uk/chebi",
              "iriPrefix": "https://purl.obolibrary.org/obo/CHEBI_"},
    "HANCESTRO": {"id": "hancestro", "name": "Human Ancestry Ontology",
                  "url": "http://purl.obolibrary.org/obo/hancestro.owl",
                  "iriPrefix": "http://purl.obolibrary.org/obo/HANCESTRO_"},
    "MAXO": {"id": "maxo", "name": "Medical Action Ontology",
             "url": "http://purl.obolibrary.org/obo/maxo.owl",
             "iriPrefix": "http://purl.obolibrary.org/obo/MAXO_"},
}

# Recorded as the version when the ontology release behind a term is not known.
UNKNOWN_VERSION = "unknown"


def is_curie(value: Optional[str]) -> bool:
    """True for a CURIE that Phenopackets tools accept, such as ``HP:0001626``."""
    return bool(value) and bool(_CURIE_RE.match(value))


def prefix_of(curie: str) -> str:
    return curie.split(":", 1)[0] if curie and ":" in curie else ""


def tidy_curie(value: str) -> str:
    """Trim a CURIE and put a well-known prefix in its usual case (``hp:1`` -> ``HP:1``)."""
    v = (value or "").strip()
    if ":" not in v:
        return v
    prefix, local = v.split(":", 1)
    return "{}:{}".format(_PREFIX_CASE.get(prefix.lower(), prefix), local.strip())


def ontology_class(curie: str, label: str) -> Dict[str, str]:
    """An ``OntologyClass``. Raises ``ValueError`` unless both parts are valid."""
    cid = tidy_curie(curie)
    if not is_curie(cid):
        raise ValueError("{!r} is not a CURIE (an ontology id such as HP:0001626)".format(curie))
    lab = (label or "").strip()
    if not lab:
        raise ValueError("ontology term {} needs a label".format(cid))
    return {"id": cid, "label": lab}


def resource(prefix: str, version: Optional[str] = None) -> Dict[str, str]:
    """A MetaData ``Resource`` for a prefix, with every field filled in.

    Prefixes this module does not know get a minimal entry whose URL and IRI
    prefix are blank; :func:`pedigree_ga4gh.validate.validate` reports those.
    """
    p = _PREFIX_CASE.get(prefix.lower(), prefix)
    known = RESOURCES.get(p)
    if known is None:
        return {"id": p.lower(), "name": p, "url": "", "version": version or UNKNOWN_VERSION,
                "namespacePrefix": p, "iriPrefix": ""}
    return {"id": known["id"], "name": known["name"], "url": known["url"],
            "version": version or UNKNOWN_VERSION, "namespacePrefix": p,
            "iriPrefix": known["iriPrefix"]}


def resources_for(prefixes: Iterable[str], versions: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """One resource per distinct prefix, in a stable order."""
    versions = versions or {}
    out = []
    for p in sorted({_PREFIX_CASE.get(x.lower(), x) for x in prefixes if x}):
        out.append(resource(p, versions.get(p)))
    return out


def iter_ontology_classes(obj, path: str = ""):
    """Yield ``(path, ontology_class_dict)`` for every OntologyClass-shaped dict.

    Used to find the prefixes a message uses. An OntologyClass is any dict
    with an ``id`` and a ``label`` and nothing else, the shape the Phenopacket
    schema gives it; relationship ``relation`` terms are included.
    """
    if isinstance(obj, dict):
        keys = set(obj)
        if keys and keys <= {"id", "label"} and "id" in keys and isinstance(obj.get("id"), str) \
                and ("label" in keys):
            yield path, obj
            return
        for k, v in obj.items():
            yield from iter_ontology_classes(v, "{}.{}".format(path, k) if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_ontology_classes(v, "{}[{}]".format(path, i))
