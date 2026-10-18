"""EBI Ontology Lookup Service (OLS4) backend for MONDO.

Searches the live MONDO without any local download. Used when the machine is
online; otherwise the CLI falls back to the local :class:`~mondonorm.mondo.MondoIndex`.

OLS returns its results in its own order of relevance. Each result is scored
here by how closely its label, or one of its synonyms, matches the name
searched for (:func:`~mondonorm.suggest.best_match`), and the results are
returned best first, so a score means the same as one from the local index.

OLS4 API docs: https://www.ebi.ac.uk/ols4/help
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .suggest import Candidate, best_match

OLS_BASE = "https://www.ebi.ac.uk/ols4/api"


def _strings(value) -> list[str]:
    """Synonyms as OLS gives them: a list of strings, one string, or objects with a value."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    out = []
    for v in value if isinstance(value, list) else [value]:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict) and isinstance(v.get("value") or v.get("val"), str):
            out.append(v.get("value") or v.get("val"))
    return out


class OlsClient:
    name = "ols"

    def __init__(self, base: str = OLS_BASE, timeout: int = 15):
        self.base = base.rstrip("/")
        self.timeout = timeout
        #: why the last ``get`` could not ask OLS, or None
        self.last_error: str | None = None

    # ------------------------------------------------------------------ utils
    def _get_json(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "mondonorm/" + __version__})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def available(self) -> bool:
        try:
            self._get_json(f"{self.base}/ontologies/mondo")
            return True
        except Exception:
            return False

    @staticmethod
    def failure_message(exc: Exception) -> str:
        """What went wrong when OLS was asked, in a sentence."""
        reason = exc.reason if isinstance(exc, urllib.error.URLError) and not isinstance(
            exc, urllib.error.HTTPError) else exc
        if isinstance(exc, urllib.error.HTTPError):
            return "EBI's Ontology Lookup Service answered with an error (HTTP {} {})".format(
                exc.code, exc.reason or "").strip()
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "EBI's Ontology Lookup Service did not answer in time"
        if isinstance(exc, ValueError):
            return "EBI's Ontology Lookup Service sent an answer that could not be read"
        return "EBI's Ontology Lookup Service did not answer ({})".format(
            str(reason) or type(reason).__name__)

    # ----------------------------------------------------------------- search
    def search(self, query: str, limit: int = 8) -> list[Candidate]:
        """Terms for the name ``query``, best first. Raises the network's error
        when OLS cannot be asked (the :class:`~mondonorm.suggest.Suggester`
        records it in ``last_error``)."""
        query = (query or "").strip()
        if not query:
            return []
        params = urllib.parse.urlencode(
            {
                "q": query,
                "ontology": "mondo",
                "type": "class",
                # more than are wanted, since they are scored and sorted here
                "rows": max(limit * 3, 25),
                "fieldList": "obo_id,label,description,synonym,is_obsolete",
            }
        )
        data = self._get_json(f"{self.base}/search?{params}")
        docs = (data.get("response") or {}).get("docs", [])
        found: list[tuple[float, int, Candidate]] = []
        seen: set[str] = set()
        for rank, doc in enumerate(docs):
            obo_id = doc.get("obo_id")
            if not obo_id or not obo_id.startswith("MONDO:"):
                continue
            if doc.get("is_obsolete"):
                continue
            if obo_id in seen:
                continue
            seen.add(obo_id)
            desc = doc.get("description")
            if isinstance(desc, list):
                desc = desc[0] if desc else None
            label = doc.get("label") or obo_id
            synonyms = list(dict.fromkeys(_strings(doc.get("synonym")) + _strings(doc.get("synonyms"))))
            score, matched_on = best_match(query, label, synonyms)
            found.append((score, rank, Candidate(
                id=obo_id,
                label=label,
                score=round(score, 1),
                matched_on=matched_on,
                definition=desc,
                source="ols",
                synonyms=synonyms,
            )))
        # the closest first; among equals, OLS's own order
        found.sort(key=lambda t: (-t[0], t[1]))
        return [c for _, _, c in found[:limit]]

    # ------------------------------------------------------------------- term
    def get(self, curie: str) -> Candidate | None:
        """The term with this id, or None. None also when OLS cannot be asked,
        as in version 1.0; then :attr:`last_error` says why."""
        from .mondo import normalise_curie

        self.last_error = None
        c = normalise_curie(curie)
        if not c:
            return None
        iri = f"http://purl.obolibrary.org/obo/{c.replace(':', '_')}"
        params = urllib.parse.urlencode({"iri": iri})
        try:
            data = self._get_json(f"{self.base}/ontologies/mondo/terms?{params}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:  # 404: OLS has no such term
                self.last_error = self.failure_message(exc)
            return None
        except Exception as exc:
            self.last_error = self.failure_message(exc)
            return None
        terms = (data.get("_embedded") or {}).get("terms", [])
        if not terms:
            return None
        t = terms[0]
        desc = t.get("description")
        if isinstance(desc, list):
            desc = desc[0] if desc else None
        return Candidate(
            id=c,
            label=t.get("label") or c,
            score=100.0,
            matched_on="exact id",
            definition=desc,
            source="ols",
            synonyms=_strings(t.get("synonyms")) or _strings(t.get("synonym")),
        )
