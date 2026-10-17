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

# -- words that look alike but are not the same ----------------------------------
#
# Spelt nearly alike is not the same as meaning the same. "Hypertension" and
# "hypotension" share all but two letters and mean the opposite; "type 1" and
# "type 2" differ by one character and are different diseases. Such words never
# count as close spellings of each other, and two names that contain them are
# scored by their words alone (see :func:`similarity_normalised`).

# Prefixes at the start of a word, any two of which make different words:
# "hypertension" and "hypotension", "microcephaly" and "acrocephaly",
# "brachydactyly" and "syndactyly", "esotropia" and "exotropia".
WORD_PREFIXES = frozenset("""
    hyper hypo micro macro mega brady tachy poly oligo olig eso exo endo ecto
    intra extra inter pre post ante sub supra infra dextro levo ab ad acro brachy
    dolicho plagio scapho trigono oxy turri clino campto syn arachno retro pro
    hemi pseudo para peri epi neo pan iso hetero homo mono uni bi tri
""".split())

# Prefixes that make different words inside a word too ("pseudohypoparathyroidism",
# "pseudohyperparathyroidism").
OPPOSITE_PREFIXES = (
    ("hyper", "hypo"),
    ("micro", "macro", "mega"),
    ("brady", "tachy"),
    ("poly", "oligo", "olig"),
)

# Prefixes that make a different word when they are added, at the start or
# after another prefix: "hypoparathyroidism" is not "hypothyroidism", nor
# "pseudohypoparathyroidism" "hypoparathyroidism".
ADDED_PREFIXES = ("pseudo", "para", "peri", "epi", "neo", "pan", "hemi", "semi", "retro", "trans", "meta")

# Prefixes that make a word into its negative ("symptomatic", "asymptomatic";
# "syndromic", "nonsyndromic"; "normal", "abnormal"). "a" counts before a
# consonant and "an" before a vowel ("atypical", "anencephaly"), so that the "a"
# of a British spelling ("aetiology", "etiology") is not taken for one.
NEGATING_PREFIXES = frozenset("non un in im ir il dis anti ab dys".split())
_VOWELS = frozenset("aeiou")

# Words that are names in themselves: numbers ("type 2"), Roman numerals ("type
# II", the same as "type 2"), single letters ("hepatitis B") and codes with a
# digit ("B12", "1A"). Two names that both have such words must have the same
# ones: otherwise they are different types of a thing, however alike the rest.
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9",
          "xi": "11", "xii": "12", "xiii": "13", "xiv": "14", "xv": "15", "xvi": "16", "xvii": "17",
          "xviii": "18", "xix": "19"}
# sex chromosomes in a karyotype ("46,XX", "47,XXY", "45,XO")
_SEX_CHROMOSOMES = re.compile(r"^(?:[xy]{2,4}|xo)$")
# "a" is an article as often as a name; it counts as a name at the end, or after one of these words
_A_AFTER = frozenset("type group class subtype form factor vitamin hepatitis stage grade protein".split())


def identifier(word: str, previous: str = "", last: bool = False) -> str | None:
    """The value of a word that names a type or a number ("ii" and "2" are both
    "2", "b12" is "b12"), or ``None`` for an ordinary word."""
    if word in _ROMAN:
        return _ROMAN[word]
    if word.isdigit():
        return str(int(word))
    if any(ch.isdigit() for ch in word) or _SEX_CHROMOSOMES.match(word):
        return word
    if len(word) == 1 and word.isalpha():
        if word == "a" and not (last or previous in _A_AFTER):
            return None
        return word
    return None


def identifiers(words: list[str]) -> list[str]:
    """The values of the words of a name that name a type or a number, in order."""
    out = []
    for i, w in enumerate(words):
        v = identifier(w, words[i - 1] if i else "", i == len(words) - 1)
        if v is not None:
            out.append(v)
    return out


_AE_OE = re.compile(r"ae|oe")


def _us(word: str) -> str:
    """British spellings made American, for comparing prefixes ("hypoaesthesia" -> "hypoesthesia")."""
    return _AE_OE.sub("e", word)


def _shared_letters(a: str, b: str) -> int:
    """How many letters two words share at their start and at their end."""
    start = 0
    for x, y in zip(a, b):
        if x != y:
            break
        start += 1
    end = 0
    for x, y in zip(reversed(a[start:]), reversed(b[start:])):
        if x != y:
            break
        end += 1
    return start + end


def _swapped_at_start(word: str, other: str) -> bool:
    for p in WORD_PREFIXES:
        if word.startswith(p):
            base = word[len(p):]
            if len(base) >= 3 and other.endswith(base):
                q = other[: len(other) - len(base)]
                if q != p and q in WORD_PREFIXES:
                    return True
    return False


def _swapped(word: str, other: str, group) -> bool:
    for x in group:
        start = word.find(x)
        while start != -1:
            head, tail = word[:start], word[start + len(x):]
            if any(y != x and other == head + y + tail for y in group):
                return True
            start = word.find(x, start + 1)
    return False


def _added(short: str, long_: str) -> bool:
    for p in ADDED_PREFIXES:
        at = long_.find(p)
        while at != -1:
            head = long_[:at]
            if (not head or head in WORD_PREFIXES) and long_[:at] + long_[at + len(p):] == short:
                return True
            at = long_.find(p, at + 1)
    return False


