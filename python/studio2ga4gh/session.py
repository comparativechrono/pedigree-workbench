"""Reading a Pedigree Studio session (the .json file Pedigree Studio saves).

A session lists ``persons`` (each with a shape, fill, marks and position),
``partnerships`` between two people, ``childLinks`` from a partnership to a
child, ``twinLinks`` between two children and ``legendLabels``, which name the
colours and shading used for conditions. This module turns that into plain
Python objects and works out the people's pedigree numbers (I-1, II-3 ...)
exactly as Pedigree Studio shows them.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Symbols that are not people: a bar under a couple for "no children" and a
# double bar for infertility. Pedigree Studio stores them as children of the couple.
MARKERS = {"no-offspring": "no children", "infertile": "infertility"}

SHAPE_SEX = {
    "male": "MALE", "female": "FEMALE", "unknown": "UNKNOWN_SEX",
    "adopted-male": "MALE", "adopted-female": "FEMALE", "adopted-unknown": "UNKNOWN_SEX",
}

_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
_WHITE = {"#fff", "#ffffff", "white", "#fffffe"}


@dataclass
class StudioPerson:
    id: str
    shape: str
    x: float
    y: float
    text: str = ""
    deceased: bool = False
    proband: bool = False
    consultand: bool = False         # an arrow without a P: the person seeking advice
    fill_mode: str = "none"
    fill_color: Optional[str] = None
    halves: List[Optional[str]] = field(default_factory=lambda: [None, None])
    quarters: List[Optional[str]] = field(default_factory=lambda: [None] * 4)
    thirds: List[Optional[str]] = field(default_factory=lambda: [None] * 3)   # a symbol in thirds: three conditions
    shading_pattern: str = "stripes"
    shading_coverage: str = "full"
    centre: str = ""                 # "", "dot", "line", "P", "D", "G" (or "S", in older files) or a number
    loss_sex: str = "unknown"        # for pregnancy losses
    custom_label: str = ""

    @property
    def is_marker(self) -> bool:
        return self.shape in MARKERS

    @property
    def is_loss(self) -> bool:
        return self.shape == "miscarriage"

    @property
    def adopted_symbol(self) -> bool:
        return self.shape.startswith("adopted-")

    @property
    def sex(self) -> str:
        if self.is_loss:
            return {"male": "MALE", "female": "FEMALE"}.get(self.loss_sex, "UNKNOWN_SEX")
        return SHAPE_SEX.get(self.shape, "UNKNOWN_SEX")

    def colours(self) -> List[str]:
        """The condition colours on this symbol (not counting shading)."""
        if self.fill_mode == "solid":
            cs = [self.fill_color]
        elif self.fill_mode == "half":
            cs = list(self.halves or [])
        elif self.fill_mode == "quartered":
            cs = list(self.quarters or [])
        elif self.fill_mode == "thirds":
            cs = list(self.thirds or [])
        else:
            cs = []
        out = []
        for c in cs:
            if c and c.lower() not in _WHITE and c not in out:
                out.append(c)
        return out

    @property
    def shaded(self) -> bool:
        return self.fill_mode == "shading"

    @property
    def filled(self) -> bool:
        return bool(self.colours()) or self.shaded


@dataclass
class Partnership:
    id: str
    a: str
    b: str
    type: str = "normal"

    @property
    def consanguineous(self) -> bool:
        return self.type in ("consanguineous", "consanguineous-separated")

    @property
    def separated(self) -> bool:
        return self.type in ("separated", "consanguineous-separated", "shared-partner-separated")


@dataclass
class ChildLink:
    id: str
    partnership: str
    child: str
    dashed: bool = False             # a dashed line: the child was adopted into this couple


@dataclass
class TwinLink:
    id: str
    a: str
    b: str
    identical: bool
    zygosity: Optional[str] = None   # "identical", "nonidentical" or "unknown" (the Studio's "Not known (?)")

    def __post_init__(self):
        if self.zygosity is None:
            self.zygosity = "identical" if self.identical else "nonidentical"


@dataclass
class Session:
    persons: Dict[str, StudioPerson]
    partnerships: Dict[str, Partnership]
    child_links: List[ChildLink]
    twin_links: List[TwinLink]
    legend: Dict[str, str]           # colour or "shading:<pattern>:<coverage>" -> condition name
    numbering_mode: str = "numbers"

    def condition_names(self, p: StudioPerson) -> List[str]:
        """The legend names of the conditions shown on a symbol, in legend order."""
        names = []
        cols = {c.lower() for c in p.colours()}
        for key, label in self.legend.items():
            label = (label or "").strip()
            if not label:
                continue
            if key.startswith("shading:"):
                parts = key.split(":")
                if p.shaded and (key == "shading:{}:{}".format(p.shading_pattern, p.shading_coverage)
                                 or (len(parts) > 1 and parts[1] == p.shading_pattern)):
                    names.append(label)
            elif key.lower() in cols:
                names.append(label)
        return list(dict.fromkeys(names))

    def unnamed_colours(self, p: StudioPerson) -> List[str]:
        named = {k.lower() for k, v in self.legend.items() if (v or "").strip() and not k.startswith("shading:")}
        out = [c for c in p.colours() if c.lower() not in named]
        if p.shaded and not self.condition_names(p) and not any(
                k.startswith("shading:") and (v or "").strip() for k, v in self.legend.items()):
            out.append("shading ({})".format(p.shading_pattern))
        return out

    def rows(self) -> List[List[StudioPerson]]:
        """The people in each row (generation) of the drawing, from left to right, as Pedigree Studio numbers
        them: a new row starts 80 px below the first person of the one above. The "no children" and
        "infertility" symbols are not people, so they are left out and do not count in their row."""
        items = sorted((p for p in self.persons.values() if not p.is_marker), key=lambda p: p.y)
        gens: List[List[StudioPerson]] = []
        for p in items:
            if gens and p.y - gens[-1][0].y < 80:
                gens[-1].append(p)
            else:
                gens.append([p])
        return [sorted(gen, key=lambda q: q.x) for gen in gens]

    def numbers(self) -> Dict[str, str]:
        """Pedigree numbers as Pedigree Studio draws them: generation in Roman
        numerals, then position from the left (II-3). As in the Studio, only
        people are numbered (see :meth:`rows`)."""
        out = {}
        for gi, gen in enumerate(self.rows()):
            g = _ROMAN[gi] if gi < len(_ROMAN) else str(gi + 1)
            for pi, p in enumerate(gen):
                out[p.id] = "{}-{}".format(g, pi + 1)
        return out

    def drawing_labels(self) -> Dict[str, str]:
        """The label each person shows in the drawing, whatever numbering it uses (the "no children" and
        "infertility" symbols have none)."""
        nums = self.numbers()
        if self.numbering_mode in ("numbers", "off"):
            return nums
        if self.numbering_mode == "freetext":
            labels = {pid: (self.persons[pid].custom_label or "").strip() for pid in nums}
            return {pid: (lab if lab and lab != "Lbl" else nums[pid]) for pid, lab in labels.items()}
        # letters / lettersonly
        gens = self.rows()

        def letter(n):
            s = ""
            while n >= 0:
                s = chr(65 + n % 26) + s
                n = n // 26 - 1
            return s

        out, k = {}, 0
        for gi, gen in enumerate(gens):
            g = _ROMAN[gi] if gi < len(_ROMAN) else str(gi + 1)
            for pi, p in enumerate(gen):
                out[p.id] = letter(k) if self.numbering_mode == "lettersonly" else "{}-{}".format(g, letter(pi))
                k += 1
        return out

    def couple_children(self) -> Dict[str, List[ChildLink]]:
        out: Dict[str, List[ChildLink]] = defaultdict(list)
        for cl in self.child_links:
            out[cl.partnership].append(cl)
        return out


def _zygosity(t: dict) -> str:
    """A twin line's zygosity: identical (the default, as in the Studio), unknown ("?"), or non-identical."""
    kind = t.get("type") or "identical"
    return kind if kind in ("identical", "unknown") else "nonidentical"


