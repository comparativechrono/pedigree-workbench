/* =====================================================================
   The workbench page: the tabs on the right (built the first time they
   are shown), the help on the left (topics, search, links between
   pages), hiding the help and full screen, the ▶ buttons of the help
   pages, the "My files" menu, the storage indicator, and the button with
   the person's name (their name in place of "user" in the terminal).

   The tabs themselves are made by page-wb.js (MG.page.lazy).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, bus, toast, store, $, $$ } = MG;
  MG.app = MG.app || {};
  MG.page = MG.page || {};
  MG.actions = MG.actions || {};

  const narrow = () => window.matchMedia('(max-width: 900px)').matches;
  let ready = false;

  /* ------------------------------------------------------------------
     the tabs of the workbench
     ------------------------------------------------------------------ */
  const TAB_HELP = { studio: 'h-studio', tools: 'h-tools', editor: 'h-files', notebook: 'h-notebook', terminal: 'h-terminal' };
  const TAB_NAME = { studio: 'Studio', tools: 'Tools', editor: 'Files', notebook: 'Notebook', terminal: 'Terminal' };
  MG.app.tabHelp = TAB_HELP;
  MG.app.tabName = TAB_NAME;

  function initTabs() {
    const tabs = $$('.wb-tab[data-wb]');
    const panes = $$('.wb-pane');
    const built = new Set();
    const building = new Map();
    /** show a tab; the first time, build it. → a promise that resolves when it is built */
    MG.app.showWorkbench = (name, opts = {}) => {
      const pane = panes.find((p) => p.dataset.wb === name);
      if (!pane) return Promise.resolve();
      tabs.forEach((t) => {
        const on = t.dataset.wb === name;
        t.classList.toggle('on', on);
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        if (on) t.classList.remove('attn');
      });
      panes.forEach((p) => (p.hidden = p !== pane));
      const prev = MG.app.currentBench;
      if (prev && prev !== name) MG.app.prevBench = prev; // (the AI assistant asks where the user came from)
      MG.app.currentBench = name;
      if (narrow() && !opts.keepHelp) document.body.classList.remove('help-open');
      let p = Promise.resolve();
      if (!built.has(name) && MG.page.lazy && MG.page.lazy[name]) {
        built.add(name);
        p = Promise.resolve()
          .then(() => MG.page.lazy[name](pane))
          .catch((e) => {
            console.error(e);
            pane.firstElementChild.innerHTML = `<div class="wb-failed"><h3>${esc(TAB_NAME[name] || name)} couldn’t start</h3><p>${esc(e.message || String(e))}</p><p>Reload the page to try again.</p></div>`;
          });
        building.set(name, p);
      } else if (building.has(name)) p = building.get(name);
      p.then(() => {
        if (MG.app.currentBench !== name) return;
        const hook = MG.page.shown && MG.page.shown[name];
        if (hook) setTimeout(() => hook(pane, opts), 20);
      });
      updateTabHelp(name);
      if (prev !== name) {
        store.set('bench', name);
        bus.emit('app:bench', { name });
      }
      return p;
    };
    MG.app.tabBuilt = (name) => built.has(name);
    tabs.forEach((t) => t.addEventListener('click', () => MG.app.showWorkbench(t.dataset.wb)));
    // arrow keys move along the tabs (as in other tab lists)
    const list = $('.wb-tabs');
    list.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      const t = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      t.focus();
      MG.app.showWorkbench(t.dataset.wb);
    });
  }

  /* ------------------------------------------------------------------
     the help pane: show and hide, resize, full screen
     ------------------------------------------------------------------ */
  function setHelpOpen(open, opts = {}) {
    if (narrow()) {
      document.body.classList.toggle('help-open', open);
    } else {
      document.body.classList.toggle('help-off', !open);
      if (!opts.noSave) store.set('helpOff', !open);
    }
    const t = $('#helpToggle');
    if (t) {
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
      t.title = open ? 'Hide the help so the workbench fills the window (Ctrl+\\)' : 'Show the help (Ctrl+\\)';
      t.innerHTML = MG.icon(open ? 'sidebarClose' : 'sidebarOpen');
    }
    const rail = $('#helpRail');
    if (rail) rail.hidden = open || narrow();
    resized();
    if (open && opts.focus) setTimeout(() => $('#helpSearch') && $('#helpSearch').focus(), 50);
    bus.emit('app:help', { open });
  }
  const helpOpen = () => (narrow() ? document.body.classList.contains('help-open') : !document.body.classList.contains('help-off'));
  MG.app.toggleHelp = (open) => setHelpOpen(open == null ? !helpOpen() : !!open);

  /** after the bench changed size: the 3D viewer, the genome browser and the editors measure themselves again */
  const resized = MG.debounce(() => {
    window.dispatchEvent(new Event('resize'));
    const hook = MG.page.shown && MG.page.shown[MG.app.currentBench];
    if (hook) hook($(`.wb-pane[data-wb="${MG.app.currentBench}"]`), { resize: true });
  }, 60);

  function initHelpPane() {
    $('#helpToggle').addEventListener('click', () => MG.app.toggleHelp());
    $('#helpCollapse').addEventListener('click', () => setHelpOpen(false));
    $('#helpRail').addEventListener('click', () => setHelpOpen(true, { focus: false }));
    const scrim = h('div.help-scrim', { 'aria-hidden': 'true' });
    scrim.addEventListener('click', () => setHelpOpen(false));
    document.body.appendChild(scrim);
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === '\\' || e.code === 'Backslash')) {
        e.preventDefault();
        MG.app.toggleHelp();
      } else if (e.key === 'Escape' && narrow() && document.body.classList.contains('help-open') && !document.querySelector('.modal-back')) {
        setHelpOpen(false);
      }
    });
    // start as the user left it (wide screens); on a phone the workbench comes first
    if (narrow()) setHelpOpen(false, { noSave: true });
    else setHelpOpen(!store.get('helpOff', false), { noSave: true });
    let wasNarrow = narrow();
    window.addEventListener('resize', () => {
      if (narrow() === wasNarrow) return;
      wasNarrow = narrow();
      document.body.classList.remove('help-open');
      setHelpOpen(wasNarrow ? false : !store.get('helpOff', false), { noSave: true });
    });

    // full screen: the browser's full screen, with the help hidden (and shown again afterwards)
    const full = $('#fullBtn');
    let helpBefore = null;
    const label = () => {
      const on = !!document.fullscreenElement;
      full.innerHTML = MG.icon(on ? 'shrink' : 'expand') + `<span>${on ? 'Exit full screen' : 'Full screen'}</span>`;
      full.title = on ? 'Leave full screen (Esc)' : 'Make the workbench fill the whole screen';
    };
    if (!document.documentElement.requestFullscreen) full.hidden = true;
    full.addEventListener('click', async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else {
          helpBefore = helpOpen();
          setHelpOpen(false, { noSave: true });
          await document.documentElement.requestFullscreen();
        }
      } catch (e) {
        toast('This browser didn’t allow full screen here. Press F11 (or ⌃⌘F on a Mac) instead.', 'warn');
        if (helpBefore != null) setHelpOpen(helpBefore, { noSave: true });
        helpBefore = null;
      }
    });
    document.addEventListener('fullscreenchange', () => {
      label();
      if (!document.fullscreenElement && helpBefore != null) {
        setHelpOpen(helpBefore, { noSave: true });
        helpBefore = null;
      }
      resized();
    });
    label();
  }

  function initSplitter() {
    const sp = $('.splitter');
    const saved = store.get('helpWidth', null);
    if (saved) document.documentElement.style.setProperty('--tut-w', saved);
    if (!sp) return;
    let drag = false;
    sp.addEventListener('pointerdown', (e) => {
      drag = true;
      sp.classList.add('drag');
      sp.setPointerCapture(e.pointerId);
      document.body.classList.add('dragging');
    });
    sp.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const w = MG.clamp((e.clientX / window.innerWidth) * 100, 18, 60);
      document.documentElement.style.setProperty('--tut-w', w.toFixed(1) + '%');
    });
    const end = () => {
      if (!drag) return;
      drag = false;
      sp.classList.remove('drag');
      document.body.classList.remove('dragging');
      store.set('helpWidth', getComputedStyle(document.documentElement).getPropertyValue('--tut-w').trim());
      resized();
    };
    sp.addEventListener('pointerup', end);
    sp.addEventListener('pointercancel', end);
    sp.addEventListener('dblclick', () => {
      document.documentElement.style.removeProperty('--tut-w');
      store.remove('helpWidth');
      resized();
    });
    // keyboard: the splitter can be moved with the arrow keys
    sp.tabIndex = 0;
    sp.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const cur = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--tut-w')) || 34;
      const w = MG.clamp(cur + (e.key === 'ArrowRight' ? 2 : -2), 18, 60);
      document.documentElement.style.setProperty('--tut-w', w + '%');
      store.set('helpWidth', w + '%');
      resized();
    });
  }

  /* ------------------------------------------------------------------
     help pages: topics, search, links
     ------------------------------------------------------------------ */
  let pages = [];
  let current = null;
  const backStack = [];

  function initHelp() {
    pages = $$('.help-page');
    const body = $('#helpBody');
    // links between help pages: <a href="#h-…">
    body.addEventListener('click', (e) => {
      const a = e.target.closest('a[href^="#h-"]');
      if (!a) return;
      e.preventDefault();
      const [id, anchor] = a.getAttribute('href').slice(1).split('/');
      showHelp(id, { anchor, push: true });
    });
    // code boxes get Copy (and Run / Insert) buttons
    body.querySelectorAll('pre.code').forEach(decorateCode);
    // search
    const input = $('#helpSearch');
    const results = h('div.help-results', { hidden: true, role: 'listbox', 'aria-label': 'Search results' });
    body.parentNode.insertBefore(results, body);
    input.addEventListener('input', MG.debounce(() => search(input.value, results), 120));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const first = results.querySelector('button');
        if (first) first.click();
      } else if (e.key === 'Escape') {
        input.value = '';
        search('', results);
      } else if (e.key === 'ArrowDown') {
        const first = results.querySelector('button');
        if (first) {
          e.preventDefault();
          first.focus();
        }
      }
    });
    results.addEventListener('keydown', (e) => {
      const bs = $$('button', results);
      const i = bs.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' && i < bs.length - 1) (e.preventDefault(), bs[i + 1].focus());
      else if (e.key === 'ArrowUp') (e.preventDefault(), i > 0 ? bs[i - 1].focus() : input.focus());
    });
    MG.app.showHelp = (id, opts) => {
      input.value = '';
      search('', results);
      showHelp(id, Object.assign({ push: true }, opts || {}));
      if (!helpOpen()) setHelpOpen(true);
    };
    // where to start: a link such as …/#h-samtools, else where the user was last time
    const fromHash = decodeURIComponent(location.hash.replace(/^#/, ''));
    const first = (fromHash && document.getElementById(fromHash.split('/')[0]) && fromHash) || store.get('helpPage', 'h-home');
    const [id, anchor] = first.split('/');
    showHelp(document.getElementById(id) ? id : 'h-home', { anchor });
    window.addEventListener('hashchange', () => {
      const x = decodeURIComponent(location.hash.replace(/^#/, ''));
      if (/^h-/.test(x)) MG.app.showHelp(x.split('/')[0], { anchor: x.split('/')[1], push: false });
    });
  }

  function showHelp(id, opts = {}) {
    const page = document.getElementById(id);
    if (!page || !page.classList.contains('help-page')) return;
    if (opts.push && current && current.id !== id) backStack.push(current.id);
    pages.forEach((p) => (p.hidden = p !== page));
    current = page;
    store.set('helpPage', id);
    // breadcrumbs: Help › group › page
    const crumbs = $('#helpCrumbs');
    crumbs.innerHTML = '';
    const home = h('a', { href: '#h-home' }, 'Help');
    crumbs.appendChild(home);
    // (the index page of a group – Recipes, Reference – is the group: no link to itself)
    if (page.dataset.group && id !== 'h-home' && !(id === page.dataset.groupPage && page.dataset.title === page.dataset.group)) {
      const g = page.dataset.groupPage;
      crumbs.append(h('span.sep', '›'), g ? h('a', { href: '#' + g }, page.dataset.group) : h('span', page.dataset.group));
    }
    if (id !== 'h-home') crumbs.append(h('span.sep', '›'), h('b', page.dataset.title || ''));
    if (backStack.length) {
      const back = h('button.linkbtn.help-back', { type: 'button', title: 'Back to the page you were reading' }, '← Back');
      back.addEventListener('click', () => {
        const prev = backStack.pop();
        if (prev) showHelp(prev, {});
      });
      crumbs.prepend(back);
    }
    crumbs.querySelectorAll('a').forEach((a) =>
      a.addEventListener('click', (e) => {
        e.preventDefault();
        showHelp(a.getAttribute('href').slice(1), { push: true });
      })
    );
    updateTabHelp(MG.app.currentBench);
    const scroller = $('#helpPane');
    if (opts.anchor) {
      const el = document.getElementById(opts.anchor) || page.querySelector(`[data-anchor="${opts.anchor}"]`);
      if (el) {
        setTimeout(() => {
          el.scrollIntoView({ block: 'start' });
          el.classList.add('flash-attn');
          setTimeout(() => el.classList.remove('flash-attn'), 1400);
        }, 30);
      } else scroller.scrollTop = 0;
    } else scroller.scrollTop = 0;
    bus.emit('help:page', { id });
  }

  /** the "help for this tab" link under the search box */
  function updateTabHelp(name) {
    const crumbs = $('#helpCrumbs');
    if (!crumbs) return;
    let link = $('.help-tablink', crumbs.parentNode);
    const target = TAB_HELP[name];
    if (!link) {
      link = h('button.help-tablink', { type: 'button' });
      link.addEventListener('click', () => MG.app.showHelp(link.dataset.target));
      crumbs.parentNode.insertBefore(link, crumbs.nextSibling);
    }
    const show = target && current && current.id !== target && document.getElementById(target);
    link.hidden = !show;
    if (show) {
      link.dataset.target = target;
      link.innerHTML = MG.icon('help') + `<span>Help for the <b>${esc(TAB_NAME[name])}</b> tab</span>`;
    }
  }

  /* search: titles and keywords count most, then headings, then the text */
  let index = null;
  function buildIndex() {
    index = pages
      .filter((p) => p.id !== 'h-home')
      .map((p) => ({
        id: p.id,
        title: p.dataset.title || '',
        group: p.dataset.group || '',
        keys: (p.dataset.keys || '').toLowerCase(),
        heads: $$('h2, h3, [data-anchor]', p).map((x) => ({ id: x.id || x.dataset.anchor || '', text: x.textContent.trim() })),
        text: p.textContent.replace(/\s+/g, ' ').toLowerCase()
      }));
  }
  function search(q, results) {
    q = q.trim().toLowerCase();
    const body = $('#helpBody');
    if (!q) {
      results.hidden = true;
      results.innerHTML = '';
      body.hidden = false;
      return;
    }
    if (!index) buildIndex();
    const words = q.split(/\s+/).filter(Boolean);
    const hits = [];
    for (const p of index) {
      let score = 0;
      let anchor = null;
      for (const w of words) {
        let s = 0;
        const tl = p.title.toLowerCase();
        if (tl === w) s += 30;
        else if (tl.split(/[\s/,()]+/).includes(w)) s += 16;
        else if (tl.includes(w)) s += 10;
        if (p.keys.split(/[\s,]+/).includes(w)) s += 12;
        else if (p.keys.includes(w)) s += 6;
        const head = p.heads.find((x) => x.text.toLowerCase().includes(w));
        if (head) {
          s += 5;
          if (!anchor && head.id) anchor = head;
        }
        const n = p.text.split(w).length - 1;
        if (n) s += Math.min(6, 1 + Math.log2(n));
        if (!s) {
          score = 0;
          break;
        }
        score += s;
      }
      if (score) hits.push({ p, score, anchor });
    }
    hits.sort((a, b) => b.score - a.score);
    results.innerHTML = '';
    body.hidden = true;
    results.hidden = false;
    if (!hits.length) {
      results.appendChild(h('div.help-noresult', h('p', `Nothing in the help mentions “${q}”.`), h('p.muted', 'Try a shorter word, or the name of a program or a format, such as studio2ped, phenotk, PED or GA4GH.')));
      return;
    }
    hits.slice(0, 30).forEach((x) => {
      const snip = snippet(x.p.text, words[0]);
      const b = h(
        'button.help-hit',
        { type: 'button', role: 'option' },
        h('span.hh-t', x.p.title),
        h('span.hh-g', x.anchor ? `${x.p.group} › ${x.anchor.text}` : x.p.group),
        snip ? h('span.hh-s', { html: snip }) : null
      );
      b.addEventListener('click', () => {
        const input = $('#helpSearch');
        input.value = '';
        search('', results);
        showHelp(x.p.id, { anchor: x.anchor && x.anchor.id, push: true });
      });
      results.appendChild(b);
    });
  }
  function snippet(text, w) {
    const i = text.indexOf(w);
    if (i < 0) return '';
    const a = Math.max(0, i - 50), b = Math.min(text.length, i + w.length + 70);
    return (a ? '…' : '') + esc(text.slice(a, i)) + '<mark>' + esc(text.slice(i, i + w.length)) + '</mark>' + esc(text.slice(i + w.length, b)) + (b < text.length ? '…' : '');
  }

  /* code boxes in the help: Copy, and – for terminal and Python code – a button that uses it */
  function decorateCode(pre) {
    const kind = pre.dataset.run || ''; // term | py
    const bar = h('div.code-bar');
    const code = () => pre.querySelector('code') ? pre.querySelector('code').textContent : pre.textContent;
    const copy = h('button.code-btn', { type: 'button', title: 'Copy to the clipboard', html: MG.icon('copy') + '<span>Copy</span>' });
    copy.addEventListener('click', async () => {
      const ok = await MG.copyText(code().replace(/\n$/, ''));
      copy.querySelector('span').textContent = ok ? 'Copied' : 'Copy failed';
      setTimeout(() => (copy.querySelector('span').textContent = 'Copy'), 1500);
    });
    if (kind === 'term') {
      const run = h('button.code-btn', { type: 'button', title: 'Type these commands in the Terminal and run them', html: MG.icon('terminal') + '<span>Run in the terminal</span>' });
      run.addEventListener('click', () => runInTerminal(code()));
      bar.appendChild(run);
    } else if (kind === 'py') {
      const ins = h('button.code-btn', { type: 'button', title: 'Add this code to the open notebook as a new cell', html: MG.icon('notebook') + '<span>Add to notebook</span>' });
      ins.addEventListener('click', () => toNotebook(code(), 'python', false));
      bar.appendChild(ins);
    }
    bar.appendChild(copy);
    pre.parentNode.insertBefore(h('div.code-box', bar), pre);
    pre.previousSibling.appendChild(pre);
  }
  MG.app.decorateCode = decorateCode;

  /* ------------------------------------------------------------------
     the ▶ buttons: data-term, data-term-run, data-nb, data-nb-run, data-bench,
     data-goto, data-open + MG.actions (data-studio, data-tool, data-example … in page-wb.js)
     ------------------------------------------------------------------ */
  async function runInTerminal(text, run = true) {
    await MG.app.showWorkbench('terminal');
    const T = MG.app.term;
    if (!T) return;
    // the commands one by one: lines that belong together (a loop, an if … fi, a here-document, a line that
    // ends in \ or |) are one command. Typed without running: only the first (the prompt has one line).
    const SL = MG.shellLang;
    const cmds = [];
    let acc = null;
    for (const line of text.replace(/\r/g, '').replace(/\n+$/, '').split('\n')) {
      if (acc == null && (!line.trim() || /^\s*#/.test(line))) continue;
      acc = acc == null ? line : acc + '\n' + line;
      let more = false;
      try {
        more = !!(SL && SL.incomplete && SL.incomplete(acc));
      } catch (e) {
        more = false;
      }
      if (!more) {
        cmds.push(acc);
        acc = null;
      }
    }
    if (acc != null) cmds.push(acc);
    for (const c of cmds) {
      if (T.busy)
        await new Promise((r) => {
          const t = setInterval(() => {
            if (!T.busy) {
              clearInterval(t);
              r();
            }
          }, 120);
        });
      if (!run && c.includes('\n')) {
        toast('This command has several lines, so use Run instead of typing it.', 'warn');
        return;
      }
      await T.type(c, run);
      if (!run) return;
    }
  }
  MG.app.runInTerminal = runInTerminal;

  async function toNotebook(code, lang, run) {
    await MG.app.showWorkbench('notebook');
    const app = MG.app.nbApp;
    if (!app) return;
    await app.insertCode(code, { lang, run });
  }
  MG.app.toNotebook = toNotebook;

  function initActions() {
    const keys = () => ['term', 'termRun', 'nb', 'nbRun', 'bench', 'goto', 'open'].concat(Object.keys(MG.actions));
    document.addEventListener('click', async (e) => {
      const sel = keys()
        .map((k) => '[data-' + k.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase()) + ']')
        .map((a) => `button${a},a${a},[role="button"]${a}`)
        .join(',');
      const b = e.target.closest(sel);
      if (!b || b.closest('.wb-tabs')) return;
      // only the help, dialogs and the workbench's own panels use these
      if (!b.closest('.help-pane, .modal, .bench, .popmenu')) return;
      e.preventDefault();
      const ds = b.dataset;
      const busy = async (fn) => {
        b.classList.add('running');
        try {
          await fn();
        } catch (err) {
          console.error(err);
          toast(esc(err.message || String(err)), 'error');
        } finally {
          b.classList.remove('running');
        }
      };
      if (ds.goto) {
        const [id, anchor] = ds.goto.split('/');
        MG.app.showHelp(id, { anchor });
        return;
      }
      if (ds.bench) await MG.app.showWorkbench(ds.bench);
      if (ds.term != null) await busy(() => runInTerminal(ds.term, false));
      if (ds.termRun != null) await busy(() => runInTerminal(ds.termRun, true));
      if (ds.nb != null || ds.nbRun != null) {
        const src = ds.nb != null ? ds.nb : ds.nbRun;
        await busy(() => toNotebook(src.replace(/\\n/g, '\n'), ds.lang || 'python', ds.nbRun != null));
      }
      if (ds.open) await busy(() => MG.app.openFile(ds.open));
      for (const k of Object.keys(MG.actions)) {
        if (ds[k] != null) await busy(() => MG.actions[k](ds[k], b));
      }
    });
  }

  /* ------------------------------------------------------------------
     "My files": download everything, add files, start afresh
     ------------------------------------------------------------------ */
  function initFilesMenu() {
    const btn = $('#projectBtn');
    const HOME = () => MG.app.HOME;
    btn.addEventListener('click', async () => {
      const u = await MG.project.usage();
      const used = u && u.usage ? `${MG.humanSize(u.usage)}B of about ${MG.humanSize(u.quota)}B used` : '';
      MG.popmenu(btn, [
        ['zip', 'Download all my files (.zip)', () => MG.project.download(HOME(), 'pedigree-workbench-files.zip')],
        ['upload', 'Add files from my computer…', () => MG.app.pickFiles(HOME(), false)],
        ['folder', 'Add a folder from my computer…', () => MG.app.pickFiles(HOME(), true)],
        ['folder', 'Show my files', () => MG.app.showWorkbench('editor')],
        ['info', 'Where are my files kept?' + (used ? ' (' + used + ')' : ''), () => MG.app.showHelp('h-files', { anchor: 'kept' })],
        ['trash', 'Start afresh: delete all my files…', () => startAfresh()]
      ]);
    });
  }

  /** a file picker that puts what is chosen into a folder */
  MG.app.pickFiles = (folder, dir) =>
    new Promise((resolve) => {
      const inp = h('input', { type: 'file', multiple: true, style: { display: 'none' } });
      if (dir) inp.webkitdirectory = true;
      document.body.appendChild(inp);
      inp.addEventListener('change', async () => {
        const files = Array.from(inp.files || []);
        inp.remove();
        if (!files.length) return resolve([]);
        const paths = await MG.project.addFiles(MG.app.fs, folder, files);
        if (paths.length) toast(`Added <b>${paths.length}</b> file${paths.length === 1 ? '' : 's'} to ${esc(MG.app.fs.pretty(folder))}.`, 'ok');
        resolve(paths);
      });
      inp.click();
    });

  function startAfresh() {
    const m = MG.modal(
      'Start afresh?',
      `<p>This deletes <b>every file</b> in your home folder (${esc(MG.app.fs.pretty(MG.app.HOME))}) from this browser, including drawings, notebooks, uploads and results. It also deletes the drawing in the Studio tab. You can’t undo this.</p>
       <p>Download your files first if you want to keep any of them.</p>
       <p><label class="check"><input type="checkbox" data-x="sure"> I have downloaded what I want to keep</label></p>
       <div class="prompt-actions"><button class="btn" data-x="dl" type="button">${MG.icon('zip')}<span>Download all my files</span></button><span class="grow"></span><button class="btn" data-x="no" type="button">Cancel</button><button class="btn danger" data-x="yes" type="button" disabled>Delete everything</button></div>`
    );
    const yes = m.box.querySelector('[data-x="yes"]');
    m.box.querySelector('[data-x="sure"]').addEventListener('change', (e) => (yes.disabled = !e.target.checked));
    m.box.querySelector('[data-x="dl"]').addEventListener('click', () => MG.project.download(MG.app.HOME, 'pedigree-workbench-files.zip'));
    m.box.querySelector('[data-x="no"]').addEventListener('click', () => m.close());
    yes.addEventListener('click', async () => {
      m.close();
      try {
        if (MG.page.beforeReset) await MG.page.beforeReset();
      } catch (e) {
        console.error(e);
      }
      await MG.project.reset(MG.app.fs);
      const keep = new Set(['helpOff', 'helpWidth', 'helpPage', 'userName']);
      try {
        const pfx = (MG.config.storePrefix || 'genomics') + ':' + document.body.dataset.page + ':';
        Object.keys(localStorage)
          .filter((k) => k.startsWith(pfx) && !keep.has(k.slice(pfx.length)))
          .forEach((k) => localStorage.removeItem(k));
      } catch (e) {
        /* ignore */
      }
      location.reload();
    });
  }

  /* ------------------------------------------------------------------
     The button with the person's name, at the top: the terminal is user@workbench until they put in a name of their
     own (MG.user in core.js). The name is kept in this browser only.
     ------------------------------------------------------------------ */
  function initUser() {
    const btn = $('#userBtn');
    if (!btn) return;
    const label = btn.querySelector('.user-name');
    const show = () => {
      const n = MG.user.name(), plain = n === MG.user.DEFAULT;
      if (label) label.textContent = n;
      btn.title = plain ? 'Put your name into the workbench, and the terminal will show it in place of user' : `Your name in the workbench is ${n}. Click to change it.`;
      btn.setAttribute('aria-label', plain ? 'Your name in the workbench is user. Click to put in your own.' : `Your name in the workbench is ${n}`);
    };
    show();
    bus.on('user:name', show);
    btn.addEventListener('click', nameDialog);
  }
  function nameDialog() {
    const D = MG.user.DEFAULT, cur = MG.user.name();
    const host = (MG.app.term && MG.app.term.hostname) || MG.config.hostname || 'workbench';
    const m = MG.modal('Your name in the workbench', '');
    const input = h('input.prompt-input#userNameIn', { type: 'text', value: cur === D ? '' : cur, placeholder: D, maxlength: '40', spellcheck: 'false', autocomplete: 'off', autocapitalize: 'off', 'aria-describedby': 'userNameNote' });
    const preview = h('code.user-prompt');
    const note = h('p.user-note#userNameNote', { 'aria-live': 'polite' });
    const save = h('button.btn.primary', { type: 'submit' }, 'Save');
    const reset = h('button.btn', { type: 'button' }, `Use “${D}”`);
    const cancel = h('button.btn', { type: 'button' }, 'Cancel');
    const form = h(
      'form.user-form',
      h('p', 'The terminal shows your name in its prompt, in place of ', h('code', D), ', and ', h('code', 'whoami'), ', ', h('code', '$USER'), ', ', h('code', 'ls -l'), ' and Python use it too. It’s kept in this browser only. Your home folder stays ', h('code', MG.app.HOME || '/home/user'), '.'),
      h('label.user-label', { for: 'userNameIn' }, 'Your name'),
      input,
      h('p.user-prev', h('span.muted', 'The prompt: '), preview),
      note,
      h('div.prompt-actions', reset, h('span.grow'), cancel, save)
    );
    m.box.querySelector('.modal-b').appendChild(form);
    let chosen = cur;
    const update = () => {
      const v = input.value.trim();
      const n = v === '' ? D : v === 'root' ? '' : MG.user.valid(v) ? v : MG.user.suggest(v);
      note.classList.toggle('bad', !n);
      if (v === 'root') note.textContent = 'root is the name of the administrator here, so choose another name.';
      else if (!n) note.textContent = 'A name here starts with a letter and has only letters, digits, dots, hyphens or underscores, with no spaces. For example: ada, ada.lovelace or a_lovelace.';
      else if (v && n !== v) note.textContent = `A name here can’t have spaces or other symbols, so yours will be ${n}.`;
      else note.textContent = '';
      chosen = n;
      preview.textContent = `${n || '…'}@${host}:~$`;
      save.disabled = !n;
    };
    input.addEventListener('input', update);
    update();
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!chosen || !MG.user.set(chosen)) return;
      m.close();
      toast(chosen === D ? `The terminal shows <b>${D}</b> again.` : `Saved. The terminal now shows <b>${esc(chosen)}</b>@${esc(host)}.`, 'ok', 3500);
    });
    reset.addEventListener('click', () => {
      input.value = '';
      update();
      input.focus();
    });
    cancel.addEventListener('click', () => m.close());
    setTimeout(() => {
      input.focus();
      input.select();
    }, 30);
  }
  MG.app.nameDialog = nameDialog;
  // (a button of the help pages: data-username)
  MG.actions.username = () => nameDialog();

  /* the indicator in the top bar: are the files kept? */
  function initStoreStatus() {
    const el = $('#storeStatus');
    if (!el) return;
    const set = (state, text, title) => {
      el.dataset.state = state;
      el.innerHTML = `<i></i><span>${esc(text)}</span>`;
      if (title) el.title = title;
    };
    if (!MG.project.ok) {
      set('off', 'Not kept', 'This browser doesn’t let the workbench keep files, perhaps because this is a private window. Download your work before you close the page.');
      return;
    }
    const OK_TITLE = 'Your files and notebooks are kept in this browser on this computer. Use My files → Download all my files (.zip) to take them elsewhere.';
    // More than config.storageWarnMB megabytes of files: the indicator says so, and once a visit a message too.
    // (Browsers limit what a site may keep; past that limit nothing more is saved.)
    let warned = false;
    const saved = () => {
      const limit = Number(MG.config.storageWarnMB) || 0;
      let bytes = 0;
      if (limit && MG.app.fs) for (const [p, e] of MG.app.fs.entries) if (e.kind !== 'dir' && p.startsWith(MG.app.HOME + '/')) bytes += MG.app.fs.size(e) || 0;
      if (!limit || bytes <= limit * 1048576) return set('ok', 'Saved in this browser', OK_TITLE);
      const much = MG.humanSize(bytes) + 'B';
      set('busy', `Saved · ${much}`, `Your files take up ${much} in this browser. Download what you want to keep, and delete large files you no longer need.`);
      if (!warned) {
        warned = true;
        toast(`Your files take up <b>${much}</b> in this browser, which is more than ${limit} MB. Browsers limit how much a site may keep, so download what you want to keep and delete large files you no longer need, such as copies of the ontologies.`, 'warn', 12000);
      }
    };
    saved();
    let t;
    bus.on('files:saving', () => set('busy', 'Saving…'));
    bus.on('files:saved', () => {
      clearTimeout(t);
      t = setTimeout(saved, 250);
    });
    bus.on('files:notsaved', () => set('off', 'Not saved', 'The browser has no room left. Download your files, then delete some of them.'));
  }

  /* the name at the top of the page (config.js: courseTitle, courseSubtitle) */
  function initBrand() {
    const C = MG.config || {};
    if (C.courseTitle) {
      const t = $('.brand-title'), a = $('.brand');
      if (t) t.textContent = C.courseTitle;
      if (a) a.title = C.courseTitle;
      document.title = C.courseTitle;
    }
    if (C.courseSubtitle != null) {
      const s = $('.brand-sub');
      if (s) s.textContent = C.courseSubtitle;
    }
  }

  /* the same workbench in two tabs: both would write the same files */
  function initTabsWarning() {
    if (!window.BroadcastChannel) return;
    const ch = new BroadcastChannel((MG.config.storePrefix || 'wb') + '-tabs');
    const me = Math.random().toString(36).slice(2);
    let warned = false;
    ch.onmessage = (e) => {
      const m = e.data || {};
      if (m.from === me) return;
      if (m.type === 'hello') ch.postMessage({ type: 'here', from: me });
      if ((m.type === 'hello' || m.type === 'here') && !warned) {
        warned = true;
        toast('The workbench is open in another tab or window too. Use only one at a time, because both keep files in the same place and one can overwrite what the other has saved.', 'warn', 12000);
      }
    };
    ch.postMessage({ type: 'hello', from: me });
  }

  /* ------------------------------------------------------------------
     start
     ------------------------------------------------------------------ */
  async function init() {
    initBrand();
    initTabs();
    initSplitter();
    initHelpPane();
    initHelp();
    initActions();
    initFilesMenu();
    initUser();
    try {
      if (MG.page.init) await MG.page.init();
    } catch (e) {
      console.error(e);
      toast('The workbench didn’t start properly: ' + esc(e.message || String(e)), 'error', 15000);
    }
    initStoreStatus();
    initTabsWarning();
    const want = new URLSearchParams(location.search).get('tab');
    const first = (want && TAB_NAME[want] && want) || store.get('bench', null) || MG.page.firstBench || 'studio';
    MG.app.showWorkbench(TAB_NAME[first] ? first : 'studio', { keepHelp: true });
    ready = true;
    document.body.classList.add('ready');
    bus.emit('app:ready');
  }
  MG.app.isReady = () => ready;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
