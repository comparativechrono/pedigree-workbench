#!/usr/bin/env python3
"""Pack the Python packages for the web page: assets/py/pedigree-tools.zip and assets/py/pedigree-analysis.zip.

The workbench's Python (Pyodide, in the browser) unpacks the first archive when
it starts and puts it on sys.path, so the packages import as they would after
``pip install``. The second holds PedNet, PedGen and PedInterp, with networkx
(from its wheel in python/vendor, without its tests): they need NumPy and other
packages of Pyodide's, so the page loads them, and this archive, only when one
of them is first used (pedwb.cli.NEEDS says which each needs).

assets/py/pedigree-tools.json records what is in each archive and a checksum,
which the page adds to the archive's address so that a browser never keeps an
old copy.

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
# the second archive's: copied from other repositories by tools/vendor_wheels.py, which records their versions in
# vendor/SOURCES.json; networkx is a wheel there
ANALYSIS = ["pednet", "PedGen", "PedInterp"]
WHEELS = ["networkx"]
SOURCES = os.path.join(HERE, "vendor", "SOURCES.json")


def version_of(pkg):
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


def wheel_files(project, sources):
    """the package in a wheel of python/vendor, without its tests, and its licence: (data, name in the archive)"""
    record = sources[project]
    package = record["package"]
    with zipfile.ZipFile(os.path.join(HERE, "vendor", record["wheel"])) as z:
        for name in sorted(z.namelist()):
            if name.endswith("/"):
                continue
            if name.startswith(package + "/"):
                parts = name.split("/")
                if "tests" in parts[1:-1] or parts[-1] == "conftest.py":
                    continue
                yield z.read(name), name
            elif re.match(r"[^/]+\.dist-info/(licenses/)?LICEN[CS]E[^/]*$", name):
                yield z.read(name), package + "/" + os.path.basename(name)


def write_archive(name, entries):
    """entries: (data, name in the archive) → (bytes, sha256, files); the same entries always give the same archive"""
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for data, rel in entries:
            # (a fixed date, so that the checksum changes only when what is in the archive does)
            info = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
            count += 1
    data = buf.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    with open(os.path.join(OUT, name), "wb") as fh:
        fh.write(data)
    print("assets/py/{}: {} files, {:.0f} KB, sha256 {}".format(name, count, len(data) / 1024, digest[:12]))
    return {"archive": name, "sha256": digest, "bytes": len(data)}


def package_entries(packages):
    for pkg in packages:
        for full, rel in files_of(pkg):
            with open(full, "rb") as fh:
                yield fh.read(), rel


def about_entries():
    # what the packages are, and their licence, for whoever downloads the archive (help: On your own computer)
    for name in ("README.md", "LICENSE"):
        with open(os.path.join(HERE, name), "rb") as fh:
            yield fh.read(), name


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = write_archive("pedigree-tools.zip", list(package_entries(PACKAGES)) + list(about_entries()))
    manifest["packages"] = {p: version_of(p) for p in PACKAGES}
    sources = json.load(open(SOURCES, encoding="utf-8"))
    projects = {r["package"]: k for k, r in sources.items()}
    missing = [p for p in ANALYSIS + WHEELS if p not in projects]
    if missing:
        raise SystemExit("python/vendor/SOURCES.json has no record of {}: copy them with tools/vendor_wheels.py"
                         .format(", ".join(missing)))
    entries = list(package_entries(ANALYSIS))
    for package in WHEELS:
        entries += list(wheel_files(projects[package], sources))
    # (README.md describes both archives; each package of this one has its own licence in its folder)
    entries += [e for e in about_entries() if e[1] == "README.md"]
    analysis = write_archive("pedigree-analysis.zip", entries)
    analysis["packages"] = {p: sources[projects[p]]["version"] for p in ANALYSIS + WHEELS}
    manifest["analysis"] = analysis
    with open(os.path.join(OUT, "pedigree-tools.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
