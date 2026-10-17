"""mondonorm: validate and normalise the disease terms of GA4GH Phenopackets
against the Mondo Disease Ontology (MONDO).

The command ``mondonorm`` (or ``python -m mondonorm``) reviews the diseases of
a file interactively. In Python::

    from mondonorm import MondoIndex, OlsClient, Suggester

    sug = Suggester(MondoIndex.load(SAMPLE_OBO))     # or Suggester(OlsClient())
    for c in sug.suggest("sickle cell anaemia", limit=5):
        print(c.id, c.label, c.score, c.matched_on)
"""
__version__ = "1.1.0"

from . import phenopackets  # noqa: E402
from .mondo import SAMPLE_OBO, MondoIndex, MondoTerm, normalise_curie  # noqa: E402
from .ols import OlsClient  # noqa: E402
from .suggest import Candidate, Suggester, best_match, similarity  # noqa: E402

__all__ = [
    "MondoIndex", "MondoTerm", "OlsClient", "Suggester", "Candidate", "SAMPLE_OBO",
    "best_match", "similarity", "normalise_curie", "phenopackets", "__version__",
]
