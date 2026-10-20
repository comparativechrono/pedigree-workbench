#!/usr/bin/env python3
"""Open the workbench in headless Chromium and do what a first session does: open an example in the Studio, convert
it in the Tools tab, check the result, run commands in the terminal, run the welcome notebook, and use the help, and
work out the risks in example families in the Risk tab, from the help's buttons. Then
PedNet, PedGen and PedInterp, which Python loads when they are first used: their commands in the terminal, their tools
in the Tools tab, and the notebook that walks through them. Then, on a desktop, a later visit (the page loaded again):
what the first visit made is still there, and Python loads the three packages again, the first download of their
archive failing as it would offline, from the terminal, from a cell that also keeps a command's output, and from a
script run with %run.

It needs Playwright and its Chromium (pip install playwright; playwright install chromium). It serves the site
itself. Only Pyodide is fetched from the web (cdn.jsdelivr.net, through Python, so that a proxy in the environment is
used, and kept in a cache folder); every other request leaving the site is refused, so EBI's Ontology Lookup Service
is never contacted.

    python3 tests/browser_smoke.py [--cache DIR] [--shots DIR]
"""
import argparse
import asyncio
import functools
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW = ("cdn.jsdelivr.net",)

SCENARIO = r"""
async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const wait = async (fn, ms = 120000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { const v = await fn(); if (v) return v; } catch (e) {} await sleep(100); } throw new Error('timed out: ' + fn.toString().slice(0, 100)); };
  const out = [];
  const check = (ok, what) => out.push((ok ? 'ok    ' : 'FAIL  ') + what);
  try {
    // the Studio: an example
    await MG.app.studioOpen('/data/examples/okafor.studio.json');
    check(MG.app.studio && !MG.app.studio.api.isEmpty(), 'Studio: the Okafor example opens');
    // the Tools tab: Drawing → GA4GH
    await MG.app.useTool('studio2ga4gh', { input: '/data/examples/okafor.studio.json', terms: '/data/examples/example-terms.json' });
    await sleep(300);
    document.querySelector('.tl-run').click();
    await wait(() => document.querySelector('.tl-done'), 240000);
    check(document.querySelector('.tl-done.ok') && MG.app.fs.exists('/home/user/results/okafor_ga4gh-pedigree.json') && MG.app.fs.exists('/home/user/results/okafor_phenopackets-family.json'), 'Tools: Drawing → GA4GH writes both files');
    // the check
    await MG.app.useTool('validate', { input: '/home/user/results/okafor_ga4gh-pedigree.json' });
    await sleep(300);
    document.querySelector('.tl-run').click();
    await wait(() => document.querySelector('.tl-verdict'), 60000);
    check(document.querySelector('.tl-verdict.ok'), 'Tools: the GA4GH Pedigree is valid');
    // an older file is refused by the drawing tool, and upgraded
    await MG.app.useTool('upgrade', { input: '/data/examples/older/abusua2ga4gh-0.2_phenopackets-family.json' });
    await sleep(300);
    document.querySelector('.tl-run').click();
    await wait(() => document.querySelector('.tl-done'), 60000);
    check(document.querySelector('.tl-done.ok') && /to do/.test(document.querySelector('.tl-result').innerText), 'Tools: an older file is upgraded, with what is left to do');
    // a file in the form of the draft of version 1 is named as such, and no upgrade is offered
    MG.app.fs.writeText('/home/user/results/draft-v1.json', JSON.stringify({ id: 'FAM1', individuals: [{ id: 'MOTHER', sexAssignedAtBirth: 'ASSIGNED_FEMALE' }, { id: 'CHILD', eggParentId: 'MOTHER' }], relationships: [{ individual: 'MOTHER', relative: 'CHILD', biologicalRelationship: [{ id: 'KIN:027', label: 'isBiologicalMotherOf' }] }] }));
    await MG.app.useTool('validate', { input: '/home/user/results/draft-v1.json' });
    await sleep(300);
    document.querySelector('.tl-run').click();
    await wait(() => document.querySelector('.tl-verdict'), 60000);
    const warn = document.querySelector('.tl-warn');
    check(document.querySelector('.tl-verdict.bad') && warn && /draft of version 1/.test(warn.textContent) && !warn.querySelector('button'), 'Tools: a draft version 1 file is named, with no upgrade offered');
    // the terminal
    await MG.app.showWorkbench('terminal');
    const T = MG.app.term;
    const run = async (cmd) => { const n0 = T.outEl.children.length; await T.type(cmd, true); await sleep(150); await wait(() => !T.busy, 120000); return Array.from(T.outEl.children).slice(n0).map((e) => e.textContent).join('\n'); };
    check(/No problems found/.test(await run('pedigree-ga4gh validate ~/results/okafor_phenopackets-family.json')), 'Terminal: pedigree-ga4gh validate');
    check(/IV-3/.test(await run('phenotk view ~/results/okafor_ga4gh-pedigree.json | grep IV-3')), 'Terminal: phenotk view, piped to grep');
    check(/Hearing_loss_from_birth/.test(await run('studio2ped /data/examples/okafor.studio.json -d ~/results -o okafor && head -1 ~/results/okafor.mped')), 'Terminal: studio2ped');
    check(/isBiologicalMotherOf/.test(await run('pedigree-ga4gh kin | grep -i mother')), 'Terminal: pedigree-ga4gh kin');
    // the welcome notebook
    await MG.app.showWorkbench('notebook');
    await wait(() => MG.app.nbApp, 20000);
    await MG.app.nbApp.open('/home/user/notebooks/pedigree-tools.ipynb');
    await sleep(500);
    const view = MG.app.nbApp.view;
    await view.runAll();
    const errs = view.cells.filter((c) => c.type === 'code' && /Traceback/.test(c.el.innerText)).length;
    check(errs === 0 && view.cells.filter((c) => c.type === 'code').every((c) => /\[\d+\]/.test(c.countEl.textContent)), 'Notebook: the welcome notebook runs without errors');
    // the Files tab: a file open in it fits the screen, on a phone too
    for (const f of ['/data/examples/okafor_phenopackets-family.json', '/data/examples/lynch.png']) {
      await MG.app.editFile(f);
      await sleep(800);
    }
    check(document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1, 'Files: an open file fits the width of the screen');
    // the help: the map, a button, the KIN table
    MG.app.showHelp('h-home');
    await sleep(300);
    check(document.querySelector('#h-home .pw-map svg'), 'Help: the map is drawn');
    MG.app.showHelp('h-kin');
    await sleep(200);
    check(document.querySelectorAll('#h-kin .kin-table tr').length === 49 + 13, 'Help: the KIN tables (48 terms, 12 retired codes)');
    MG.app.showHelp('h-walk-ped');
    await sleep(200);
    Array.from(document.querySelectorAll('#h-walk-ped button.do')).find((b) => /Take one condition out/.test(b.textContent)).click();
    await wait(() => document.querySelector('.tl-title') && /Take one condition out/.test(document.querySelector('.tl-title').textContent), 20000);
    check(true, 'Help: a walkthrough button opens its tool');

    // the Risk tab: from the walkthrough, the pregnancy of the cousins in the cystic fibrosis family; a test result; a
    // GA4GH Pedigree, read in Python; and a sum by hand, from the help
    MG.app.showHelp('h-walk-risk');
    await sleep(200);
    document.querySelector('#h-walk-risk button[data-risk][data-person="V-1"]').click();
    await wait(() => MG.app.risk && document.querySelector('#riskRoot .rk-all'), 20000);
    await sleep(300);
    const rk = document.querySelector('#riskRoot');
    const rkLines = (n) => Array.from(rk.querySelectorAll(`.rk-answers > section:nth-of-type(${n}) .rk-line`)).map((l) => l.innerText.replace(/\s+/g, ' ').trim()).join(' | ');
    const rkTest = async (label, value) => {
      const s = Array.from(rk.querySelectorAll('.rk-all tbody tr')).find((tr) => tr.querySelector('th b').textContent === label).querySelector('select');
      s.value = value;
      s.dispatchEvent(new Event('change'));
      await sleep(200);
    };
    check(/Will be affected about 1 in 12 \(8\.4%\)/.test(rkLines(1)) && /Affected about 1 in 12 \(8\.4%\)/.test(rkLines(2)), 'Risk: the pregnancy in the cystic fibrosis family, about 1 in 12, for it and for its parents\' child');
    await rkTest('III-2', 'none');
    check(/Will be affected 1 in 12 \(8\.3%\)/.test(rkLines(1)), 'Risk: with Lisa\'s mother tested and found not to carry it, exactly 1 in 12');
    await rkTest('III-2', '');
    await MG.app.riskOpen({ source: '/data/examples/okafor_ga4gh-pedigree.json', person: 'IV-1' });
    await wait(() => /Hearing impairment/.test(rk.querySelector('#rk-condition').selectedOptions[0].textContent) && rk.querySelector('.rk-all'), 120000);
    check(/Is a carrier \(one copy\) 2\/3/.test(rkLines(1)), 'Risk: a GA4GH Pedigree, read in Python: the twins\' sister a carrier with a chance of 2/3');
    MG.app.showHelp('h-risk');
    await sleep(200);
    document.querySelector('#h-risk button[data-inherit="calc ar 2/3 1/25"]').click();
    await wait(() => rk.querySelector('.calc-res'), 10000);
    check(/1\/150/.test(rk.querySelector('.calc-res').innerText), 'Risk: by hand, 2/3 × 1/25 × 1/4 = 1/150');
    const tabs = document.querySelector('.wb-tabs');
    check(tabs.scrollWidth <= tabs.clientWidth + 1, 'Risk: the six tabs fit across the page');

    // PedNet, PedGen and PedInterp: loaded the first time they are used, with what they need
    await MG.app.showWorkbench('terminal');
    let said = await run('pednet mode /data/examples/lynch.ped');
    check(/Loading PedNet, with NumPy/.test(said) && /Family FAM1: autosomal dominant/.test(said), 'Terminal: pednet loads, with NumPy, and calls the Lynch family dominant');
    said = await run('pednet graph /data/examples/okafor.mped | grep -c loop');
    check(/^\s*1\s*$/m.test(said) && !/Loading/.test(said), 'Terminal: pednet again, piped to grep, with nothing more to load');
    const tool = async (id, values, ms = 300000) => {
      await MG.app.useTool(id, values);
      await sleep(400);
      document.querySelector('.tl-run').click();
      await wait(() => document.querySelector('.tl-done'), ms);
      return document.querySelector('.tl-result');
    };
    let res = await tool('pedinterp', { input: '/data/examples/lynch.png' });
    const ped = (p) => MG.app.fs.readText(p).then((s) => s.trim().split('\n').map((l) => l.split('\t').slice(1).join(' ')).join('\n'));
    check(res.querySelector('.tl-done.ok') && (await ped('/home/user/results/lynch.ped')) === (await ped('/data/examples/lynch.ped')) && /read enlarged 5\.6 times/.test(res.innerText), 'Tools: Picture → PED file reads the Lynch picture as lynch.ped, enlarged as its symbols need');
    // the Okafor family sketched by hand, from the help's button, which ticks Drawn by hand
    MG.app.showHelp('h-tool-pedinterp');
    await sleep(200);
    document.querySelector('#h-tool-pedinterp button[data-input="/data/examples/okafor-sketch.png"]').click();
    await wait(() => document.querySelector('.tl-title') && /Picture/.test(document.querySelector('.tl-title').textContent), 20000);
    await sleep(400);
    document.querySelector('.tl-run').click();
    await wait(() => document.querySelector('.tl-done'), 300000);
    res = document.querySelector('.tl-result');
    const sketched = MG.app.fs.exists('/home/user/results/okafor-sketch.ped') ? (await ped('/home/user/results/okafor-sketch.ped')).split('\n') : [];
    check(res.querySelector('.tl-done.ok') && /twins: IV-3 and IV-4 \(identical\)/.test(res.innerText) && sketched.length === 16 && sketched.filter((l) => / 2$/.test(l)).length === 3, 'Tools: Picture → PED file reads the Okafor family sketched by hand, from the help, with its identical twins');
    res = await tool('pedgen', { mode: 'AR', generations: 4, seed: '7', ga4gh: true, condId: 'MONDO:0009061', condLabel: 'cystic fibrosis' });
    const affected = (await MG.app.fs.readText('/home/user/results/FAM1.ped')).trim().split('\n').filter((l) => l.split('\t')[5] === '2').length;
    const simulated = '/home/user/results/FAM1_ga4gh-pedigree.json';
    check(res.querySelector('.tl-done.ok') && MG.app.fs.exists('/home/user/results/FAM1-genotypes.tsv') && Array.from(res.querySelectorAll('.tl-next button')).length === 4 && affected >= 2, 'Tools: Simulate a family makes a recessive family with cousins who marry and two people affected, with four next steps');
    check(MG.app.fs.exists(simulated) && /MONDO:0009061/.test(await MG.app.fs.readText(simulated)), 'Tools: Simulate a family writes a GA4GH Pedigree too, with the condition given');
    // its risks, from the next step, with the simulation's mode of inheritance
    Array.from(res.querySelectorAll('.tl-next button')).find((b) => /risks/.test(b.textContent)).click();
    await wait(() => MG.app.risk && MG.app.risk.st.source === simulated && document.querySelector('#riskRoot .rk-all'), 120000);
    await sleep(300);
    check(/cystic fibrosis/.test(document.querySelector('#rk-condition').selectedOptions[0].textContent) && MG.app.risk.st.mode === 'AR', 'Risk: the simulated family\'s GA4GH Pedigree, from Simulate a family, as autosomal recessive');
    res = await tool('pednet-mode', { input: simulated });
    check(res.querySelector('.tl-done.ok') && /Family FAM1/.test(res.innerText), 'Tools: Mode of inheritance reads the simulated family\'s GA4GH Pedigree');
    await MG.app.useTool('pednet-rank', { input: '/home/user/results/FAM1.ped' });
    await sleep(400);
    const variants = Array.from(document.querySelectorAll('.tl-field')).find((f) => f.dataset.key === 'variants').querySelector('select').value;
    check(variants === '/home/user/results/FAM1-genotypes.tsv', 'Tools: Rank candidate variants finds the genotypes that go with the PED file');
    res = await tool('pednet-rank', { input: '/home/user/results/FAM1.ped', variants: '/home/user/results/FAM1-genotypes.tsv' });
    check(res.querySelector('.tl-done.ok') && /causal/.test(res.innerText) && MG.app.fs.exists('/home/user/results/FAM1-ranked.tsv'), 'Tools: Rank candidate variants ranks the simulated variant, and saves the scores');
    res = await tool('pednet-graph', { input: '/data/examples/pednet/consanguineous.ped', kinship: true });
    check(res.querySelector('.tl-done.ok') && /a loop, from consanguinity/.test(res.innerText) && MG.app.fs.exists('/home/user/results/consanguineous-kinship.tsv'), 'Tools: The pedigree as a graph finds the loop, and saves the kinship table');
    // the notebook that walks through them
    await MG.app.showWorkbench('notebook');
    await MG.app.nbApp.open('/home/user/notebooks/pedigree-analysis.ipynb');
    await sleep(500);
    const v2 = MG.app.nbApp.view;
    await v2.runAll();
    const errs2 = v2.cells.filter((c) => c.type === 'code' && /Traceback|Error|couldn’t/.test(c.el.innerText)).length;
    check(errs2 === 0 && /the same as lynch.ped: True/.test(v2.el ? v2.el.innerText : document.body.innerText) && /twins: \[\['IV-3', 'IV-4', 'MZ'\]\]/.test(v2.el ? v2.el.innerText : document.body.innerText), 'Notebook: the analysis notebook runs without errors, and reads the sketch\'s twins');
  } catch (e) {
    out.push('FAIL  ' + (e && e.stack || e));
  }
  return out;
}
"""

