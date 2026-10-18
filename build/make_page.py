#!/usr/bin/env python3
"""Build index.html from build/template.html and the help pages in build/help/.

- <!--ICON:name--> placeholders (in the template and the help pages) become the SVG icons of
  assets/js/icons.js, so that the page shows them before any script has run;
- each help page (build/help/*.html, in file-name order) becomes an <article class="help-page">;
  its first line is a comment with its id, title, group, summary, keywords and icon:
    <!-- id: h-terminal | title: The terminal | group: Terminal and programs | summary: … | keys: bash shell | icon: terminal -->
- the first page (h-home) gets the index of all topics, grouped (<!--TOPICS-->);
- a page with "index: yes" in its header introduces its group: <!--GROUP--> becomes the list of the group's other
  pages, and the breadcrumbs of those pages lead to it (else to the first page of the group);
- <!--KIN--> becomes the table of the KIN terms and <!--KIN-RETIRED--> that of the retired codes, read from the
  workbench's pedigree_ga4gh (python/), and <!--VERSIONS--> the table of the packages' versions, from
  assets/py/pedigree-tools.json and assets/studio/SOURCE.json;
- <!--CITE: program …--> becomes the section "References" with the papers of those programs, and
  <!--CITE-SHORT: program--> a short link to them (author, year), from build/citations.json – which is also written
  into the page (window.WB_CITATIONS), for the Tools tab;
- the list of example files (data/examples) and of the starter notebooks (data/starter) is written into the page
  (window.WB_EXAMPLES, window.WB_STARTERS), with what assets/py/pedigree-tools.json says of the Python packages
  (window.WB_BUNDLE) and which Pedigree Studio assets/studio holds (window.WB_STUDIO).

Run:  python3 build/make_page.py   (after python3 python/build_bundle.py, if the packages changed)
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# build/ is either inside the site (as it is handed over) or next to a folder site/ (as it was developed)
SITE = ROOT if os.path.isdir(os.path.join(ROOT, 'assets')) else os.path.join(ROOT, 'site')

# the groups of the help, in order, with the page that introduces each (for the breadcrumbs)
GROUPS = [
    ('Start here', 'book2'),
    ('Walkthroughs', 'route'),
    ('Pedigree Studio', 'pedigree'),
    ('Tools', 'wrench'),
    ('Files and standards', 'tag'),
    ('Notebook and terminal', 'terminal'),
    ('Reference', 'info'),
]


def icons():
    src = open(os.path.join(SITE, 'assets/js/icons.js'), encoding='utf-8').read()
    out = {}
    for m in re.finditer(r"^\s{4}(\w+):\s*'((?:[^'\\]|\\.)*)',?\s*$", src, re.M):
        out[m.group(1)] = m.group(2).replace("\\'", "'")
    return out


ICONS = icons()


def icon(name, cls=''):
    body = ICONS.get(name) or ICONS.get('info')
    return (f'<svg class="ic{(" " + cls) if cls else ""}" viewBox="0 0 24 24" width="18" height="18" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
            f'focusable="false">{body}</svg>')


def with_icons(text):
    def rep(m):
        if m.group(1) not in ICONS:
            print(f'warning: no icon called {m.group(1)}', file=sys.stderr)
        return icon(m.group(1))
    return re.sub(r'<!--ICON:(\w+)-->', rep, text)


def read_pages():
    d = os.path.join(HERE, 'help')
    pages = []
    for name in sorted(os.listdir(d)):
        if not name.endswith('.html'):
            continue
        text = open(os.path.join(d, name), encoding='utf-8').read()
        m = re.match(r'\s*<!--(.*?)-->', text, re.S)
        if not m:
            raise SystemExit(f'{name}: the first line must be <!-- id: … | title: … | group: … -->')
        meta = {}
        for part in m.group(1).split('|'):
            if ':' in part:
                k, v = part.split(':', 1)
                meta[k.strip()] = v.strip()
        for k in ('id', 'title', 'group'):
            if k not in meta:
                raise SystemExit(f'{name}: the header has no {k}')
        if meta['group'] not in [g for g, _ in GROUPS]:
            raise SystemExit(f"{name}: unknown group {meta['group']!r}")
        meta['body'] = text[m.end():].strip()
        meta['file'] = name
        pages.append(meta)
    ids = [p['id'] for p in pages]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise SystemExit(f'pages with the same id: {dup}')
    return pages


def topics(pages):
    out = ['<div class="help-topics">']
    for g, ic in GROUPS:
        if g == 'Start here':
            continue
        ps = [p for p in pages if p['group'] == g and p['id'] != 'h-home' and p.get('index') != 'yes']
        if not ps:
            continue
        # (a group with a page of its own: its heading leads there)
        idx = next((p for p in pages if p['group'] == g and p.get('index') == 'yes'), None)
        head = f'<a href="#{idx["id"]}">{html.escape(g)}</a>' if idx else html.escape(g)
        out.append(f'<section><h2>{icon(ic)}{head}</h2><ul>')
        for p in ps:
            summ = f'<small>{html.escape(p["summary"])}</small>' if p.get('summary') else ''
            out.append(f'<li><a href="#{p["id"]}">{html.escape(p["title"])}{summ}</a></li>')
        out.append('</ul></section>')
    out.append('</div>')
    return '\n'.join(out)


def group_list(pages, group, self_id):
    """the pages of a group, for its index page (<!--GROUP-->): a page with "index: yes" in its header introduces the
    group, and the breadcrumbs of the group's pages lead to it"""
    out = ['<ul class="help-grouplist">']
    for p in pages:
        if p['group'] != group or p['id'] == self_id or p.get('index') == 'yes':
            continue
        summ = f'<small>{html.escape(p["summary"])}</small>' if p.get('summary') else ''
        out.append(f'<li><a href="#{p["id"]}">{html.escape(p["title"])}{summ}</a></li>')
    out.append('</ul>')
    return '\n'.join(out)


