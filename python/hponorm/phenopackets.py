"""Read a phenopacket / family JSON, locate every phenotypic-feature ``type``,
apply chosen HPO mappings in place, and write the normalised file back out.

The finder is deliberately schema-tolerant: it recursively walks the document
and collects the ``type`` object of every entry under any ``phenotypicFeatures``
array. That covers the GA4GH ``Phenopacket.phenotypicFeatures`` and
``Family.proband`` / ``Family.relatives`` layouts (and any nesting of them)
without hard-coding paths. An entry's ``excluded`` flag is left untouched -- it
qualifies the feature, not the term, so the ``type`` is mapped either way.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FeatureRef:
    """A live, mutable reference to one phenotypic-feature ``type`` object."""

    path: str
    type: dict  # the actual {"id": ..., "label": ...} dict inside the loaded JSON
    excluded: bool = False  # GA4GH PhenotypicFeature.excluded (informational)

    @property
    def label(self) -> str:
        return (self.type.get("label") or "").strip()

    @property
    def id(self) -> str:
        return (self.type.get("id") or "").strip()

    def apply(self, curie: str, label: str) -> None:
        self.type["id"] = curie
        self.type["label"] = label


def load(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def find_phenotypic_features(obj, path: str = "$") -> list[FeatureRef]:
    """Recursively collect every phenotypic-feature ``type`` dict in *obj*."""
    found: list[FeatureRef] = []

    def walk(node, p):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "phenotypicFeatures" and isinstance(value, list):
                    for i, entry in enumerate(value):
                        if isinstance(entry, dict) and isinstance(
                            entry.get("type"), dict
                        ):
                            found.append(
                                FeatureRef(
                                    f"{p}.phenotypicFeatures[{i}].type",
                                    entry["type"],
                                    bool(entry.get("excluded", False)),
                                )
                            )
                        walk(entry, f"{p}.phenotypicFeatures[{i}]")
                else:
                    walk(value, f"{p}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{p}[{i}]")

    walk(obj, path)
    return found


def group_by_label(refs: list[FeatureRef]) -> "dict[tuple[str, str], list[FeatureRef]]":
    """Group feature references by their current (label, id) so each distinct
    label is reviewed once and the decision applied to every occurrence."""
    groups: dict[tuple[str, str], list[FeatureRef]] = {}
    for ref in refs:
        groups.setdefault((ref.label, ref.id), []).append(ref)
    return groups


def save(data: dict, path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
