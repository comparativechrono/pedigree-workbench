"""EBI Ontology Lookup Service (OLS4) backend for MONDO.

Provides high-quality ranked search over the live MONDO ontology without any
local download. Used when the machine is online; otherwise the CLI falls back
to the local :class:`~mondonorm.mondo.MondoIndex`.

OLS4 API docs: https://www.ebi.ac.uk/ols4/help
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .suggest import Candidate

OLS_BASE = "https://www.ebi.ac.uk/ols4/api"


class OlsClient:
    name = "ols"

    def __init__(self, base: str = OLS_BASE, timeout: int = 15):
        self.base = base.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ utils
    def _get_json(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "mondonorm/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def available(self) -> bool:
        try:
            self._get_json(f"{self.base}/ontologies/mondo")
            return True
        except Exception:
            return False

    # ----------------------------------------------------------------- search
    def search(self, query: str, limit: int = 8) -> list[Candidate]:
        query = (query or "").strip()
        if not query:
            return []
        params = urllib.parse.urlencode(
            {
                "q": query,
                "ontology": "mondo",
                "type": "class",
                "rows": max(limit, 10),
                "fieldList": "obo_id,label,description,synonym,is_obsolete",
            }
        )
        data = self._get_json(f"{self.base}/search?{params}")
        docs = (data.get("response") or {}).get("docs", [])
        out: list[Candidate] = []
        seen: set[str] = set()
        # OLS returns docs in relevance order; map that to a descending score.
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
            out.append(
                Candidate(
                    id=obo_id,
                    label=doc.get("label") or obo_id,
                    score=round(max(1.0, 100.0 - rank * 4), 1),
                    matched_on="OLS relevance",
                    definition=desc,
                    source="ols",
                )
            )
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------- term
    def get(self, curie: str) -> Candidate | None:
        from .mondo import normalise_curie

        c = normalise_curie(curie)
        if not c:
            return None
        iri = f"http://purl.obolibrary.org/obo/{c.replace(':', '_')}"
        params = urllib.parse.urlencode({"iri": iri})
        try:
            data = self._get_json(f"{self.base}/ontologies/mondo/terms?{params}")
        except Exception:
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
        )
