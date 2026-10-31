#!/usr/bin/env python3
"""The Risk tab reads drawings, PED and MPED files in the page (assets/js/risk-read.js) and GA4GH files in Python
(python/pedwb/risk.py). This checks that it reads them as the rest of the workbench does:

- each example drawing as studio2ped reads it: the same people, sexes and genetic parents, and for each condition
  in the key, the same affected, carrier and unaffected people as the PED or MPED file that studio2ped writes (and
  tests/risk/thirds.studio.json, the drawing with every kind of symbol with two people in thirds);
- each example PED and MPED file as mpedtools reads it;
- each example GA4GH Pedigree and Phenopackets Family as PedNet reads it, for each of its conditions: the same
  people, parents and phenotypes, with people who have no record of the condition taken as PedNet takes them.

usage: python3 tests/risk/readers.py      (needs Node, for the page's readers)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'python'))

from mpedtools import core as mped          # noqa: E402
from studio2ped import converter as s2p      # noqa: E402

CODE = {'affected': 2, 'unaffected': 1, 'carrier': 3}
SEX = {'M': 1, 'F': 2, 'U': 0}
failures = []


def check(ok, what):
    print(('ok    ' if ok else 'FAIL  ') + what)
    if not ok:
        failures.append(what)


def page_reading():
    out = subprocess.run(['node', os.path.join(HERE, 'read_examples.js')], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def compare(where, people, rows, codes_of, skip=()):
    """people: the page's people by id; rows: mpedtools' Individuals; codes_of(person) -> the phenotype codes the page
    gives them, in the file's columns, but for the columns in skip"""
    by_id = {p['id']: p for p in people}
    wrong = []
    if set(by_id) != {r.ind_id for r in rows}:
        wrong.append(f'people: page {sorted(set(by_id) - {r.ind_id for r in rows})}, '
                     f'python {sorted({r.ind_id for r in rows} - set(by_id))}')
    for r in rows:
        p = by_id.get(r.ind_id)
        if p is None:
            continue
        # (studio2ped writes a pregnancy loss as of unknown sex; the page takes the sex drawn for it, as studio2ga4gh does)
        sex = 0 if p.get('loss') else SEX[p['sex']]
        page = (sex, p['father'] or '0', p['mother'] or '0', codes_of(p))
        python = (r.sex, r.father_id, r.mother_id, [v for n, v in r.phenotypes.items() if n not in skip])
        if page != python:
            wrong.append(f'{r.ind_id}: page {page}, python {python}')
    check(not wrong, f'{where}: {len(rows)} people as the Python reads them' + (': ' + '; '.join(wrong[:4]) if wrong else ''))


def drawing(entry):
    family = entry['families'][0]
    with open(os.path.join(ROOT, entry['file']), encoding='utf-8') as fh:
        session = json.load(fh)
    result = s2p.convert(session, ids='studio')
    named = [c for c in family['conditions'] if not c.get('unnamed')]
    for name, content in result.files:
        parsed = mped.parse(content)
        if parsed.is_mped:
            def codes(p):
                return [CODE.get(p['status'].get(c['key']), 0) for c in named]
        else:
            # one condition, and no carriers: affected (2), or not (1)
            def codes(p):
                return [2 if any(p['status'].get(c['key']) == 'affected' for c in named) else 1]
        # (the Carrier column that studio2ped adds for carriers' dots is not a condition: the page leaves it out)
        skip = {'Carrier'} if parsed.is_mped and 'Carrier' in parsed.phenotype_names and len(parsed.phenotype_names) > 1 else set()
        compare(f"{entry['file']} ({name})", family['people'], parsed.individuals, codes, skip)


def ped_file(entry):
    with open(os.path.join(ROOT, entry['file']), encoding='utf-8') as fh:
        parsed = mped.parse(fh.read())
    for family in entry['families']:
        rows = [r for r in parsed.individuals if r.family_id == family['id']]
        names = parsed.phenotype_names

        skip = {'Carrier'} if parsed.is_mped and 'Carrier' in names and len(names) > 1 else set()

        def codes(p):
            return [CODE.get(p['status'].get(n), 0) for n in names if n not in skip]
        # (mpedtools keeps -9 and other codes as they are; the page has no record of them, as for 0)
        for r in rows:
            r.phenotypes = {n: (v if v in (1, 2, 3) else 0) for n, v in r.phenotypes.items()}
        compare(f"{entry['file']} family {family['id']}", family['people'], rows, codes, skip)


def ga4gh_files():
    try:
        import pednet
        from pednet import read_ga4gh
    except ImportError:
        print('skip  GA4GH files: this PedNet has no read_ga4gh (PedNet 2.1.0 has it)')
        return
    from pedwb import risk
    examples = os.path.join(ROOT, 'data', 'examples')
    for name in sorted(os.listdir(examples)):
        if not name.endswith(('_ga4gh-pedigree.json', '_phenopackets-family.json')):
            continue
        path = os.path.join(examples, name)
        family = risk.family(path)
        for c in family['conditions']:
            if c['key'] == risk.FAMILY_STATUS:
                theirs = read_ga4gh(path)            # the Family's own status, as PedNet reads it by default
            else:
                theirs = read_ga4gh(path, condition=c['key'])
            pedigree = next(iter(theirs.values()))
            rule = (family.get('unrecordedFor') or {}).get(c['key']) or family['unrecorded']
            if rule == 'auto':
                rule = 'unknown' if any(p['status'].get(c['key']) == 'unaffected' for p in family['people']) else 'unaffected'
            wrong = []
            for p in family['people']:
                s = p['status'].get(c['key'])
                mine = 2 if s == 'affected' else 1 if s == 'unaffected' else (1 if rule == 'unaffected' else 0)
                q = pedigree[p['id']]
                if (mine, p['father'], p['mother'], SEX[p['sex']]) != (q.phenotype, q.father, q.mother, q.sex):
                    wrong.append(f"{p['id']}: page {(mine, p['father'], p['mother'], SEX[p['sex']])}, "
                                 f"PedNet {(q.phenotype, q.father, q.mother, q.sex)}")
            check(not wrong, f"{name}, {c['label']}: {len(family['people'])} people as PedNet reads them"
                  + (': ' + '; '.join(wrong[:4]) if wrong else ''))


for entry in page_reading():
    if entry['file'].endswith('.studio.json'):
        drawing(entry)
    else:
        ped_file(entry)
# the drawing with every kind of symbol, with two people in thirds, which the Studio draws for three conditions
thirds = subprocess.run(['node', os.path.join(HERE, 'read_examples.js'), os.path.join(HERE, 'thirds.studio.json')],
                        capture_output=True, text=True, check=True)
for entry in json.loads(thirds.stdout):
    drawing(entry)
ga4gh_files()
print(f'\n{len(failures)} failed' if failures else '\nall the same')
sys.exit(1 if failures else 0)
