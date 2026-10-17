"""Unified suggestion layer.

A ``Suggester`` wraps one of two interchangeable backends:

* ``hpo``  - a local :class:`~hponorm.hpo.HpoIndex` (offline capable)
* ``ols``  - the EBI Ontology Lookup Service v4 (online, best ranking)

and exposes a backend-agnostic API used by the CLI:

* ``suggest(label)``    -> ranked list of :class:`Candidate`
* ``resolve(curie)``    -> validate a specific HPO id and return its canonical term
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Candidate:
    """A single suggested ontology term."""

    id: str  # e.g. "HP:0001657"
    label: str  # canonical HPO label
    score: float  # 0-100 match score (higher is better)
    matched_on: str  # "label" or 'synonym: "..."'
    definition: str | None = None
    source: str = ""  # which backend produced it

    def short_def(self, n: int = 90) -> str:
        if not self.definition:
            return ""
        d = " ".join(self.definition.split())
        return d if len(d) <= n else d[: n - 1] + "\u2026"


class Suggester:
    def __init__(self, backend, *, fallback=None, name: str = ""):
        self.backend = backend
        self.fallback = fallback
        self.name = name or getattr(backend, "name", "backend")

    def suggest(self, label: str, limit: int = 8) -> list[Candidate]:
        try:
            results = self.backend.search(label, limit=limit)
        except Exception:
            results = []
        if not results and self.fallback is not None:
            try:
                results = self.fallback.search(label, limit=limit)
            except Exception:
                results = []
        return results

    def resolve(self, curie: str) -> Candidate | None:
        """Look up a specific HPO id to validate it and fetch its canonical label."""
        for be in (self.backend, self.fallback):
            if be is None:
                continue
            try:
                term = be.get(curie)
            except Exception:
                term = None
            if term is not None:
                # ``HpoIndex.get`` returns an HpoTerm; OLS returns a Candidate.
                if isinstance(term, Candidate):
                    return term
                return Candidate(
                    id=term.id,
                    label=term.label,
                    score=100.0,
                    matched_on="exact id",
                    definition=getattr(term, "definition", None),
                    source=getattr(be, "name", self.name),
                )
        return None