CITATIONS = json.load(open(os.path.join(HERE, 'citations.json'), encoding='utf-8'))


def cite_authors(r):
    if r.get('corporate') and not r.get('authors'):
        return r['corporate']
    a = r.get('authors') or []
    return ', '.join(a[:6]) + (', et al.' if len(a) > 6 else '')


def cite_html(key):
    """one reference, formatted: authors (year) title. journal volume(issue): pages. link"""
    r = CITATIONS['refs'][key]
    e = html.escape
    title = r['title'] + ('' if r['title'][-1:] in '.?!' else '.')
    who = cite_authors(r)
    if r.get('year'):
        parts = [f'{e(who)} ({r["year"]}) {e(title)}']
    else:  # a program's web site or repository
        parts = [(f'{e(who)}. ' if who else '') + e(title)]
    if r.get('container') == 'arXiv':
        parts.append(f'arXiv:{e(r["pages"])}.')
    elif r.get('container', '').startswith('PhD thesis'):
        parts.append(f'{e(r["container"])}.')
    elif r.get('container'):
        where = f'<i>{e(r["container"])}</i>'
        if r.get('volume'):
            where += f' {e(str(r["volume"]))}' + (f'({e(str(r["issue"]))})' if r.get('issue') else '')
        if r.get('pages'):
            pages = e(str(r['pages']).replace('-', '–') if r.get('doi') else str(r['pages']))
            where += f': {pages}' if r.get('volume') else f', pp. {pages}' if '–' in pages else f' {pages}'
        parts.append(where + '.')
    if r.get('doi'):
        parts.append(f'<a href="https://doi.org/{e(r["doi"], quote=True)}" target="_blank" rel="noopener">doi:{e(r["doi"])}</a>')
    elif r.get('url'):
        parts.append(f'<a href="{e(r["url"], quote=True)}" target="_blank" rel="noopener">{e(r["url"].split("://", 1)[-1].rstrip("/"))}</a>')
    return ' '.join(parts)


def cite_short(key):
    """author and year, for a table: Chen et al. 2018, Li and Durbin 2009, Li 2018"""
    r = CITATIONS['refs'][key]
    if r.get('short'):
        who = r['short']
    elif r.get('corporate') and not r.get('authors'):
        who = r['corporate']
    else:
        fam = [a.rsplit(' ', 1)[0] if ' ' in a else a for a in r['authors']]
        who = fam[0] if len(fam) == 1 else f'{fam[0]} and {fam[1]}' if len(fam) == 2 else f'{fam[0]} et al.'
    when = f' {r["year"]}' if r.get('year') else ''
    url = f'https://doi.org/{r["doi"]}' if r.get('doi') else r.get('url', '')
    return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{html.escape(who + when)}</a>'


