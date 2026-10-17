"""Local HPO (Human Phenotype Ontology) index.

Loads HPO from a local ``.obo`` or obographs ``.json`` file (downloading and
caching the official release on first use if permitted), builds an in-memory
search index over term labels + synonyms, and answers two questions:

* ``search(query)``  -> ranked candidate terms for a free-text phenotype label
* ``get(curie)``     -> the canonical term for a specific ``HP:xxxxxxx`` id

A search first finds the names (labels and synonyms) that share a word with
the query, or a word spelt nearly the same, giving rare words more weight
than common ones; it then scores that shortlist with
:func:`~hponorm.suggest.similarity`, the scoring the OLS backend uses too.
``rapidfuzz``, when installed, adds names that are alike letter by letter but
share no word with the query (a name written as one word, say); a term found
either way has the same score.
"""
from __future__ import annotations

import difflib
import heapq
import json
import math
import os
import pickle
import re
import urllib.request
from array import array
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .suggest import (EXACT_LABEL, EXACT_SYNONYM, EXTENDED, PLURAL, Candidate, content_words, normalise_text,
                      similarity_normalised)

# Official, version-pinned-to-"latest" PURLs maintained by the Monarch Initiative.
HPO_OBO_URL = "https://purl.obolibrary.org/obo/hp.obo"
HPO_JSON_URL = "https://purl.obolibrary.org/obo/hp.json"

#: The small sample of the HPO that comes with the package, for trying the tool offline.
SAMPLE_OBO = Path(__file__).resolve().parent / "data" / "hpo-sample.obo"

_CURIE_RE = re.compile(r"^HP:\d{7}$")
_IRI_RE = re.compile(r"HP_(\d{7})")