def parse(data: dict) -> Session:
    """Read a Pedigree Studio session (any version from 3 to 5)."""
    if not isinstance(data, dict) or "persons" not in data:
        raise ValueError("this is not a Pedigree Studio file: it has no 'persons'")
    persons: Dict[str, StudioPerson] = {}
    for pd in data.get("persons") or []:
        pid = str(pd["id"])
        fill_mode = pd.get("fillMode") or "none"
        fill_color = pd.get("fillColor")
        if pd.get("affected") and fill_mode == "none":   # files from before fill modes existed
            fill_mode, fill_color = "solid", "#1a2332"
        persons[pid] = StudioPerson(
            id=pid, shape=pd.get("shape") or "unknown",
            x=float(pd.get("x") or 0), y=float(pd.get("y") or 0),
            text=pd.get("text") or "", deceased=bool(pd.get("deceased")), proband=bool(pd.get("proband")),
            consultand=bool(pd.get("consultand")),
            fill_mode=fill_mode, fill_color=fill_color,
            halves=list(pd.get("halves") or [None, None]), quarters=list(pd.get("quarters") or [None] * 4),
            thirds=list(pd.get("thirds") or [None] * 3),
            shading_pattern=pd.get("shadingPattern") or "stripes",
            shading_coverage=pd.get("shadingCoverage") or "full",
            centre=str(pd.get("centerText") or ""), loss_sex=pd.get("miscarriageSex") or "unknown",
            custom_label=pd.get("customLabel") or "")
    partnerships = {}
    for p in data.get("partnerships") or []:
        if p.get("fromId") in persons and p.get("toId") in persons:
            partnerships[str(p["id"])] = Partnership(str(p["id"]), p["fromId"], p["toId"], p.get("type") or "normal")
    child_links = [ChildLink(str(c["id"]), str(c["partnershipId"]), str(c["childId"]), bool(c.get("dashed")))
                   for c in data.get("childLinks") or []
                   if str(c.get("partnershipId")) in partnerships and c.get("childId") in persons]
    twin_links = [TwinLink(str(t["id"]), t["child1Id"], t["child2Id"], _zygosity(t) == "identical", _zygosity(t))
                  for t in data.get("twinLinks") or []
                  if t.get("child1Id") in persons and t.get("child2Id") in persons]
    return Session(persons, partnerships, child_links, twin_links,
                   dict(data.get("legendLabels") or {}), data.get("numberingMode") or "numbers")
