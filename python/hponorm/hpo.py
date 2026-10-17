"""Local HPO (Human Phenotype Ontology) index.

Loads HPO from a local ``.obo`` or obographs ``.json`` file (downloading and
caching the official release on first use if permitted), builds an in-memory
search index over term labels + synonyms, and answers two questions:

* ``search(query)``  -> ranked candidate terms for a free-text phenotype label
* ``get(curie)``     -> the canonical term for a specific ``HP:xxxxxxx`` id

Fuzzy matching uses ``rapidfuzz`` when available and falls back to the stdlib
``difflib`` otherwise, so the tool runs even in a minimal environment.
"""
from __future__ import annotations

import json
import os
import pickle
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .suggest import Candidate

# Official, version-pinned-to-"latest" PURLs maintained by the Monarch Initiative.
HPO_OBO_URL = "http://purl.obolibrary.org/obo/hp.obo"
HPO_JSON_URL = "http://purl.obolibrary.org/obo/hp.json"

_CURIE_RE = re.compile(r"^HP:\d{7}$")
_IRI_RE = re.compile(r"HP_(\d{7})")

try:  # Optional, much faster + better quality.
    from rapidfuzz import fuzz, process

    _HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - exercised only when dep is absent
    import difflib

    _HAVE_RAPIDFUZZ = False


@dataclass
class HpoTerm:
    id: str
    label: str
    synonyms: list[str] = field(default_factory=list)
    definition: str | None = None
    obsolete: bool = False


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "hponorm"


def normalise_curie(raw: str) -> str | None:
    """Coerce user input / IRIs to a canonical ``HP:xxxxxxx`` curie, or None."""
    s = raw.strip()
    if not s:
        return None
    m = _IRI_RE.search(s)
    if m:
        return f"HP:{m.group(1)}"
    s = s.replace("_", ":")
    if not s.upper().startswith("HP"):
        # Allow bare 7-digit ids like "0001657".
        digits = re.sub(r"\D", "", s)
        if len(digits) == 7:
            return f"HP:{digits}"
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) != 7:
        return None
    return f"HP:{digits}"