def cite_section(ids):
    progs = CITATIONS['programs']
    unknown = [i for i in ids if i not in progs]
    if unknown:
        raise SystemExit(f'<!--CITE--> names programs that build/citations.json does not have: {unknown}')
    out = ['<h2 data-anchor="cite">References</h2>',
           '<p>If you use ' + ('this program' if len(ids) == 1 else 'these programs') +
           ' in your work, cite the papers below, and give the ' + ('version' if len(ids) == 1 else 'versions') +
           ' you used (<a href="#h-versions">Versions, and how to cite</a>):</p>',
           '<dl class="cite-list">']
    for i in ids:
        p = progs[i]
        out.append(f'<dt>{html.escape(p["name"])}</dt>')
        if p.get('note'):
            out.append(f'<dd class="cite-note">{html.escape(p["note"])}</dd>')
        out.extend(f'<dd>{cite_html(k)}</dd>' for k in p['refs'])
    out.append('</dl>')
    return '\n'.join(out)


def citations_json():
    # every reference, formatted, for the Tools tab (no "</" inside a script element)
    return json.dumps({k: cite_html(k) for k in CITATIONS['refs']}, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')


def with_citations(body):
    body = re.sub(r'<!--CITE:\s*([^>]*?)\s*-->', lambda m: cite_section(m.group(1).split()), body)
    return re.sub(r'<!--CITE-SHORT:\s*([^>]*?)\s*-->',
                  lambda m: '; '.join(cite_short(k) for i in m.group(1).split() for k in CITATIONS['programs'][i]['refs']), body)


def kin_module():
    """the workbench's own pedigree_ga4gh (python/), for the tables of KIN"""
    sys.path.insert(0, os.path.join(SITE, 'python'))
    from pedigree_ga4gh import kin
    return kin


def kin_table():
    kin = kin_module()
    e = html.escape
    rows = ['<div class="help-xscroll"><table class="kin-table kin-terms">',
            '<tr><th>Code</th><th>Label</th><th>KIN\'s definition</th></tr>']
    for code, t in kin.TERMS.items():
        extra = []
        if t.symmetric:
            extra.append('the same both ways')
        elif t.inverse:
            extra.append(f'the other way: <code>{e(t.inverse)}</code> {e(kin.TERMS[t.inverse].label)}')
        if t.subject_sex:
            extra.append('the first person is ' + ('female' if t.subject_sex == 'FEMALE' else 'male'))
        note = f'<br><small>{"; ".join(extra)}</small>' if extra else ''
        rows.append(f'<tr><td><code>{e(code)}</code></td><td>{e(t.label)}</td><td>{e(t.definition or "")}{note}</td></tr>')
    rows.append('</table></div>')
    return '\n'.join(rows)


def kin_retired():
    kin = kin_module()
    e = html.escape
    rows = ['<table class="kin-table">', '<tr><th>Retired code</th><th>Becomes</th></tr>']
    for old, (new, swap) in sorted(kin.RETIRED.items()):
        rows.append(f'<tr><td><code>{e(old)}</code></td><td><code>{e(new)}</code> {e(kin.TERMS[new].label)}'
                    f'{" – with the two people swapped" if swap else ""}</td></tr>')
    rows.append('</table>')
    return '\n'.join(rows)


def versions_table():
    b = bundle()
    names = {'phenopacket_toolkit': 'phenopacket-toolkit (phenotk)', 'pedigree_ga4gh': 'pedigree-ga4gh',
             'pedwb': 'pedwb (the workbench\'s own runner, not on PyPI)'}
    rows = ['<table>', '<tr><th>Package</th><th>Version</th></tr>']
    for k, v in b['packages'].items():
        rows.append(f'<tr><td>{html.escape(names.get(k, k))}</td><td>{html.escape(str(v))}</td></tr>')
    s = json.load(open(os.path.join(SITE, 'assets/studio/SOURCE.json'), encoding='utf-8'))
    rows.append(f'<tr><td>Pedigree Studio</td><td>commit <code>{html.escape(s.get("commit", "")[:7])}</code> of '
                f'{html.escape(s.get("committed", "")[:10])}</td></tr>')
    rows.append('</table>')
    return '\n'.join(rows)


def with_tables(body):
    if '<!--KIN-->' in body:
        body = body.replace('<!--KIN-->', kin_table())
    if '<!--KIN-RETIRED-->' in body:
        body = body.replace('<!--KIN-RETIRED-->', kin_retired())
    if '<!--VERSIONS-->' in body:
        body = body.replace('<!--VERSIONS-->', versions_table())
    return body


def check_links(pages):
    ids = {p['id'] for p in pages}
    bad = []
    for p in pages:
        for m in re.finditer(r'(?:href="#|data-goto=")(h-[\w-]+)', p['body']):
            if m.group(1) not in ids:
                bad.append((p['file'], m.group(1)))
    for f, i in bad:
        print(f'warning: {f} links to a page that does not exist: {i}', file=sys.stderr)
    return bad


def examples():
    base = os.path.join(SITE, 'data/examples')
    out = []
    for dp, dn, fn in os.walk(base):
        dn.sort()
        for f in sorted(fn):
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, base).replace(os.sep, '/')
            out.append({'p': rel, 's': os.path.getsize(full)})
    return out


