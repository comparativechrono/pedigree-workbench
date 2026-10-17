"""Unified suggestion layer.

A ``Suggester`` wraps one of two interchangeable backends:

* ``hpo``  - a local :class:`~hponorm.hpo.HpoIndex` (offline capable)
* ``ols``  - the EBI Ontology Lookup Service v4 (online)

and exposes a backend-agnostic API used by the CLI:

* ``suggest(label)``    -> ranked list of :class:`Candidate`
* ``resolve(curie)``    -> validate a specific HPO id and return its canonical term

Both backends score their suggestions in the same way, with :func:`best_match`:
100 when the name is a term's label, 98 when it is one of its synonyms (in
either case ignoring case and punctuation), and otherwise how closely the name
matches the label or the closest synonym, from 0 to 96. So a score means the
same whichever backend gave it, and a threshold such as 90 means what it says.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

EXACT_LABEL = 100.0
EXACT_SYNONYM = 98.0
SAME_WORDS = 97.0      # the same words in another order
FUZZY_MAX = 96.0       # the most a name that is not one of the term's names can score

# Words that say little about which term is meant, left out when words are compared.
STOPWORDS = frozenset("a an and as at by for from in into of on or the to".split())

_WORD = re.compile(r"[^\W_]+")
_POSSESSIVE = re.compile(r"['\u2019`]s\b")
_APOSTROPHE = re.compile(r"['\u2019`]")


def normalise_text(text: str) -> str:
    """A name reduced for comparison: lower case, accents, possessives and
    punctuation removed, single spaces ("Long-QT  interval" -> "long qt
    interval", "Huntington's disease" -> "huntington disease")."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = _APOSTROPHE.sub("", _POSSESSIVE.sub("", text))
    return " ".join(_WORD.findall(text))


def content_words(normalised: str) -> list[str]:
    """The words of a normalised name, without words such as "of" and "the"
    (all of them if that would leave none)."""
    words = normalised.split()
    return [w for w in words if w not in STOPWORDS] or words


PLURAL = 0.95       # "seizure" and "seizures"
EXTENDED = 0.85     # "abnormal" and "abnormality": a word of five letters or more, and up to four more


def _plural(a: str, b: str) -> bool:
    return b in (a + "s", a + "es") or a in (b + "s", b + "es")


def _extended(a: str, b: str) -> bool:
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 5 and 0 < len(long_) - len(short) <= 4 and long_.startswith(short)


def _word_similarity(word: str, others: list[str]) -> float:
    """How closely ``word`` matches the closest of ``others``: 1 for the same
    word, 0.95 for its plural, 0.85 for the same word with an ending
    ("abnormal", "abnormality"), the share of letters in common for a close
    spelling of a longer word (0.85 or more, as for "anaemia" and "anemia" or
    "diabetis" and "diabetes"), else 0. Words of four letters or fewer must be
    the same, or plurals: "ear" is not "fear"."""
    if word in others:
        return 1.0
    best = 0.0
    for other in others:
        if _plural(word, other):
            best = max(best, PLURAL)
            continue
        if _extended(word, other):
            best = max(best, EXTENDED)
        longest = max(len(word), len(other))
        if longest <= 4 or abs(len(word) - len(other)) > 0.4 * longest:
            continue
        r = SequenceMatcher(None, word, other, autojunk=False).ratio()
        if r > best:
            best = r
    return best if best >= 0.85 else 0.0


def _shared_words(a: list[str], b: list[str]) -> float:
    """The share of the words of two names that the other name also has
    (allowing close spellings), from 0 to 1."""
    if not a or not b:
        return 0.0
    total = sum(_word_similarity(w, b) for w in a) + sum(_word_similarity(w, a) for w in b)
    return total / (len(a) + len(b))


def similarity_normalised(a: str, b: str) -> float:
    """:func:`similarity` for two names already put through :func:`normalise_text`."""
    if not a or not b:
        return 0.0
    if a == b:
        return EXACT_LABEL
    wa, wb = a.split(), b.split()
    sa, sb = sorted(wa), sorted(wb)
    if sa == sb:
        return SAME_WORDS
    letters = max(SequenceMatcher(None, a, b, autojunk=False).ratio(),
                  SequenceMatcher(None, " ".join(sa), " ".join(sb), autojunk=False).ratio())
    words = _shared_words(content_words(a), content_words(b))
    return round(min(FUZZY_MAX, 50.0 * (letters + words)), 1)


def similarity(name: str, text: str) -> float:
    """How closely two names match, from 0 to 100.

    100 means the same name once case, accents, possessives and punctuation are
    ignored, and 97 the same words in another order. Otherwise the score is the mean of how
    alike the two are letter by letter and the share of their words they have in
    common (close spellings counting), so "learning disability" is closer to
    "Specific learning disability" (80) than to "Reading disability" (68), and a
    name inside a longer one is not taken for it: "hearing loss from birth"
    against "Hearing loss" scores 74. It never goes above 96.
    """
    return similarity_normalised(normalise_text(name), normalise_text(text))


def best_match(query: str, label: str, synonyms=()) -> tuple[float, str]:
    """``(score, matched_on)`` for a term with ``label`` and ``synonyms`` as a
    match for the name ``query``: 100 if the name is the label, 98 if it is a
    synonym, otherwise the :func:`similarity` of the closest of them.
    ``matched_on`` is ``"label"`` or ``"synonym: <the synonym>"``."""
    q = normalise_text(query)
    if not q:
        return 0.0, "label"
    names = [(normalise_text(label), "label")]
    names += [(normalise_text(s), "synonym: " + s.strip()) for s in synonyms if (s or "").strip()]
    if names[0][0] == q:
        return EXACT_LABEL, "label"
    for norm, tag in names[1:]:
        if norm == q:
            return EXACT_SYNONYM, tag
    best, tag = 0.0, "label"
    for norm, t in names:
        score = similarity_normalised(q, norm)
        if score > best:
            best, tag = score, t
    return best, tag


@dataclass
class Candidate:
    """A single suggested ontology term."""

    id: str  # e.g. "HP:0001657"
    label: str  # canonical HPO label
    score: float  # 0-100 match score (higher is better); see best_match
    matched_on: str  # "label", 'synonym: <synonym>' or "exact id"
    definition: str | None = None
    source: str = ""  # which backend produced it
    synonyms: list[str] = field(default_factory=list)  # the term's synonyms, where the backend gives them

    def short_def(self, n: int = 90) -> str:
        if not self.definition:
            return ""
        d = " ".join(self.definition.split())
        return d if len(d) <= n else d[: n - 1] + "…"


def _failure(backend, exc: Exception) -> str:
    explain = getattr(backend, "failure_message", None)
    if callable(explain):
        return explain(exc)
    name = getattr(backend, "name", "") or type(backend).__name__
    return "{} failed ({})".format(name, str(exc) or type(exc).__name__)


class Suggester:
    """Suggestions from a backend, with an optional fallback for when it gives none.

    A backend that fails (OLS not answering, say) does not raise: as in
    version 1.0, ``suggest`` returns the fallback's suggestions, or an empty
    list. Since version 1.1 the failure is recorded in :attr:`last_error`, so
    that "no suggestions" and "OLS did not answer" can be told apart.
    """

    def __init__(self, backend, *, fallback=None, name: str = ""):
        self.backend = backend
        self.fallback = fallback
        self.name = name or getattr(backend, "name", "backend")
        #: why the last ``suggest`` or ``resolve`` could not ask a backend, or None
        self.last_error: str | None = None

    def suggest(self, label: str, limit: int = 8) -> list[Candidate]:
        self.last_error = None
        errors = []
        try:
            results = self.backend.search(label, limit=limit)
        except Exception as exc:
            errors.append(_failure(self.backend, exc))
            results = []
        if not results and self.fallback is not None:
            try:
                results = self.fallback.search(label, limit=limit)
            except Exception as exc:
                errors.append(_failure(self.fallback, exc))
                results = []
        self.last_error = "; ".join(errors) or None
        return results

    def resolve(self, curie: str) -> Candidate | None:
        """Look up a specific HPO id to validate it and fetch its canonical label."""
        self.last_error = None
        errors = []
        for be in (self.backend, self.fallback):
            if be is None:
                continue
            try:
                term = be.get(curie)
            except Exception as exc:
                errors.append(_failure(be, exc))
                term = None
            if term is None and getattr(be, "last_error", None):
                errors.append(be.last_error)
            if term is not None:
                # an answer from the fallback, after the backend failed, still says so
                self.last_error = "; ".join(errors) or None
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
                    synonyms=list(getattr(term, "synonyms", []) or []),
                )
        self.last_error = "; ".join(errors) or None
        return None
