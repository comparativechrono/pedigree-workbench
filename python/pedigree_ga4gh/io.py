"""Reading and writing GA4GH JSON files."""
from __future__ import annotations

import json
from typing import Dict, Union


def loads(text: Union[str, bytes]) -> Dict:
    """Parse JSON (or YAML, when PyYAML is installed and the text is not JSON)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    text = text.lstrip("﻿")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        try:
            import yaml  # type: ignore
        except ImportError:
            raise ValueError("not valid JSON: {}".format(exc)) from None
        try:
            data = yaml.safe_load(text)
        except Exception:
            raise ValueError("not valid JSON: {}".format(exc)) from None
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object at the top level")
    return data


def load(path: str) -> Dict:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return loads(fh.read())


def dumps(doc: Dict) -> str:
    """Canonical JSON text: two-space indent, UTF-8 characters kept, final newline."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def dump(doc: Dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(doc))
