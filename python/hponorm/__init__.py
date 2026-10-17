"""hponorm: validate and normalise the phenotypic features of GA4GH
Phenopackets against the Human Phenotype Ontology (HPO).

The command ``hponorm`` (or ``python -m hponorm``) reviews the features of a
file interactively. In Python::

    from hponorm import HpoIndex, OlsClient, Suggester

    sug = Suggester(HpoIndex.load(SAMPLE_OBO))     # or Suggester(OlsClient())
    for c in sug.suggest("long qt interval", limit=5):
        print(c.id, c.label, c.score, c.matched_on)
"""
__version__ = "1.1.0"

from . import phenopackets  # noqa: E402
from .hpo import SAMPLE_OBO, HpoIndex, HpoTerm, normalise_curie  # noqa: E402
from .ols import OlsClient  # noqa: E402
from .suggest import Candidate, Suggester, best_match, similarity  # noqa: E402

__all__ = [
    "HpoIndex", "HpoTerm", "OlsClient", "Suggester", "Candidate", "SAMPLE_OBO",
    "best_match", "similarity", "normalise_curie", "phenopackets", "__version__",
]
