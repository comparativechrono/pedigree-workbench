#!/usr/bin/env python3
"""Run every code box of the help (index.html), as a reader would: the terminal boxes with bash, the Python boxes
with Python, in a fresh home folder with the examples beside it.

The boxes are run in the order of the pages, so a box may use what an earlier box of its page wrote. Paths are
those of the workbench: /data/examples and /home/user (~) are replaced by folders made for the run, and the
pedigree programs are small scripts that run the workbench's own packages (python/). `studio`, `download` and
`export-session` do nothing here. Boxes that would ask EBI's Ontology Lookup Service are skipped (the tests never
contact it); boxes that need copies of the ontologies run only when ONTOLOGIES is a folder with hp.obo and mondo.obo.

Run:  python3 tests/help_code.py            (after python3 build/make_page.py)
"""
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAMS = ["studio2ped", "ped2studio", "studio2ga4gh", "ga4gh2studio", "mpedtools", "hponorm", "mondonorm",
            "phenotk", "pedigree-ga4gh"]


COLUMN = (
    "import sys\n"
    "a = sys.argv[1:]; sep = None; files = []\n"
    "i = 0\n"
    "while i < len(a):\n"
    "    if a[i] == '-s': sep = a[i + 1]; i += 2; continue\n"
    "    if a[i] != '-t': files.append(a[i])\n"
    "    i += 1\n"
    "text = ''.join(open(f).read() for f in files) if files else sys.stdin.read()\n"
    "rows = [l.split(sep) if sep else l.split() for l in text.splitlines()]\n"
    "w = [max(len(r[i]) for r in rows if len(r) > i) for i in range(max(map(len, rows)))]\n"
    "print('\\n'.join('  '.join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in rows))\n"
).replace('"', '\\"')


def boxes():
    page = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    for art in re.finditer(r'<article class="help-page" id="(h-[\w-]+)".*?</article>', page, re.S):
        for m in re.finditer(r'<pre class="code" data-run="(term|py)"><code>(.*?)</code></pre>', art.group(0), re.S):
            yield art.group(1), m.group(1), html.unescape(m.group(2))


def main():
    onto = os.environ.get("ONTOLOGIES", "")
    have_onto = bool(onto) and all(os.path.exists(os.path.join(onto, f)) for f in ("hp.obo", "mondo.obo"))
    tmp = tempfile.mkdtemp(prefix="help-code-")
    home, ex, bin_ = os.path.join(tmp, "home"), os.path.join(tmp, "examples"), os.path.join(tmp, "bin")
    for d in (home, bin_):
        os.makedirs(d)
    for d in ("pedigrees", "results", "terms", "notebooks"):
        os.makedirs(os.path.join(home, d))
    shutil.copytree(os.path.join(ROOT, "data", "examples"), ex)
    if have_onto:
        os.makedirs(os.path.join(home, "ontologies"))
        for f in ("hp.obo", "mondo.obo"):
            shutil.copyfile(os.path.join(onto, f), os.path.join(home, "ontologies", f))
    py = os.path.join(ROOT, "python")
    for name in PROGRAMS:
        with open(os.path.join(bin_, name), "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" -I -c "import sys; sys.path.insert(0, %r); from pedwb.cli import run; '
                     'sys.exit(run(sys.argv[1:]))" %s "$@"\n' % (sys.executable, py, name))
    for name in ("studio", "download", "export-session"):
        with open(os.path.join(bin_, name), "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
    if not shutil.which("column"):
        # (the terminal has column; a computer without it gets a small one: column -t [-s SEP])
        with open(os.path.join(bin_, "column"), "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" -I -c "%s" "$@"\n' % (sys.executable, COLUMN))
    with open(os.path.join(bin_, "python"), "w") as fh:
        fh.write('#!/bin/sh\nPYTHONPATH=%r exec "%s" "$@"\n' % (py, sys.executable))
    for f in os.listdir(bin_):
        os.chmod(os.path.join(bin_, f), 0o755)
    env = dict(os.environ, HOME=home, PATH=bin_ + os.pathsep + os.environ.get("PATH", ""), PYTHONPATH=py)

    def paths(text):
        return text.replace("/data/examples", ex).replace("/home/user", home)

    failed, ran, skipped = [], 0, 0
    for page, kind, code in boxes():
        if "OlsClient" in code or "ebi.ac.uk" in code:
            skipped += 1
            continue
        if "/ontologies/" in code and not have_onto:
            skipped += 1
            continue
        code = paths(code)
        if kind == "term":
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", code], cwd=home, env=env,
                               capture_output=True, text=True, timeout=600)
        else:
            # a notebook cell: ! lines are commands; the rest is Python
            lines = []
            for line in code.split("\n"):
                if line.startswith("!"):
                    lines.append("__import__('subprocess').run(%r, shell=True, check=True, executable='bash')" % line[1:])
                else:
                    lines.append(line)
            r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r)\n" % py + "\n".join(lines)],
                               cwd=home, env=env, capture_output=True, text=True, timeout=600)
        ran += 1
        # (validate and diff end with 1 when a file is invalid or files differ, as they should in some boxes)
        if r.returncode != 0 and not (kind == "term" and expected_failure(code, r)):
            failed.append((page, kind, code, r.stdout[-1500:], r.stderr[-1500:]))
    for page, kind, code, out, err in failed:
        print("=" * 70, "\nFAILED", page, kind, "\n" + code, "\n--- stdout\n" + out, "\n--- stderr\n" + err)
    print("%d boxes run, %d skipped, %d failed" % (ran, skipped, len(failed)))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


def expected_failure(code, r):
    """the boxes that show an invalid file or a difference end with exit status 1 on purpose"""
    last = [l for l in code.strip().split("\n") if l.strip()][-1]
    return r.returncode == 1 and (re.match(r"\s*(pedigree-ga4gh validate|phenotk diff|mpedtools validate)", last) is not None)


if __name__ == "__main__":
    sys.exit(main())
