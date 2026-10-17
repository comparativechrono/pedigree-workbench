#!/usr/bin/env python3
"""Pack the Python packages for the web page: assets/py/pedigree-tools.zip.

The workbench's Python (Pyodide, in the browser) unpacks this archive when it
starts and puts it on sys.path, so the packages import as they would after
``pip install``. assets/py/pedigree-tools.json records what is in it and a
checksum, which the page adds to the archive's address so that a browser never
keeps an old copy.

Run after changing anything under python/:   python3 python/build_bundle.py
"""
import hashlib
import io
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "assets", "py")

# the packages, in the order the help lists them
PACKAGES = ["studio2ped", "ped2studio", "studio2ga4gh", "ga4gh2studio", "mpedtools", "hponorm", "mondonorm",
            "phenopacket_toolkit", "pedigree_ga4gh", "pedwb"]
# versions of the two packages that have none in their code
FIXED_VERSIONS = {"hponorm": "1.0.0", "mondonorm": "1.0.0"}


def version_of(pkg):
    if pkg in FIXED_VERSIONS:
        return FIXED_VERSIONS[pkg]
    init = os.path.join(HERE, pkg, "__init__.py")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)', open(init, encoding="utf-8").read(), re.M)
    return m.group(1) if m else ""


def files_of(pkg):
    base = os.path.join(HERE, pkg)
    for dp, dn, fn in os.walk(base):
        dn[:] = sorted(d for d in dn if d != "__pycache__" and not d.startswith("."))
        for f in sorted(fn):
            if f.endswith((".pyc", ".pyo")) or f.startswith("."):
                continue
            full = os.path.join(dp, f)
            yield full, os.path.relpath(full, HERE).replace(os.sep, "/")


def main():
    os.makedirs(OUT, exist_ok=True)
    buf = io.BytesIO()
    count = 0
    # fixed dates, so that the same sources always give the same archive (and the same checksum)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for pkg in PACKAGES:
            for full, rel in files_of(pkg):
                info = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read())
                count += 1
        # what the packages are, and their licence, for whoever downloads the archive (help: On your own computer)
        for name in ("README.md", "LICENSE"):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(HERE, name), "rb") as fh:
                z.writestr(info, fh.read())
            count += 1
    data = buf.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    with open(os.path.join(OUT, "pedigree-tools.zip"), "wb") as fh:
        fh.write(data)
    manifest = {
        "archive": "pedigree-tools.zip",
        "sha256": digest,
        "bytes": len(data),
        "packages": {p: version_of(p) for p in PACKAGES},
    }
    with open(os.path.join(OUT, "pedigree-tools.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print("assets/py/pedigree-tools.zip: {} files, {:.0f} KB, sha256 {}".format(count, len(data) / 1024, digest[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