try:  # Optional: makes the search faster, and finds names written quite differently.
    from rapidfuzz import fuzz, process

    _HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - exercised only when dep is absent
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
        self._norm: list[str] = []  # _names[i] put through normalise_text
        self._owner: list[str] = []  # term id for _names[i]
        self._kind: list[str] = []  # "label" or "synonym"
        self._exact: dict[str, list[int]] = {}  # normalised text -> indices into _names
        # built on the first search: word -> indices of the names that have it, and the words by length
        self._postings: dict[str, array] | None = None
        self._by_length: dict[int, list[str]] = {}
        self._words_in: list[int] = []
        for t in terms.values():
            if t.obsolete:
                continue
            self._add_name(t.id, t.label, "label")
            for syn in t.synonyms:
                self._add_name(t.id, syn, "synonym")

    def _add_name(self, term_id: str, text: str, kind: str) -> None:
        text = (text or "").strip()
        norm = normalise_text(text)
        if not norm:
            return
        self._exact.setdefault(norm, []).append(len(self._names))
        self._names.append(text)
        self._norm.append(norm)
        self._owner.append(term_id)
        self._kind.append(kind)

    # ------------------------------------------------------------------ lookup
    def get(self, curie: str) -> HpoTerm | None:
        c = normalise_curie(curie)
        return self.terms.get(c) if c else None

    def __len__(self) -> int:
        return len(self.terms)

    # ------------------------------------------------------------------ search
    def search(self, query: str, limit: int = 8) -> list[Candidate]:
        q = normalise_text(query)
        if not q:
            return []
        scored: dict[str, Candidate] = {}

        def consider(i: int, score: float) -> None:
            t = self.terms.get(self._owner[i])
            if t is None or t.obsolete:
                return
            kind = self._kind[i]
            prev = scored.get(t.id)
            if prev is not None and (score < prev.score or (score == prev.score and (
                    prev.matched_on == "label" or kind != "label"))):
                return
            scored[t.id] = Candidate(
                id=t.id,
                label=t.label,
                score=round(float(score), 1),
                matched_on="label" if kind == "label" else "synonym: " + self._names[i],
                definition=t.definition,
                source="hpo-local",
                synonyms=list(t.synonyms),
            )

        # 1) The query is a label or a synonym (whatever the case and punctuation).
        for i in self._exact.get(q, []):
            consider(i, EXACT_LABEL if self._kind[i] == "label" else EXACT_SYNONYM)

        # 2) The closest of the names on the shortlist.
        for i in self._shortlist(q, max(limit * 25, 150)):
            if self._norm[i] != q:  # exact names were scored above
                consider(i, similarity_normalised(q, self._norm[i]))

        ranked = sorted(scored.values(), key=lambda c: (-c.score, c.matched_on != "label", len(c.label), c.id))
        return ranked[:limit]

    def _shortlist(self, q: str, n: int) -> set[int]:
        """Indices of up to ``n`` names worth scoring for the normalised query ``q``
        (with rapidfuzz, up to ``n`` more)."""
        picks = set(self._word_shortlist(q, n))
        if _HAVE_RAPIDFUZZ:
            # names alike letter by letter, which may share no word with the query ("longqt")
            for _text, _score, i in process.extract(q, self._norm, scorer=fuzz.ratio, limit=n, score_cutoff=70):
                picks.add(i)
        return picks

    def _build_word_index(self) -> None:
        postings: dict[str, list[int]] = {}
        words_in = []
        for i, norm in enumerate(self._norm):
            words = content_words(norm)
            words_in.append(len(words))
            for w in set(words):
                postings.setdefault(w, []).append(i)
        by_length: dict[int, list[str]] = {}
        for w in postings:
            by_length.setdefault(len(w), []).append(w)
        self._postings = {w: array("I", ids) for w, ids in postings.items()}
        self._by_length = by_length
        self._words_in = words_in

    def _similar_words(self, word: str) -> list[tuple[str, float]]:
        """The index's words that are ``word`` or spelt nearly like it (plurals, typos,
        UK and US spellings), with how alike they are (1 for the word itself)."""
        found = [(word, 1.0)] if word in self._postings else []
        for plural in (word + "s", word + "es", word[:-1] if word.endswith("s") else "",
                       word[:-2] if word.endswith("es") else ""):
            if plural and plural != word and plural in self._postings:
                found.append((plural, PLURAL))
        if len(word) < 5:
            return found
        have = {w for w, _ in found}
        for n in range(len(word) + 1, len(word) + 5):   # the word with an ending: "abnormal", "abnormality"
            for w in self._by_length.get(n, ()):
                if w not in have and w.startswith(word):
                    found.append((w, EXTENDED))
                    have.add(w)
        slack = max(2, len(word) // 4)
        nearby = [w for n in range(len(word) - slack, len(word) + slack + 1) for w in self._by_length.get(n, ())]
        for w in difflib.get_close_matches(word, nearby, n=6, cutoff=0.85):
            if w not in have:
                found.append((w, difflib.SequenceMatcher(None, word, w, autojunk=False).ratio()))
        return found

    def _word_shortlist(self, q: str, n: int) -> list[int]:
        if self._postings is None:
            self._build_word_index()
        total = len(self._norm) or 1
        weight: dict[int, float] = {}
        for word in dict.fromkeys(content_words(q)):
            best: dict[int, float] = {}
            for w, alike in self._similar_words(word):
                ids = self._postings[w]
                score = alike * math.log(1.0 + total / len(ids))  # rare words count for more
                for i in ids:
                    if score > best.get(i, 0.0):
                        best[i] = score
            for i, score in best.items():
                weight[i] = weight.get(i, 0.0) + score
        if not weight:
            # no word of the query is in the index: compare the whole names instead (slower)
            near = difflib.get_close_matches(q, list(self._exact), n=n, cutoff=0.6)
            return [i for text in near for i in self._exact[text]]
        words_in = self._words_in
        return [i for i, _ in heapq.nlargest(n, weight.items(), key=lambda kv: (kv[1], -words_in[kv[0]]))]

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
    req = urllib.request.Request(url, headers={"User-Agent": "hponorm/" + __version__})
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
