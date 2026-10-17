#!/usr/bin/env python3
"""Open the workbench in headless Chromium and do what a first session does: open an example in the Studio, convert
it in the Tools tab, check the result, run commands in the terminal, run the welcome notebook, and use the help.

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