# Endings taken off before prefixes are compared, so that "hypertension" and
# "hypotensive" are seen to differ by their prefixes too.
_ENDINGS = ("ations", "ation", "itions", "ition", "ions", "ion", "ives", "ive", "isms", "ism", "ists", "ist",
            "ities", "ity", "ics", "ic", "ias", "ia", "al", "ous", "es", "s", "y", "e")


def _stem(word: str) -> str:
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 4:
            return word[: -len(end)]
    return word


def _negated(short: str, long_: str) -> bool:
    if len(short) < 4 or not long_.endswith(short):
        return False
    prefix = long_[: len(long_) - len(short)]
    if prefix in NEGATING_PREFIXES:
        return True
    return (prefix == "a" and short[0] not in _VOWELS) or (prefix == "an" and short[0] in _VOWELS)


def different_words(word: str, other: str) -> bool:
    """True for two words that look alike but are not the same:

    * they differ by their prefixes ("hypertension", "hypotension";
      "microcephaly", "acrocephaly"; "pseudohypoparathyroidism",
      "pseudohyperparathyroidism"),
    * one is the other with a prefix added ("hypothyroidism",
      "hypoparathyroidism") or a negating one ("symptomatic", "asymptomatic";
      "normal", "abnormal"),
    * or they are different numbers or letters ("1", "2"; "ii", "iii"; "a", "b").

    British and American spellings of a word are the same word: "anaemia" and
    "anemia" are not different, nor "hypoaesthesia" and "hypoesthesia"."""
    if word == other:
        return False
    a, b = identifier(word, last=True), identifier(other, last=True)
    if a is not None or b is not None:
        return a is not None and b is not None and a != b
    us_word, us_other = _us(word), _us(other)
    for x, y in ((word, other), (us_word, us_other), (_stem(us_word), _stem(us_other))):
        if x == y:
            return False
        short, long_ = (x, y) if len(x) <= len(y) else (y, x)
        # each of these changes at most a prefix's worth of letters, leaving the rest as it was
        if _shared_letters(x, y) < max(3, len(short) - 7):
            continue
        if (_swapped_at_start(x, y) or any(_swapped(x, y, group) for group in OPPOSITE_PREFIXES)
                or _added(short, long_) or _negated(short, long_)):
            return True
    return False


def contrasting(words_a: list[str], words_b: list[str]) -> bool:
    """True if two names are not the same thing however alike they look: they
    name different types or numbers ("type 1", "type 2"; "hepatitis A",
    "hepatitis B"), or one has a word whose opposite, negative or variant the
    other has ("hypothyroidism", "hyperthyroidism"; "syndromic",
    "nonsyndromic"; see :func:`different_words`)."""
    ids_a, ids_b = identifiers(words_a), identifiers(words_b)
    if ids_a and ids_b and sorted(ids_a) != sorted(ids_b):
        return True
    for x in words_a:
        for y in words_b:
            if x != y and len(x) > 3 and len(y) > 3 and different_words(x, y):
                return True
    return False


def _plural(a: str, b: str) -> bool:
    return b in (a + "s", a + "es") or a in (b + "s", b + "es")


def _extended(a: str, b: str) -> bool:
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 5 and 0 < len(long_) - len(short) <= 4 and long_.startswith(short)


def _word_similarity(word: str, others: list[str]) -> float:
    """How closely ``word`` matches the closest of ``others``: 1 for the same
    word (or the same number, "ii" and "2"), 0.95 for its plural, 0.85 for the
    same word with an ending ("abnormal", "abnormality"), the share of letters
    in common for a close spelling of a longer word (0.85 or more, as for
    "anaemia" and "anemia" or "diabetis" and "diabetes"), else 0. Words of four
    letters or fewer must be the same, or plurals: "ear" is not "fear". Words
    that differ by an opposite or negating prefix, or that are different
    numbers or letters, are never close (:func:`different_words`)."""
    if word in others:
        return 1.0
    value = identifier(word, last=True)
    best = 0.0
    for other in others:
        if value is not None and identifier(other, last=True) == value:
            return 1.0
        if _plural(word, other):
            alike = PLURAL
        else:
            alike = EXTENDED if _extended(word, other) else 0.0
            longest = max(len(word), len(other))
            if longest > 4 and abs(len(word) - len(other)) <= 0.4 * longest:
                alike = max(alike, SequenceMatcher(None, word, other, autojunk=False).ratio())
        # checked last, as it is needed only for the few words alike enough to count
        if alike >= 0.85 and alike > best and not different_words(word, other):
            best = alike
    return best


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
    words = _shared_words(content_words(a), content_words(b))
    if contrasting(wa, wb):
        # alike letter by letter, but not the same thing: only the words they share count
        return round(min(FUZZY_MAX, 50.0 * words), 1)
    letters = max(SequenceMatcher(None, a, b, autojunk=False).ratio(),
                  SequenceMatcher(None, " ".join(sa), " ".join(sb), autojunk=False).ratio())
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

    Names that are alike letter by letter but not the same thing are scored by
    their shared words alone: names of different types or numbers ("Type 1
    diabetes mellitus", "Type 2 diabetes mellitus": 33) and names with words of
    opposite or negated meaning ("Maternal hypothyroidism", "Maternal
    hyperthyroidism": 25; "Hypertension", "hypotension": 0). See
    :func:`contrasting`.
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
