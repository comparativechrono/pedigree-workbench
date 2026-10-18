"""What the workbench's Tools tab asks Python.

The tab runs most of its tools as command lines (``run``), so that what it
does is exactly what the terminal and the packages do. A few things need
answers rather than files, and those are here: what a file is (``inspect``),
the conditions in a drawing's colour key (``conditions``), ontology terms for
names (``suggest`` and ``lookup``), and a check against the standard
(``validate``).

Every function takes and returns plain JSON-like values, because the page
calls them through the web worker that runs Python.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
from typing import Any, Dict, List, Optional

from . import cli

# --------------------------------------------------------------------- running programs


def run(argv: List[str], cwd: Optional[str] = None) -> Dict[str, Any]:
    """Run a program (``argv[0]``) as the terminal would and return
    ``{"code", "stdout", "stderr"}``."""
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(os.path.expanduser(cwd))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run([str(a) for a in argv])
    finally:
        os.chdir(old)
    return {"code": code, "stdout": out.getvalue(), "stderr": err.getvalue()}


def versions() -> Dict[str, str]:
    """The version of each package in the workbench."""
    import importlib
    out = {}
    for mod, name in (("studio2ped", "studio2ped"), ("ped2studio", "ped2studio"), ("studio2ga4gh", "studio2ga4gh"),
                      ("ga4gh2studio", "ga4gh2studio"), ("mpedtools", "mpedtools"), ("hponorm", "hponorm"),
                      ("mondonorm", "mondonorm"), ("phenopacket_toolkit", "phenopacket-toolkit"),
                      ("pedigree_ga4gh", "pedigree-ga4gh"), ("pedwb", "pedwb")):
        try:
            out[name] = getattr(importlib.import_module(mod), "__version__", "")
        except Exception:  # noqa: BLE001
            out[name] = ""
    return out


# --------------------------------------------------------------------- what a file is

_CURIE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]*:[^\s:]+$")


def _read_text(path: str, limit: int = 60 * 1024 * 1024) -> str:
    with open(path, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ValueError("the file is larger than 60 MB")
    return data.decode("utf-8", errors="replace")


def _is_studio(doc: Any) -> bool:
    return isinstance(doc, dict) and "persons" in doc and ("partnerships" in doc or "childLinks" in doc)


def _is_terms(doc: Any) -> bool:
    if not isinstance(doc, dict) or not doc:
        return False
    if isinstance(doc.get("resolved"), dict):
        doc = doc["resolved"]
    for v in doc.values():
        if isinstance(v, str) and _CURIE.match(v.strip()):
            continue
        if isinstance(v, dict) and isinstance(v.get("id"), str):
            continue
        return False
    return True


def _studio_summary(doc: Dict) -> Dict[str, Any]:
    from studio2ga4gh import converter, session
    s = session.parse(doc)
    people = [p for p in s.persons.values() if not p.is_marker]
    names = [v.strip() for v in s.legend.values() if (v or "").strip()]
    families = converter._components(s)
    return {
        "people": len(people),
        "families": len(families),
        "conditions": list(dict.fromkeys(names)),
        "proband": sum(1 for p in people if p.proband),
        "numbering": s.numbering_mode,
        "version": doc.get("version"),
    }


def _ga4gh_summary(doc: Dict, kind: str) -> Dict[str, Any]:
    from pedigree_ga4gh import legacy
    old = legacy.identify(doc)
    out: Dict[str, Any] = {}
    if kind == "pedigree":
        out["people"] = len(doc.get("individuals") or [])
        out["relationships"] = len(doc.get("relationships") or [])
        out["indexPatients"] = list(doc.get("indexPatients") or doc.get("index_patients") or [])
        out["id"] = doc.get("id", "")
    elif kind == "family":
        ped = (doc.get("pedigree") or {}).get("persons") or []
        out["people"] = len(ped) or (1 + len(doc.get("relatives") or []))
        out["withFindings"] = (1 if doc.get("proband") else 0) + len(doc.get("relatives") or [])
        out["proband"] = ((doc.get("proband") or {}).get("subject") or {}).get("id", "")
        out["id"] = doc.get("id", "")
    elif kind == "cohort":
        out["people"] = len(doc.get("members") or [])
        out["id"] = doc.get("id", "")
    elif kind == "phenopacket":
        out["people"] = 1
        out["id"] = doc.get("id", "")
    if old:
        out["legacy"] = {"form": old.form, "description": old.description, "unreadable": bool(old.unreadable),
                         "upgradable": bool(old.upgradable)}
    return out


def _ped_summary(text: str) -> Optional[Dict[str, Any]]:
    from mpedtools import core
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines or any(len(l.split()) < 6 for l in lines[:20]):
        return None
    ped = core.parse(text)
    if not ped.individuals:
        return None
    return {
        "kind": "mped" if ped.is_mped else "ped",
        "people": len(ped.individuals),
        "families": ped.families,
        "phenotypes": ped.phenotype_names,
        "affected": len(ped.get_affected()),
    }


def _obo_header(text: str) -> str:
    """The header of an OBO file: everything before its first stanza."""
    i = text.find("\n[")
    return text[: i if i >= 0 else 65536]


def _obo_summary(text: str) -> Optional[Dict[str, Any]]:
    if not text.startswith("format-version:"):
        return None
    head = _obo_header(text)
    m = re.search(r"^ontology:\s*(\S+)", head, re.M)
    v = re.search(r"^data-version:\s*(\S+)", head, re.M)
    date = re.search(r"(\d{4}-\d{2}-\d{2})", v.group(1)) if v else None
    name = (m.group(1) if m else "").lower()
    if name.endswith(".obo"):
        name = name[:-4]
    return {"ontology": name, "version": date.group(1) if date else (v.group(1) if v else ""),
            "terms": text.count("\n[Term]")}


KIND_NAMES = {
    "studio": "Pedigree Studio drawing",
    "pedigree": "GA4GH Pedigree",
    "family": "Phenopackets Family",
    "cohort": "Phenopackets Cohort",
    "phenopacket": "Phenopacket",
    "ped": "PED file",
    "mped": "MPED file (several phenotypes)",
    "terms": "terms file (names matched to ontology terms)",
    "obo": "ontology file (OBO)",
    "json": "JSON file",
    "text": "text file",
}


def inspect(path: str) -> Dict[str, Any]:
    """What a file is, with a short summary of what is in it."""
    from pedigree_ga4gh.kindred import detect
    path = os.path.expanduser(path)
    text = _read_text(path)
    out: Dict[str, Any] = {"path": path}
    doc = None
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            doc = json.loads(text)
        except ValueError as e:
            out.update(kind="text", error="not valid JSON: {}".format(e))
            out["name"] = KIND_NAMES["text"]
            return out
    if doc is not None:
        if _is_studio(doc):
            out["kind"] = "studio"
            try:
                out.update(_studio_summary(doc))
            except Exception as e:  # noqa: BLE001
                out["error"] = str(e)
        else:
            kind = detect(doc)
            if kind != "unknown":
                out["kind"] = kind
                out.update(_ga4gh_summary(doc, kind))
            elif _is_terms(doc):
                out["kind"] = "terms"
                out["terms"] = len(doc.get("resolved", doc))
            else:
                out["kind"] = "json"
    else:
        obo = _obo_summary(text)
        if obo:
            out["kind"] = "obo"
            out.update(obo)
        else:
            try:
                ped = _ped_summary(text)
            except Exception:  # noqa: BLE001
                ped = None
            if ped:
                out.update(ped)
            else:
                out["kind"] = "text"
    out["name"] = KIND_NAMES.get(out["kind"], out["kind"])
    return out


# --------------------------------------------------------------------- a drawing's colour key


def conditions(path: str, terms: Optional[str] = None) -> Dict[str, Any]:
    """The conditions named in a drawing's colour key, with how many people
    show each and the term each is matched to (from an id written in the key,
    as ``Breast cancer [MONDO:0007254]``, or from a terms file)."""
    from studio2ga4gh import converter, session
    path = os.path.expanduser(path)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not _is_studio(doc):
        raise ValueError("{} is not a Pedigree Studio drawing".format(os.path.basename(path)))
    mapping: Dict[str, Dict[str, str]] = {}
    if terms:
        tp = os.path.expanduser(terms)
        if os.path.exists(tp):
            with open(tp, encoding="utf-8") as fh:
                mapping = converter.load_terms(json.load(fh))
    s = session.parse(doc)
    counts: Dict[str, int] = {}
    for p in s.persons.values():
        if p.is_marker:
            continue
        for name in s.condition_names(p):
            counts[name] = counts.get(name, 0) + 1
    rows = []
    for name in dict.fromkeys(v.strip() for v in s.legend.values() if (v or "").strip()):
        base, curie = converter.split_key_label(name)
        hit = mapping.get(name.lower()) or mapping.get(base.lower())
        row = {"key": name, "name": base, "people": counts.get(name, 0), "id": "", "label": "", "from": ""}
        if hit:
            row.update(id=hit["id"], label=hit.get("label") or base, version=hit.get("version", ""), **{"from": "terms"})
        elif curie:
            row.update(id=curie, label=base, **{"from": "key"})
        rows.append(row)
    unnamed = sorted({c for p in s.persons.values() if not p.is_marker for c in s.unnamed_colours(p)})
    return {"conditions": rows, "unnamed": unnamed}


# --------------------------------------------------------------------- ontology terms

_INDEXES: Dict[tuple, Any] = {}


def _norm(ontology: str) -> str:
    o = (ontology or "").upper()
    if o in ("HP", "HPO"):
        return "HP"
    if o in ("MONDO",):
        return "MONDO"
    raise ValueError("ontology must be HP or MONDO, not {!r}".format(ontology))


def _backend(ontology: str, source: str, file: Optional[str]):
    """What hponorm or mondonorm searches – their OLS client, or their index
    of a local OBO file – with the release it holds and a name for it.

    (The packages' Suggester is not used here: the Tools tab asks the OLS
    client or the index itself, so that it can say why a search failed.)"""
    from phenopacket_toolkit.ontology.backends import obo_version, ols_version
    o = _norm(ontology)
    if o == "HP":
        from hponorm import hpo as local, ols
        Index, olsname = local.HpoIndex, "hp"
    else:
        from mondonorm import mondo as local, ols
        Index, olsname = local.MondoIndex, "mondo"
    if source == "ols":
        client = ols.OlsClient()
        key = ("ols", o)
        if not _INDEXES.get(key):
            _INDEXES[key] = ols_version(client, olsname)
        return client, _INDEXES[key], "EBI OLS"
    if source != "local":
        raise ValueError("source must be ols or local")
    if not file:
        raise ValueError("Choose the {} file to search.".format("HPO (hp.obo)" if o == "HP" else "Mondo (mondo.obo)"))
    path = os.path.expanduser(file)
    if not os.path.exists(path):
        raise FileNotFoundError("There's no file called {}.".format(file))
    held = ontology_file(path).get("ontology", "") if path.endswith(".obo") else ""
    if held and held != olsname:
        raise ValueError("{} holds {}, not {}.".format(
            os.path.basename(path), {"hp": "the HPO", "mondo": "Mondo"}.get(held, held), "the HPO" if o == "HP" else "Mondo"))
    st = os.stat(path)
    key = (o, path, st.st_size, int(st.st_mtime))
    if key not in _INDEXES:
        for k in [k for k in _INDEXES if k[0] == o]:
            del _INDEXES[k]  # one index of each ontology at a time: they are large
        idx = Index.load(path, allow_download=False)
        _INDEXES[key] = (idx, obo_version(path))
    idx, version = _INDEXES[key]
    return idx, version, os.path.basename(path)


def _cand(c) -> Dict[str, Any]:
    d = " ".join((getattr(c, "definition", None) or "").split())
    return {"id": c.id, "label": c.label, "score": round(float(getattr(c, "score", 100.0)), 1),
            "matchedOn": getattr(c, "matched_on", "exact id"), "definition": d if len(d) <= 200 else d[:199] + "…"}


def suggest(names: List[str], ontology: str = "MONDO", source: str = "ols", file: Optional[str] = None,
            limit: int = 8) -> Dict[str, Any]:
    """Terms that may match each name, best first, from the ontology on EBI's
    Ontology Lookup Service (``source="ols"``) or a local OBO file
    (``source="local"``, with ``file``)."""
    backend, version, where = _backend(ontology, source, file)
    results, errors = {}, {}
    for name in names:
        try:
            results[name] = [_cand(c) for c in backend.search(name, limit=int(limit))]
        except Exception as e:  # noqa: BLE001
            errors[name] = _explain(e, source)
            results[name] = []
    return {"ontology": _norm(ontology), "version": version, "source": where, "results": results, "errors": errors}


def lookup(curie: str, ontology: Optional[str] = None, source: str = "ols", file: Optional[str] = None) -> Dict[str, Any]:
    """Check an id typed by hand: its label, or ``found: False``."""
    from pedigree_ga4gh import ontology as onto
    raw = (curie or "").strip()
    m = re.match(r"^([A-Za-z]+)_(\d+)$", raw)  # HP_0000365, as in the terms' web addresses
    c = onto.tidy_curie(m.group(1) + ":" + m.group(2) if m else raw)
    if not onto.is_curie(c):
        return {"id": curie, "found": False, "error": "{!r} isn't an ontology id. Ontology ids look like MONDO:0007254 or HP:0000365.".format(curie)}
    o = ontology or onto.prefix_of(c)
    if _norm_or_none(o) is None:
        return {"id": c, "found": False, "error": "Only HPO (HP:) and Mondo (MONDO:) ids can be checked here."}
    try:
        backend, version, where = _backend(o, source, file)
        hit = backend.get(c)
    except Exception as e:  # noqa: BLE001
        return {"id": c, "found": False, "error": _explain(e, source)}
    if not hit:
        if source == "ols" and hasattr(backend, "available") and not backend.available():
            return {"id": c, "found": False, "error": _explain(RuntimeError("no answer"), source)}
        name = "the HPO" if _norm(o) == "HP" else "Mondo"
        if where == "EBI OLS":
            return {"id": c, "found": False, "error": "{} isn't in {} on EBI's Ontology Lookup Service.".format(c, name)}
        return {"id": c, "found": False, "error": "{} isn't in your copy of {} ({}).".format(c, name, where)}
    out = _cand(hit)
    out.update(found=True, version=version, source=where, obsolete=bool(getattr(hit, "obsolete", False)))
    return out


def _norm_or_none(o):
    try:
        return _norm(o)
    except ValueError:
        return None


def _explain(e: Exception, source: str) -> str:
    msg = str(e) or type(e).__name__
    if source == "ols" and ("URLError" in type(e).__name__ or "no answer" in msg or "CORS" in msg or "XMLHttpRequest" in msg):
        return ("EBI's Ontology Lookup Service did not answer ({}). Check your internet connection, or search a "
                "copy of the ontology on this computer instead.".format(msg))
    return msg


# --------------------------------------------------------------------- checking a file


def validate(path: str) -> Dict[str, Any]:
    """Check a GA4GH Pedigree, Phenopackets Family, Cohort or Phenopacket
    against the standard; the findings, most serious first."""
    import pedigree_ga4gh as pg
    from pedigree_ga4gh import legacy
    from pedigree_ga4gh.kindred import detect
    path = os.path.expanduser(path)
    with open(path, encoding="utf-8") as fh:
        doc = pg.loads(fh.read())
    kind = detect(doc)
    findings = pg.validate(doc)
    order = {pg.ERROR: 0, pg.WARNING: 1, pg.INFO: 2}
    findings = sorted(findings, key=lambda f: order.get(f.severity, 3))
    old = legacy.identify(doc)
    return {
        "kind": kind,
        "name": KIND_NAMES.get(kind, kind),
        "valid": pg.is_valid(findings),
        "errors": sum(1 for f in findings if f.severity == pg.ERROR),
        "warnings": sum(1 for f in findings if f.severity == pg.WARNING),
        "findings": [{"severity": f.severity, "code": f.code, "message": f.message, "path": f.path, "fix": f.fix}
                     for f in findings],
        "legacy": {"form": old.form, "description": old.description, "upgradable": bool(old.upgradable)} if old else None,
    }


def ontology_file(path: str) -> Dict[str, Any]:
    """The ontology (``hp``, ``mondo`` …) and release of an OBO file."""
    path = os.path.expanduser(path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        head = fh.read(65536)
    info = _obo_summary(head) or {}
    info.pop("terms", None)
    return info
