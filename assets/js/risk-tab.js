/* =====================================================================
   The Risk tab: genetic risks worked out from a whole pedigree.

   The family comes from the drawing in the Studio tab, or from a file: a
   drawing, a PED or MPED file, a GA4GH Pedigree or a Phenopackets
   Family. Drawings, PED and MPED files are read in the page
   (risk-read.js, as the converters read them), and GA4GH files by
   Python (pedwb.risk, with pedigree-ga4gh). Under a single-gene model
   (the mode of inheritance, how common the variant is, its penetrance)
   the tab gives, exactly (risk-engine.js):
     - one person's chance of carrying the variant and of being affected,
       with the Bayesian table that leads to it;
     - the chance that a child of a couple will be affected;
     - everyone's chances, in a table that can be saved in ~/results.
   Below them, "by hand": a couple's four equally likely children, and
   chances multiplied together, as on the Inheritance tab of the
   pedigree practical (its assets/js/inherit.js).

   Other tabs open it with MG.app.riskOpen({source, person, mode, …}),
   and the help's buttons with data-risk and data-inherit.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, store, toast } = MG;
  const ENGINE = window.PedRisk, READ = window.PedRead;

  const HOME = () => MG.app.HOME;
  const KINDS = ['studio', 'ped', 'mped', 'pedigree', 'family'];
  const MODES = [
    ['AD', 'Autosomal dominant'],
    ['AR', 'Autosomal recessive'],
    ['XLR', 'X-linked recessive'],
    ['XLD', 'X-linked dominant']
  ];
  const isX = (mode) => mode === 'XLR' || mode === 'XLD';
  const isRecessive = (mode) => mode === 'AR' || mode === 'XLR';
  const PRESETS = [
    ['allele:10000', '1 in 10,000 copies of the gene (rare)'],
    ['allele:1000', '1 in 1,000 copies of the gene'],
    ['allele:100', '1 in 100 copies of the gene (common)'],
    ['carrier:25', '1 in 25 people carry it (cystic fibrosis)'],
    ['custom', 'something else…']
  ];
  const DEFAULTS = {
    source: 'studio', family: null, condition: null, mode: 'AR', freq: 'allele:1000', freqAs: 'allele', freqN: 1000,
    penetrance: 100, phenocopy: 0, mutation: 0, unrecorded: '', person: null, couple: null, single: null, tests: {}
  };
  // the results that can be given to someone under Everyone (risk-read.js: forEngine)
  const TESTS = { variant: 'has the variant', carrier: 'a carrier (one copy)', homozygous: 'two copies', none: 'doesn’t have it', clear: 'not tested', unknown: 'status not known' };

  const base = (p) => String(p || '').split('/').pop();
  const tilde = (p) => (String(p).startsWith(HOME() + '/') ? '~' + String(p).slice(HOME().length) : String(p));
  /** a file's name without its kind: okafor.studio.json → okafor, okafor_ga4gh-pedigree.json → okafor */
  const stemOf = (p) => base(p).replace(/(_ga4gh-pedigree|_phenopackets-family)?\.(studio\.json|pedigree\.json|family\.json|json|ped|mped|fam)$/i, '') || 'family';
  /** a chance in words, with its percentage: 2/3 (67%), about 1 in 12 (8.4%) */
  const say = (x) => {
    if (x === 0) return '0';
    const d = ENGINE.describe(x);
    return d.pct ? `${d.text} (${d.pct})` : d.text;
  };
  const sayShort = (x) => ENGINE.describe(x).text;
  const icon = (n) => MG.icon(n);
  const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);
  const sexWord = (s) => ({ M: 'male', F: 'female' }[s] || 'sex not known');
  const sexShort = (s) => ({ M: 'male', F: 'female' }[s] || 'unknown');
  /** a person in a list: II-3 · Jane (the label the drawing shows, and the first line of their text) */
  const optionText = (p) => (p.name ? `${p.label} · ${p.name}` : p.label);
  /** a list of people in a sentence: II-3, III-1 and III-2 */
  const listOf = (labels, most = 6) => {
    const shown = labels.slice(0, most);
    if (labels.length > most) shown.push(`${labels.length - most} more`);
    return shown.length > 1 ? `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}` : shown[0] || '';
  };
  /** a Python error, for people: without its kind, or a traceback */
  const cleanError = (r) => String((r && (r.message || r.error)) || 'Python couldn’t read the file').replace(/^[A-Za-z]*Error: /, '');

  /** the people in the order of their labels, generation by generation (I-1, I-2, II-1 …), if every label is of that
      form; otherwise in the order the file has them */
  const ROMAN = { I: 1, V: 5, X: 10, L: 50 };
  const roman = (s) => {
    let n = 0;
    for (let i = 0; i < s.length; i++) {
      const v = ROMAN[s[i]], w = ROMAN[s[i + 1]] || 0;
      n += v < w ? -v : v;
    }
    return n;
  };
  function inOrder(people) {
    const key = (p) => {
      const m = /^([IVXL]+)-(\d+)$/.exec(p.label || '');
      return m ? [roman(m[1]), Number(m[2])] : null;
    };
    if (!people.every(key)) return people.slice();
    return people.slice().sort((a, b) => {
      const x = key(a), y = key(b);
      return x[0] - y[0] || x[1] - y[1];
    });
  }

  /** an allele frequency from the setting: 1 in N copies of the gene, or 1 in N people carrying it (people from the
      population who are unaffected: 2q / (1 + q) = 1/N, so q = 1 / (2N − 1), as in the textbooks' examples) */
  function alleleFrequency(as, n) {
    n = Number(n);
    if (!(n > 1) || !isFinite(n)) return null;
    return as === 'carrier' ? 1 / (2 * n - 1) : 1 / n;
  }

  /** a row of a Bayesian table: one genotype */
  function genotypeName(state, mode) {
    const c = state.copies;
    if (isX(mode) && state.sex === 'M') return c ? 'has the variant' : 'doesn’t have it';
    if (isRecessive(mode)) return ['not a carrier', 'a carrier (one copy)', 'two copies'][c];
    return ['doesn’t have it', 'one copy', 'two copies'][c];
  }

  class RiskTab {
    constructor(root, opts) {
      this.root = root;
      this.fs = opts.fs;
      this.st = Object.assign({}, DEFAULTS, store.get('risk', {}));
      if (!this.st.tests || typeof this.st.tests !== 'object') this.st.tests = {};
      if (!MODES.some(([m]) => m === this.st.mode)) this.st.mode = DEFAULTS.mode;
      this.families = [];
      this.error = null;
      this.ticket = 0;
      this.cache = new Map(); // GA4GH files as Python read them: path → {mtime, family}
      this.hand = null;
      this._save = MG.debounce(() => store.set('risk', this.st), 300);
      this._later = MG.debounce(() => this.update(), 160);
      this._build();
      this.fs.onChange((p) => {
        if (/\.(json|ped|mped|fam)$/i.test(p)) {
          clearTimeout(this._ft);
          this._ft = setTimeout(() => this._sources(), 300);
        }
        if (p === this.st.source) {
          clearTimeout(this._rt);
          this._rt = setTimeout(() => this.load(), 300);
        }
      });
      this.ready = this.load();
    }

    /* ---------------------------------------------------------------- the page */
    _build() {
      let n = 0;
      /** a labelled field: the label is for the first input or select in el */
      const field = (label, el, help) => {
        const input = el.matches('input, select, textarea') ? el : el.querySelector('input, select, textarea');
        if (input && !input.id) input.id = 'rk-' + ++n;
        return h('div.tl-field', h('label.tl-label', input ? { for: input.id } : null, label), el, help ? h('div.tl-help', help) : null);
      };
      const linkBtn = (ic, label, fn, title) => {
        const b = h('button.linkbtn', { type: 'button', title: title || null, html: icon(ic) + `<span>${esc(label)}</span>` });
        b.addEventListener('click', fn);
        return b;
      };

      // the family
      this.sourceSel = h('select.tl-input#rk-source');
      this.sourceSel.addEventListener('change', () => this.choose({ source: this.sourceSel.value }));
      const upload = linkBtn('upload', 'From my computer…', async () => {
        const paths = await MG.app.pickFiles(HOME() + '/pedigrees', false);
        if (paths && paths[0]) this.choose({ source: paths[0] });
      }, 'Add a drawing, PED, MPED or GA4GH file from your computer to ~/pedigrees, and use it here');
      const look = linkBtn('eye', 'Look at it', () => (this.st.source === 'studio' ? MG.app.showWorkbench('studio') : MG.app.openFile(this.st.source)));
      this.familySel = h('select.tl-input');
      this.familySel.addEventListener('change', () => this.choose({ family: this.familySel.value }));
      this.familyRow = field('Family', this.familySel, 'This file has more than one family.');
      this.conditionSel = h('select.tl-input#rk-condition');
      this.conditionSel.addEventListener('change', () => this.choose({ condition: this.conditionSel.value }));
      this.unrecordedSel = h('select.tl-input');
      this.unrecordedSel.addEventListener('change', () => this.choose({ unrecorded: this.unrecordedSel.value }));
      this.unrecordedRow = field('People with no record of the condition', this.unrecordedSel,
        'A GA4GH Pedigree records who has a condition, but only sometimes who doesn’t. As PedNet does, people with no record of it are taken as unaffected if no one in the file is recorded as not having it, and as not known if anyone is.');
      this.summary = h('div.rk-summary');
      this.notes = h('div.rk-notes');
      const familyCard = h('section.tl-form.rk-card',
        h('h3.rk-h', 'The family'),
        h('div.tl-field', h('label.tl-label', { for: 'rk-source' }, 'From'), h('div.tl-picker', this.sourceSel, h('div.tl-pickbtns', upload, look))),
        this.familyRow,
        field('The condition', this.conditionSel),
        this.unrecordedRow,
        this.summary,
        this.notes);

      // the model
      this.modeSeg = h('div.rk-seg', { role: 'group', 'aria-label': 'Mode of inheritance' });
      MODES.forEach(([m, name]) => {
        const b = h('button', { type: 'button', dataset: { mode: m }, 'aria-pressed': 'false' }, name);
        b.addEventListener('click', () => this.choose({ mode: m }));
        this.modeSeg.appendChild(b);
      });
      this.freqSel = h('select.tl-input#rk-freq');
      PRESETS.forEach(([v, t]) => this.freqSel.appendChild(h('option', { value: v }, t)));
      this.freqSel.addEventListener('change', () => {
        const v = this.freqSel.value;
        if (v === 'custom') this.choose({ freq: 'custom' });
        else {
          const [as, num] = v.split(':');
          this.choose({ freq: v, freqAs: as, freqN: Number(num) });
        }
      });
      this.freqN = h('input.tl-input.small.rk-num', { type: 'number', min: '2', step: 'any', 'aria-label': 'One in how many' });
      this.freqN.addEventListener('input', () => {
        if (Number(this.freqN.value) > 1) this.choose({ freqN: Number(this.freqN.value) }, true);
      });
      this.freqAsSel = h('select.tl-input.small', { 'aria-label': 'Of what' }, h('option', { value: 'carrier' }, 'people carry it'), h('option', { value: 'allele' }, 'copies of the gene have it (the allele frequency)'));
      this.freqAsSel.addEventListener('change', () => this.choose({ freqAs: this.freqAsSel.value }));
      this.freqCustom = h('div.rk-inline', h('span', '1 in'), this.freqN, this.freqAsSel);
      this.freqHint = h('div.tl-help');
      const number = (min, max, key) => {
        const el = h('input.tl-input.small.rk-num', { type: 'number', min: String(min), max: String(max), step: 'any' });
        el.addEventListener('input', () => {
          const v = Number(el.value);
          if (el.value !== '' && v >= min && v <= max) this.choose({ [key]: v }, true);
        });
        return el;
      };
      this.pen = number(1, 100, 'penetrance');
      this.pheno = number(0, 50, 'phenocopy');
      this.mut = number(0, 50000, 'mutation');
      this.more = h('details.rk-more',
        h('summary', 'Phenocopies and new mutations'),
        field('Phenocopies', h('div.rk-inline', this.pheno, h('span', '%')),
          'The share of people without the variant who are affected anyway, for another reason. With none, someone affected must have the variant (or, under a recessive mode, two copies).'),
        field('New mutations', h('div.rk-inline', this.mut, h('span', 'in 100,000 eggs or sperm')),
          'How often a new copy of the variant arises. With none, an affected child of two parents without the variant can’t happen under a dominant mode. For a single case of an X-linked condition, as in the textbooks, give the mutation rate, and an allele frequency of about twice it.'));
      const modelCard = h('section.tl-form.rk-card',
        h('h3.rk-h', 'How it is inherited'),
        h('div.tl-field', h('span.tl-label', 'Mode of inheritance'), this.modeSeg),
        h('div.tl-field', h('label.tl-label', { for: 'rk-freq' }, 'How common the variant is'), this.freqSel, this.freqCustom, this.freqHint),
        field('Penetrance', h('div.rk-inline', this.pen, h('span', '%')),
          'The share of people with the variant (with two copies, under a recessive mode) who are affected. The Risk tab doesn’t allow for age: for a condition that starts later in life, give the chance of being affected by the age most of the family have reached, and, under Everyone, take the status of people too young to show it yet as not known.'),
        this.more);

      // the answers
      this.problem = h('div.rk-problem');
      this.personSel = h('select.tl-input#rk-person');
      this.personSel.addEventListener('change', () => this.choose({ person: this.personSel.value }));
      this.personOut = h('div.rk-out');
      const personCard = h('section.tl-form.rk-card', h('h3.rk-h', 'One person'), field('Whose chance', this.personSel), this.personOut);
      this.coupleSel = h('select.tl-input#rk-couple');
      this.coupleSel.addEventListener('change', () => this.choose({ couple: this.coupleSel.value }));
      this.singleSel = h('select.tl-input');
      this.singleSel.addEventListener('change', () => this.choose({ single: this.singleSel.value }));
      this.singleRow = field('Who, from the family', this.singleSel);
      this.childOut = h('div.rk-out');
      const childCard = h('section.tl-form.rk-card', h('h3.rk-h', 'A child of a couple'), field('The couple', this.coupleSel), this.singleRow, this.childOut);
      this.tableOut = h('div.rk-tablewrap');
      this.savedOut = h('div.rk-saved');
      const saveBtn = h('button.btn.small', { type: 'button', html: icon('save') + '<span>Save as a table</span>', title: 'Save everyone’s chances in your results folder, as a table that the Notebook and spreadsheets read' });
      saveBtn.addEventListener('click', () => this.saveTable());
      this.allCard = h('section.tl-form.rk-card.rk-allcard',
        h('div.rk-hrow', h('h3.rk-h', 'Everyone'), saveBtn),
        h('div.tl-help', 'Each person’s chances, given everything known of the family. Click a name to see that person’s chances above. Give someone a test result to see what it would change, or leave out whether they are affected, as for someone too young to show a condition of later life yet. These are used here only, and aren’t put in the family’s file.'),
        this.tableOut,
        this.savedOut);
      this.answers = h('div.rk-answers', this.problem, personCard, childCard);

      // by hand
      this.handRoot = h('div.rk-hand');
      this.handBox = h('details.tl-samebox.rk-handbox', h('summary', h('span', { html: icon('book') }), h('span', 'By hand: what each child of a couple can inherit, and chances multiplied together')), this.handRoot);
      this.handBox.addEventListener('toggle', () => {
        if (this.handBox.open) this._handOpen();
      });

      const helpBtn = h('button.tl-py', { type: 'button', html: icon('help') + '<span>How the chances are worked out</span>', title: 'Help: the Risk tab' });
      helpBtn.addEventListener('click', () => MG.app.showHelp('h-risk'));
      const head = h('div.tl-head', h('span.tl-crumb', 'Genetic risk'), h('span.grow'), helpBtn);
      this.root.append(h('div.tl-wrap.rk-wrap', head, h('div.rk-main',
        h('p.tl-lead.rk-lead', 'The chance that someone in a family carries its variant or will be affected, and that a couple’s child will be, worked out exactly from everything known of the whole family, under the model of inheritance you choose.'),
        h('div.rk-grid', h('div.rk-col', familyCard, modelCard), h('div.rk-col', this.answers)),
        this.allCard,
        this.handBox)));
      this._sources();
      this._syncModel();
    }

    /** the choices of family: the drawing in the Studio, your files, the examples */
    _sources() {
      const fs = this.fs;
      const mine = [], ex = [];
      for (const [p, e] of fs.entries) {
        if (e.kind === 'dir') continue;
        const inHome = p.startsWith(HOME() + '/'), inEx = p.startsWith('/data/examples/');
        if ((!inHome && !inEx) || /\/\.[^/]*$/.test(p) || p.includes('/.cache/') || p.startsWith('/data/examples/older/')) continue;
        const k = MG.app.pedKind(p);
        if (KINDS.includes(k)) (inHome ? mine : ex).push({ path: p, kind: k, mtime: e.mtime || 0 });
      }
      mine.sort((a, b) => b.mtime - a.mtime);
      ex.sort((a, b) => (a.path < b.path ? -1 : 1));
      const cur = this.st.source;
      if (cur !== 'studio' && ![...mine, ...ex].some((x) => x.path === cur) && fs.exists(cur)) mine.unshift({ path: cur, kind: MG.app.pedKind(cur) });
      const sel = this.sourceSel;
      sel.innerHTML = '';
      sel.appendChild(h('option', { value: 'studio' }, 'The drawing in the Studio tab'));
      const names = MG.app.kindNames || {};
      const group = (label, list) => {
        if (!list.length) return;
        const g = h('optgroup', { label });
        list.forEach((x) => g.appendChild(h('option', { value: x.path }, `${tilde(x.path).replace(/^\/data\/examples\//, '')} (${names[x.kind] || x.kind})`)));
        sel.appendChild(g);
      };
      group('Your files', mine);
      group('Examples', ex);
      sel.value = cur;
      if (sel.value !== cur) sel.value = 'studio';
    }

    /* ---------------------------------------------------------------- choosing and reading */
    /** change some settings, and work everything out again (reading the family again if it is another one).
        later: wait a moment first (a number being typed) */
    choose(change, later) {
      const newSource = 'source' in change && change.source !== this.st.source;
      const newFamily = 'family' in change && change.family !== this.st.family;
      Object.assign(this.st, change);
      if (newSource) this.st.family = null;
      if (newSource || newFamily) Object.assign(this.st, { person: null, couple: null, single: null });
      this._save();
      if (newSource) {
        this._sources();
        this.load();
        return;
      }
      this._syncModel();
      if (later) this._later();
      else this.update();
    }
    /** the drawing in the Studio: the Studio's own, if it has started, or the one it keeps in the browser */
    _drawing() {
      const S = MG.app.studio;
      if (S && S.api) {
        try {
          return { data: S.api.data(), name: S.path ? stemOf(S.path) : 'drawing' };
        } catch (e) {
          /* not ready: as below */
        }
      }
      try {
        return { data: JSON.parse(localStorage.getItem('pedwb:studio-session') || 'null'), name: 'drawing' };
      } catch (e) {
        return { data: null, name: 'drawing' };
      }
    }
    /** read the family again, from wherever it comes from */
    async load() {
      const src = this.st.source;
      const ticket = ++this.ticket;
      let families = [], error = null;
      try {
        families = await this._read(src);
      } catch (e) {
        error = e.message || String(e);
      }
      if (ticket !== this.ticket) return; // (another family was asked for meanwhile)
      this.families = families;
      this.error = error;
      this._familyChoices();
      this.update();
    }
    async _read(src) {
      if (src === 'studio') {
        const { data, name } = this._drawing();
        const family = data && Array.isArray(data.persons) && data.persons.length ? READ.fromStudio(data, name) : null;
        if (!family || !family.people.length) throw new Error('There is no drawing in the Studio tab yet. Draw a family there, or choose a file or an example above.');
        return [family];
      }
      if (!this.fs.exists(src)) throw new Error(`There is no file ${tilde(src)} any more. Choose another above.`);
      const kind = MG.app.pedKind(src);
      if (kind === 'studio') {
        let doc;
        try {
          doc = JSON.parse(await this.fs.readText(src));
        } catch (e) {
          throw new Error(`${tilde(src)} couldn’t be read as a drawing: ${e.message}`);
        }
        return [READ.fromStudio(doc, stemOf(src))];
      }
      if (kind === 'ped' || kind === 'mped') return READ.fromPed(await this.fs.readText(src));
      if (kind === 'pedigree' || kind === 'family') {
        const e = this.fs.get(src);
        const mtime = (e && e.mtime) || 0;
        const hit = this.cache.get(src);
        if (hit && hit.mtime === mtime) return [hit.family];
        this._status('Reading the file with Python… (the first time on each visit, Python starts in your browser, which takes a few seconds)');
        const r = await MG.app.pyCall('pedwb.risk.family', { path: src });
        if (!r.ok) throw new Error(cleanError(r));
        this.cache.set(src, { mtime, family: r.result });
        return [r.result];
      }
      throw new Error('The Risk tab reads drawings, PED and MPED files, GA4GH Pedigrees and Phenopackets Families.');
    }
    _status(text) {
      this.summary.innerHTML = '';
      this.summary.appendChild(h('div.tl-status', h('span.spinner'), h('span', text)));
    }
    get family() {
      return this.families.find((f) => f.id === this.st.family) || this.families[0] || null;
    }
    _familyChoices() {
      this.familySel.innerHTML = '';
      this.families.forEach((f) => this.familySel.appendChild(h('option', { value: f.id }, f.id)));
      this.familyRow.hidden = this.families.length < 2;
      const fam = this.family;
      if (fam) this.familySel.value = fam.id;
    }
    /** the test results given here for this family, by person */
    _tests() {
      const fam = this.family;
      const key = `${this.st.source}#${fam ? fam.id : ''}`;
      if (!this.st.tests[key]) this.st.tests[key] = {};
      return this.st.tests[key];
    }
    /** a person, by id or by the label the drawing shows */
    _find(fam, x) {
      if (x == null) return null;
      return fam.people.find((p) => p.id === x) || fam.people.find((p) => p.label === x) || null;
    }

    /* ---------------------------------------------------------------- the model */
    _syncModel() {
      const st = this.st;
      this.modeSeg.querySelectorAll('button').forEach((b) => {
        b.classList.toggle('on', b.dataset.mode === st.mode);
        b.setAttribute('aria-pressed', b.dataset.mode === st.mode ? 'true' : 'false');
      });
      const preset = PRESETS.some(([v]) => v === st.freq) ? st.freq : 'custom';
      this.freqSel.value = preset;
      this.freqCustom.hidden = preset !== 'custom';
      const keep = (el, v) => {
        if (document.activeElement !== el) el.value = v;
      };
      keep(this.freqN, st.freqN);
      this.freqAsSel.value = st.freqAs;
      keep(this.pen, st.penetrance);
      keep(this.pheno, st.phenocopy);
      keep(this.mut, st.mutation);
      const q = alleleFrequency(st.freqAs, st.freqN);
      if (!q) this.freqHint.textContent = 'Give a number above 1.';
      else if (isRecessive(st.mode)) this.freqHint.textContent = `An allele frequency of ${sayShort(q)}: ${st.mode === 'XLR' ? 'a woman' : 'someone'} from the population who is unaffected carries it with a chance of ${sayShort((2 * q) / (1 + q))}.`;
      else this.freqHint.textContent = `An allele frequency of ${sayShort(q)}: ${st.mode === 'XLD' ? 'a woman' : 'someone'} from the population has it with a chance of ${sayShort(1 - (1 - q) * (1 - q))}, before anything is known of them.`;
      if (st.phenocopy > 0 || st.mutation > 0) this.more.open = true;
    }
    model() {
      const st = this.st;
      return { mode: st.mode, q: alleleFrequency(st.freqAs, st.freqN), penetrance: st.penetrance / 100, phenocopy: st.phenocopy / 100, mutation: st.mutation / 100000 };
    }

    /* ---------------------------------------------------------------- the family, for the engine */
    /** the condition to start with: one the proband is affected by, else one anyone is, else the first (a
        Phenopackets Family's own status, which puts all its conditions together, only if there is no other) */
    _firstCondition(fam) {
      const own = fam.conditions.filter((c) => c.key !== 'family');
      const list = own.length ? own : fam.conditions;
      const by = (p) => list.find((c) => p.status && p.status[c.key] === 'affected');
      const proband = fam.people.find((p) => (p.proband || p.index) && by(p));
      if (proband) return by(proband).key;
      const anyone = fam.people.find(by);
      return anyone ? by(anyone).key : (list[0] || {}).key || '';
    }
    /** the people as the engine takes them, for the condition chosen */
    _people(fam) {
      const cond = this.st.condition;
      const auto = ((fam.unrecordedFor && fam.unrecordedFor[cond]) || fam.unrecorded) === 'auto';
      return READ.forEngine(fam, cond, this._tests(), auto ? this.st.unrecorded || null : null);
    }
    /** the person to start with: a pregnancy, else the proband (if not affected), else someone whose status isn't
        known, else an unaffected child or brother or sister of someone affected, else the first */
    _firstPerson(fam, people) {
      const q = new Map(people.map((x) => [x.id, x]));
      const aff = (id) => !!id && !!q.get(id) && q.get(id).affected === true;
      const list = inOrder(fam.people);
      const sibs = (p) => list.filter((s) => s !== p && s.father && s.father === p.father && s.mother === p.mother);
      const pick = list.find((p) => p.pregnancy) ||
        list.find((p) => (p.proband || p.index) && q.get(p.id).affected !== true) ||
        list.find((p) => q.get(p.id).affected === null && !q.get(p.id).test) ||
        list.find((p) => q.get(p.id).affected === false && (aff(p.father) || aff(p.mother) || sibs(p).some((s) => aff(s.id)))) ||
        list[0];
      return pick ? pick.id : null;
    }
    /** the couples who could have children: the parents of each child, and the couples drawn or recorded as partners */
    _couples(fam) {
      const byId = new Map(fam.people.map((p) => [p.id, p]));
      const at = new Map(inOrder(fam.people).map((p, i) => [p.id, i]));
      const seen = new Set(), out = [];
      const add = (a, b, children) => {
        const pa = byId.get(a), pb = byId.get(b);
        if (!pa || !pb || a === b) return;
        let f, m;
        if (pa.sex === 'M' || pb.sex === 'F') [f, m] = [pa, pb];
        else if (pa.sex === 'F' || pb.sex === 'M') [f, m] = [pb, pa];
        else return; // (neither's sex is known)
        if (f.sex === 'F' || m.sex === 'M') return; // (two men, or two women: the engine needs a father and a mother)
        const key = `${f.id}|${m.id}`;
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ key, father: f, mother: m, children, at: Math.min(at.get(f.id), at.get(m.id)) });
      };
      for (const p of fam.people) if (p.father && p.mother) add(p.father, p.mother, true);
      for (const [a, b] of fam.partners || []) add(a, b, false);
      return out.sort((x, y) => x.at - y.at);
    }

    /* ---------------------------------------------------------------- the answers */
    _clear() {
      this.problem.innerHTML = '';
      this.personOut.innerHTML = '';
      this.childOut.innerHTML = '';
      this.tableOut.innerHTML = '';
      this.savedOut.innerHTML = '';
      this.allCard.hidden = true;
    }
    update() {
      const fam = this.family;
      this._clear();
      this.notes.innerHTML = '';
      if (this.error || !fam) {
        this.summary.innerHTML = '';
        this.summary.appendChild(h('div.tl-fail', this.error || 'No family yet.'));
        this.answers.classList.add('rk-none');
        this.conditionSel.innerHTML = '';
        this.conditionSel.disabled = true;
        this.unrecordedRow.hidden = true;
        return;
      }
      this.answers.classList.remove('rk-none');
      const st = this.st;
      // the condition
      this.conditionSel.innerHTML = '';
      fam.conditions.forEach((c) => this.conditionSel.appendChild(h('option', { value: c.key }, c.label)));
      if (!fam.conditions.length) this.conditionSel.appendChild(h('option', { value: '' }, 'none: no one in this family is affected by anything'));
      if (!fam.conditions.some((c) => c.key === st.condition)) st.condition = this._firstCondition(fam);
      this.conditionSel.value = st.condition;
      this.conditionSel.disabled = fam.conditions.length < 2;
      const cond = st.condition;
      // people with no record of it (GA4GH files)
      const auto = ((fam.unrecordedFor && fam.unrecordedFor[cond]) || fam.unrecorded) === 'auto';
      this.unrecordedRow.hidden = !auto;
      if (auto) {
        const guess = READ.unrecordedAs(fam, cond);
        this.unrecordedSel.innerHTML = '';
        this.unrecordedSel.append(
          h('option', { value: '' }, `as the file suggests: ${guess === 'unknown' ? 'not known' : 'unaffected'}`),
          h('option', { value: 'unaffected' }, 'unaffected'),
          h('option', { value: 'unknown' }, 'not known'));
        this.unrecordedSel.value = st.unrecorded || '';
      }
      const people = this._people(fam);
      const q = new Map(people.map((x) => [x.id, x]));
      const byId = new Map(fam.people.map((p) => [p.id, p]));
      // what the family says
      const affected = people.filter((x) => x.affected === true).length;
      const carriers = fam.people.filter((p) => p.status && p.status[cond] === 'carrier').length;
      const unknown = people.filter((x) => x.affected === null && x.test !== 'carrier').length;
      const facts = [`${people.length} ${people.length === 1 ? 'person' : 'people'}`, `${affected} affected`];
      if (carriers) facts.push(`${carriers} marked as ${carriers === 1 ? 'a carrier' : 'carriers'}`);
      if (unknown) facts.push(`${unknown} whose status isn’t known`);
      this.summary.innerHTML = '';
      this.summary.appendChild(h('div.rk-facts', facts.join(', ') + '.'));
      if (fam.notes && fam.notes.length) {
        const d = h('details.rk-notebox', h('summary', `${fam.notes.length === 1 ? 'A note' : fam.notes.length + ' notes'} on how the family was read`));
        fam.notes.forEach((t) => d.appendChild(h('div.tl-help', t)));
        this.notes.appendChild(d);
      }
      // whose chance, and which couple's child
      const order = inOrder(fam.people);
      const found = this._find(fam, st.person);
      st.person = found ? found.id : this._firstPerson(fam, people);
      this.personSel.innerHTML = '';
      order.forEach((p) => this.personSel.appendChild(h('option', { value: p.id }, optionText(p) + (p.pregnancy ? ' (a pregnancy)' : ''))));
      this.personSel.value = st.person;
      const couples = this._couples(fam);
      if (st.couple !== 'pop' && !couples.some((c) => c.key === st.couple)) {
        const me = byId.get(st.person);
        const mine = couples.find((c) => c.father.id === st.person || c.mother.id === st.person);
        const parents = me && couples.find((c) => c.father.id === me.father && c.mother.id === me.mother);
        st.couple = (mine || parents || couples[0] || { key: 'pop' }).key;
      }
      this.coupleSel.innerHTML = '';
      couples.forEach((c) => this.coupleSel.appendChild(h('option', { value: c.key }, `${optionText(c.father)} and ${optionText(c.mother)}`)));
      this.coupleSel.appendChild(h('option', { value: 'pop' }, 'someone in the family, and a partner from the population'));
      this.coupleSel.value = st.couple;
      const known = order.filter((p) => p.sex !== 'U');
      this.singleRow.hidden = st.couple !== 'pop';
      if (!known.some((p) => p.id === st.single)) st.single = (known.find((p) => p.id === st.person) || known[0] || {}).id || null;
      this.singleSel.innerHTML = '';
      known.forEach((p) => this.singleSel.appendChild(h('option', { value: p.id }, optionText(p))));
      if (st.single) this.singleSel.value = st.single;
      this._save();

      // the chances
      const m = this.model();
      if (!m.q) {
        this.problem.appendChild(h('div.tl-fail', 'Say how common the variant is: 1 in a number above 1.'));
        return;
      }
      let all;
      try {
        all = ENGINE.analyse(people, m);
      } catch (e) {
        this._problem(e.message);
        return;
      }
      if (!all.ok) {
        this._problem(all.message, true);
        return;
      }
      this._person(people, q, byId, m, all);
      this._child(people, byId, m, couples);
      this._table(order, q, m, all);
    }
    _problem(message, impossible) {
      this._clear();
      this.problem.appendChild(h('div.tl-warn', h('b', impossible ? 'This family can’t happen under this model. ' : 'This can’t be worked out. '), cap(message)));
    }

    /** one person's chances, and the Bayesian table behind them */
    _person(people, q, byId, m, all) {
      const out = this.personOut;
      const id = this.st.person, p = byId.get(id), x = q.get(id), r = all.people[id];
      if (!p || !x || !r) return;
      const status = p.status ? p.status[this.st.condition] : undefined;
      // what is known of them: II-3 · Jane: female, unaffected. IV-5: a pregnancy, sex not known.
      const unborn = (p.pregnancy || p.loss) && status !== 'affected' && status !== 'carrier';
      let known;
      if (status === 'affected') known = 'affected';
      else if (status === 'unaffected') known = 'unaffected';
      else if (status === 'carrier') known = 'marked as a carrier';
      else known = x.affected === false ? 'unaffected (no record of the condition)' : 'status not known';
      const test = this._tests()[id];
      const what = [];
      if (p.pregnancy) what.push('a pregnancy');
      if (p.loss) what.push('a pregnancy loss');
      what.push(sexWord(p.sex));
      if (!unborn) what.push(test === 'unknown' ? `${known}, but left out here` : known);
      if (test === 'clear') what.push('the carrier mark left out here');
      else if (test && test !== 'unknown' && TESTS[test]) what.push(`tested: ${TESTS[test]}`);
      // the chances
      const lines = [];
      if (m.mode === 'AR' || (m.mode === 'XLR' && p.sex === 'F')) lines.push(['Is a carrier (one copy)', r.one, true]);
      else lines.push(['Has the variant', r.variant, true]);
      if (!(isX(m.mode) && p.sex === 'M') && r.two >= 1e-4) lines.push(['Has two copies', r.two]);
      if (x.affected === null) lines.push([p.pregnancy ? 'Will be affected' : 'Is, or will be, affected', r.affected, true]);
      const box = h('div.rk-big');
      lines.forEach(([label, val, main]) => box.appendChild(h('div.rk-line' + (main ? '.main' : ''), h('span.rk-what', label), h('span.rk-val', say(val)))));
      out.append(h('div.tl-help', `${optionText(p)}: ${what.join(', ')}.`), box);
      // the Bayesian table
      let b;
      try {
        b = ENGINE.bayes(people, m, id);
      } catch (e) {
        return;
      }
      if (!b.ok || !b.rows.length) return;
      const evidence = b.about.map((e) => byId.get(e)).filter(Boolean);
      if (!evidence.length) {
        out.appendChild(h('div.tl-help', `Nothing is known of ${p.label} or of anyone descended from them, so their chances come from the rest of the family alone.`));
        return;
      }
      const top = Math.max(...b.rows.map((row) => row.conditional));
      const scale = top > 0 && top < 1e-3 ? top : 1;
      const twoSexes = p.sex === 'U' && isX(m.mode);
      const rows = b.rows.map((row) => h('tr',
        h('th', (twoSexes ? (row.sex === 'M' ? 'a boy: ' : 'a girl: ') : '') + genotypeName(row, m.mode)),
        h('td', sayShort(row.prior)), h('td', sayShort(row.conditional / scale)), h('td', sayShort(row.joint / scale)), h('td.rk-post', sayShort(row.posterior))));
      const self = { M: 'himself', F: 'herself' }[p.sex] || 'themselves';
      const them = evidence.length === 1 && evidence[0].id === id ? `${p.label} ${self}` : listOf(evidence.map((e) => e.label));
      out.append(
        h('div.rk-h4', 'How the chance comes about'),
        h('div.rk-tablewrap', h('table.rk-table.rk-bayes',
          h('thead', h('tr', h('th', h('span.sr-only', 'Genotype')), h('th', 'Prior'), h('th', 'Conditional'), h('th', 'Joint'), h('th', 'Posterior'))),
          h('tbody', rows))),
        h('div.tl-help', `The prior is the chance of each genotype from the rest of the family. The conditional is the chance of what is known of ${them}, if ${p.label} has that genotype. The joint is the prior times the conditional, and the posterior is each joint divided by the sum of the joints.` +
          (scale !== 1 ? ' The conditionals and joints are shown as multiples of the largest conditional, as only how they compare matters.' : '')));
    }

    /** a child of the couple chosen, not yet born */
    _child(people, byId, m, couples) {
      const out = this.childOut;
      let list = people, father, mother, about;
      if (this.st.couple === 'pop') {
        const a = byId.get(this.st.single);
        if (!a) {
          out.appendChild(h('div.tl-help', 'No one in this family is recorded as male or female, so no one can be a parent here.'));
          return;
        }
        const sex = a.sex === 'M' ? 'F' : 'M';
        const pid = '\u0000partner';
        list = people.concat([{ id: pid, label: 'their partner', sex, affected: false }]);
        [father, mother] = a.sex === 'M' ? [a.id, pid] : [pid, a.id];
        // the partner's chance, from the population: someone unrelated, unaffected, with no children yet
        const alone = ENGINE.analyse([{ id: 'x', sex, affected: false }], m);
        const carries = isRecessive(m.mode) && !(isX(m.mode) && sex === 'M');
        const chance = alone.ok ? (carries ? alone.people.x.one : alone.people.x.variant) : null;
        const who = sex === 'M' ? 'a man' : 'a woman';
        about = `${a.label} and ${who} from the population, who is unaffected, and so ` +
          (chance === 0 ? 'doesn’t have the variant' : `${carries ? 'carries it' : 'has it'} with a chance of ${say(chance)}`);
      } else {
        const c = couples.find((x) => x.key === this.st.couple);
        if (!c) return;
        father = c.father.id;
        mother = c.mother.id;
        about = `${c.father.label} and ${c.mother.label} who isn’t born yet`;
      }
      let r;
      try {
        r = ENGINE.childRisk(list, m, father, mother);
      } catch (e) {
        out.appendChild(h('div.tl-help', cap(e.message) + '.'));
        return;
      }
      if (!r.ok) {
        out.appendChild(h('div.tl-help', r.message));
        return;
      }
      const box = h('div.rk-big');
      const line = (label, val, main) => box.appendChild(h('div.rk-line' + (main ? '.main' : ''), h('span.rk-what', label), h('span.rk-val', say(val))));
      if (!isX(m.mode)) {
        line('Affected', r.any.affected, true);
        if (m.mode === 'AR') line('A carrier (one copy)', r.any.one);
        else line('Has the variant', r.any.variant);
      } else {
        line('A son: affected', r.son.affected, true);
        line('A daughter: affected', r.daughter.affected, true);
        if (m.mode === 'XLR') line('A daughter: a carrier', r.daughter.one);
        line('Before the sex is known: affected', r.any.affected);
      }
      out.append(box, h('div.tl-help', `A child of ${about}.`));
    }

    /** everyone's chances: the person, their status and their chances first, so that a phone shows those without
        scrolling the table sideways */
    _table(order, q, m, all) {
      const tests = this._tests();
      const ar = m.mode === 'AR';
      const head = ['Person', 'Status', ar ? 'Carrier (one copy)' : 'Has the variant', 'Two copies', 'Affected (if not known)', 'Sex', 'Test result'];
      const testSel = (p, x) => {
        const s = h('select.tl-input.small', { 'aria-label': `Test result: ${p.label}` });
        const status = p.status && p.status[this.st.condition];
        const opts = [['', status === 'carrier' ? 'a carrier, as marked' : '—'], ['variant', TESTS.variant]];
        if (isRecessive(m.mode) && !(isX(m.mode) && p.sex === 'M')) opts.push(['carrier', TESTS.carrier]);
        if (!(isX(m.mode) && p.sex === 'M')) opts.push(['homozygous', TESTS.homozygous]);
        opts.push(['none', TESTS.none]);
        if (status === 'carrier') opts.push(['clear', 'not tested (leave out the mark)']);
        // (someone affected or unaffected can be taken as not known: someone young, for a condition of later life)
        if (x.affected !== null || tests[p.id] === 'unknown') opts.push(['unknown', 'status not known (leave it out)']);
        opts.forEach(([v, t]) => s.appendChild(h('option', { value: v }, t)));
        s.value = tests[p.id] && opts.some(([v]) => v === tests[p.id]) ? tests[p.id] : '';
        s.addEventListener('change', () => {
          if (s.value) tests[p.id] = s.value;
          else delete tests[p.id];
          this._save();
          this.update();
        });
        return s;
      };
      const rows = order.map((p) => {
        const x = q.get(p.id), r = all.people[p.id];
        const status = p.status && p.status[this.st.condition];
        let known = status === 'affected' ? 'affected' : status === 'unaffected' ? 'unaffected' : status === 'carrier' ? 'a carrier' : x.affected === false ? 'no record (unaffected)' : 'not known';
        if (p.pregnancy && status !== 'affected' && status !== 'carrier') known = 'a pregnancy';
        else if (p.loss && status !== 'affected' && status !== 'carrier') known = 'a pregnancy loss';
        if (tests[p.id] === 'unknown') known += ' (left out)';
        const pick = h('button.linkbtn', { type: 'button', title: 'Show this person’s chances above' }, h('b', p.label), p.name ? h('small', p.name) : null);
        pick.addEventListener('click', () => {
          this.choose({ person: p.id });
          this.personSel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        });
        return h('tr' + (p.id === this.st.person ? '.on' : ''),
          h('th', pick), h('td', known),
          h('td.rk-n', sayShort(ar ? r.one : r.variant)),
          h('td.rk-n', isX(m.mode) && p.sex === 'M' ? '' : sayShort(r.two)),
          h('td.rk-n', x.affected === null ? sayShort(r.affected) : ''),
          h('td', sexShort(p.sex)), h('td', testSel(p, x)));
      });
      this.tableOut.appendChild(h('table.rk-table.rk-all', h('thead', h('tr', head.map((t) => h('th', t)))), h('tbody', rows)));
      this.allCard.hidden = false;
    }

    /** everyone's chances, as a table in ~/results */
    async saveTable() {
      const fam = this.family;
      if (!fam) return;
      const m = this.model();
      if (!m.q) return;
      const people = this._people(fam);
      let all;
      try {
        all = ENGINE.analyse(people, m);
      } catch (e) {
        toast(esc(cap(e.message)), 'warn');
        return;
      }
      if (!all.ok) {
        toast(esc(all.message), 'warn');
        return;
      }
      const S = MG.app.studio;
      let stem = this.st.source === 'studio' ? (S && S.path ? stemOf(S.path) : 'drawing') : stemOf(this.st.source);
      if (this.families.length > 1) stem += '_' + fam.id;
      const path = `${HOME()}/results/${stem.replace(/[^\w.-]+/g, '_')}_risks.tsv`;
      const cond = (fam.conditions.find((c) => c.key === this.st.condition) || {}).label || '';
      const n6 = (v) => (typeof v === 'number' ? String(Number(v.toPrecision(6))) : '');
      const clean = (s) => String(s == null ? '' : s).replace(/[\t\r\n]+/g, ' ');
      const lines = [['person', 'label', 'text', 'sex', 'status', 'test', 'has_variant', 'one_copy', 'two_copies', 'affected', 'condition', 'mode', 'allele_frequency', 'penetrance', 'phenocopies', 'new_mutations'].join('\t')];
      for (const x of people) {
        const p = fam.people.find((y) => y.id === x.id), r = all.people[x.id];
        const status = x.affected === true ? 'affected' : x.affected === false ? 'unaffected' : 'unknown';
        lines.push([x.id, p.label, p.name, p.sex, status, x.test || '', n6(r.variant), n6(r.one), n6(r.two), n6(r.affected), cond, m.mode, n6(m.q), n6(m.penetrance), n6(m.phenocopy), n6(m.mutation)].map(clean).join('\t'));
      }
      if (this.fs.exists(path) && !(await MG.confirmBox('Replace the table?', `<p>There is already a file <b>${esc(tilde(path))}</b>. Replace it with these chances?</p>`, 'Replace', { danger: true }))) return;
      this.fs.mkdirp(HOME() + '/results');
      this.fs.writeText(path, lines.join('\n') + '\n');
      this.savedOut.innerHTML = '';
      const open = h('button.linkbtn', { type: 'button' }, 'Look at it');
      open.addEventListener('click', () => MG.app.editFile(path));
      this.savedOut.append(h('span', { html: `Saved as <code>${esc(tilde(path))}</code>, a row for each person. ` }), open);
      toast(`Saved everyone’s chances as <b>${esc(tilde(path))}</b>.`, 'ok');
    }

    /* ---------------------------------------------------------------- by hand */
    _handOpen() {
      if (!this.hand) this.hand = buildHand(this.handRoot);
    }
    /** open "by hand" with a cross or a sum: 'ar 1 1', 'xl 1 0', 'ar 1 1 unaffected', 'calc ar 2/3 1/25', 'calc ad 1/2' */
    byHand(spec) {
      this.handBox.open = true;
      this._handOpen();
      if (spec) this.hand.set(spec);
      setTimeout(() => this.handBox.scrollIntoView({ block: 'start', behavior: 'smooth' }), 60);
    }

    /* ---------------------------------------------------------------- from the other tabs */
    shown() {
      // the drawing may have changed in the Studio since
      if (this.st.source === 'studio') this.load();
    }
    /** show a family: {source: 'studio' or a path, person (an id or a label), couple ('A+B', ids or labels), condition
        (a key or a label), mode, freq (a preset: 'carrier:25') or allele (an allele frequency), penetrance, phenocopy
        (%) and mutation (in 100,000)} */
    async open(spec = {}) {
      const st = this.st;
      const src = spec.source || st.source;
      if (src !== st.source) Object.assign(st, { source: src, family: null, person: null, couple: null, single: null });
      if (spec.mode && MODES.some(([m]) => m === spec.mode)) st.mode = spec.mode;
      if (spec.freq && spec.freq !== 'custom' && PRESETS.some(([v]) => v === spec.freq)) {
        const [as, num] = spec.freq.split(':');
        Object.assign(st, { freq: spec.freq, freqAs: as, freqN: Number(num) });
      }
      if (spec.allele != null && Number(spec.allele) > 0 && Number(spec.allele) < 1) {
        // an allele frequency (a simulated family's): one of the choices, if it is one
        const n = Number((1 / Number(spec.allele)).toPrecision(6));
        const preset = PRESETS.find(([v]) => v === `allele:${n}`);
        Object.assign(st, { freq: preset ? preset[0] : 'custom', freqAs: 'allele', freqN: n });
      }
      if (spec.penetrance != null && Number(spec.penetrance) >= 1 && Number(spec.penetrance) <= 100) st.penetrance = Number(spec.penetrance);
      if (spec.phenocopy != null) st.phenocopy = Number(spec.phenocopy) || 0;
      if (spec.mutation != null) st.mutation = Number(spec.mutation) || 0;
      if (spec.person) st.person = spec.person;
      this._sources();
      this._syncModel();
      await this.load();
      const fam = this.family;
      if (!fam) return;
      let again = false;
      if (spec.condition) {
        const want = String(spec.condition).toLowerCase();
        const c = fam.conditions.find((x) => x.key.toLowerCase() === want || x.label.toLowerCase() === want);
        if (c) {
          st.condition = c.key;
          again = true;
        }
      }
      if (spec.couple) {
        const [a, b] = String(spec.couple).split('+').map((x) => this._find(fam, x.trim()));
        const c = a && b && this._couples(fam).find((x) => [a.id, b.id].includes(x.father.id) && [a.id, b.id].includes(x.mother.id));
        if (c) {
          st.couple = c.key;
          again = true;
        }
      }
      if (again) this.update();
      this._save();
    }
  }

  /* ---------------------------------------------------------------- by hand */
  /* What each child of a couple can inherit, drawn as chromosomes, and chances multiplied together into the chance
     that a baby is affected: the Inheritance tab of the pedigree practical (assets/js/inherit.js there), with its state
     kept in the workbench's store. → {set(spec)} */
  function buildHand(root) {
    const st = Object.assign({ pattern: 'ar', mother: 1, father: 1, unaffected: false }, store.get('riskHand', {}));
    st.calc = Object.assign({ mode: 'ar', p1: '2/3', p2: '1/25', p: '1/2' }, st.calc || {});
    const save = () => store.set('riskHand', st);
    const PATTERNS = {
      ar: { name: 'Autosomal recessive', desc: 'A person is affected only if they inherit two faulty copies of the gene, one from each parent. Someone with one faulty copy is a carrier and is not affected.' },
      ad: { name: 'Autosomal dominant', desc: 'One faulty copy is enough to be affected or at risk. Each child of a parent with one faulty copy has a 1 in 2 chance of inheriting it, whatever their sex.' },
      xl: { name: 'X-linked recessive', desc: 'The gene is on the X chromosome. Males have one X, so one faulty copy affects them; females have two X chromosomes, so with one faulty copy they are usually carriers.' }
    };
    const OPTIONS = {
      ar: { mother: [['0', 'Not a carrier'], ['1', 'Carrier'], ['2', 'Affected']], father: [['0', 'Not a carrier'], ['1', 'Carrier'], ['2', 'Affected']] },
      ad: { mother: [['0', 'Unaffected'], ['1', 'Affected (one faulty copy)']], father: [['0', 'Unaffected'], ['1', 'Affected (one faulty copy)']] },
      xl: { mother: [['0', 'Not a carrier'], ['1', 'Carrier'], ['2', 'Affected (two faulty X)']], father: [['0', 'Unaffected'], ['1', 'Affected']] }
    };
    function chrom(x, faulty, kind) {
      const tall = kind !== 'Y';
      const hgt = tall ? 46 : 26, y = tall ? 4 : 24, w = 11;
      const notch = y + hgt * 0.4;
      const band = faulty ? `<rect x="${x + 1}" y="${y + hgt * 0.18}" width="${w - 2}" height="6" fill="#d62828"/>` : `<rect x="${x + 1}" y="${y + hgt * 0.18}" width="${w - 2}" height="6" fill="#fff" stroke="#8a99ad" stroke-width="0.6"/>`;
      return `<g><path d="M${x} ${y + 5} a5.5 5.5 0 0 1 ${w} 0 V${notch - 2} l-2 2 l2 2 V${y + hgt - 5} a5.5 5.5 0 0 1 -${w} 0 V${notch + 2} l2 -2 l-2 -2 Z" fill="#f4f7fb" stroke="#33465c" stroke-width="1.3"/>${band}${kind === 'X' || kind === 'Y' ? `<text x="${x + w / 2}" y="${y + hgt + 10}" font-size="8" text-anchor="middle" fill="#647086" font-family="system-ui,sans-serif">${kind}</text>` : ''}</g>`;
    }
    const pairSVG = (pair) => `<svg class="inh-pair" viewBox="0 0 44 62" width="44" height="62" aria-hidden="true">${chrom(8, pair[0].faulty, pair[0].kind)}${chrom(25, pair[1].faulty, pair[1].kind)}</svg>`;
    const oneSVG = (c) => `<svg class="inh-one" viewBox="0 0 22 62" width="22" height="62" aria-hidden="true">${chrom(5, c.faulty, c.kind)}</svg>`;
    function parentChroms(pattern, who, n) {
      if (pattern === 'xl') {
        if (who === 'mother') return [{ faulty: n >= 1, kind: 'X' }, { faulty: n >= 2, kind: 'X' }];
        return [{ faulty: n >= 1, kind: 'X' }, { faulty: false, kind: 'Y' }];
      }
      return [{ faulty: n >= 1, kind: 'A' }, { faulty: n >= 2, kind: 'A' }];
    }
    function childStatus(pattern, pair) {
      const f = pair.filter((c) => c.faulty).length;
      if (pattern === 'xl') {
        if (pair.some((c) => c.kind === 'Y')) return { sex: 'son', status: f ? 'affected' : 'unaffected' };
        return { sex: 'daughter', status: f === 2 ? 'affected' : f === 1 ? 'carrier' : 'unaffected' };
      }
      if (pattern === 'ad') return { status: f ? 'affected' : 'unaffected' };
      return { status: f === 2 ? 'affected' : f === 1 ? 'carrier' : 'unaffected' };
    }
    const WORD = { affected: 'Affected', carrier: 'Carrier', unaffected: 'Unaffected' };
    const gcd = (a, b) => (b ? gcd(b, a % b) : Math.abs(a));
    const frac = (n, d) => {
      const g = gcd(n, d) || 1;
      return { n: n / g, d: d / g };
    };
    const decimal = (v) => frac(Math.round(v * 10000), 10000);
    function parseFrac(s) {
      s = String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
      let m = /^(\d+)\s*\/\s*(\d+)$/.exec(s) || /^(\d+) in (\d+)$/.exec(s);
      if (m && +m[2] > 0 && +m[1] <= +m[2]) return frac(+m[1], +m[2]);
      m = /^(\d*\.?\d+)\s*%$/.exec(s);
      if (m) {
        const v = parseFloat(m[1]) / 100;
        return v >= 0 && v <= 1 ? decimal(v) : null;
      }
      m = /^(\d*\.?\d+)$/.exec(s);
      if (m) {
        const v = parseFloat(m[1]);
        return v >= 0 && v <= 1 ? decimal(v) : null;
      }
      return null;
    }
    const mul = (a, b) => frac(a.n * b.n, a.d * b.d);
    function show(fr) {
      if (!fr || !fr.d) return '–';
      if (fr.n === 0) return '0';
      const pct = (100 * fr.n) / fr.d, oneIn = fr.d / fr.n;
      return `<b>${fr.n}/${fr.d}</b> = ${Number.isInteger(oneIn) ? `1 in ${oneIn}` : `about 1 in ${Math.round(oneIn)}`} (${pct >= 1 ? pct.toFixed(pct < 10 ? 1 : 0) : pct.toPrecision(2)}%)`;
    }
    const PRESETS_AR = [['1', '1 – known carrier (e.g. tested)'], ['2/3', '2/3 – unaffected brother or sister of someone affected'], ['1/2', '1/2 – child of a known carrier'], ['1/25', '1/25 – CF carrier chance, northern European population'], ['custom', 'Something else…']];
    const PRESETS_AD = [['1', '1 – has the variant'], ['1/2', '1/2 – child of someone with the variant'], ['1/4', '1/4 – grandchild, parent untested'], ['custom', 'Something else…']];
    function presetSel(key, val, presets, label) {
      const isPreset = presets.some((p) => p[0] === val);
      return `<select data-pkey="${key}" aria-label="${esc(label)}">${presets.map(([v, t]) => `<option value="${v}"${(isPreset ? v === val : v === 'custom') ? ' selected' : ''}>${t}</option>`).join('')}</select><input type="text" data-pin="${key}" value="${esc(val)}" ${isPreset ? 'hidden' : ''} placeholder="e.g. 1/4" aria-label="${esc(label)}, as a fraction">`;
    }
    function summary(kids) {
      const pick = st.unaffected ? kids.filter((k) => k.status !== 'affected') : kids;
      const cnt = (fn) => pick.filter(fn).length;
      const fr = (a, b) => {
        if (!a) return 'no';
        const g = gcd(a, b);
        return `${a / g} in ${b / g}`;
      };
      if (st.pattern === 'xl') {
        const sons = pick.filter((k) => k.sex === 'son'), dau = pick.filter((k) => k.sex === 'daughter');
        const s = (list, status) => fr(list.filter((k) => k.status === status).length, list.length);
        return `<p><b>Each son</b>: ${s(sons, 'affected')} chance of being affected.</p><p><b>Each daughter</b>: ${s(dau, 'affected')} chance of being affected, ${s(dau, 'carrier')} of being a carrier.</p>`;
      }
      if (st.pattern === 'ad') return `<p><b>Each child</b>, son or daughter: ${fr(cnt((k) => k.status === 'affected'), pick.length)} chance of inheriting a faulty copy.</p>`;
      if (st.unaffected) return `<p>Of the <b>three</b> ways to be unaffected, <b>two</b> are carriers. So an unaffected child has a <b>${fr(cnt((k) => k.status === 'carrier'), pick.length)}</b> chance of being a carrier – not 1 in 2.</p>`;
      return `<p><b>Each child</b>: ${fr(cnt((k) => k.status === 'affected'), pick.length)} affected, ${fr(cnt((k) => k.status === 'carrier'), pick.length)} a carrier, ${fr(cnt((k) => k.status === 'unaffected'), pick.length)} neither.</p>`;
    }
    function result() {
      const c = st.calc;
      if (c.mode === 'ad') {
        const p = parseFrac(c.p);
        return p ? mul(p, frac(1, 2)) : null;
      }
      const a = parseFrac(c.p1), b = parseFrac(c.p2);
      return a && b ? mul(mul(a, b), frac(1, 4)) : null;
    }
    function calcHTML() {
      const c = st.calc;
      if (c.mode === 'ad') {
        return `<div class="calc-row"><span>Chance the parent has the variant</span>${presetSel('p', c.p, PRESETS_AD, 'Chance the parent has the variant')}</div>
          <div class="calc-row"><span>× chance of passing it on</span><b>1/2</b></div>
          <div class="calc-res">= ${show(result())}</div>`;
      }
      return `<div class="calc-row"><span>Chance parent 1 is a carrier</span>${presetSel('p1', c.p1, PRESETS_AR, 'Chance parent 1 is a carrier')}</div>
        <div class="calc-row"><span>× chance parent 2 is a carrier</span>${presetSel('p2', c.p2, PRESETS_AR, 'Chance parent 2 is a carrier')}</div>
        <div class="calc-row"><span>× chance two carriers have an affected child</span><b>1/4</b></div>
        <div class="calc-res">= ${show(result())}</div>`;
    }
    function render() {
      const opts = OPTIONS[st.pattern];
      if (!opts.mother.some((o) => +o[0] === st.mother)) st.mother = 1;
      if (!opts.father.some((o) => +o[0] === st.father)) st.father = 0;
      const m = parentChroms(st.pattern, 'mother', st.mother), f = parentChroms(st.pattern, 'father', st.father);
      const kids = [];
      m.forEach((mc, i) => f.forEach((fc, j) => kids.push(Object.assign({ i, j, pair: [mc, fc] }, childStatus(st.pattern, [mc, fc])))));
      const canCondition = st.pattern === 'ar' && kids.some((k) => k.status === 'affected') && kids.some((k) => k.status !== 'affected');
      if (!canCondition) st.unaffected = false;
      const sel = (who) => `<select data-who="${who}" aria-label="${who === 'mother' ? 'Mother' : 'Father'}">${opts[who].map(([v, t]) => `<option value="${v}"${+v === st[who] ? ' selected' : ''}>${t}</option>`).join('')}</select>`;
      const gam = (list, who) => list.map((c) => `<div class="inh-gam">${oneSVG(c)}<span>${who === 'mother' ? 'egg' : 'sperm'}</span></div>`).join('');
      let grid = '<table class="inh-grid"><tr><th></th>' + f.map((c) => `<th>${oneSVG(c)}</th>`).join('') + '</tr>';
      m.forEach((mc, i) => {
        grid += `<tr><th>${oneSVG(mc)}</th>`;
        f.forEach((fc, j) => {
          const k = kids.find((x) => x.i === i && x.j === j);
          grid += `<td class="inh-kid ${k.status}${st.unaffected && k.status === 'affected' ? ' out' : ''}">${pairSVG(k.pair)}<span class="inh-lab">${k.sex ? (k.sex === 'son' ? 'Son: ' : 'Daughter: ') : ''}${WORD[k.status]}</span></td>`;
        });
        grid += '</tr>';
      });
      grid += '</table>';
      const seg = (attr, items, on) => items.map(([k, label]) => `<button type="button" class="${k === on ? 'on' : ''}" aria-pressed="${k === on}" data-${attr}="${k}">${label}</button>`).join('');
      root.innerHTML = `
        <div class="inh">
          <div class="rk-seg" role="group" aria-label="Pattern of inheritance">${seg('pattern', Object.entries(PATTERNS).map(([k, v]) => [k, v.name]), st.pattern)}</div>
          <p class="inh-desc">${esc(PATTERNS[st.pattern].desc)}</p>
          <div class="inh-parents">
            <div class="inh-parent"><div class="inh-ptitle">Mother</div>${pairSVG(m)}${sel('mother')}</div>
            <div class="inh-x">×</div>
            <div class="inh-parent"><div class="inh-ptitle">Father</div>${pairSVG(f)}${sel('father')}</div>
          </div>
          <div class="inh-gametes"><div><div class="inh-gt">Her eggs</div><div class="inh-gl">${gam(m, 'mother')}</div></div><div><div class="inh-gt">His sperm</div><div class="inh-gl">${gam(f, 'father')}</div></div></div>
          <div class="inh-gridwrap"><div class="inh-gt">Each pregnancy is one of these four, equally likely</div>${grid}</div>
          ${canCondition ? `<label class="inh-cond"><input type="checkbox" data-unaffected${st.unaffected ? ' checked' : ''}> We already know this child is <b>unaffected</b></label>` : ''}
          <div class="inh-sum">${summary(kids)}</div>
          <p class="inh-key"><span class="sw red"></span>faulty copy of the gene <span class="sw white"></span>working copy</p>
        </div>
        <div class="inh inh-calc">
          <h4>Chance that a baby is affected</h4>
          <div class="rk-seg" role="group" aria-label="Calculator">${seg('calc', [['ar', 'Recessive'], ['ad', 'Dominant']], st.calc.mode)}</div>
          ${calcHTML()}
          <p class="tl-help">Multiplying chances like this is right when each comes from a different part of the family. The Risk tab, above, works out each chance from the whole family at once, and so allows for what each person’s relatives tell you about them as well.</p>
        </div>`;
      root.querySelectorAll('[data-pattern]').forEach((b) => b.addEventListener('click', () => {
        st.pattern = b.dataset.pattern;
        changed();
      }));
      root.querySelectorAll('select[data-who]').forEach((s) => s.addEventListener('change', () => {
        st[s.dataset.who] = +s.value;
        changed();
      }));
      const u = root.querySelector('[data-unaffected]');
      if (u) u.addEventListener('change', () => {
        st.unaffected = u.checked;
        changed();
      });
      root.querySelectorAll('[data-calc]').forEach((b) => b.addEventListener('click', () => {
        st.calc.mode = b.dataset.calc;
        changed();
      }));
      root.querySelectorAll('select[data-pkey]').forEach((s) => s.addEventListener('change', () => {
        const inp = root.querySelector(`[data-pin="${s.dataset.pkey}"]`);
        if (s.value === 'custom') {
          inp.hidden = false;
          inp.focus();
          return;
        }
        st.calc[s.dataset.pkey] = s.value;
        changed();
      }));
      root.querySelectorAll('input[data-pin]').forEach((inp) => {
        const apply = () => {
          if (parseFrac(inp.value)) {
            st.calc[inp.dataset.pin] = inp.value.trim();
            changed();
          } else inp.classList.add('bad');
        };
        inp.addEventListener('change', apply);
        inp.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            apply();
          }
        });
      });
    }
    function changed() {
      save();
      render();
    }
    /* a cross or a sum, from the help: 'ar 1 1', 'xl 1 0', 'ar 1 1 unaffected', 'calc ar 2/3 1/25', 'calc ad 1/2' */
    function set(spec) {
      const p = String(spec).trim().split(/\s+/);
      if (p[0] === 'calc') {
        st.calc.mode = p[1] === 'ad' ? 'ad' : 'ar';
        if (st.calc.mode === 'ad') {
          if (p[2]) st.calc.p = p[2];
        } else {
          if (p[2]) st.calc.p1 = p[2];
          if (p[3]) st.calc.p2 = p[3];
        }
      } else {
        if (PATTERNS[p[0]]) st.pattern = p[0];
        if (p[1] != null) st.mother = +p[1];
        if (p[2] != null) st.father = +p[2];
        st.unaffected = p.includes('unaffected');
      }
      changed();
    }
    render();
    return { set, parseFrac };
  }

  MG.RiskTab = RiskTab;
  MG.app = MG.app || {};
  MG.actions = MG.actions || {};
  /** the Risk tab, showing a family: {source: 'studio'} for the drawing in the Studio, or {source: path}; and a
      person, a couple, a condition and a model, if wanted (RiskTab.open) */
  MG.app.riskOpen = async (spec = {}) => {
    await MG.app.showWorkbench('risk');
    const T = await MG.app.waitFor(() => MG.app.risk, 8000);
    if (!T) return;
    await T.ready;
    const s = Object.assign({}, spec);
    if (s.source && s.source !== 'studio') s.source = MG.app.fs.resolve(String(s.source).replace(/^~(?=\/|$)/, MG.app.HOME));
    await T.open(s);
  };
  /* the help's buttons: data-risk="studio" or a file, with data-person, data-couple, data-condition, data-mode,
     data-freq, data-penetrance, data-phenocopy and data-mutation; and data-inherit="ar 1 1" (by hand). A button
     with a mode sets the whole model, as the help describes it: what it doesn't give is as the tab starts */
  MG.actions.risk = (value, btn) => {
    const ds = (btn && btn.dataset) || {};
    const model = ds.mode ? { mode: ds.mode, freq: ds.freq || DEFAULTS.freq, penetrance: ds.penetrance || DEFAULTS.penetrance, phenocopy: ds.phenocopy || 0, mutation: ds.mutation || 0 } : {};
    return MG.app.riskOpen(Object.assign({ source: value || 'studio', person: ds.person, couple: ds.couple, condition: ds.condition }, model));
  };
  MG.actions.inherit = async (value) => {
    await MG.app.showWorkbench('risk');
    const T = await MG.app.waitFor(() => MG.app.risk, 8000);
    if (T) T.byHand(value);
  };
})();