def starters():
    base = os.path.join(SITE, 'data/starter')
    if not os.path.isdir(base):
        return []
    return [{'p': 'notebooks/' + f} for f in sorted(os.listdir(base)) if f.endswith('.ipynb')]


def bundle():
    """the archive of the Python packages: its name, checksum and the packages' versions"""
    p = os.path.join(SITE, 'assets/py/pedigree-tools.json')
    if not os.path.exists(p):
        raise SystemExit('assets/py/pedigree-tools.json is missing: run  python3 python/build_bundle.py  first')
    return json.load(open(p, encoding='utf-8'))


def studio_source():
    """the commit of Pedigree Studio that assets/studio holds (for the frame's address, so that a new copy is loaded)"""
    p = os.path.join(SITE, 'assets/studio/SOURCE.json')
    if not os.path.exists(p):
        raise SystemExit('assets/studio/SOURCE.json is missing: run  python3 build/update_studio.py  first')
    s = json.load(open(p, encoding='utf-8'))
    return (s.get('commit') or s.get('sha256_of_original') or '')[:12]


def main():
    tpl = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    pages = read_pages()
    # the page that introduces a group: its index page if it has one, else its first page
    first_of = {}
    for p in pages:
        if p.get('index') == 'yes':
            first_of[p['group']] = p['id']
    for p in pages:
        first_of.setdefault(p['group'], p['id'])
    parts = []
    for p in pages:
        body = with_tables(with_citations(p['body'].replace('<!--TOPICS-->', topics(pages)).replace('<!--GROUP-->', group_list(pages, p['group'], p['id']))))
        attrs = {
            'class': 'help-page',
            'id': p['id'],
            'data-title': p['title'],
            'data-group': p['group'],
            'data-group-page': first_of.get(p['group'], ''),
            'data-keys': p.get('keys', ''),
        }
        a = ' '.join(f'{k}="{html.escape(v, quote=True)}"' for k, v in attrs.items() if v)
        parts.append(f'<article {a} hidden>\n{body}\n</article>')
    check_links(pages)
    out = tpl.replace('<!--HELP-->', '\n'.join(parts))
    data = (f'<script>window.WB_EXAMPLES = {json.dumps(examples(), separators=(",", ":"))};\n'
            f'window.WB_STARTERS = {json.dumps(starters(), separators=(",", ":"))};\n'
            f'window.WB_BUNDLE = {json.dumps(bundle(), separators=(",", ":"))};\n'
            f'window.WB_STUDIO = {json.dumps(studio_source())};\n'
            f'window.WB_CITATIONS = {citations_json()};</script>')
    out = out.replace('<!--DATA-->', data)
    out = with_icons(out)
    left = re.findall(r'<!--ICON:\w+-->|<!--HELP-->|<!--DATA-->|<!--TOPICS-->|<!--GROUP-->|<!--CITE|<!--KIN|<!--VERSIONS-->', out)
    if left:
        raise SystemExit(f'placeholders left: {left[:5]}')
    open(os.path.join(SITE, 'index.html'), 'w', encoding='utf-8').write(out)
    print(f'index.html: {len(pages)} help pages, {len(examples())} example files, {len(starters())} starter notebooks, {len(out) // 1024} KB')


if __name__ == '__main__':
    main()