LATER = r"""
async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const wait = async (fn, ms = 120000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { const v = await fn(); if (v) return v; } catch (e) {} await sleep(100); } throw new Error('timed out: ' + fn.toString().slice(0, 100)); };
  const out = [];
  const check = (ok, what) => out.push((ok ? 'ok    ' : 'FAIL  ') + what);
  try {
    // what the first visit made, the empty folders among it, was kept in the browser
    const fs = MG.app.fs;
    check(['notebooks/pedigree-tools.ipynb', 'notebooks/pedigree-analysis.ipynb', 'pedigrees', 'terms', 'results'].every((p) => fs.exists('/home/user/' + p)), 'Later visit: the starter notebooks and the home folders are still there');
    // the size of a picture, on its page in the Tools tab
    await MG.app.showWorkbench('tools');
    await wait(() => MG.app.tools, 20000);
    MG.app.tools.go({ page: 'file', path: '/data/examples/lynch.png' });
    await wait(() => document.querySelector('.tl-summary'), 20000);
    check(/1,056 × 540 pixels/.test(document.querySelector('.tl-summary').innerText), 'Tools: a picture\'s page gives its size');
    // PedNet, the archive's first download failing: said in words, and the next try loads it
    await MG.app.showWorkbench('terminal');
    const T = MG.app.term;
    const run = async (cmd) => { const n0 = T.outEl.children.length; await T.type(cmd, true); await sleep(150); await wait(() => !T.busy, 300000); return Array.from(T.outEl.children).slice(n0).map((e) => e.textContent).join('\n'); };
    let said = await run('pednet mode /data/examples/lynch.ped');
    check(/couldn’t be downloaded – check the internet connection/.test(said) && !/Failed to fetch/.test(said), 'Later visit: a failed download is said in words');
    said = await run('pednet mode /data/examples/lynch.ped');
    check(/Family FAM1: autosomal dominant/.test(said), 'Later visit: the next try loads PedNet');
    // a cell that keeps a command's output (files = !ls) and imports PedGen, and a script that imports PedInterp
    fs.writeText('/home/user/results/picture.py', 'import PedInterp\nprint("PedInterp", PedInterp.__version__)\n');
    const cell = (src) => ({ cell_type: 'code', metadata: {}, outputs: [], execution_count: null, source: src });
    fs.writeText('/home/user/notebooks/later.ipynb', JSON.stringify({ cells: [cell('files = !ls ~\nimport PedGen\nprint("PedGen", PedGen.__version__, len(files) > 0)'), cell('%run /home/user/results/picture.py')], metadata: { kernelspec: { name: 'python3', display_name: 'Python 3', language: 'python' } }, nbformat: 4, nbformat_minor: 5 }));
    await MG.app.showWorkbench('notebook');
    await MG.app.nbApp.open('/home/user/notebooks/later.ipynb');
    await sleep(500);
    const view = MG.app.nbApp.view;
    await view.runAll();
    const text = (i) => view.cells.filter((c) => c.type === 'code')[i].el.innerText;
    check(/PedGen 0\.\d/.test(text(0)) && /True/.test(text(0)) && !/Error/.test(text(0)), 'Notebook: a cell with files = !ls loads PedGen when it imports it');
    check(/PedInterp 0\.\d/.test(text(1)) && !/Error/.test(text(1)), 'Notebook: %run loads PedInterp for a script that imports it');
  } catch (e) {
    out.push('FAIL  ' + (e && e.stack || e));
  }
  return out;
}
"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    handler = functools.partial(Quiet, directory=ROOT)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(tempfile.gettempdir(), "pedwb-netcache"))
    ap.add_argument("--shots", default=None)
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    from playwright.async_api import async_playwright

    refused = []

    async def external(route):
        url = route.request.url
        host = url.split("/")[2]
        if not any(host.endswith(h) for h in ALLOW):
            refused.append(url)
            await route.abort()
            return
        key = os.path.join(a.cache, hashlib.sha1(url.encode()).hexdigest())
        if not os.path.exists(key):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (pedigree-workbench tests)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                body, ct = r.read(), r.headers.get("Content-Type", "application/octet-stream")
            with open(key, "wb") as fh:
                fh.write(body)
            with open(key + ".json", "w") as fh:
                json.dump({"ct": ct}, fh)
        with open(key, "rb") as fh:
            body = fh.read()
        with open(key + ".json") as fh:
            ct = json.load(fh)["ct"]
        await route.fulfill(status=200, body=body, headers={"Content-Type": ct, "Access-Control-Allow-Origin": "*"})

    httpd = serve()
    url = "http://127.0.0.1:%d/" % httpd.server_address[1]
    failed = 0
    async with async_playwright() as p:
        for name, kw in (("desktop", dict(viewport={"width": 1440, "height": 900})),
                         ("phone", dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True))):
            browser = await p.chromium.launch()
            ctx = await browser.new_context(**kw)
            await ctx.route(lambda u: not u.startswith(url), external)
            page = await ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(url)
            await page.wait_for_function("window.MG && MG.app && MG.app.isReady && MG.app.isReady()", timeout=60000)
            results = await asyncio.wait_for(page.evaluate(SCENARIO), timeout=900)
            if name == "desktop":
                # a later visit: the page loaded again, the first download of the second archive failing (offline)
                left = {"n": 1}

                async def flaky(route):
                    if left["n"] > 0:
                        left["n"] -= 1
                        await route.abort("internetdisconnected")
                    else:
                        await route.fallback()

                await ctx.route(lambda u: "/assets/py/pedigree-analysis.zip" in u, flaky)
                await page.reload()
                await page.wait_for_function("window.MG && MG.app && MG.app.isReady && MG.app.isReady()", timeout=60000)
                results += await asyncio.wait_for(page.evaluate(LATER), timeout=900)
                if left["n"]:
                    results.append("FAIL  the archive was never asked for, so its failed download wasn't tried")
            print("--", name)
            for line in results:
                print(line)
            for e in errors:
                print("FAIL  page error:", e[:300])
            failed += sum(1 for l in results if l.startswith("FAIL")) + len(errors)
            if a.shots:
                os.makedirs(a.shots, exist_ok=True)
                await page.screenshot(path=os.path.join(a.shots, name + ".png"))
            await browser.close()
    httpd.shutdown()
    if refused:
        print("refused (never sent):", *sorted(set(u.split("?")[0] for u in refused))[:10], sep="\n  ")
    print("%d failed" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