class HpoIndex:
    """An in-memory, searchable index of HPO phenotype terms."""

    name = "hpo-local"

    def __init__(self, terms: dict[str, HpoTerm], source: str):
        self.source = source
        self.terms: dict[str, HpoTerm] = terms
        # Parallel arrays for fast fuzzy scanning: searchable string -> term id.
        self._names: list[str] = []
        self._owner: list[str] = []  # term id for _names[i]
        self._kind: list[str] = []  # "label" or "synonym"
        self._exact: dict[str, list[tuple[str, str]]] = {}  # lower text -> [(id, kind)]
        for t in terms.values():
            if t.obsolete:
                continue
            self._add_name(t.id, t.label, "label")
            for syn in t.synonyms:
                self._add_name(t.id, syn, "synonym")

    def _add_name(self, term_id: str, text: str, kind: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._names.append(text)
        self._owner.append(term_id)
        self._kind.append(kind)
        self._exact.setdefault(text.lower(), []).append((term_id, kind))

    # ------------------------------------------------------------------ lookup
    def get(self, curie: str) -> HpoTerm | None:
        c = normalise_curie(curie)
        return self.terms.get(c) if c else None

    def __len__(self) -> int:
        return len(self.terms)

    # ------------------------------------------------------------------ search
    def search(self, query: str, limit: int = 8) -> list[Candidate]:
        query = (query or "").strip()
        if not query:
            return []
        scored: dict[str, Candidate] = {}

        def consider(term_id: str, score: float, matched_on: str, kind: str) -> None:
            t = self.terms.get(term_id)
            if t is None or t.obsolete:
                return
            tag = "label" if kind == "label" else f"synonym: {matched_on}"
            prev = scored.get(term_id)
            if prev is None or score > prev.score:
                scored[term_id] = Candidate(
                    id=t.id,
                    label=t.label,
                    score=round(float(score), 1),
                    matched_on=tag,
                    definition=t.definition,
                    source="hpo-local",
                )

        # 1) Exact (case-insensitive) label / synonym hits get a strong score.
        for term_id, kind in self._exact.get(query.lower(), []):
            consider(term_id, 100.0 if kind == "label" else 98.0, query, kind)

        # 2) Fuzzy scan across all label + synonym strings.
        if _HAVE_RAPIDFUZZ:
            matches = process.extract(
                query, self._names, scorer=fuzz.WRatio, limit=limit * 6
            )
            for matched_text, score, idx in matches:
                consider(self._owner[idx], score, matched_text, self._kind[idx])
        else:  # difflib fallback
            ratios = (
                (difflib.SequenceMatcher(None, query.lower(), n.lower()).ratio(), i)
                for i, n in enumerate(self._names)
            )
            top = sorted(ratios, reverse=True)[: limit * 6]
            for ratio, idx in top:
                consider(
                    self._owner[idx], ratio * 100.0, self._names[idx], self._kind[idx]
                )

        ranked = sorted(scored.values(), key=lambda c: c.score, reverse=True)
        return ranked[:limit]

    # ----------------------------------------------------------- construction
    @classmethod
    def load(
        cls,
        path: str | os.PathLike | None = None,
        *,
        allow_download: bool = True,
        update: bool = False,
        cache_dir: str | os.PathLike | None = None,
        log=lambda *a, **k: None,
    ) -> "HpoIndex":
        """Load HPO from *path*, the cache, or by downloading the release."""
        cache = Path(cache_dir) if cache_dir else default_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)

        src_path: Path
        if path is not None:
            src_path = Path(path)
            if not src_path.exists():
                raise FileNotFoundError(f"HPO file not found: {src_path}")
        else:
            src_path = cache / "hp.obo"
            if update or not src_path.exists():
                if not allow_download:
                    raise FileNotFoundError(
                        "No local HPO file and downloading is disabled. "
                        "Pass --hpo-file or allow downloading."
                    )
                log(f"Downloading HPO from {HPO_OBO_URL} (one-time) ...")
                _download(HPO_OBO_URL, src_path)
                log(f"Saved HPO to {src_path}")

        # Use a parsed-index pickle cache keyed on source size+mtime.
        stat = src_path.stat()
        key = f"{src_path.name}-{stat.st_size}-{int(stat.st_mtime)}.idx.pkl"
        idx_cache = cache / key
        if idx_cache.exists() and not update:
            try:
                with idx_cache.open("rb") as fh:
                    terms = pickle.load(fh)
                log(f"Loaded {len(terms)} HPO terms from cache.")
                return cls(terms, source=str(src_path))
            except Exception:
                pass  # fall through and re-parse

        log(f"Parsing HPO from {src_path} ...")
        terms = _parse_file(src_path)
        log(f"Indexed {len(terms)} HPO terms.")
        try:
            with idx_cache.open("wb") as fh:
                pickle.dump(terms, fh, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            pass
        return cls(terms, source=str(src_path))


# --------------------------------------------------------------------- parsing
def _download(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "hponorm/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def _parse_file(path: Path) -> dict[str, HpoTerm]:
    head = path.open("rb").read(256).lstrip()
    if head[:1] == b"{":
        return _parse_obographs(path)
    return _parse_obo(path)


def _parse_obo(path: Path) -> dict[str, HpoTerm]:
    terms: dict[str, HpoTerm] = {}
    cur: dict | None = None
    in_term = False

    def flush(block: dict | None) -> None:
        if not block:
            return
        tid = block.get("id")
        if not tid or not _CURIE_RE.match(tid):
            return
        terms[tid] = HpoTerm(
            id=tid,
            label=block.get("name", tid),
            synonyms=block.get("synonyms", []),
            definition=block.get("def"),
            obsolete=block.get("obsolete", False),
        )

    syn_re = re.compile(r'synonym:\s*"((?:[^"\\]|\\.)*)"')
    def_re = re.compile(r'def:\s*"((?:[^"\\]|\\.)*)"')
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("[Term]"):
                flush(cur)
                cur = {"synonyms": []}
                in_term = True
                continue
            if line.startswith("[") and line.endswith("]"):
                flush(cur)
                cur = None
                in_term = False
                continue
            if not in_term or cur is None:
                continue
            if line.startswith("id:"):
                cur["id"] = line[3:].strip()
            elif line.startswith("name:"):
                cur["name"] = line[5:].strip()
            elif line.startswith("def:"):
                m = def_re.match(line)
                if m:
                    cur["def"] = _unescape(m.group(1))
            elif line.startswith("synonym:"):
                m = syn_re.match(line)
                if m:
                    cur["synonyms"].append(_unescape(m.group(1)))
            elif line.startswith("is_obsolete:") and line.split(":", 1)[1].strip() == "true":
                cur["obsolete"] = True
    flush(cur)
    return terms


def _parse_obographs(path: Path) -> dict[str, HpoTerm]:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        data = json.load(fh)
    terms: dict[str, HpoTerm] = {}
    for graph in data.get("graphs", []):
        for node in graph.get("nodes", []):
            m = _IRI_RE.search(node.get("id", ""))
            if not m:
                continue
            tid = f"HP:{m.group(1)}"
            meta = node.get("meta", {}) or {}
            synonyms = [s.get("val", "") for s in meta.get("synonyms", []) if s.get("val")]
            definition = (meta.get("definition") or {}).get("val")
            terms[tid] = HpoTerm(
                id=tid,
                label=node.get("lbl") or tid,
                synonyms=synonyms,
                definition=definition,
                obsolete=bool(meta.get("deprecated", False)),
            )
    return terms


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\n", " ").replace("\\\\", "\\").strip()
