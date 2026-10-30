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
    // the Studio offers to be installed only on its own website: here it names no manifest and starts no worker
    const studioDoc = document.querySelector('iframe.st-frame').contentDocument;
    const workers = navigator.serviceWorker ? await navigator.serviceWorker.getRegistrations() : [];
    check(!studioDoc.querySelector('link[rel=manifest]') && workers.length === 0,
      'Studio: the copy here offers no install and starts no service worker');
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
    check(res.querySelector('.tl-done.ok') && (await ped('/home/user/results/lynch.ped')) === (await ped('/data/examples/lynch.ped')) && /read enlarged 5\.6 times/.test(res.innerText) && MG.app.fs.exists('/home/user/results/lynch.studio.json'), 'Tools: Picture → PED file and drawing reads the Lynch picture as lynch.ped, enlarged as its symbols need, and makes its drawing');
    // the Okafor family sketched by hand, from the help's button that reads the marks too, and ticks Drawn by hand and
    // the drawing: who has died and the proband, in the drawing and the table, and no PED file, which can't hold them
    MG.app.showHelp('h-tool-pedinterp');
    await sleep(200);
    document.querySelector('#h-tool-pedinterp button[data-input="/data/examples/okafor-sketch.png"][data-marks="true"]').click();
    await wait(() => document.querySelector('.tl-title') && /Picture/.test(document.querySelector('.tl-title').textContent), 20000);
    await sleep(400);
    document.querySelector('.tl-run').click();
    await wait(() => document.querySelector('.tl-done'), 300000);
    res = document.querySelector('.tl-result');
    const marked = MG.app.fs.exists('/home/user/results/okafor-sketch.studio.json') ? JSON.parse(await MG.app.fs.readText('/home/user/results/okafor-sketch.studio.json')) : { persons: [] };
    const table = res.querySelector('.tl-main-out') ? res.querySelector('.tl-main-out').innerText : '';
    check(res.querySelector('.tl-done.ok') && !MG.app.fs.exists('/home/user/results/okafor-sketch.ped') && /Deceased\s+Proband\s+Carrier/.test(table) && /IV-3\s+III-2\s+III-3\s+1\s+2\s+False\s+True\s+False/.test(table) && marked.persons.filter((p) => p.deceased).length === 5 && marked.persons.filter((p) => p.proband).length === 1, 'Tools: Picture → PED file and drawing reads who has died and the proband in the Okafor sketch, from the help, into the drawing and the table, and writes no PED file');
    // the same sketch, from the help's button that reads its structure and fills only, as before
    MG.app.showHelp('h-tool-pedinterp');
    await sleep(200);
    document.querySelector('#h-tool-pedinterp button[data-input="/data/examples/okafor-sketch.png"][data-marks="false"]').click();
    await wait(() => document.querySelector('.tl-title') && /Picture/.test(document.querySelector('.tl-title').textContent), 20000);
    await sleep(400);
    document.querySelector('.tl-run').click();
    // (it asks before it replaces the drawing made with the marks, and only that: there was no PED file)
    await wait(() => document.querySelector('.modal .prompt-actions [data-x="yes"]'), 20000);
    const asked = document.querySelector('.modal').innerText;
    check(/Replace these files/.test(asked) && /okafor-sketch\.studio\.json/.test(asked) && !/okafor-sketch\.ped/.test(asked), 'Tools: reading the sketch again asks before it replaces the drawing made with the marks');
    document.querySelector('.modal .prompt-actions [data-x="yes"]').click();
    await wait(() => document.querySelector('.tl-done'), 300000);
    res = document.querySelector('.tl-result');
    const sketched = MG.app.fs.exists('/home/user/results/okafor-sketch.ped') ? (await ped('/home/user/results/okafor-sketch.ped')).split('\n') : [];
    // (what is printed is the PED file's table, and nothing more: the twins are in the drawing)
    const printed = res.querySelector('.tl-main-out') ? res.querySelector('.tl-main-out').innerText : '';
    check(res.querySelector('.tl-done.ok') && /IV-5/.test(printed) && !/twin|identical/i.test(printed) && sketched.length === 16 && sketched.filter((l) => / 2$/.test(l)).length === 3, 'Tools: Picture → PED file and drawing reads the Okafor family sketched by hand, from the help, and prints just the PED file\'s table');
    const drawn = MG.app.fs.exists('/home/user/results/okafor-sketch.studio.json') ? JSON.parse(await MG.app.fs.readText('/home/user/results/okafor-sketch.studio.json')) : { persons: [], twinLinks: [] };
    check(drawn.persons.length === 16 && drawn.twinLinks.length === 1 && drawn.twinLinks[0].type === 'identical', 'Tools: Picture → PED file and drawing makes a drawing of the sketch, with its identical twins');
    // the drawing, from the next step, in the Studio tab (going on without saving any changes to the drawing there)
    Array.from(res.querySelectorAll('.tl-next button')).find((b) => /Open the drawing/.test(b.textContent)).click();
    await wait(() => MG.app.studio && MG.app.studio.path === '/home/user/results/okafor-sketch.studio.json' || document.querySelector('.prompt-actions [data-x="yes"]'), 60000);
    if (document.querySelector('.prompt-actions [data-x="yes"]')) document.querySelector('.prompt-actions [data-x="yes"]').click();
    await wait(() => MG.app.studio && MG.app.studio.path === '/home/user/results/okafor-sketch.studio.json', 60000);
    const shown = MG.app.studio.api.data();
    check(shown.persons.length === 16 && shown.twinLinks.length === 1 && shown.twinLinks[0].type === 'identical' && Object.values(shown.legendLabels || {}).includes('Affected'), 'Studio: the drawing opens from the next step, with its people, its identical twins and its colour key');
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
    // Workflows (the Tools tab): the page, from the button beside All tools; an example run step by step into a folder of
    // its own, and its commands run again in the terminal; a workflow drawn in the editor – connected by dragging from a
    // file to an input, and from the side column – and run; and a workflow made from the tools run above
    const WF = MG.workflowEngine;
    await MG.app.showWorkbench('tools');
    document.querySelector('.tl-wfbtn').click();
    await wait(() => document.querySelectorAll('.wf-cards .wf-card').length >= 4, 20000);
    check(document.querySelector('.tl-wfbtn.on') && /Share a drawing in the GA4GH standard/.test(document.querySelector('.tl-main').innerText), 'Workflows: the button beside All tools shows the workflows, with the examples');
    await MG.app.workflowOpen('/data/examples/workflows/sketch-to-drawing.workflow.json', 'run');
    await wait(() => document.querySelector('.tl-form .tl-run'), 20000);
    await sleep(300);
    document.querySelector('.tl-form .tl-run').click();
    await wait(() => document.querySelector('.wf-result .tl-next'), 300000);
    const wfDir = '/home/user/results/from-a-sketch-to-a-drawing-and-its-mode-of-inheritance/okafor-sketch';
    const wfSteps = Array.from(document.querySelectorAll('.wf-result .wf-step'));
    check(wfSteps.length === 3 && wfSteps.every((li) => li.classList.contains('ok')) && ['okafor-sketch.ped', 'okafor-sketch.studio.json', 'okafor-sketch_ga4gh-pedigree.json', 'workflow-run.json', 'commands.sh'].every((f) => MG.app.fs.exists(wfDir + '/' + f)), 'Workflows: an example runs, every step done, its files, record and commands in a folder of its own');
    check(/Valid: a correct GA4GH Pedigree/.test(document.querySelector('.wf-result').innerText), 'Workflows: the run says what its check found');
    Array.from(document.querySelectorAll('.wf-result .tl-next button')).find((b) => /notebook/.test(b.textContent)).click();
    await wait(() => MG.app.nbApp && MG.app.nbApp.view && /from-a-sketch/.test(MG.app.nbApp.view.path || ''), 30000);
    check(MG.app.fs.exists(MG.app.nbApp.view.path) && /pedigree_processing/.test(await MG.app.fs.readText(MG.app.nbApp.view.path)), 'Workflows: the run’s steps open as a notebook of Python');
    await MG.app.showWorkbench('terminal');
    said = await run(`rm ${wfDir}/okafor-sketch.ped && bash ${wfDir}/commands.sh > /dev/null; ls ${wfDir}`);
    check(/okafor-sketch\.ped/.test(said) && !/not found/.test(said), 'Workflows: the run’s commands.sh runs again in the terminal');
    // a workflow drawn in the editor
    await MG.app.workflowOpen(null, 'list');
    await wait(() => document.querySelector('.wf-actions .btn.primary'), 20000);
    document.querySelector('.wf-actions .btn.primary').click();
    await wait(() => document.querySelector('.wf-ed .wf-canvas') && MG.app.tools.wf.ed, 20000);
    const ui = MG.app.tools.wf;
    const drawingIn = ui.addInputHere();
    const toPed = ui.addStepHere(MG.toolsKit.TOOL.studio2ped);
    ui.select(null);
    const summary = ui.addStepHere(MG.toolsKit.TOOL['mped-info']);
    ui.select(null);
    const modeStep = ui.addStepHere(MG.toolsKit.TOOL['pednet-mode']);
    // (the boxes where the wire can be drawn on a phone too: one under the other)
    Object.assign(toPed, { x: 16, y: 150 });
    Object.assign(summary, { x: 16, y: 330 });
    ui.draw();
    ui.ed.wrap.scrollTo(0, 0);
    await sleep(300);
    check(WF.connsOf(toPed, 'input').length === 1 && WF.connsOf(toPed, 'input')[0].step === drawingIn.id, 'Workflows: a step added after the drawing reads it');
    const dotOut = document.querySelector(`.gx-port.out[data-step="${toPed.id}"] .dot`);
    const dotIn = document.querySelector(`.gx-port.in[data-step="${summary.id}"] .dot`);
    const ra = dotOut.getBoundingClientRect(), rb = dotIn.getBoundingClientRect();
    dotOut.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: ra.x + ra.width / 2, clientY: ra.y + ra.height / 2, pointerId: 1 }));
    window.dispatchEvent(new PointerEvent('pointermove', { clientX: rb.x + rb.width / 2, clientY: rb.y + rb.height / 2, pointerId: 1 }));
    window.dispatchEvent(new PointerEvent('pointerup', { clientX: rb.x + rb.width / 2, clientY: rb.y + rb.height / 2, pointerId: 1 }));
    await sleep(400);
    check(WF.connsOf(WF.stepOf(ui.ed.w, summary.id), 'input').length === 1 && document.querySelectorAll('.wf-canvas path.gx-wire').length === 2, 'Workflows: in the editor, dragging from a file to an input connects them, with a wire');
    ui.select(modeStep.id);
    await sleep(200);
    const src = document.querySelector('.wf-side .wf-source select');
    src.value = Array.from(src.options).find((o) => /PED or MPED file/.test(o.textContent)).value;
    src.dispatchEvent(new Event('change'));
    await sleep(300);
    check(WF.connsOf(WF.stepOf(ui.ed.w, modeStep.id), 'input').length === 1 && !WF.problems(ui.ed.w).length && /Ready to run/.test((ui.select(null), document.querySelector('.wf-side').innerText)), 'Workflows: … and from the side column, after which it is ready to run');
    const nameBox = document.querySelector('.wf-name');
    nameBox.value = 'Drawing to PED and its mode';
    nameBox.dispatchEvent(new Event('input'));
    nameBox.dispatchEvent(new Event('change'));
    await sleep(500);
    const drawnPath = ui.ed.path;
    check(/\/home\/user\/workflows\/drawing-to-ped-and-its-mode\.workflow\.json$/.test(drawnPath) && MG.app.fs.exists(drawnPath) && /pednet-mode/.test(await MG.app.fs.readText(drawnPath)), 'Workflows: it is saved as you go, in ~/workflows, named after it');
    await MG.app.workflowOpen(drawnPath, 'run');
    await wait(() => document.querySelector('.tl-form .tl-run'), 20000);
    const pick = document.querySelector('.tl-form select.tl-file');
    pick.value = '/data/examples/okafor.studio.json';
    pick.dispatchEvent(new Event('change'));
    await sleep(200);
    document.querySelector('.tl-form .tl-run').click();
    await wait(() => document.querySelector('.wf-result .tl-next'), 300000);
    const drawnSteps = Array.from(document.querySelectorAll('.wf-result .wf-step'));
    check(drawnSteps.length === 3 && drawnSteps.every((li) => li.classList.contains('ok')) && MG.app.fs.exists('/home/user/results/drawing-to-ped-and-its-mode/okafor/okafor.mped'), 'Workflows: the workflow drawn runs, every step done (' + drawnSteps.map((li) => li.className).join(', ') + ')');
    // a workflow from the tools run above: the simulated family, and the ranking of its variant
    await MG.app.workflowOpen(null, 'extract');
    await wait(() => document.querySelector('.wf-log'), 20000);
    const logRows = Array.from(document.querySelectorAll('.wf-log tr')).slice(1);
    logRows.forEach((tr) => (tr.querySelector('input').checked = false));
    ['Simulate a family', 'Rank candidate variants'].forEach((name) => logRows.filter((tr) => tr.textContent.includes(name)).pop().querySelector('input').checked = true);
    document.querySelector('.wf-extract .btn.primary').click();
    await wait(() => document.querySelector('.wf-ed .wf-canvas .gx-node') && MG.app.tools.wf.ed, 20000);
    const madeW = MG.app.tools.wf.ed.w;
    const rankStep = madeW.steps.find((s) => s.tool === 'pednet-rank');
    check(madeW.steps.length === 2 && rankStep && WF.connsOf(rankStep, 'input').length === 1 && WF.connsOf(rankStep, 'variants').length === 1 && !WF.problems(madeW).length, 'Workflows: one made from the tools run connects them by the files one wrote and the other read');
    // the notebook that walks through them
    await MG.app.showWorkbench('notebook');
    await MG.app.nbApp.open('/home/user/notebooks/pedigree-analysis.ipynb');
    await sleep(500);
    const v2 = MG.app.nbApp.view;
    await v2.runAll();
    const errs2 = v2.cells.filter((c) => c.type === 'code' && /Traceback|Error|couldn’t/.test(c.el.innerText)).length;
    check(errs2 === 0 && /the same as lynch.ped: True/.test(v2.el ? v2.el.innerText : document.body.innerText) && /16 people; the twins are identical/.test(v2.el ? v2.el.innerText : document.body.innerText), 'Notebook: the analysis notebook runs without errors, and draws the sketch with its twins');
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
