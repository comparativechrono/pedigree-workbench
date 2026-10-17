#!/usr/bin/env python3
"""Copy Pedigree Studio into the workbench: assets/studio/index.html.

The Studio tab shows Pedigree Studio (github.com/comparativechrono/PedigreeStudio)
in a frame. Its page is copied here unchanged except for two things:

1. it keeps its drawing in the browser under the name ``pedwb:studio-session``
   rather than ``pedigree-studio-session``, so that the workbench's drawing and
   one made in Pedigree Studio itself, on the same web address, never overwrite
   each other;
2. it loads ``bridge.js`` (assets/studio/bridge.js), through which the workbench
   opens files in it, saves its drawing and runs Tidy.

To take a newer Pedigree Studio, run one of

    python3 build/update_studio.py --git ../PedigreeStudio            (its origin/main)
    python3 build/update_studio.py --git ../PedigreeStudio --ref v1.2
    python3 build/update_studio.py --file path/to/index.html

and check the Studio tab. assets/studio/SOURCE.json records what was copied.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "assets", "studio")
OLD_KEY = "'pedigree-studio-session'"
NEW_KEY = "'pedwb:studio-session'"
BRIDGE = '<script src="bridge.js"></script>\n'


def from_git(repo, ref):
    run = lambda *a: subprocess.run(["git", "-C", repo] + list(a), check=True, capture_output=True, text=True).stdout
    text = run("show", "{}:index.html".format(ref))
    commit = run("rev-parse", ref).strip()
    when = run("log", "-1", "--format=%cI", ref).strip()
    url = run("remote", "get-url", "origin").strip() if run("remote").strip() else ""
    return text, {"repository": url, "ref": ref, "commit": commit, "committed": when}


def patch(text):
    n = text.count(OLD_KEY)
    if n == 0:
        raise SystemExit("Pedigree Studio no longer stores its drawing under {} – look at how it does now, "
                         "and change this script to match".format(OLD_KEY))
    text = text.replace(OLD_KEY, NEW_KEY)
    if "bridge.js" not in text:
        i = text.rfind("</body>")
        if i < 0:
            raise SystemExit("index.html has no </body>")
        text = text[:i] + BRIDGE + text[i:]
    # the functions bridge.js uses must still be there
    for fn in ("buildSessionData", "restoreSession", "runManagedPedigreeLayout", "fitToView", "scheduleSave",
               "pushUndo", "deselectAll"):
        if not re.search(r"function\s+{}\s*\(".format(fn), text):
            raise SystemExit("Pedigree Studio has no function {}() any more: bridge.js needs it".format(fn))
    return text, n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--git", metavar="REPO", help="a clone of PedigreeStudio")
    g.add_argument("--file", metavar="INDEX_HTML", help="Pedigree Studio's index.html")
    ap.add_argument("--ref", default="origin/main", help="with --git: the branch, tag or commit (default origin/main)")
    a = ap.parse_args()
    if a.git:
        text, source = from_git(a.git, a.ref)
    else:
        text = open(a.file, encoding="utf-8").read()
        source = {"file": os.path.basename(a.file)}
    source["sha256_of_original"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    text, n = patch(text)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(text)
    source["copied"] = datetime.date.today().isoformat()
    source["changes"] = ["the browser-storage key {} became {} ({} places)".format(OLD_KEY, NEW_KEY, n),
                         "loads bridge.js before </body>"]
    with open(os.path.join(OUT, "SOURCE.json"), "w", encoding="utf-8") as fh:
        json.dump(source, fh, indent=2)
        fh.write("\n")
    print("assets/studio/index.html: {} KB from {}".format(len(text) // 1024, source.get("commit", source.get("file"))[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
