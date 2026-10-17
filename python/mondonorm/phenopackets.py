"""Read a phenopacket / family JSON, locate every disease ``term``, apply
chosen MONDO mappings in place, and write the normalised file back out.

The disease term finder is deliberately schema-tolerant: it recursively walks
the document and collects the ``term`` object of every entry under any
``diseases`` array. That covers the GA4GH ``Phenopacket.diseases`` and
``Family.proband`` / ``Family.relatives`` layouts (and any nesting of them)
without hard-coding paths.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TermRef:
    """A live, mutable reference to one disease ``term`` object in the document."""

    path: str
    term: dict  # the actual {"id": ..., "label": ...} dict inside the loaded JSON

    @property
    def label(self) -> str:
        return (self.term.get("label") or "").strip()

    @property
    def id(self) -> str:
        return (self.term.get("id") or "").strip()

    def apply(self, curie: str, label: str) -> None:
        self.term["id"] = curie
        self.term["label"] = label


def load(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def find_disease_terms(obj, path: str = "$") -> list[TermRef]:
    """Recursively collect every disease ``term`` dict in *obj*."""
    found: list[TermRef] = []

    def walk(node, p):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "diseases" and isinstance(value, list):
                    for i, entry in enumerate(value):
                        if isinstance(entry, dict) and isinstance(
                            entry.get("term"), dict
                        ):
                            found.append(
                                TermRef(f"{p}.diseases[{i}].term", entry["term"])
                            )
                        walk(entry, f"{p}.diseases[{i}]")
                else:
                    walk(value, f"{p}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{p}[{i}]")

    walk(obj, path)
    return found


def group_by_label(refs: list[TermRef]) -> "dict[tuple[str, str], list[TermRef]]":
    """Group term references by their current (label, id) so each distinct
    label is reviewed once and the decision applied to every occurrence."""
    groups: dict[tuple[str, str], list[TermRef]] = {}
    for ref in refs:
        groups.setdefault((ref.label, ref.id), []).append(ref)
    return groups


def save(data: dict, path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
