#!/usr/bin/env python3
"""Copy the packages that come from other repositories into python/, from their wheels.

    python3 python/tools/vendor_wheels.py pednet-2.0.0-py3-none-any.whl pedgen-….whl pedinterp-….whl \\
        networkx-3.4.2-py3-none-any.whl

PedNet, PedGen and PedInterp go in python/pednet, python/PedGen and python/PedInterp, with their licences. A
package's folder is replaced as a whole, so nothing of an older copy is left behind.

networkx, which PedNet needs, is kept as its wheel, in python/vendor: build_bundle.py takes the package from it,
without its tests, and Python can import it from the wheel as it is (the tests put the wheel on sys.path). Pyodide
has networkx too, but it loads it with matplotlib, which PedNet doesn't need and which would add several megabytes
to the first use of PedNet.

What was copied, and from which wheel (its name and SHA-256), is recorded in python/vendor/SOURCES.json, which
python/build_bundle.py reads for the versions. So is a SHA-256 of the files copied (files_sha256: see tree_digest),
which the tests check, so that a copy changed by hand doesn't go unnoticed.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.dirname(HERE)
SOURCES = os.path.join(PY, 'vendor', 'SOURCES.json')

# a wheel's project name → the package in it, the folder it goes in (under python/), and where it comes from
PACKAGES = {
    'pednet': ('pednet', 'pednet', 'https://pypi.org/project/PedNet/'),
    'pedgen': ('PedGen', 'PedGen', 'https://github.com/comparativechrono/pedigree-generator'),
    'pedinterp': ('PedInterp', 'PedInterp', 'https://github.com/comparativechrono/pedigree-interpreter'),
    'networkx': ('networkx', 'vendor', 'https://pypi.org/project/networkx/'),
}


def wheel_name(path):
    """pedgen-0.1.4.dev5+g4ab719d58-py3-none-any.whl → ('pedgen', '0.1.4.dev5+g4ab719d58')"""
    m = re.match(r'([A-Za-z0-9_.]+?)-([^-]+)-[^-]+-[^-]+-[^-]+\.whl$', os.path.basename(path))
    if not m:
        raise SystemExit(f'{path}: not the name of a wheel')
    return m.group(1).lower().replace('_', '-'), m.group(2)


def tree_digest(folder):
    """A SHA-256 of a folder's files: of each one's path in the folder and its own SHA-256, in order of path.
    Python's caches (__pycache__) are left out."""
    files = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            if name.endswith('.pyc'):
                continue
            full = os.path.join(dirpath, name)
            with open(full, 'rb') as fh:
                files.append((os.path.relpath(full, folder).replace(os.sep, '/'), hashlib.sha256(fh.read()).hexdigest()))
    digest = hashlib.sha256()
    for rel, sha in sorted(files):
        digest.update(f'{rel}\0{sha}\n'.encode('utf-8'))
    return digest.hexdigest()


def copy(path):
    project, version = wheel_name(path)
    if project not in PACKAGES:
        raise SystemExit(f'{path}: not one of the packages copied here ({", ".join(PACKAGES)})')
    package, folder, origin = PACKAGES[project]
    dest = os.path.join(PY, folder)
    data = open(path, 'rb').read()
    record = {'package': package, 'folder': folder, 'version': version, 'wheel': os.path.basename(path),
              'sha256': hashlib.sha256(data).hexdigest(), 'from': origin}
    if folder == 'vendor':
        # the wheel itself, in place of any other version's
        os.makedirs(dest, exist_ok=True)
        for old in os.listdir(dest):
            if old.endswith('.whl') and wheel_name(old)[0] == project:
                os.remove(os.path.join(dest, old))
        shutil.copyfile(path, os.path.join(dest, os.path.basename(path)))
        print(f'vendor/{os.path.basename(path)}')
        return project, record
    shutil.rmtree(dest, ignore_errors=True)
    files = 0
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            if name.endswith('/'):
                continue
            if name.startswith(package + '/'):
                rel = name[len(package) + 1:]
            elif re.match(r'[^/]+\.dist-info/(licenses/)?(LICEN[CS]E[^/]*|COPYING[^/]*)$', name):
                rel = os.path.basename(name)
            else:
                continue
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, 'wb') as fh:
                fh.write(z.read(name))
            files += 1
    record['files_sha256'] = tree_digest(dest)
    print(f'{folder}: {files} files from {os.path.basename(path)}')
    return project, record


def main(paths):
    if not paths:
        print(__doc__)
        return 2
    sources = json.load(open(SOURCES, encoding='utf-8')) if os.path.exists(SOURCES) else {}
    for path in paths:
        project, record = copy(path)
        sources[project] = record
    os.makedirs(os.path.dirname(SOURCES), exist_ok=True)
    with open(SOURCES, 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(sources.items())), fh, indent=2)
        fh.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
