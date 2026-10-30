/* =====================================================================
   The Pedigree workbench's set-up: the file system (your files, kept in
   the browser, and the read-only examples), the terminal, the notebooks,
   and the other tabs – each built the first time it is shown.
   Also: what kind of pedigree file a file is (MG.app.pedKind), opening a
   file in the right tab, and the buttons the Files tab shows for
   pedigree files (MG.app.fileActions).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, toast, store } = MG;
  const CFG = MG.config;
  MG.app = MG.app || {};
  MG.page = MG.page || {};
  MG.actions = MG.actions || {};

  const HOME = '/home/user';
  MG.app.HOME = HOME;
  MG.app.PROJECT = HOME;
  const abs = (u) => new URL(u, location.href).href;
  const EX_TIME = Date.parse('2026-10-17T09:00:00Z');

  /* the example data: the list is written into the page by build/make_page.py (window.WB_EXAMPLES) */
  const EXAMPLES = (window.WB_EXAMPLES || []).map((f) => ({ path: '/data/examples/' + f.p, url: abs('data/examples/' + f.p), size: f.s, mtime: EX_TIME }));
  MG.app.exampleFiles = EXAMPLES;
  /* the notebooks a new user finds in ~/notebooks (data/starter/*.ipynb) */
  const STARTERS = window.WB_STARTERS || [];
  /* the folders of a new user's home */
  const FOLDERS = ['pedigrees', 'results', 'terms', 'notebooks'];

  /** a notebook to start from (data/starter) → ~/notebooks; false if it couldn't be fetched (offline, or a
      connection that stalls, which mustn't hold up the page for long) */
  async function addStarter(fs, rel) {
    const stop = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = stop && setTimeout(() => stop.abort(), 15000);
    try {
      const r = await fetch(abs('data/starter/' + rel.split('/').pop()), stop ? { signal: stop.signal } : {});
      if (!r.ok) return false;
      const text = await r.text();
      fs.mkdirp(MG.path.dirname(HOME + '/' + rel));
      fs.writeText(HOME + '/' + rel, text);
      return true;
    } catch (e) {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async function setupFs() {
    const fs = new MG.VFS(HOME);
    fs.mkdirp('/data/examples');
    for (const f of EXAMPLES) {
      fs.mkdirp(MG.path.dirname(f.path));
      fs.put(f.path, { kind: 'url', url: f.url, size: f.size, protected: true, readonly: true, mtime: f.mtime });
    }
    for (const [p, e] of fs.entries) if (e.kind === 'dir' && (p === '/data' || p.startsWith('/data/'))) e.protected = true;
    await MG.project.restore(fs, [HOME]);
    fs.cwd = HOME;
    // keep every change from here on, the first visit's folders and notebooks among them
    MG.project.watch(fs);
    // the first visit: folders, and notebooks to start from (a file that is there already is left alone). A notebook
    // added to the workbench since someone's last visit is given to them once; one they have had before is never put
    // back, in case they deleted it. (Until October 2026 the notebooks weren't kept in the browser unless they were
    // changed, so anyone who came before then is given them once more.)
    const first = !store.get('seeded', false);
    const given = store.get('starters', []);
    if (first) FOLDERS.forEach((d) => fs.mkdirp(HOME + '/' + d));
    for (const s of STARTERS) {
      if (given.includes(s.p)) continue;
      if (!fs.exists(HOME + '/' + s.p) && !(await addStarter(fs, s.p))) continue;
      given.push(s.p);
    }
    store.set('starters', given);
    store.set('seeded', true);
    return fs;
  }

  MG.page.firstBench = 'studio';
  MG.page.init = async function () {
    const fs = (MG.app.fs = await setupFs());
    MG.app.term = new MG.TerminalUI(document.getElementById('termRoot'), {
      fs,
      hostname: CFG.hostname || 'pedigrees',
      env: {},
      welcome:
        `A Linux terminal (bash) in your browser, with the pedigree programs studio2ped, ped2studio, studio2ga4gh, ga4gh2studio, mpedtools, hponorm, mondonorm, phenotk, pedigree-ga4gh, pednet, pedgen and pedinterp. Your files are in ~ (${HOME}), and the examples, which can’t be changed, are in /data/examples. Type  help  to see what’s here, or  man NAME  to read about a command.` +
        (MG.user.name() === MG.user.DEFAULT ? ' To see your name in place of user, click “user” at the top of the page.' : '')
    });
    MG.app.nbApp = new MG.NotebookApp(document.getElementById('nbRoot'), { fs, dir: HOME + '/notebooks' });
    MG.project.persist();
  };

  /* ------------------------------------------------------------------
     the tabs that are built when first shown
     ------------------------------------------------------------------ */
  let nbOpened = false;
  async function openFirstNotebook() {
    if (nbOpened) return;
    nbOpened = true;
    const fs = MG.app.fs, app = MG.app.nbApp;
    const last = store.get('nbOpen', null);
    const welcome = HOME + '/notebooks/pedigree-tools.ipynb';
    const start = (last && fs.exists(last) && last) || (fs.exists(welcome) && welcome) || (app.list()[0] || {}).path;
    if (start) await app.open(start);
    else await app.newNotebook('python');
  }
  MG.page.lazy = {
    studio: (pane) => {
      MG.app.studio = new MG.StudioTab(pane.querySelector('#studioRoot'), { fs: MG.app.fs });
      return MG.app.studio.ready;
    },
    tools: (pane) => {
      MG.app.tools = new MG.ToolsTab(pane.querySelector('#toolsRoot'), { fs: MG.app.fs });
    },
    risk: (pane) => {
      MG.app.risk = new MG.RiskTab(pane.querySelector('#riskRoot'), { fs: MG.app.fs });
      return MG.app.risk.ready;
    },
    terminal: () => {},
    notebook: () => openFirstNotebook(),
    editor: (pane) => {
      MG.app.editor = new MG.Editor(pane.querySelector('#edRoot'), { fs: MG.app.fs });
    }
  };
  /* each time a tab is shown */
  MG.page.shown = {
    studio: (pane, opts) => MG.app.studio && MG.app.studio.shown(opts),
    tools: (pane, opts) => MG.app.tools && MG.app.tools.shown(opts),
    risk: (pane, opts) => MG.app.risk && !(opts && opts.resize) && MG.app.risk.shown(),
    notebook: () => MG.app.nbApp && MG.app.nbApp.shown(),
    terminal: (pane, opts) => {
      if (MG.app.term && !(opts && opts.resize) && !window.matchMedia('(max-width: 900px)').matches) MG.app.term.focus();
    },
    editor: () => MG.app.editor && MG.app.editor.shown && MG.app.editor.shown()
  };

  async function waitFor(get, ms = 4000) {
    for (let t = 0; t < ms && !get(); t += 50) await new Promise((r) => setTimeout(r, 50));
    return get();
  }
  MG.app.waitFor = waitFor;

  /* ------------------------------------------------------------------
     what kind of pedigree file a file is: by its name, and – for a JSON
     file whose name says nothing – by a look at what is in it
     ------------------------------------------------------------------ */
  const KIND_NAMES = {
    studio: 'Pedigree Studio drawing',
    pedigree: 'GA4GH Pedigree',
    family: 'Phenopackets Family',
    cohort: 'Phenopackets Cohort',
    phenopacket: 'Phenopacket',
    ped: 'PED file',
    mped: 'MPED file',
    terms: 'terms file',
    obo: 'ontology (OBO)',
    image: 'picture',
    vcf: 'VCF file',
    variants: 'table of genotypes',
    notebook: 'notebook',
    workflow: 'workflow',
    workflowrun: 'record of a workflow’s run',
    json: 'JSON file',
    other: 'file'
  };
  MG.app.kindNames = KIND_NAMES;
  function sniffJson(text) {
    const head = text.slice(0, 20000);
    // (the workflows of the Tools tab, and the records of their runs: workflows.js)
    if (/^\s*\{\s*"pedigree_workbench_workflow_run"\s*:/.test(head)) return 'workflowrun';
    if (/^\s*\{\s*"pedigree_workbench_workflow"\s*:/.test(head)) return 'workflow';
    if (/"persons"\s*:/.test(head) && /"(partnerships|childLinks)"\s*:/.test(text)) return 'studio';
    if (/"(relationships|indexPatients|index_patients)"\s*:/.test(head) || (/"individuals"\s*:/.test(head) && !/"proband"\s*:/.test(head))) return 'pedigree';
    if (/"proband"\s*:/.test(head) || (/"pedigree"\s*:/.test(head) && /"persons"\s*:/.test(head))) return 'family';
    if (/"members"\s*:/.test(head)) return 'cohort';
    if (/"subject"\s*:/.test(head) || /"phenotypicFeatures"\s*:/.test(head)) return 'phenopacket';
    if (/^\s*\{\s*"[^"]+"\s*:\s*("[A-Za-z][\w.-]*:[^"\s]+"|\{\s*"id"\s*:)/.test(head) || /"resolved"\s*:/.test(head)) return 'terms';
    return 'json';
  }
  /** a table with a column for each person's genotypes, as PedNet reads candidate variants (PedGen writes them) */
  const isGenotypeTable = (path, n) => {
    if (/(^|[\/_.-])genotypes?\.(tsv|csv)$/.test(n)) return true;
    const e = MG.app.fs && MG.app.fs.get(path);
    return !!(e && e.kind === 'text' && /^\s*variant[\t,]/i.test(e.text.slice(0, 200)));
  };
  /** → studio | pedigree | family | cohort | phenopacket | ped | mped | terms | obo | image | vcf | variants | notebook |
      workflow | workflowrun | json | other */
  MG.app.pedKind = (path) => {
    const n = path.toLowerCase();
    if (n.endsWith('.ipynb')) return 'notebook';
    if (n.endsWith('.workflow.json')) return 'workflow';
    if (/(^|\/)workflow-run\.json$/.test(n)) return 'workflowrun';
    if (/\.(png|jpe?g|gif|bmp|tiff?|webp)$/.test(n)) return 'image';
    if (/\.vcf(\.b?gz)?$/.test(n)) return 'vcf';
    if (/\.(tsv|csv|txt)$/.test(n) && isGenotypeTable(path, n)) return 'variants';
    if (n.endsWith('.studio.json')) return 'studio';
    if (/_ga4gh-pedigree\.json$|\.pedigree\.json$/.test(n)) return 'pedigree';
    if (/_phenopackets-family\.json$|\.family\.json$/.test(n)) return 'family';
    if (n.endsWith('.mped')) return 'mped';
    if (n.endsWith('.ped') || n.endsWith('.fam')) return 'ped';
    if (n.endsWith('.obo')) return 'obo';
    if (/(^|[\/_.-])terms\.json$/.test(n)) return 'terms';
    if (n.endsWith('.json') || n.endsWith('.yaml') || n.endsWith('.yml')) {
      const e = MG.app.fs && MG.app.fs.get(path);
      if (e && e.kind === 'text') return n.endsWith('.json') ? sniffJson(e.text) : 'json';
      return 'json';
    }
    return 'other';
  };
  /** the buttons the Files tab shows for a file: [icon, label, title, fn] */
  MG.app.fileActions = (path) => {
    const k = MG.app.pedKind(path);
    const tool = (id) => () => MG.app.useTool(id, { input: path });
    const risk = ['percent', 'Risks', 'The chance that each person carries the family’s variant, and that a couple’s child will be affected (Risk tab)', () => MG.app.riskOpen({ source: path })];
    const out = [];
    if (k === 'studio') {
      out.push(['pedigree', 'Open in Studio', 'Open this drawing in the Studio tab', () => MG.app.studioOpen(path)]);
      out.push(risk);
      out.push(['convert', 'Convert…', 'Make GA4GH, Phenopackets or PED files from this drawing (Tools tab)', () => MG.app.toolsFor(path)]);
    } else if (k === 'pedigree' || k === 'family') {
      out.push(['pedigree', 'Draw in Studio', 'Draw this family in Pedigree Studio (ga4gh2studio)', tool('ga4gh2studio')]);
      out.push(['badgeCheck', 'Check', 'Check this file against the GA4GH and Phenopackets standards (Tools tab)', tool('validate')]);
      out.push(risk);
      out.push(['convert', 'More…', 'Everything the Tools tab can do with this file', () => MG.app.toolsFor(path)]);
    } else if (k === 'cohort' || k === 'phenopacket') {
      out.push(['badgeCheck', 'Check', 'Check this file against the Phenopackets standard (Tools tab)', tool('validate')]);
      out.push(['convert', 'More…', 'Everything the Tools tab can do with this file', () => MG.app.toolsFor(path)]);
    } else if (k === 'ped' || k === 'mped') {
      out.push(['pedigree', 'Draw in Studio', 'Draw this PED file in Pedigree Studio (ped2studio)', tool('ped2studio')]);
      out.push(['table', 'Summary', 'See what’s in this file and whether it’s valid (mpedtools)', tool('mped-info')]);
      out.push(['network', 'Analyse', 'The family as a graph: its loops, kinship and closest affected relatives (PedNet)', tool('pednet-graph')]);
      out.push(risk);
      out.push(['convert', 'More…', 'Everything the Tools tab can do with this file', () => MG.app.toolsFor(path)]);
    } else if (k === 'image') {
      // (a PED file, as it says, whatever was ticked last: not with the marks read, as then none is written)
      out.push(['table', 'Read it into a PED file and a drawing', 'Read the pedigree in this picture, and write it as a PED file and a Pedigree Studio drawing (PedInterp)', () => MG.app.useTool('pedinterp', { input: path, marks: false })]);
    } else if (k === 'workflow') {
      out.push(['play', 'Run', 'Run this workflow (Tools tab)', () => MG.app.workflowOpen(path, 'run')]);
      out.push(['workflow', path.startsWith(HOME + '/') ? 'Edit' : 'Edit a copy', 'Open this workflow in the editor (Tools tab)', () => MG.app.workflowOpen(path, 'edit')]);
    } else if (k === 'workflowrun') {
      out.push(['workflow', 'View the run', 'What this run of a workflow did, step by step (Tools tab)', () => MG.app.workflowOpen(path, 'record')]);
    } else if (k === 'vcf' || k === 'variants') {
      out.push(['dna', 'Rank the variants', 'Rank these candidate variants by how well each co-segregates with the condition (PedNet)', () => MG.app.useTool('pednet-rank', { variants: path })]);
    } else if (k === 'terms') {
      out.push(['tag', 'Use in Match conditions to terms', 'Open the tool Match conditions to terms with this terms file', () => MG.app.useTool('terms', { terms: path })]);
    } else if (k === 'obo') {
      out.push(['tag', 'Search it in Match conditions to terms', 'Use this ontology file to match condition names (Tools tab)', () => MG.app.useTool('terms', { obo: path })]);
    }
    return out;
  };

  /* ------------------------------------------------------------------
     opening files: the right tab for each kind
     ------------------------------------------------------------------ */
  /** edit or look at a file in the Files tab */
  MG.app.editFile = async (path, opts = {}) => {
    await MG.app.showWorkbench('editor');
    const ed = await waitFor(() => MG.app.editor);
    if (ed) await ed.openFile(path, opts);
  };
  /** open a file where it belongs: a notebook in Notebook, a drawing in Studio, the rest in Files */
  MG.app.openFile = async (path, opts = {}) => {
    const p = MG.app.fs.resolve(path);
    if (!opts.edit && /\.ipynb$/i.test(p)) {
      await MG.app.showWorkbench('notebook');
      return MG.app.nbApp.open(p);
    }
    if (!opts.edit && MG.app.pedKind(p) === 'studio') return MG.app.studioOpen(p);
    if (!opts.edit && MG.app.pedKind(p) === 'workflow') return MG.app.workflowOpen(p, p.startsWith(HOME + '/') ? 'edit' : 'run');
    if (!opts.edit && MG.app.pedKind(p) === 'workflowrun') return MG.app.workflowOpen(p, 'record');
    return MG.app.editFile(p, opts);
  };
  /** show a folder or file in the Files tab */
  MG.app.revealFile = async (path) => {
    await MG.app.showWorkbench('editor');
    const ed = await waitFor(() => MG.app.editor);
    if (ed && ed.reveal) ed.reveal(MG.app.fs.resolve(path));
  };
  /** a drawing → the Studio tab (opts.tidy: lay it out afresh) */
  MG.app.studioOpen = async (path, opts = {}) => {
    await MG.app.showWorkbench('studio');
    const S = await waitFor(() => MG.app.studio, 8000);
    if (!S) throw new Error('The Studio tab couldn’t start.');
    await S.ready;
    return S.openFile(MG.app.fs.resolve(path), opts);
  };
  /** the Tools tab with a tool chosen (and its fields filled in: {input: path, …}) */
  MG.app.useTool = async (id, values) => {
    await MG.app.showWorkbench('tools');
    const T = await waitFor(() => MG.app.tools, 8000);
    if (T) T.choose(id, values || {});
  };
  /** a workflow in the Tools tab: view 'run', 'edit' (an example: a copy of it) or 'record' (a run's record), or the
      Workflows page itself (view 'list', or 'extract': a workflow from the tools run). extra.input: a file to run it
      on (its first input that takes a file of that kind) */
  MG.app.workflowOpen = async (path, view = 'edit', extra = {}) => {
    await MG.app.showWorkbench('tools');
    const T = await waitFor(() => MG.app.tools, 8000);
    if (T) T.go(Object.assign({ page: 'workflows', view, path: path ? MG.app.fs.resolve(path) : null }, extra.input ? { input: MG.app.fs.resolve(extra.input) } : {}));
  };
  /** the Tools tab, showing what can be done with a file */
  MG.app.toolsFor = async (path) => {
    await MG.app.showWorkbench('tools');
    const T = await waitFor(() => MG.app.tools, 8000);
    if (T) T.forFile(MG.app.fs.resolve(path));
  };

  /* Files edited in the Files tab are saved with Save / Ctrl+S, and a drawing in Studio with the Studio tab's Save:
     before the page is left or reloaded with unsaved edits, the browser asks (it shows its own message). */
  window.addEventListener('beforeunload', (e) => {
    const ed = MG.app.editor;
    if (ed && ed.dirtyPaths && ed.dirtyPaths().length) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  /* ------------------------------------------------------------------
     ▶ buttons of the help pages
     data-example="okafor.studio.json"   copy an example into ~/examples
     data-studio="/data/examples/x"      open a drawing in Studio
     data-tool="studio2ga4gh"            open a tool (data-input="…" fills in its input; data-hand-drawn="true"
                                         or "false" ticks Drawn by hand, or not, for Picture → PED file and drawing,
                                         and data-marks="true" or "false" ticks Read who has died, the proband
                                         and carriers, or not)
     data-new-nb / data-open-nb          a new notebook / open a notebook
     ------------------------------------------------------------------ */
  MG.actions.example = async (rel) => {
    const fs = MG.app.fs;
    const src = '/data/examples/' + rel.replace(/^\/+/, '');
    if (!fs.exists(src)) throw new Error('There is no example ' + rel);
    const dest = HOME + '/examples/' + rel.replace(/^\/+/, '');
    if (fs.isDir(src)) {
      for (const [p, e] of Array.from(fs.entries)) if (p.startsWith(src + '/') && e.kind !== 'dir') fs.copy(p, dest + p.slice(src.length));
    } else fs.copy(src, dest);
    toast(`Copied to <b>${esc(fs.pretty(dest))}</b>. This copy is yours to change.`, 'ok');
  };
  /* a file in the Files tab, as text (a drawing too, which data-open would show in the Studio) */
  MG.actions.edit = async (path) => MG.app.editFile(path.replace(/^~(?=\/|$)/, HOME));
  MG.actions.studio = async (path, btn) => MG.app.studioOpen(path.replace(/^~(?=\/|$)/, HOME), { tidy: btn && btn.dataset.tidy != null });
  MG.actions.tool = async (id, btn) => {
    const values = {};
    if (btn && btn.dataset.input) values.input = btn.dataset.input.replace(/^~(?=\/|$)/, HOME);
    if (btn && btn.dataset.input2) values.input2 = btn.dataset.input2.replace(/^~(?=\/|$)/, HOME);
    // (a terms file: for Drawing → GA4GH and Match conditions to terms, and for Fill in missing terms)
    if (btn && btn.dataset.terms) values.terms = btn.dataset.terms.replace(/^~(?=\/|$)/, HOME);
    if (btn && btn.dataset.mapping) values.mapping = btn.dataset.mapping.replace(/^~(?=\/|$)/, HOME);
    // (the variants to rank, for Rank candidate variants)
    if (btn && btn.dataset.variants) values.variants = btn.dataset.variants.replace(/^~(?=\/|$)/, HOME);
    // (a picture drawn by hand, or not, for Picture → PED file and drawing, whatever was ticked last)
    if (btn && btn.dataset.handDrawn != null) values.handDrawn = btn.dataset.handDrawn === 'true';
    // (and whether to read who has died, the proband and carriers, with the drawing to hold them)
    if (btn && btn.dataset.marks != null) {
      values.marks = btn.dataset.marks === 'true';
      if (values.marks) values.studio = true;
    }
    return MG.app.useTool(id, values);
  };
  /* data-workflow="~/workflows/x.workflow.json" (data-view="edit" or "run", the default; data-input="…" a file to run
     it on); data-workflows="list" or "extract": the Workflows page */
  MG.actions.workflow = async (path, btn) => {
    const ds = (btn && btn.dataset) || {};
    return MG.app.workflowOpen(path.replace(/^~(?=\/|$)/, HOME), ds.view || 'run', { input: ds.input ? ds.input.replace(/^~(?=\/|$)/, HOME) : null });
  };
  MG.actions.workflows = async (view) => MG.app.workflowOpen(null, view || 'list');
  MG.actions.newNb = async () => {
    await MG.app.showWorkbench('notebook');
    await MG.app.nbApp.newNotebook('python');
  };
  MG.actions.openNb = async (path) => {
    await MG.app.showWorkbench('notebook');
    const p = path.startsWith('~/') ? HOME + path.slice(1) : path;
    // (a notebook to start from that isn't there, deleted or never given: a fresh copy)
    const starter = STARTERS.find((s) => HOME + '/' + s.p === p);
    if (!MG.app.fs.exists(p) && starter) await addStarter(MG.app.fs, starter.p);
    if (!MG.app.fs.exists(p)) throw new Error(`There is no notebook ${path} (was it renamed or deleted?)`);
    await MG.app.nbApp.open(p);
  };

  /* Start afresh: forget the open notebooks and the drawing first */
  MG.page.beforeReset = async () => {
    store.remove('nbOpen');
    store.remove('seeded');
    store.remove('starters');
    store.remove('termHistory');
    store.remove('studioFile');
    try {
      localStorage.removeItem('pedwb:studio-session');
    } catch (e) {
      /* the browser keeps nothing */
    }
  };
  // (h is used by the tabs built here)
  void h;
})();
