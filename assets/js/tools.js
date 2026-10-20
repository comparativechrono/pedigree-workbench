/* =====================================================================
   The Tools tab: the Python packages, point and click.

   Each tool is a form for one command of one package. Running it runs
   that command in the workbench's Python, exactly as the terminal would
   (pedwb.gui.run), so the tab also shows the same command for the
   terminal and the same thing in Python, to copy or to run there.

   The tools are described in TOOLS below: a tool's fields, the command
   they make (argv), what it writes (outputs) and its Python (python).
   The first page is a map of the formats and the tools between them,
   with the tasks most people come for; a file's page (forFile) lists
   what can be done with that file.

   The Match terms tool has a page of its own (TermsTool, below).

   PedNet, PedGen and PedInterp are loaded into Python the first time
   one of their tools runs (py-worker.js), which can take a while: what
   is being loaded is shown under the form.
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, toast, store, bus } = MG;

  /* ------------------------------------------------------------------ small helpers */
  const HOME = () => MG.app.HOME;
  const expand = (p) => String(p || '').replace(/^~(?=\/|$)/, HOME());
  const tilde = (p) => (p === HOME() ? '~' : String(p).startsWith(HOME() + '/') ? '~' + String(p).slice(HOME().length) : String(p));
  const shq = (s) => (/^[\w@%+=:,./~-]+$/.test(s) ? s : "'" + String(s).replace(/'/g, "'\\''") + "'");
  /** a path or word for the terminal: ~/my lynch.png → ~/'my lynch.png' (a ~ in quotes isn't the home folder) */
  const shArg = (s) => {
    const t = tilde(s);
    return /^~\//.test(t) && shq(t) !== t ? '~/' + shq(t.slice(2)) : shq(t);
  };
  const pyq = (s) => JSON.stringify(String(s));
  const base = (p) => String(p || '').split('/').pop();
  const dirOf = (p) => MG.path.dirname(p);
  /** the name of a file without its kind's ending: okafor.studio.json → okafor */
  const stemOf = (p) =>
    base(p)
      .replace(/(_ga4gh-pedigree|_phenopackets-family|\.normalised|\.upgraded|\.deidentified|-genotypes)?\.(studio\.json|json|ya?ml|ped|mped|fam|obo|tsv|jsonl|png|jpe?g|gif|bmp|tiff?|webp|vcf|vcf\.gz|graphml)$/i, '')
      .replace(/^$/, 'family') || 'family';
  const joinPath = (dir, name) => expand(dir).replace(/\/+$/, '') + '/' + name;
  const GA4GH = ['pedigree', 'family', 'cohort', 'phenopacket'];
  // (the kinds of file the Risk tab reads)
  const RISK_KINDS = ['studio', 'ped', 'mped', 'pedigree', 'family'];
  const KIND = () => MG.app.kindNames || {};
  const icon = (n) => MG.icon(n);

  /* ------------------------------------------------------------------ Python */
  const kernel = () => MG.kernels.get();
  /** a function of the packages, by name → {ok, result, error, stdout, stderr, files: the paths it wrote}.
      onStatus(text): what Python is loading for it, if anything (PedNet and NumPy, say, the first time) */
  async function pyCall(fn, args, onStatus) {
    const r = await kernel().call(fn, args, onStatus ? { handlers: { onStatus } } : {});
    const files = ((r.changes && r.changes.files) || []).map((f) => f.path);
    return Object.assign({}, r, { files });
  }
  /** a command line, as the terminal runs it → {ok, code, stdout, stderr, files, error} */
  async function runArgv(argv, onStatus) {
    const r = await pyCall('pedwb.gui.run', { argv }, onStatus);
    if (!r.ok && r.kind === 'LoadError') throw new Error(r.error);
    if (!r.ok) return { ok: false, code: 1, stdout: r.stdout || '', stderr: (r.stderr || '') + (r.error || ''), files: r.files, error: r.error, traceback: r.traceback };
    return { ok: r.result.code === 0, code: r.result.code, stdout: r.result.stdout, stderr: r.result.stderr, files: r.files };
  }
  MG.app.pyCall = pyCall;

  /** a picture's size in pixels, {width, height}, or null if the browser can't show it (a TIFF, in most) */
  async function pictureSize(fs, path) {
    if (!path || !fs.exists(path)) return null;
    const url = URL.createObjectURL(await fs.toBlob(path));
    try {
      return await new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve(img.naturalWidth ? { width: img.naturalWidth, height: img.naturalHeight } : null);
        img.onerror = () => resolve(null);
        img.src = url;
      });
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  /* ------------------------------------------------------------------ the tools */
  const GROUPS = [
    ['start', 'Start', 'route'],
    ['convert', 'Convert', 'convert'],
    ['terms', 'Ontology terms', 'tag'],
    ['check', 'Check and look inside', 'badgeCheck'],
    ['share', 'Prepare to share', 'eyeOff'],
    ['ped', 'PED and MPED files', 'table'],
    ['analyse', 'Analyse and simulate', 'network']
  ];
  const optArgs = (cond, ...a) => (cond ? a : []);
  /** a number for a command line and for Python: 0.6, not '0.60' or '.6' */
  const num = (x) => String(Number(x));
  /** the family id of a PED file to write: one word */
  const oneWord = (label, x) => (!String(x || '').trim() ? `Give the ${label}.` : /\s/.test(String(x)) ? `The ${label} must be one word, with no spaces: PED files are split at spaces.` : '');
  const PENETRANCE = '0.6,0.8,0.95,0.99';
  /** penetrances as given (0.6 0.8, or 0.6, 0.8) → as the command takes them: 0.6,0.8 */
  const penList = (x) => String(x || '').trim().split(/[\s,]+/).filter(Boolean).map(num).join(',');
  const ALL_MODES = 'AD,AR,XLR,XLD';
  /** the enlargement given for Picture → PED file, or '' to leave it to PedInterp */
  const upscaleOf = (v) => String(v.upscale == null ? '' : v.upscale).trim();
  /** the families of a PED file, in Python, for PedNet's tools */
  /** a GA4GH Pedigree or Phenopackets Family, which PedNet reads as well as PED files */
  const isGA4GHFile = (p) => ['pedigree', 'family'].includes(MG.app.pedKind(p || ''));
  const readFamilies = (v) => {
    if (!isGA4GHFile(v.input)) return `families = pednet.read_ped(${pyq(v.input)}${v.family ? `, ${pyq(v.family)}` : ''})   # {family id: pedigree}`;
    const opts = [v.family ? `family=${pyq(v.family)}` : '', (v.condition || '').trim() ? `condition=${pyq(v.condition.trim())}` : '', v.unrecorded ? `unrecorded=${pyq(v.unrecorded)}` : ''].filter(Boolean);
    return `families = pednet.read_ga4gh(${pyq(v.input)}${opts.map((o) => ', ' + o).join('')})   # {family id: pedigree}`;
  };
  /** PedNet's options for a GA4GH file: the condition, and what people with no record of it are taken to be */
  const ga4ghArgs = (v) => (isGA4GHFile(v.input) ? [...optArgs((v.condition || '').trim(), '--condition', (v.condition || '').trim()), ...optArgs(v.unrecorded, '--unrecorded', v.unrecorded)] : []);
  const GA4GH_FIELDS = [
    { key: 'condition', type: 'text', label: 'Condition (optional)', def: '', placeholder: 'any of the file’s conditions', show: (v) => isGA4GHFile(v.input), help: 'For a GA4GH file that names several conditions, the one that makes someone affected, by its ontology id or its name, such as HP:0000365 or Hearing impairment. Without one, anyone with any of them is affected, and a Phenopackets Family’s own record of who is affected is used.' },
    { key: 'unrecorded', type: 'select', label: 'People with no record of the condition', def: '', options: [['', 'as the file suggests'], ['unaffected', 'unaffected'], ['unknown', 'not known']], show: (v) => isGA4GHFile(v.input), help: 'A GA4GH Pedigree records who has a condition, but only sometimes who doesn’t. As the file suggests: unaffected if no one in it is recorded as not having it, as in the files studio2ga4gh writes, and not known if anyone is, as in those PedGen and PedInterp write.' }
  ];
  /** a GA4GH file's condition, for PedGen and PedInterp: an ontology term and its name, or both left empty */
  const CONDITION_FIELDS = [
    { key: 'condId', type: 'text', label: 'The condition’s ontology term (optional)', def: '', placeholder: 'e.g. MONDO:0007739', show: (v) => v.ga4gh, help: 'Without one, the GA4GH Pedigree names the condition MONDO:0000001, disease.' },
    { key: 'condLabel', type: 'text', label: 'Its name', def: '', placeholder: 'e.g. Huntington disease', show: (v) => v.ga4gh && (v.condId || '').trim() }
  ];
  const conditionOf = (v) => (v.ga4gh && (v.condId || '').trim() ? [v.condId.trim(), (v.condLabel || '').trim()] : null);
  const checkCondition = (v) => {
    const c = conditionOf(v);
    if (!c) return '';
    if (!/^[A-Za-z][\w.-]*:\S+$/.test(c[0])) return 'Give the condition’s ontology term as a prefix and a number, such as MONDO:0007739 or HP:0000365.';
    return c[1] ? '' : 'Give the condition’s name too, such as Huntington disease.';
  };
  const conditionPy = (v) => {
    const c = conditionOf(v);
    return c ? `, condition=(${pyq(c[0])}, ${pyq(c[1])})` : '';
  };
  /** the file of ids for phenotk filter --id-list ('' when no ids are given) */
  const idFile = (v) => ((v.ids || '').trim() && v.out ? joinPath(dirOf(v.out), stemOf(v.out) + '-ids.txt') : '');

  const TOOLS = [
    /* ---------------- Convert ---------------- */
    {
      id: 'studio2ga4gh',
      group: 'convert',
      title: 'Drawing → GA4GH Pedigree and Phenopackets',
      pkg: 'studio2ga4gh',
      what: 'Write a drawing as a GA4GH Pedigree and a Phenopackets Family, the standard files for sharing a family’s pedigree and findings.',
      about:
        'Each person becomes a Phenopacket, and the lines between people become relationships named with KIN’s kinship terms. The conditions in the colour key go in as the Mondo terms (for diseases) or HPO terms (for phenotypes) that you give them in a <b>terms file</b>. A condition without a term is left out, because the files have no place for a condition that is only a name. People are named by their pedigree numbers (II-3) unless you choose otherwise.',
      help: 'h-tool-studio2ga4gh',
      fields: [
        { key: 'input', type: 'file', label: 'The drawing', kinds: ['studio'], studio: true },
        { key: 'terms', type: 'file', label: 'Terms for its conditions', kinds: ['terms'], optional: true, none: 'none (conditions are left out)', conditions: true },
        { key: 'ids', type: 'select', label: 'People are named by', def: 'numbers', options: [['numbers', 'pedigree numbers, such as II-3'], ['drawing', 'the labels in the drawing (these may be names)'], ['studio', 'Pedigree Studio’s own ids']] },
        { key: 'family', type: 'text', label: 'Family id', def: 'FAM', help: 'The default, FAM, gives FAM1, then FAM2 and so on if the drawing holds more than one family.' },
        { key: 'only', type: 'select', label: 'Files to write', def: '', options: [['', 'both the GA4GH Pedigree and the Phenopackets Family'], ['pedigree', 'the GA4GH Pedigree only'], ['family', 'the Phenopackets Family only']] },
        { key: 'outdir', type: 'folder', label: 'Save in', def: '~/results' },
        { key: 'prefix', type: 'text', label: 'Start of the file names', def: (v) => stemOf(v.input) }
      ],
      argv: (v) => ['studio2ga4gh', v.input, '-d', v.outdir, '-o', v.prefix, ...optArgs(v.terms, '-t', v.terms), ...optArgs(v.ids !== 'numbers', '--ids', v.ids), ...optArgs(v.family && v.family !== 'FAM', '--family-id', v.family), ...optArgs(v.only, '--only', v.only)],
      outputs: (v) => [v.only !== 'family' && joinPath(v.outdir, v.prefix + '_ga4gh-pedigree.json'), v.only !== 'pedigree' && joinPath(v.outdir, v.prefix + '_phenopackets-family.json')].filter(Boolean),
      python: (v) =>
        [
          'import json',
          'from studio2ga4gh import convert_file',
          '',
          v.terms ? `terms = json.load(open(${pyq(v.terms)}))` : 'terms = None   # a terms file: {"Condition name": "MONDO:…", …}',
          `result = convert_file(${pyq(v.input)}, ${pyq(v.prefix)}, ${pyq(v.outdir)},`,
          `                      terms=terms, ids=${pyq(v.ids)}, family_id=${pyq(v.family || 'FAM')}${v.only ? `, outputs=(${pyq(v.only)},)` : ''})`,
          'print(result.summary)',
          'for path, _ in result.files:',
          '    print("wrote", path)',
          'for note in result.warnings:',
          '    print("note:", note)'
        ].join('\n')
    },
    {
      id: 'ga4gh2studio',
      group: 'convert',
      title: 'GA4GH or Phenopackets → drawing',
      pkg: 'ga4gh2studio',
      what: 'Draw a GA4GH Pedigree or a Phenopackets Family in Pedigree Studio, with its conditions in the colour key.',
      about:
        'The family is laid out from its relationships. Each condition gets a colour, and the key names it with its term (“breast cancer [MONDO:0007254]”), so the drawing converts back to the same terms. Files made by older versions of our tools need upgrading first (Check and look inside → Upgrade a file from an older tool).',
      help: 'h-tool-ga4gh2studio',
      fields: [
        { key: 'input', type: 'file', label: 'The GA4GH file', kinds: ['pedigree', 'family'] },
        { key: 'out', type: 'path', label: 'Save the drawing as', def: (v) => `~/pedigrees/${stemOf(v.input)}.studio.json` },
        { key: 'tidy', type: 'check', label: 'Tidy the drawing when it opens', def: true, gui: true }
      ],
      argv: (v) => ['ga4gh2studio', v.input, '-o', v.out],
      outputs: (v) => [v.out],
      python: (v) => ['from ga4gh2studio import convert_file', '', `result = convert_file(${pyq(v.input)}, None, ${pyq(v.out)})`, 'print(result.summary)', 'for note in result.warnings:', '    print("note:", note)'].join('\n'),
      next: (res, v) => [['pedigree', 'Open the drawing in Studio', () => MG.app.studioOpen(v.out, { tidy: v.tidy })]]
    },
    {
      id: 'studio2ped',
      group: 'convert',
      title: 'Drawing → PED or MPED',
      pkg: 'studio2ped',
      what: 'Write a drawing as a PED file for linkage and association programs (an MPED file when it shows several conditions or carriers).',
      about:
        'A PED file has one line per person, giving their family, their id, their father and mother, their sex and whether they are affected. The father and mother are the genetic parents, so an adopted child, or a child carried by a surrogate, gets 0 in place of those parents. studio2ped names people by their pedigree numbers (II-3), as the GA4GH files do. It can use the drawing’s labels or the text under the symbols instead, but these are often names, so check them before you share the file. If an id would be empty, 0 or shared by two people, the pedigree number is used instead. The “no children” and “infertility” bars are left out, as they aren’t people.',
      help: 'h-tool-studio2ped',
      fields: [
        { key: 'input', type: 'file', label: 'The drawing', kinds: ['studio'], studio: true },
        { key: 'outdir', type: 'folder', label: 'Save in', def: '~/results' },
        { key: 'prefix', type: 'text', label: 'Start of the file name', def: (v) => stemOf(v.input) },
        { key: 'ids', type: 'select', label: 'People are named by', def: 'numbers', options: [['numbers', 'pedigree numbers, such as II-3'], ['drawing', 'the labels in the drawing (these may be names)'], ['studio', 'Pedigree Studio’s own ids'], ['text', 'the text under the symbols, as version 0.1 did (often names)']] }
      ],
      argv: (v) => ['studio2ped', v.input, '-d', v.outdir, '-o', v.prefix, ...optArgs(v.ids && v.ids !== 'numbers', '--ids', v.ids)],
      python: (v) => ['from studio2ped import convert_file', '', `result = convert_file(${pyq(v.input)}, output_prefix=${pyq(v.prefix)}, output_dir=${pyq(v.outdir)}${v.ids && v.ids !== 'numbers' ? `, ids=${pyq(v.ids)}` : ''})`, 'print(result.summary)', 'for path, _ in result.files:', '    print("wrote", path)', 'for note in result.notes:', '    print("note:", note)'].join('\n'),
      after: async (res, v, out) => {
        // the PED files it wrote, checked with mpedtools
        for (const f of res.files.filter((p) => /\.m?ped$/i.test(p))) {
          const r = await runArgv(['mpedtools', 'validate', f]);
          const text = (r.stdout || '').trim();
          if (r.code) out.appendChild(h('div.tl-warn', h('b', `${tilde(f)}: `), 'mpedtools found problems in this file:', h('pre.tl-pre', text), h('p', 'Look at the people and lines it mentions in the drawing. If people aren’t named by their pedigree numbers, check their labels too.')));
          else out.appendChild(h('div.tl-ok', h('b', `${tilde(f)}: `), text || 'valid'));
        }
      }
    },
    {
      id: 'ped2studio',
      group: 'convert',
      title: 'PED or MPED → drawing',
      pkg: 'ped2studio',
      what: 'Draw a PED file in Pedigree Studio: the people, their parents, and who is affected.',
      about:
        'Founders, couples and their children are laid out generation by generation, and affected people (status 2) are filled in with the colour you choose. Pedigree Studio’s Tidy usually makes the drawing neater. A PED file says nothing about twins, deaths or adoptions, so add those in the Studio.',
      help: 'h-tool-ped2studio',
      fields: [
        { key: 'input', type: 'file', label: 'The PED file', kinds: ['ped', 'mped'] },
        { key: 'out', type: 'path', label: 'Save the drawing as', def: (v) => `~/pedigrees/${stemOf(v.input)}.studio.json` },
        { key: 'colour', type: 'colour', label: 'Colour for affected people', def: '#1a2332' },
        { key: 'fill', type: 'select', label: 'Fill', def: 'full', options: [['full', 'the whole symbol'], ['half', 'the left half']] },
        { key: 'shading', type: 'check', label: 'Shade with a pattern instead of filling', def: false },
        { key: 'pattern', type: 'select', label: 'Pattern', def: 'stripes', options: [['stripes', 'stripes'], ['dots', 'dots']], show: (v) => v.shading },
        { key: 'tidy', type: 'check', label: 'Tidy the drawing when it opens', def: true, gui: true }
      ],
      argv: (v) => ['ped2studio', v.input, v.out, ...optArgs(v.colour && v.colour.toLowerCase() !== '#1a2332', '--colour', v.colour), ...optArgs(v.shading, '--shading'), ...optArgs(v.shading && v.pattern !== 'stripes', '--pattern', v.pattern), ...optArgs(v.fill !== 'full', '--fill', v.fill)],
      outputs: (v) => [v.out],
      python: (v) =>
        ['from ped2studio import convert_file', '', `session = convert_file(${pyq(v.input)}, ${pyq(v.out)},`, `                       affected_color=${pyq(v.colour || '#1a2332')}, use_shading=${v.shading ? 'True' : 'False'},`, `                       shading_pattern=${pyq(v.pattern || 'stripes')}, fill_type=${pyq(v.fill || 'full')})`, 'print(len(session["persons"]), "people")'].join('\n'),
      next: (res, v) => [['pedigree', 'Open the drawing in Studio', () => MG.app.studioOpen(v.out, { tidy: v.tidy })]]
    },
    {
      id: 'ga4gh-convert',
      group: 'convert',
      title: 'GA4GH Pedigree ⇄ Phenopackets Family',
      pkg: 'phenotk',
      what: 'Turn a GA4GH Pedigree into a Phenopackets Family, or the other way round.',
      about:
        'The two hold the same family in different ways. A GA4GH Pedigree lists everyone and the KIN relationships between them, while a Phenopackets Family has a proband, the relatives with findings, and a pedigree laid out like a PED file. When you make a Family you can choose the proband. Otherwise it’s the pedigree’s index patient, or the first affected person.',
      help: 'h-tool-ga4gh-convert',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: ['pedigree', 'family'] },
        { key: 'to', type: 'select', label: 'Make', def: (v) => (MG.app.pedKind(v.input || '') === 'family' ? 'pedigree' : 'family'), options: [['family', 'a Phenopackets Family'], ['pedigree', 'a GA4GH Pedigree']] },
        { key: 'proband', type: 'text', label: 'Proband (a person’s id; optional)', def: '', show: (v) => v.to === 'family', placeholder: 'e.g. IV-3' },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}_${v.to === 'pedigree' ? 'ga4gh-pedigree' : 'phenopackets-family'}.json` }
      ],
      argv: (v) => ['phenotk', 'convert', v.input, '--to', v.to, '-o', v.out, ...optArgs(v.to === 'family' && v.proband, '--proband', v.proband)],
      outputs: (v) => [v.out],
      python: (v) =>
        ['import phenopacket_toolkit as ptk', 'from phenopacket_toolkit.ops import to_kind', '', `doc = ptk.read(${pyq(v.input)})`, `new, notes = to_kind(doc, ${pyq(v.to)}${v.to === 'family' && v.proband ? `, proband_id=${pyq(v.proband)}` : ''})`, `ptk.write(new, ${pyq(v.out)})`, 'for note in notes:', '    print("note:", note)'].join('\n')
    },
    {
      id: 'export',
      group: 'convert',
      title: 'GA4GH → PED, table or YAML',
      pkg: 'phenotk',
      what: 'Write a GA4GH or Phenopackets file as a PED file, a table (TSV) of people and terms, YAML or JSON Lines.',
      about:
        'The PED file uses the people’s ids from the GA4GH file, which are pedigree numbers if studio2ga4gh made it. From a Phenopackets Family, people its pedigree marks as unaffected get 1. From a GA4GH Pedigree, people without a condition get 0 (unknown), because a GA4GH Pedigree doesn’t record that someone is unaffected. The table has one row for each person and term.',
      help: 'h-tool-export',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: GA4GH },
        { key: 'fmt', type: 'select', label: 'Make', def: 'ped', options: [['ped', 'a PED file'], ['tsv', 'a table of people and terms (TSV)'], ['yaml', 'YAML'], ['jsonl', 'JSON Lines (one Phenopacket a line)']] },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}.${{ ped: 'ped', tsv: 'tsv', yaml: 'yaml', jsonl: 'jsonl' }[v.fmt] || 'txt'}` }
      ],
      argv: (v) => ['phenotk', 'convert', v.input, '--to', v.fmt, '-o', v.out],
      outputs: (v) => [v.out],
      python: (v) => {
        const head = ['import phenopacket_toolkit as ptk', '', `doc = ptk.read(${pyq(v.input)})`];
        if (v.fmt === 'yaml') return head.concat([`ptk.write(doc, ${pyq(v.out)}, fmt="yaml")`]).join('\n');
        if (v.fmt === 'jsonl') return head.concat([`ptk.write_many([doc], ${pyq(v.out)})`]).join('\n');
        return ['import phenopacket_toolkit as ptk', 'from phenopacket_toolkit.ops import to_format', '', `doc = ptk.read(${pyq(v.input)})`, `with open(${pyq(v.out)}, "w") as fh:`, `    fh.write(to_format(doc, ${pyq(v.fmt)}))`].join('\n');
      }
    },
    {
      id: 'pedinterp',
      group: 'convert',
      title: 'Picture → PED file',
      pkg: 'PedInterp',
      what: 'Read a picture of a pedigree, such as one in a paper or a clinic letter, and write it as a PED file.',
      about:
        'PedInterp finds the symbols and the lines between them, and so who is male or female, who is affected (a filled symbol), who are partners, parents and children, and which children are twins, and whether they are identical. It reads pictures drawn in the usual way, dark on white, with each generation in a row of its own, such as those Pedigree Studio saves, and, if you tick Drawn by hand, pedigrees sketched roughly, as with the Studio’s Draw tool, or begun with its symbols and finished by hand. The labels by the symbols can’t be read here, because that needs the Tesseract program, which can’t run in a browser. Instead, the people are numbered by generation, from the top, and from the left in each: I-1, I-2, II-1 and so on, as Pedigree Studio numbers them. A PED file can’t hold twins, so they are listed under the table, and a GA4GH Pedigree records them. Half-filled or shaded symbols aren’t read yet, and a sketch may be misread, so compare the PED file with the picture, or draw it, before you use it.',
      help: 'h-tool-pedinterp',
      fields: [
        { key: 'input', type: 'file', label: 'The picture', kinds: ['image'] },
        { key: 'handDrawn', type: 'check', label: 'Drawn by hand', def: false, help: 'For a pedigree sketched by hand, in whole or in part, as with Pedigree Studio’s Draw tool: symbols of unequal sizes, outlines that don’t quite close, filled symbols scribbled in, and lines that wobble and stop short of what they join. Leave it unticked for a picture drawn with software, such as one Pedigree Studio saves.' },
        { key: 'family', type: 'text', label: 'Family id', def: (v) => stemOf(v.input).replace(/\s+/g, '_'), help: 'It names the PED file too.' },
        { key: 'outdir', type: 'folder', label: 'Save in', def: '~/results' },
        { key: 'upscale', type: 'number', label: 'Enlarge the picture by (optional)', def: '', min: 0.25, max: 20, step: 'any', placeholder: 'as much as its symbols need', help: 'PedInterp enlarges the picture so that its symbols are about 200 pixels across (100 for a sketch), which reads best, and says how much under the table. Give a number to enlarge it more or less.' },
        { key: 'ga4gh', type: 'check', label: 'Write a GA4GH Pedigree too', def: false, help: 'FAMILY_ga4gh-pedigree.json, which the GA4GH tools read: ga4gh2studio, phenopacket-toolkit and PedNet, and the Risk tab. The affected have the condition, and the unaffected have it marked as looked for and not found.' },
        ...CONDITION_FIELDS
      ],
      check: (v) => oneWord('family id', v.family) || (upscaleOf(v) && !(Number(v.upscale) > 0) ? 'Enlarge the picture by a number above 0, or leave it empty.' : '') || checkCondition(v),
      argv: (v) => ['pedinterp', v.input, '-f', v.family, '-d', v.outdir, '--labels', 'none', ...optArgs(v.handDrawn, '--hand-drawn'), ...optArgs(upscaleOf(v), '--upscale', num(v.upscale)), ...optArgs(v.ga4gh, '--ga4gh'), ...(conditionOf(v) ? ['--condition', ...conditionOf(v)] : [])],
      outputs: (v) => [joinPath(v.outdir, v.family + '.ped'), v.ga4gh && joinPath(v.outdir, v.family + '_ga4gh-pedigree.json')].filter(Boolean),
      // (what it prints is the table it read, which is better kept whole than wrapped)
      stdoutIsResult: true,
      python: (v) =>
        [`from PedInterp import pedigree_processing, PED_export${v.ga4gh ? ', GA4GH_export' : ''}`, '', `df = pedigree_processing(${pyq(v.family)}, image_path=${pyq(v.input)}, ocr=None${v.handDrawn ? ', hand_drawn=True' : ''}${upscaleOf(v) ? `, upscale_factor=${num(v.upscale)}` : ''})`, 'print(df.to_string(index=False))', 'for twin, other, kind in df.attrs["twins"]:   # [twin, twin, "MZ" (identical) or "DZ"]', '    print("twins:", twin, "and", other, "(identical)" if kind == "MZ" else "(not identical)")', `print(f"(the picture was read enlarged {df.attrs['upscale_factor']:g} times)")`, `print("wrote", PED_export(df, ${pyq(expand(v.outdir).replace(/\/+$/, ''))}))`, ...(v.ga4gh ? [`print("wrote", GA4GH_export(df, ${pyq(expand(v.outdir).replace(/\/+$/, ''))}${conditionPy(v)}))`] : [])].join('\n'),
      next: (res, v) => {
        const ped = joinPath(v.outdir, v.family + '.ped');
        const ga4gh = joinPath(v.outdir, v.family + '_ga4gh-pedigree.json');
        return [
          // (a GA4GH Pedigree holds the twins, which a PED file can't, so the drawing made from it has them too)
          v.ga4gh ? ['pedigree', 'Draw it, with any twins (GA4GH → drawing)', () => MG.app.useTool('ga4gh2studio', { input: ga4gh })]
            : ['pedigree', 'Draw it (PED → drawing)', () => MG.app.useTool('ped2studio', { input: ped })],
          ['network', 'Look at it with PedNet', () => MG.app.useTool('pednet-graph', { input: ped })],
          ['percent', 'Work out its risks', () => MG.app.riskOpen({ source: v.ga4gh ? ga4gh : ped })]
        ];
      }
    },

    /* ---------------- Ontology terms ---------------- */
    {
      id: 'terms',
      group: 'terms',
      title: 'Match conditions to terms',
      pkg: 'hponorm · mondonorm',
      what: 'Find the Mondo or HPO term for each condition in a drawing’s colour key, and keep the matches in a terms file.',
      about: '',
      help: 'h-tool-terms',
      custom: true
    },
    {
      id: 'normalise',
      group: 'terms',
      title: 'Fill in missing terms',
      pkg: 'phenotk',
      what: 'Give terms to the findings in a GA4GH or Phenopackets file that have a name but no id, from a terms file or by looking them up.',
      about:
        'Findings that have a name but no ontology id, which are common in older files, get their id from a terms file. If you allow it, names can also be looked up in the HPO (for phenotypes) or Mondo (for diseases). By default, a looked-up term is used only when the name is its label or one of its synonyms. The tool also tidies the file into the standard form, and writes a log of every decision next to the new file.',
      help: 'h-tool-normalise',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: GA4GH },
        { key: 'mapping', type: 'file', label: 'Terms file', kinds: ['terms'], optional: true, none: 'none' },
        { key: 'lookup', type: 'select', label: 'Look up names without a term', def: 'no', options: [['no', 'no, use the terms file only'], ['ols', 'yes, on EBI’s Ontology Lookup Service (online)'], ['local', 'yes, in copies of the ontologies on this computer']] },
        { key: 'hpo', type: 'file', label: 'HPO (hp.obo)', kinds: ['obo'], optional: true, none: 'none', show: (v) => v.lookup === 'local' },
        { key: 'mondo', type: 'file', label: 'Mondo (mondo.obo)', kinds: ['obo'], optional: true, none: 'none', show: (v) => v.lookup === 'local' },
        { key: 'threshold', type: 'number', label: 'Accept a looked-up match from', def: 0.98, min: 0.5, max: 1, step: 0.01, show: (v) => v.lookup !== 'no', help: 'The lowest score a looked-up term needs before it is used. The default, 0.98, accepts only a term whose label or synonym is the condition’s name. Anything lower is a guess that you should check.' },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}.normalised.json` }
      ],
      argv: (v) => ['phenotk', 'normalise', v.input, '-o', v.out, '--log', v.out.replace(/\.json$/, '') + '.log.json', ...optArgs(v.mapping, '--mapping', v.mapping), ...(v.lookup === 'no' ? ['--no-online'] : ['--backend', v.lookup, '--threshold', String(v.threshold)]), ...optArgs(v.lookup === 'local' && v.hpo, '--hpo-file', v.hpo), ...optArgs(v.lookup === 'local' && v.mondo, '--mondo-file', v.mondo)],
      outputs: (v) => [v.out, v.out.replace(/\.json$/, '') + '.log.json'],
      python: (v) =>
        [
          'import json',
          'import phenopacket_toolkit as ptk',
          'from phenopacket_toolkit.ops import normalise',
          '',
          `doc = ptk.read(${pyq(v.input)})`,
          v.mapping ? `mapping = json.load(open(${pyq(v.mapping)}))` : 'mapping = None',
          `new, log = normalise(doc, mapping=mapping, threshold=${Number(v.threshold) || 0.98}, backend=${pyq(v.lookup === 'no' ? 'auto' : v.lookup)}, use_ontology=${v.lookup === 'no' ? 'False' : 'True'}${v.lookup === 'local' && v.hpo ? `, hpo_file=${pyq(v.hpo)}` : ''}${v.lookup === 'local' && v.mondo ? `, mondo_file=${pyq(v.mondo)}` : ''})`,
          `ptk.write(new, ${pyq(v.out)})`,
          `with open(${pyq(v.out.replace(/\.json$/, '') + '.log.json')}, "w") as fh:`,
          '    fh.write(log.to_json())',
          'print(log.summary())'
        ].join('\n')
    },

    /* ---------------- Check and look inside ---------------- */
    {
      id: 'validate',
      group: 'check',
      title: 'Check against the standard',
      pkg: 'pedigree-ga4gh',
      what: 'Check a GA4GH Pedigree, Phenopackets Family, Cohort or Phenopacket against the standards, and say how to fix what is wrong.',
      about:
        'It applies the checks of the Phenopackets v2 schema and of phenopacket-tools, the Phenopackets team’s own validator, such as required fields, ontology ids, ages and the resources in metaData. For a GA4GH Pedigree it also checks the KIN relations, that everyone named in a relationship or as an index patient is in the file, the sexes of parents, and that nobody is their own ancestor. Errors make a file invalid, warnings are worth fixing, and notes are for information.',
      help: 'h-tool-validate',
      fields: [{ key: 'input', type: 'file', label: 'The file', kinds: GA4GH }],
      argv: (v) => ['pedigree-ga4gh', 'validate', v.input],
      call: { fn: 'pedwb.gui.validate', args: (v) => ({ path: v.input }) },
      python: (v) => ['import pedigree_ga4gh as pg', '', `doc = pg.load(${pyq(v.input)})`, 'findings = pg.validate(doc)', 'print(pg.render_findings(findings))', 'print("valid" if pg.is_valid(findings) else "not valid")'].join('\n'),
      render: (r, v, out) => renderFindings(r.result, v, out)
    },
    {
      id: 'upgrade',
      group: 'check',
      title: 'Upgrade a file from an older tool',
      pkg: 'pedigree-ga4gh',
      what: 'Rewrite a file made by an older version of studio2ga4gh or abusua2ga4gh (or any non-standard file) in the standard form.',
      about:
        'Earlier versions of our tools wrote GA4GH files that the standard doesn’t accept, with names in the subject, diseases in the wrong place, retired KIN codes, empty ontology ids or no metaData. The upgrade fixes what it can and lists every change. Findings it can’t give a term to are listed for you to match with Fill in missing terms.',
      help: 'h-tool-upgrade',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: GA4GH.concat(['json']) },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}.upgraded.json` }
      ],
      argv: (v) => ['pedigree-ga4gh', 'upgrade', v.input, '-o', v.out],
      outputs: (v) => [v.out],
      python: (v) => ['import pedigree_ga4gh as pg', '', `doc = pg.load(${pyq(v.input)})`, 'new, changes, todo = pg.upgrade(doc)', `pg.dump(new, ${pyq(v.out)})`, 'for c in changes:', '    print("changed:", c)', 'for t in todo:', '    print("to do:", t)'].join('\n'),
      next: (res, v) => [['badgeCheck', 'Check the upgraded file', () => MG.app.useTool('validate', { input: v.out })]]
    },
    {
      id: 'view',
      group: 'check',
      title: 'Look inside a GA4GH file',
      pkg: 'phenotk',
      what: 'Show a GA4GH or Phenopackets file as a table of people and their terms, or count what is in it.',
      about: 'It’s a quick way to read a file without wading through its JSON. You can see who is in it, with their sex, status, diseases and phenotypes, or just count the people, terms and relationships.',
      help: 'h-tool-view',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: GA4GH },
        { key: 'what', type: 'select', label: 'Show', def: 'view', options: [['view', 'a table of the people and their terms'], ['stats', 'counts: people, terms, relationships']] }
      ],
      argv: (v) => ['phenotk', v.what, v.input],
      python: (v) => (v.what === 'stats' ? ['import phenopacket_toolkit as ptk', 'from phenopacket_toolkit.ops import stats, render_stats', '', `doc = ptk.read(${pyq(v.input)})`, 'print(render_stats(stats(doc)))'] : ['import phenopacket_toolkit as ptk', 'from phenopacket_toolkit.ops import render', '', `doc = ptk.read(${pyq(v.input)})`, 'print(render(doc))']).join('\n'),
      stdoutIsResult: true
    },
    {
      id: 'diff',
      group: 'check',
      title: 'Compare two files',
      pkg: 'phenotk',
      what: 'Show what differs between two GA4GH or Phenopackets files, in their people, terms and relationships, ignoring the order of things and when the files were made.',
      about: 'Use it to see what a conversion changed, or what’s new in a later version of a family’s file.',
      help: 'h-tool-diff',
      fields: [
        { key: 'input', type: 'file', label: 'The first file', kinds: GA4GH },
        { key: 'input2', type: 'file', label: 'The second file', kinds: GA4GH },
        { key: 'strict', type: 'check', label: 'Count differences of order and of provenance too', def: false }
      ],
      argv: (v) => ['phenotk', 'diff', v.input, v.input2, ...optArgs(v.strict, '--strict')],
      python: (v) => ['import phenopacket_toolkit as ptk', 'from phenopacket_toolkit.ops import diff, render_diff', '', `a = ptk.read(${pyq(v.input)})`, `b = ptk.read(${pyq(v.input2)})`, `print(render_diff(diff(a, b${v.strict ? ', ignore=[]' : ''})))`].join('\n'),
      stdoutIsResult: true,
      okCodes: [0, 1]
    },

    /* ---------------- Prepare to share ---------------- */
    {
      id: 'deidentify',
      group: 'share',
      title: 'De-identify',
      pkg: 'phenotk',
      what: 'Give people new ids, and take out dates of birth, other ids and, if you like, who made the file.',
      about:
        'The ids are replaced with IND-0001, IND-0002 and so on, or with codes made from the old ids. Each new id is used everywhere the old one appeared: in the relationships, the pedigree and the index patient. The key from old ids to new can be saved in a separate file, which you should keep apart from the file you share. De-identifying removes what the file says directly. Whether the family could still be recognised from what’s left, such as a rare condition or a large family, is for you to judge.',
      help: 'h-tool-deidentify',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: GA4GH },
        { key: 'remap', type: 'select', label: 'New ids', def: 'seq', options: [['seq', 'IND-0001, IND-0002 … in order'], ['hash', 'codes made from the old ids (the same each time, with the same secret)'], ['keep', 'keep the ids as they are']] },
        { key: 'salt', type: 'text', label: 'Secret for the codes', def: '', show: (v) => v.remap === 'hash', placeholder: 'any words (keep them private)', help: 'With the same secret, the same person gets the same code in every file.' },
        { key: 'keepDob', type: 'check', label: 'Keep dates of birth', def: false },
        { key: 'binAge', type: 'select', label: 'Ages', def: '', options: [['', 'as they are'], ['5y', 'in 5-year bands'], ['10y', 'in 10-year bands']] },
        { key: 'keepNames', type: 'check', label: 'Keep other ids (alternateIds)', def: false },
        { key: 'dropProv', type: 'check', label: 'Hide who made the file and when (the de-identification is recorded instead)', def: false },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}.deidentified.json` },
        { key: 'keyfile', type: 'path', label: 'Save the key (old id → new) as', def: (v) => `~/results/${stemOf(v.input)}.key.json`, optional: true, show: (v) => v.remap !== 'keep' }
      ],
      argv: (v) => ['phenotk', 'deidentify', v.input, '-o', v.out, ...(v.remap === 'keep' ? ['--keep-ids'] : optArgs(v.remap !== 'seq', '--remap-ids', v.remap)), ...optArgs(v.remap === 'hash' && v.salt, '--salt', v.salt), ...optArgs(v.keepDob, '--keep-dob'), ...optArgs(v.binAge, '--bin-age', v.binAge), ...optArgs(v.keepNames, '--keep-names'), ...optArgs(v.dropProv, '--drop-provenance'), ...optArgs(v.remap !== 'keep' && v.keyfile, '--keyfile', v.keyfile)],
      outputs: (v) => [v.out, v.remap !== 'keep' && v.keyfile].filter(Boolean),
      python: (v) =>
        [
          'import json',
          'import phenopacket_toolkit as ptk',
          'from phenopacket_toolkit.ops import deidentify',
          '',
          `doc = ptk.read(${pyq(v.input)})`,
          `res = deidentify(doc, remap_ids=${v.remap === 'keep' ? 'None' : pyq(v.remap)}${v.remap === 'hash' && v.salt ? `, salt=${pyq(v.salt)}` : ''}, drop_dob=${v.keepDob ? 'False' : 'True'}${v.binAge ? `, bin_age=${pyq(v.binAge)}` : ''}, drop_names=${v.keepNames ? 'False' : 'True'}, drop_provenance=${v.dropProv ? 'True' : 'False'})`,
          `ptk.write(res.document, ${pyq(v.out)})`,
          ...(v.remap !== 'keep' && v.keyfile ? [`json.dump(res.crosswalk, open(${pyq(v.keyfile)}, "w"), indent=2)`] : []),
          'for w in res.warnings:',
          '    print("warning:", w)'
        ].join('\n')
    },
    {
      id: 'filter',
      group: 'share',
      title: 'Keep some people or terms',
      pkg: 'phenotk',
      what: 'Make a smaller file with only the proband, the affected people, one sex or the people you name, or with only some terms.',
      about:
        'Filters on people keep or drop whole people. In a GA4GH Pedigree, the relationships of the people left out are always dropped too, and in a Family, “Tidy the pedigree” takes them out of its pedigree. Filters on terms keep only the terms you list, one CURIE per line, or drop them if you tick Reverse.',
      help: 'h-tool-filter',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: GA4GH },
        { key: 'who', type: 'select', label: 'People', def: '', options: [['', 'everyone'], ['proband', 'the proband only'], ['affected', 'affected people only']] },
        { key: 'sex', type: 'select', label: 'Sex', def: '', options: [['', 'any'], ['FEMALE', 'female'], ['MALE', 'male']] },
        { key: 'ids', type: 'textarea', label: 'Only these people (ids, one per line; optional)', def: '', placeholder: 'II-3\nIII-1' },
        { key: 'terms', type: 'textarea', label: 'Only these terms (CURIEs, one per line; optional)', def: '', placeholder: 'MONDO:0007254\nHP:0000365' },
        { key: 'observed', type: 'select', label: 'Of the terms', def: '', options: [['', 'keep observed and excluded'], ['observed', 'keep only those observed'], ['excluded', 'keep only those excluded']] },
        { key: 'invert', type: 'check', label: 'Reverse: drop what matches instead of keeping it', def: false },
        { key: 'prune', type: 'check', label: 'Tidy the pedigree: remove the people left out from a Family’s pedigree', def: true },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}.filtered.json` }
      ],
      // (the command takes the people's ids in a file: it is written beside the result before the run)
      prepare: (v, fs) => {
        const ids = (v.ids || '').split(/\s*[\n,]\s*/).filter(Boolean);
        if (ids.length) fs.writeText(idFile(v), ids.join('\n') + '\n');
      },
      argv: (v) => {
        const terms = (v.terms || '').split(/\s*[\n,]\s*/).filter(Boolean);
        return ['phenotk', 'filter', v.input, '-o', v.out, ...terms.flatMap((t) => ['--term', t]), ...optArgs(v.who === 'proband', '--proband-only'), ...optArgs(v.who === 'affected', '--affected'), ...optArgs(v.sex, '--sex', v.sex), ...optArgs(idFile(v), '--id-list', idFile(v)), ...optArgs(v.observed === 'observed', '--observed'), ...optArgs(v.observed === 'excluded', '--excluded'), ...optArgs(v.invert, '--invert'), ...optArgs(v.prune, '--prune-pedigree')];
      },
      outputs: (v) => [v.out],
      python: (v) => {
        const terms = (v.terms || '').split(/\s*[\n,]\s*/).filter(Boolean);
        const ids = (v.ids || '').split(/\s*[\n,]\s*/).filter(Boolean);
        return [
          'import phenopacket_toolkit as ptk',
          'from phenopacket_toolkit.ops import filter_document',
          '',
          `doc = ptk.read(${pyq(v.input)})`,
          `new = filter_document(doc${terms.length ? `, terms=${JSON.stringify(terms)}` : ''}${v.who === 'proband' ? ', proband_only=True' : ''}${v.who === 'affected' ? ', affected_only=True' : ''}${v.sex ? `, sex=${pyq(v.sex)}` : ''}${ids.length ? `, id_list=${JSON.stringify(ids)}` : ''}${v.observed === 'observed' ? ', observed_only=True' : ''}${v.observed === 'excluded' ? ', excluded_only=True' : ''}${v.invert ? ', invert=True' : ''}${v.prune ? ', prune_pedigree=True' : ''})`,
          `ptk.write(new, ${pyq(v.out)})`
        ].join('\n');
      }
    },
    {
      id: 'split',
      group: 'share',
      title: 'One file for each person',
      pkg: 'phenotk',
      what: 'Split a Family, Cohort or GA4GH Pedigree into a Phenopacket for each person (or for each affected person).',
      about: 'Each Phenopacket is named after its person’s id. Use it to send one person’s findings without the rest of the family.',
      help: 'h-tool-split',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: ['pedigree', 'family', 'cohort'] },
        { key: 'affected', type: 'check', label: 'Only the affected people', def: false },
        { key: 'outdir', type: 'folder', label: 'Save in the folder', def: (v) => `~/results/${stemOf(v.input)}-people` }
      ],
      argv: (v) => ['phenotk', 'split', v.input, '--out-dir', v.outdir, ...optArgs(v.affected, '--affected-only')],
      python: (v) =>
        ['import os', 'import phenopacket_toolkit as ptk', 'from phenopacket_toolkit.ops import split', '', `doc = ptk.read(${pyq(v.input)})`, `os.makedirs(${pyq(v.outdir)}, exist_ok=True)`, `for packet in split(doc${v.affected ? ', affected_only=True' : ''}):`, '    sid = packet.proband().subject.id', `    ptk.write(packet, os.path.join(${pyq(v.outdir)}, sid + ".json"))`].join('\n')
    },
    {
      id: 'merge',
      group: 'share',
      title: 'Put files together',
      pkg: 'phenotk',
      what: 'Merge Phenopackets (or Families) into one Cohort, or into one Family.',
      about:
        'A Cohort is a set of people who needn’t be related, such as the probands of several families. In a Cohort, if someone’s id is already used by a person in another file (IV-3 in two families, say), they are renamed after their file’s id. A Family is one family. Its pedigree comes from the Families and GA4GH Pedigrees among the files, and anyone who appears in more than one file is kept once.',
      help: 'h-tool-merge',
      fields: [
        { key: 'inputs', type: 'files', label: 'The files', kinds: GA4GH },
        { key: 'into', type: 'select', label: 'Into', def: 'cohort', options: [['cohort', 'a Cohort'], ['family', 'a Family']] },
        { key: 'cid', type: 'text', label: 'Its id', def: 'cohort' },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${v.cid || 'cohort'}.json` }
      ],
      argv: (v) => ['phenotk', 'merge', ...v.inputs, '--into', v.into, '--id', v.cid || 'cohort', '-o', v.out],
      outputs: (v) => [v.out],
      python: (v) =>
        ['import phenopacket_toolkit as ptk', 'from phenopacket_toolkit.ops import merge', '', `docs = [ptk.read(p) for p in ${JSON.stringify(v.inputs || [])}]`, 'notes = []', `new = merge(docs, into=${pyq(v.into)}, cohort_id=${pyq(v.cid || 'cohort')}, notes=notes)`, `ptk.write(new, ${pyq(v.out)})`, 'for note in notes:', '    print("note:", note)'].join('\n')
    },
    {
      id: 'add',
      group: 'share',
      title: 'Add findings to people',
      pkg: 'phenotk',
      what: 'Add diseases or phenotypes (with an age of onset), or a vital status, to the proband, to everyone, or to one person.',
      about:
        'Write each term as its id, followed by = and its label if you like: <code>HP:0000365=Hearing impairment</code>. Phenotypes can be marked as looked for and not found (excluded). To add a gene variant or other details, use phenotk add in the terminal (see man phenotk).',
      help: 'h-tool-add',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: GA4GH },
        { key: 'target', type: 'text', label: 'To', def: 'proband', help: 'proband, all, affected, unaffected, or one person’s id (II-3).' },
        { key: 'phenotypes', type: 'textarea', label: 'Phenotypes (one per line)', def: '', placeholder: 'HP:0000365=Hearing impairment' },
        { key: 'excluded', type: 'check', label: 'These phenotypes were looked for and not found (excluded)', def: false },
        { key: 'diseases', type: 'textarea', label: 'Diseases (one per line)', def: '', placeholder: 'MONDO:0007254=breast cancer' },
        { key: 'onset', type: 'text', label: 'Age at onset (optional)', def: '', placeholder: 'P45Y – 45 years' },
        { key: 'vital', type: 'select', label: 'Vital status', def: '', options: [['', 'leave as it is'], ['ALIVE', 'alive'], ['DECEASED', 'deceased'], ['UNKNOWN_STATUS', 'unknown']] },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}.json` }
      ],
      check: (v) => (!(v.phenotypes || '').trim() && !(v.diseases || '').trim() && !v.vital ? 'Give a phenotype, a disease or a vital status to add.' : ''),
      argv: (v) => {
        const lines = (s) => (s || '').split('\n').map((x) => x.trim()).filter(Boolean);
        return ['phenotk', 'add', v.input, '--target', v.target || 'proband', ...lines(v.phenotypes).flatMap((t) => ['--phenotype', t]), ...optArgs(v.excluded && lines(v.phenotypes).length, '--excluded'), ...lines(v.diseases).flatMap((t) => ['--disease', t]), ...optArgs(v.onset, '--onset', v.onset), ...optArgs(v.vital, '--vital-status', v.vital), '-o', v.out];
      },
      outputs: (v) => [v.out],
      python: (v) => {
        const lines = (s) => (s || '').split('\n').map((x) => x.trim()).filter(Boolean);
        const item = (spec, extra) => {
          const [id, label] = spec.includes('=') ? [spec.slice(0, spec.indexOf('=')).trim(), spec.slice(spec.indexOf('=') + 1).trim()] : [spec, ''];
          return `{"id_": ${pyq(id)}, "label": ${pyq(label)}${extra}}`;
        };
        const on = v.onset ? `, "onset": ${pyq(v.onset)}` : '';
        const ph = lines(v.phenotypes).map((s) => item(s, (v.excluded ? ', "excluded": True' : '') + on));
        const ds = lines(v.diseases).map((s) => item(s, on));
        return [
          'import phenopacket_toolkit as ptk',
          'from phenopacket_toolkit.ops import add',
          ...(v.vital ? ['from phenopacket_toolkit.model import builders'] : []),
          '',
          `doc = ptk.read(${pyq(v.input)})`,
          `new = add(doc, ${pyq(v.target || 'proband')}${ph.length ? `,\n          phenotypes=[${ph.join(', ')}]` : ''}${ds.length ? `,\n          diseases=[${ds.join(', ')}]` : ''}${v.vital ? `,\n          vital_status=builders.vital_status(${pyq(v.vital)})` : ''})`,
          `ptk.write(new, ${pyq(v.out)})`
        ].join('\n');
      }
    },

    /* ---------------- PED and MPED ---------------- */
    {
      id: 'mped-info',
      group: 'ped',
      title: 'Summary and check',
      pkg: 'mpedtools',
      what: 'See what a PED or MPED file holds (families, people, conditions and who is affected) and whether it is valid.',
      about: 'The check finds people listed twice, parents who are not in the file, parents of the wrong sex, and status codes other than 0, 1, 2 and 3.',
      help: 'h-tool-mpedtools',
      fields: [{ key: 'input', type: 'file', label: 'The file', kinds: ['ped', 'mped'] }],
      argv: (v) => [
        ['mpedtools', 'info', v.input],
        ['mpedtools', 'validate', v.input]
      ],
      python: (v) => ['import mpedtools', '', `ped = mpedtools.read(${pyq(v.input)})`, 'print(mpedtools.summarise(ped))', 'for issue in mpedtools.validate(ped):', '    print(issue.level, issue.message)'].join('\n'),
      stdoutIsResult: true,
      okCodes: [0, 1]
    },
    {
      id: 'mped-extract',
      group: 'ped',
      title: 'Take one condition out',
      pkg: 'mpedtools',
      what: 'Make a plain PED file for one condition in an MPED file, or one for each condition.',
      about: 'Most linkage programs read one condition at a time. This makes the PED file they need from the MPED file that studio2ped writes for a drawing with several conditions.',
      help: 'h-tool-mpedtools',
      fields: [
        { key: 'input', type: 'file', label: 'The MPED file', kinds: ['mped'] },
        { key: 'which', type: 'text', label: 'The condition (its column name)', def: '', placeholder: 'e.g. Breast_cancer, or leave it empty for every condition', help: 'The names are on the file’s first line (# MPED v1 …), or run Summary and check to see them.' },
        { key: 'outdir', type: 'folder', label: 'Save in', def: '~/results' },
        { key: 'prefix', type: 'text', label: 'Start of the file names', def: (v) => stemOf(v.input) }
      ],
      argv: (v) => (v.which ? ['mpedtools', 'extract', v.input, v.which, '-o', joinPath(v.outdir, `${v.prefix}_${v.which}.ped`)] : ['mpedtools', 'extract-all', v.input, '-d', v.outdir, '-p', v.prefix]),
      python: (v) =>
        v.which
          ? ['import mpedtools', '', `ped = mpedtools.read(${pyq(v.input)})`, `one = mpedtools.extract_phenotype(ped, ${pyq(v.which)})`, `mpedtools.write(one, ${pyq(joinPath(v.outdir, `${v.prefix}_${v.which}.ped`))}, force_format="ped")`].join('\n')
          : ['import mpedtools', '', `ped = mpedtools.read(${pyq(v.input)})`, `for path in mpedtools.extract_all_phenotypes(ped, ${pyq(v.outdir)}, ${pyq(v.prefix)}):`, '    print("wrote", path)'].join('\n')
    },
    {
      id: 'mped-merge',
      group: 'ped',
      title: 'Put PED files together',
      pkg: 'mpedtools',
      what: 'Merge PED files of the same people, one condition each, into one MPED file.',
      about: 'The files must list the same families and people. Each one gives a condition column, named as you choose or after its file.',
      help: 'h-tool-mpedtools',
      fields: [
        { key: 'inputs', type: 'files', label: 'The PED files', kinds: ['ped'] },
        { key: 'names', type: 'text', label: 'Names of the conditions (in the same order; optional)', def: '', placeholder: 'Bowel_cancer Pancreatic_cancer' },
        { key: 'out', type: 'path', label: 'Save as', def: '~/results/merged.mped' }
      ],
      argv: (v) => ['mpedtools', 'merge', ...v.inputs, '-o', v.out, ...((v.names || '').trim() ? ['-n', ...v.names.trim().split(/[\s,]+/)] : [])],
      outputs: (v) => [v.out],
      python: (v) => ['import mpedtools', '', `peds = [mpedtools.read(p) for p in ${JSON.stringify(v.inputs || [])}]`, `merged = mpedtools.merge(peds${(v.names || '').trim() ? `, ${JSON.stringify(v.names.trim().split(/[\s,]+/))}` : ''})`, `mpedtools.write(merged, ${pyq(v.out)}, force_format="mped")`].join('\n')
    },
    {
      id: 'mped-split',
      group: 'ped',
      title: 'One file for each family',
      pkg: 'mpedtools',
      what: 'Split a PED or MPED file that holds several families into a file for each.',
      about: 'The files are named after the families’ ids.',
      help: 'h-tool-mpedtools',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: ['ped', 'mped'] },
        { key: 'outdir', type: 'folder', label: 'Save in', def: '~/results' },
        { key: 'prefix', type: 'text', label: 'Start of the file names', def: (v) => stemOf(v.input) }
      ],
      argv: (v) => ['mpedtools', 'split', v.input, '-d', v.outdir, '-p', v.prefix],
      python: (v) => ['import mpedtools', '', `ped = mpedtools.read(${pyq(v.input)})`, 'for fam in mpedtools.split_families(ped):', `    path = f"${expand(v.outdir).replace(/\/+$/, '')}/${v.prefix}_{fam.families[0]}" + (".mped" if ped.is_mped else ".ped")`, '    mpedtools.write(fam, path)', '    print("wrote", path)'].join('\n')
    },
    {
      id: 'mped-convert',
      group: 'ped',
      title: 'PED ⇄ MPED, and columns',
      pkg: 'mpedtools',
      what: 'Turn a PED file into an MPED file or back, or add or remove a condition column.',
      about: 'An MPED file is a PED file with a header line that names its condition columns, so it can hold several conditions. In a new column, everyone starts with the value you choose (0 unknown, 1 unaffected, 2 affected, 3 carrier).',
      help: 'h-tool-mpedtools',
      fields: [
        { key: 'input', type: 'file', label: 'The file', kinds: ['ped', 'mped'] },
        { key: 'action', type: 'select', label: 'Do', def: (v) => (MG.app.pedKind(v.input || '') === 'mped' ? 'to-ped' : 'to-mped'), options: [['to-mped', 'make it an MPED file'], ['to-ped', 'make it a plain PED file'], ['add', 'add a condition column'], ['remove', 'remove a condition column']] },
        { key: 'column', type: 'text', label: 'Condition (column name)', def: '', placeholder: 'e.g. Hearing_loss', show: (v) => v.action !== 'to-mped', help: 'For a plain PED file, the condition to keep (leave it empty for the first).' },
        { key: 'value', type: 'select', label: 'New column starts at', def: '0', options: [['0', '0 – unknown'], ['1', '1 – unaffected'], ['2', '2 – affected'], ['3', '3 – carrier']], show: (v) => v.action === 'add' },
        { key: 'out', type: 'path', label: 'Save as', def: (v) => `~/results/${stemOf(v.input)}${v.action === 'to-ped' ? '.ped' : v.action === 'to-mped' ? '.mped' : MG.app.pedKind(v.input || '') === 'mped' ? '.mped' : '.mped'}` }
      ],
      check: (v) => ((v.action === 'add' || v.action === 'remove') && !(v.column || '').trim() ? 'Give the name of the column.' : ''),
      argv: (v) =>
        v.action === 'add'
          ? ['mpedtools', 'add-phenotype', v.input, v.column, '-o', v.out, ...optArgs(v.value !== '0', '--default', v.value)]
          : v.action === 'remove'
            ? ['mpedtools', 'remove-phenotype', v.input, v.column, '-o', v.out]
            : ['mpedtools', 'convert', v.input, '-o', v.out, '-f', v.action === 'to-ped' ? 'ped' : 'mped', ...optArgs(v.column, '--phenotype', v.column)],
      outputs: (v) => [v.out],
      python: (v) => {
        const head = ['import mpedtools', '', `ped = mpedtools.read(${pyq(v.input)})`];
        if (v.action === 'add') return head.concat([`new = mpedtools.add_phenotype(ped, ${pyq(v.column)}, ${Number(v.value) || 0})`, `mpedtools.write(new, ${pyq(v.out)})`]).join('\n');
        if (v.action === 'remove') return head.concat([`new = mpedtools.remove_phenotype(ped, ${pyq(v.column)})`, `mpedtools.write(new, ${pyq(v.out)})`]).join('\n');
        const f = v.action === 'to-ped' ? 'ped' : 'mped';
        return head.concat([`new = mpedtools.to_${f}(ped${v.column ? `, ${pyq(v.column)}` : ''})`, `mpedtools.write(new, ${pyq(v.out)}, force_format=${pyq(f)})`]).join('\n');
      }
    },

    /* ---------------- Analyse and simulate ---------------- */
    {
      id: 'pednet-graph',
      group: 'analyse',
      title: 'The pedigree as a graph',
      pkg: 'PedNet',
      what: 'See how a family is put together: its loops, how closely its people are related, who is inbred, which affected people are closest, and network measures of the pedigree.',
      about:
        'PedNet treats a pedigree as a directed graph, with an edge from each parent to each child. It finds the loops (a marriage between relatives makes one), works out the kinship coefficient of every pair of people and the inbreeding coefficient of each person, and names the relationships of the affected people who are related, the closest first. It also gives network measures of the pedigree, and of the pattern of affected people in it. The kinship coefficients can be saved as a table, and the graph as GraphML, for network tools such as Gephi or Cytoscape. In an MPED file, the first condition is taken as who is affected. PedNet reads GA4GH Pedigrees and Phenopackets Families too, such as those that studio2ga4gh, PedGen and PedInterp write.',
      help: 'h-tool-pednet',
      fields: [
        { key: 'input', type: 'file', label: 'The PED or GA4GH file', kinds: ['ped', 'mped', 'pedigree', 'family'] },
        ...GA4GH_FIELDS,
        { key: 'family', type: 'text', label: 'Family (optional)', def: '', placeholder: 'every family in the file', help: 'The kinship table and the graph need one family, if the file holds more than one.' },
        { key: 'kinship', type: 'check', label: 'Save everyone’s kinship coefficients as a table', def: false },
        { key: 'xlinked', type: 'check', label: 'For the X chromosome', def: false, show: (v) => v.kinship },
        { key: 'kinout', type: 'path', label: 'Save the table as', def: (v) => `~/results/${stemOf(v.input)}${v.family ? '-' + v.family : ''}-kinship${v.xlinked ? '-x' : ''}.tsv`, show: (v) => v.kinship },
        { key: 'graphml', type: 'check', label: 'Save the graph as GraphML', def: false },
        { key: 'mating', type: 'check', label: 'The mating graph, with a node for each couple', def: false, show: (v) => v.graphml },
        { key: 'gout', type: 'path', label: 'Save the graph as', def: (v) => `~/results/${stemOf(v.input)}${v.family ? '-' + v.family : ''}${v.mating ? '-mating' : ''}.graphml`, show: (v) => v.graphml }
      ],
      argv: (v) => ['pednet', 'graph', v.input, ...ga4ghArgs(v), ...optArgs(v.family, '--family', v.family), ...(v.kinship ? ['--kinship', v.kinout, ...optArgs(v.xlinked, '--x')] : []), ...(v.graphml ? ['--graphml', v.gout, ...optArgs(v.mating, '--mating')] : [])],
      outputs: (v) => [v.kinship && v.kinout, v.graphml && v.gout].filter(Boolean),
      stdoutIsResult: true,
      python: (v) =>
        [
          ...(v.kinship ? ['import csv'] : []),
          'import pednet',
          ...(v.graphml ? ['from pednet.graph import write_graph'] : []),
          '',
          readFamilies(v),
          ...((v.kinship || v.graphml) && !v.family ? ['if len(families) > 1:', '    raise ValueError("the kinship table and the graph are for one family, and the file holds several: give the family\'s id")'] : []),
          'for name, pedigree in families.items():',
          '    print("Family", name)',
          '    for loop in pednet.loops(pedigree):',
          '        print("  a loop, from", loop.kind + ":", ", ".join(loop.people))',
          '    inbred = {pid: round(f, 4) for pid, f in pednet.inbreeding(pedigree).items() if f > 0}',
          '    print("  inbred:", inbred or "no one")',
          '    affected = pedigree.affected()',
          '    for i, a in enumerate(affected):',
          '        for b in affected[i + 1:]:',
          '            r = pednet.relationship(pedigree, a, b)',
          '            if r.degree is not None:',
          '                print(f"  {b} is the {r.name} of {a} (kinship {r.kinship:.4f})")',
          '    print("  network metrics:", {k: round(x, 3) for k, x in pednet.network_metrics(pedigree).items()})',
          ...(v.kinship
            ? [
                `    # everyone's kinship coefficients${v.xlinked ? ' for the X chromosome' : ''}, without the parents PedNet adds for people with one parent in the file`,
                `    ids, phi = pednet.kinship_matrix(pedigree${v.xlinked ? ', x_linked=True' : ''})`,
                '    keep = [k for k, pid in enumerate(ids) if not pedigree[pid].placeholder]',
                `    with open(${pyq(v.kinout)}, "w", newline="") as fh:`,
                '        table = csv.writer(fh, delimiter="\\t", lineterminator="\\n")',
                '        table.writerow([""] + [ids[k] for k in keep])',
                '        for k in keep:',
                '            table.writerow([ids[k]] + [f"{phi[k, j]:.6g}" for j in keep])'
              ]
            : []),
          ...(v.graphml ? [`    write_graph(pedigree, ${pyq(v.gout)}${v.mating ? ', mating=True' : ''})`] : [])
        ].join('\n'),
      next: (res, v) => [['network', 'Its mode of inheritance', () => MG.app.useTool('pednet-mode', { input: v.input })]]
    },
    {
      id: 'pednet-mode',
      group: 'analyse',
      title: 'Mode of inheritance',
      pkg: 'PedNet',
      what: 'Weigh up how likely each mode of inheritance is – autosomal dominant or recessive, X-linked dominant or recessive – from who is affected in a family.',
      about:
        'The default method is exact. PedNet treats the pedigree as a Bayesian network of genotypes, works out the likelihood of who is affected under each mode, summed over everyone’s genotypes and averaged over a range of penetrances, and turns the likelihoods into probabilities. The other two methods are classifiers that learnt from simulated families: one reads the pattern of affected people in the graph, and the other is the original PedNet’s classifier of network measures, which tells dominant from recessive by a vote. With the first two methods, a mode is called only when its probability reaches the threshold. Otherwise the answer is “uncertain”, with the probabilities.',
      help: 'h-tool-pednet',
      fields: [
        { key: 'input', type: 'file', label: 'The PED or GA4GH file', kinds: ['ped', 'mped', 'pedigree', 'family'] },
        ...GA4GH_FIELDS,
        { key: 'method', type: 'select', label: 'Method', def: 'likelihood', options: [['likelihood', 'exact likelihoods'], ['patterns', 'the pattern of affected people (a classifier)'], ['metrics', 'network measures (the original PedNet: dominant or recessive)']] },
        { key: 'family', type: 'text', label: 'Family (optional)', def: '', placeholder: 'every family in the file' },
        { key: 'together', type: 'check', label: 'The families have the same condition: give one answer for them all', def: false, show: (v) => v.method === 'likelihood' && !v.family },
        { key: 'proband', type: 'text', label: 'Proband (optional)', def: '', placeholder: 'e.g. III-2', show: (v) => v.method === 'likelihood' && !(v.together && !v.family), help: 'The person through whom the family came to attention. Without one, each affected person is taken in turn.' },
        { key: 'penetrance', type: 'text', label: 'Penetrance', def: PENETRANCE, show: (v) => v.method === 'likelihood', help: 'The chance that someone with the disease genotype is affected, or several, separated by commas, to average over.' },
        { key: 'phenocopy', type: 'number', label: 'Chance of being affected without the disease genotype', def: 0.001, min: 0, max: 0.5, step: 0.001, show: (v) => v.method === 'likelihood' },
        { key: 'threshold', type: 'number', label: 'Probability needed to call a mode', def: 0.8, min: 0.5, max: 1, step: 0.05, show: (v) => v.method !== 'metrics' }
      ],
      check: (v) => {
        const within = (x, lo, hi) => String(x == null ? '' : x).trim() !== '' && Number(x) >= lo && Number(x) <= hi;
        if (v.method === 'likelihood' && !/^\s*(0?\.\d+|1(\.0*)?|0)(\s*[,\s]\s*(0?\.\d+|1(\.0*)?|0))*\s*$/.test(v.penetrance || '')) return 'Give the penetrance as numbers between 0 and 1, separated by commas.';
        if (v.method === 'likelihood' && !within(v.phenocopy, 0, 0.5)) return 'Give the chance of being affected without the disease genotype as a number from 0 to 0.5.';
        if (v.method !== 'metrics' && !within(v.threshold, 0.5, 1)) return 'Give the probability needed to call a mode as a number from 0.5 to 1.';
        return '';
      },
      argv: (v) => {
        const lik = v.method === 'likelihood';
        return ['pednet', 'mode', v.input, ...ga4ghArgs(v), ...optArgs(!lik, '--method', v.method), ...optArgs(v.family, '--family', v.family), ...optArgs(lik && v.together, '--together'), ...optArgs(lik && v.proband, '--proband', v.proband), ...optArgs(lik && penList(v.penetrance) !== PENETRANCE, '--penetrance', penList(v.penetrance)), ...optArgs(lik && Number(v.phenocopy) !== 0.001, '--phenocopy', num(v.phenocopy)), ...optArgs(v.method !== 'metrics' && Number(v.threshold) !== 0.8, '--threshold', num(v.threshold))];
      },
      stdoutIsResult: true,
      python: (v) => {
        const lik = v.method === 'likelihood';
        const pen = (v.penetrance || PENETRANCE).split(/[\s,]+/).filter(Boolean).map(num).join(', ');
        const opts = lik ? `, penetrance=[${pen}], phenocopy=${num(v.phenocopy)}${v.proband && !v.together ? `, proband=${pyq(v.proband)}` : ''}, threshold=${num(v.threshold)}` : '';
        const head = ['import pednet', '', readFamilies(v)];
        if (lik && v.together) return head.concat([`print(pednet.infer_shared_mode(families${opts.replace(/, proband=[^,]*/, '')}))`]).join('\n');
        if (lik) return head.concat(['for pedigree in families.values():', `    print(pednet.infer_mode(pedigree${opts}))`, '    print()']).join('\n');
        if (v.method === 'patterns') return head.concat(['for pedigree in families.values():', `    print(pednet.classify_by_patterns(pedigree, threshold=${num(v.threshold)}))`, '    print()']).join('\n');
        return head.concat(['for name, pedigree in families.items():', '    print(f"Family {name}, by the original PedNet metric classifier: {pednet.classify_by_metrics(pedigree)}")', '    print("  " + ", ".join(f"{k} {x:.3f}" for k, x in pednet.network_metrics(pedigree).items()))', '    print()']).join('\n');
      },
      next: (res, v) => [['network', 'The pedigree as a graph', () => MG.app.useTool('pednet-graph', { input: v.input })]]
    },
    {
      id: 'pednet-rank',
      group: 'analyse',
      title: 'Rank candidate variants',
      pkg: 'PedNet',
      what: 'Rank the candidate variants found in a family by how well each co-segregates with the condition, as evidence for (PP1) or against (BS4) its causing it.',
      about:
        'For each variant, PedNet works out the likelihood of everyone’s genotypes and of who is affected if the variant causes the condition, and if it doesn’t. The ratio of the two is a Bayes factor, and its strength is given as evidence for co-segregation (PP1) or against it (BS4) under the ACMG/AMP guidelines. The variants are ranked by their odds of being the cause, which also take account of whether a variant’s chromosome suits the family’s mode of inheritance. Pairs of variants in one gene that an affected person carries both of are scored too, as compound heterozygotes under the recessive modes. The variants come from a VCF file, whose samples must be named with the PED file’s ids, or from a table with a column for each person, like the one Simulate a family writes. If the PED file holds several families, they are taken to have the same condition, and each variant is ranked by its evidence across the families in which an affected person carries it.',
      help: 'h-tool-pednet',
      fields: [
        { key: 'input', type: 'file', label: 'The PED or GA4GH file', kinds: ['ped', 'mped', 'pedigree', 'family'], pair: 'variants' },
        { key: 'variants', type: 'file', label: 'The variants (VCF, or a table of genotypes)', kinds: ['vcf', 'variants'], pair: 'input', primary: true },
        ...GA4GH_FIELDS,
        { key: 'family', type: 'text', label: 'Family (optional)', def: '', placeholder: 'every family in the file' },
        { key: 'modes', type: 'select', label: 'Modes of inheritance', def: ALL_MODES, options: [[ALL_MODES, 'all four, weighed up'], ['AD', 'autosomal dominant'], ['AR', 'autosomal recessive'], ['XLR', 'X-linked recessive'], ['XLD', 'X-linked dominant'], ['AD,AR', 'autosomal: dominant or recessive']] },
        { key: 'maxfreq', type: 'text', label: 'Leave out variants commoner than (optional)', def: '', placeholder: 'an allele frequency, e.g. 0.01' },
        { key: 'passed', type: 'check', label: 'Only the VCF’s sites that passed their filters', def: false, show: (v) => MG.app.pedKind(v.variants || '') === 'vcf' },
        { key: 'top', type: 'number', label: 'How many to show', def: 20, min: 0, step: 1, help: '0 shows them all.' },
        { key: 'out', type: 'path', label: 'Save every variant’s scores as (optional)', def: (v) => `~/results/${stemOf(v.variants || v.input)}-ranked.tsv`, optional: true }
      ],
      check: (v) => ((v.maxfreq || '').trim() && !(Number(v.maxfreq) >= 0 && Number(v.maxfreq) <= 1) ? 'Give the frequency as a number between 0 and 1.' : !/^\d+$/.test(String(v.top == null ? '' : v.top).trim()) ? 'Give how many to show as a whole number (0 for all).' : ''),
      argv: (v) => {
        const vcf = MG.app.pedKind(v.variants || '') === 'vcf';
        return ['pednet', 'rank', v.input, v.variants, ...ga4ghArgs(v), ...optArgs(v.family, '--family', v.family), ...optArgs(v.modes !== ALL_MODES, '--modes', v.modes), ...optArgs((v.maxfreq || '').trim(), '--max-frequency', num(v.maxfreq)), ...optArgs(vcf && v.passed, '--passed-only'), ...optArgs(Number(v.top) !== 20, '--top', String(Math.round(Number(v.top) || 0))), ...optArgs(v.out, '--out', v.out)];
      },
      outputs: (v) => [v.out].filter(Boolean),
      stdoutIsResult: true,
      python: (v) => {
        const vcf = MG.app.pedKind(v.variants || '') === 'vcf';
        const modes = v.modes !== ALL_MODES ? `modes=${JSON.stringify(v.modes.split(','))}` : '';
        return [
          ...(v.out ? ['import csv'] : []),
          'import pednet',
          '',
          readFamilies(v),
          vcf
            ? `variants = pednet.read_vcf(${pyq(v.variants)}, samples={pid for p in families.values() for pid in p.ids}${v.passed ? ', passed_only=True' : ''})`
            : `variants = pednet.read_genotype_table(${pyq(v.variants)})`,
          ...((v.maxfreq || '').trim() ? [`variants = [x for x in variants if x.allele_frequency is None or x.allele_frequency <= ${num(v.maxfreq)}]`] : []),
          '# one family on its own, or several taken to have the same condition',
          'if len(families) == 1:',
          `    scores = pednet.rank_variants(next(iter(families.values())), variants${modes ? ', ' + modes : ''})`,
          'else:',
          `    scores = pednet.rank_variants_across(families, variants${modes ? ', ' + modes : ''})`,
          `for s in scores${Number(v.top) ? `[:${Math.round(Number(v.top))}]` : ''}:`,
          '    print(s.rank, s.id, s.log10_bf, s.evidence)',
          ...(v.out
            ? [
                '# every variant\'s scores, as a table',
                'rows = [s.row() for s in scores]',
                `with open(${pyq(v.out)}, "w", newline="") as fh:`,
                '    table = csv.DictWriter(fh, fieldnames=list(dict.fromkeys(k for row in rows for k in row)) or ["candidate"],',
                '                           delimiter="\\t", lineterminator="\\n")',
                '    table.writeheader()',
                '    table.writerows(rows)'
              ]
            : [])
        ].join('\n');
      }
    },
    {
      id: 'pedgen',
      group: 'analyse',
      title: 'Simulate a family',
      pkg: 'PedGen',
      what: 'Make up a family with a dominant or recessive condition, by Mendelian inheritance from an affected founder, as a PED file.',
      about:
        'PedGen starts from a founder with the condition and adds generations of children, each inheriting one of each parent’s two copies of the gene. Partners join the family from a population in which the condition’s allele has the frequency you give, a rare one unless you change it, and some of them come with their own parents. Who is affected follows from the genotypes: one copy is enough for a dominant condition, and a recessive one needs two. A rare recessive allele seldom comes together twice in a family unless cousins marry, so for a recessive condition, cousins marry whenever they can, and PedGen makes families until one has at least two people affected, unless you change these. The families are good for teaching, and for trying out PedNet on families whose mode of inheritance is known. With a seed, the same settings always make the same family, here, in the terminal and in Python.',
      help: 'h-tool-pedgen',
      fields: [
        { key: 'mode', type: 'select', label: 'Mode of inheritance', def: 'AD', options: [['AD', 'autosomal dominant'], ['AR', 'autosomal recessive']] },
        { key: 'generations', type: 'number', label: 'Generations', def: (v) => (v.mode === 'AR' ? 4 : 3), min: 1, max: 8, step: 1, help: 'Cousins are first found in the third generation, so their children in the fourth.' },
        { key: 'children', type: 'number', label: 'The most children a couple has', def: 3, min: 1, max: 10, step: 1 },
        { key: 'seed', type: 'text', label: 'Seed (optional)', def: '', placeholder: 'a whole number, e.g. 7', help: 'Leave it empty for a new family every time. Give a number to make the same family again.' },
        { key: 'family', type: 'text', label: 'Family id', def: 'FAM1', help: 'It names the PED file too.' },
        { key: 'partners', type: 'number', label: 'Chance that a child has a partner, and children', def: 0.6, min: 0, max: 1, step: 0.05, help: 'In every generation but the last, the first child of each couple always does.' },
        { key: 'ancestors', type: 'number', label: 'Chance that a partner’s parents are added', def: 0.25, min: 0, max: 1, step: 0.05 },
        { key: 'freq', type: 'number', label: 'Frequency of the allele among partners', def: 0.001, min: 0, max: 1, step: 'any', help: 'A rare allele, as a rare disease’s is, unless you change it.' },
        { key: 'cousins', type: 'number', label: 'Chance that someone marries a cousin', def: (v) => (v.mode === 'AR' ? 1 : 0), min: 0, max: 1, step: 'any', help: 'When a cousin has no partner yet: 1 is whenever one hasn’t.' },
        { key: 'minAffected', type: 'number', label: 'At least this many affected', def: (v) => (v.mode === 'AR' ? 2 : 1), min: 1, max: 20, step: 1, help: 'PedGen makes families until one has as many, as families come to notice through their affected members.' },
        { key: 'clean', type: 'check', label: 'Partners never carry the allele', def: false, help: 'Their parents and grandparents, if they’re added, still can. A frequency of 0 keeps the allele to the founder’s descendants.' },
        { key: 'genotypes', type: 'check', label: 'Save everyone’s genotypes too, to rank as a candidate variant', def: true },
        { key: 'ga4gh', type: 'check', label: 'Write a GA4GH Pedigree too', def: false, help: 'FAMILY_ga4gh-pedigree.json, which the GA4GH tools read: ga4gh2studio, phenopacket-toolkit and PedNet, and the Risk tab. The affected have the condition, and the unaffected have it marked as looked for and not found.' },
        ...CONDITION_FIELDS,
        { key: 'outdir', type: 'folder', label: 'Save in', def: '~/results' }
      ],
      check: (v) => {
        const whole = (x, lo, hi) => /^\d+$/.test(String(x).trim()) && Number(x) >= lo && Number(x) <= hi;
        const share = (x) => String(x).trim() !== '' && Number(x) >= 0 && Number(x) <= 1;
        if (!whole(v.generations, 1, 8)) return 'Give between 1 and 8 generations.';
        if (!whole(v.children, 1, 10)) return 'Give the most children as a whole number from 1 to 10.';
        if ((v.seed || '').trim() && !/^-?\d+$/.test(v.seed.trim())) return 'The seed must be a whole number.';
        if (![v.partners, v.ancestors, v.freq, v.cousins].every(share)) return 'Give the chances and the frequency as numbers between 0 and 1.';
        if (!whole(v.minAffected, 1, 20)) return 'Give how many must be affected as a whole number from 1 to 20.';
        return oneWord('family id', v.family) || checkCondition(v);
      },
      argv: (v) => [
        'pedgen', '-m', v.mode, '-g', num(v.generations), '-c', num(v.children), '-f', v.family, '-d', v.outdir,
        ...optArgs((v.seed || '').trim(), '-s', String(v.seed).trim()),
        ...optArgs(Number(v.partners) !== 0.6, '--partners', num(v.partners)),
        ...optArgs(Number(v.ancestors) !== 0.25, '--ancestors', num(v.ancestors)),
        ...optArgs(Number(v.freq) !== 0.001, '--allele-frequency', num(v.freq)),
        ...optArgs(v.clean, '--unaffected-partners'),
        ...optArgs(Number(v.cousins) > 0, '--cousins', num(v.cousins)),
        ...optArgs(Number(v.minAffected) > 1, '--min-affected', num(v.minAffected)),
        ...optArgs(v.genotypes, '--genotypes', joinPath(v.outdir, v.family + '-genotypes.tsv')),
        ...optArgs(v.ga4gh, '--ga4gh'),
        ...(conditionOf(v) ? ['--condition', ...conditionOf(v)] : [])
      ],
      outputs: (v) => [joinPath(v.outdir, v.family + '.ped'), v.genotypes && joinPath(v.outdir, v.family + '-genotypes.tsv'), v.ga4gh && joinPath(v.outdir, v.family + '_ga4gh-pedigree.json')].filter(Boolean),
      python: (v) =>
        [
          `from PedGen import pedigree_generator, gen_PED_export${v.genotypes ? ', gen_genotype_export' : ''}${v.ga4gh ? ', gen_GA4GH_export' : ''}`,
          '',
          `df = pedigree_generator(max_children=${num(v.children)}, FamilyID=${pyq(v.family)}, mode=${pyq(v.mode)}, generation_count=${num(v.generations)},`,
          `                        SpouseLikelihood=${num(v.partners)}, AffectedSpouse=${v.clean ? 'False' : 'True'}, BackpropLikelihood=${num(v.ancestors)},`,
          `                        alt_freq=${num(v.freq)}, seed=${/^-?\d+$/.test((v.seed || '').trim()) ? BigInt(v.seed.trim()).toString() : 'None'}${Number(v.cousins) > 0 ? `, CousinLikelihood=${num(v.cousins)}` : ''}${Number(v.minAffected) > 1 ? `, min_affected=${num(v.minAffected)}` : ''})`,
          'print(len(df), "people,", (df["Phenotype"] == 2).sum(), "affected")',
          `print("wrote", gen_PED_export(df, ${pyq(expand(v.outdir).replace(/\/+$/, ''))}))`,
          ...(v.genotypes ? [`print("wrote", gen_genotype_export(df, ${pyq(joinPath(v.outdir, v.family + '-genotypes.tsv'))}, alt_freq=${num(v.freq)}))`] : []),
          ...(v.ga4gh ? [`print("wrote", gen_GA4GH_export(df, ${pyq(expand(v.outdir).replace(/\/+$/, ''))}${conditionPy(v)}))`] : [])
        ].join('\n'),
      next: (res, v) => {
        const ped = joinPath(v.outdir, v.family + '.ped');
        return [
          ['pedigree', 'Draw it (PED → drawing)', () => MG.app.useTool('ped2studio', { input: ped })],
          ['network', 'Its mode of inheritance', () => MG.app.useTool('pednet-mode', { input: ped })],
          ...(v.genotypes ? [['dna', 'Rank its variant', () => MG.app.useTool('pednet-rank', { input: ped, variants: joinPath(v.outdir, v.family + '-genotypes.tsv') })]] : []),
          // (the Risk tab, with the simulation's model: its mode and allele, full penetrance)
          ['percent', 'Work out its risks', () => MG.app.riskOpen({ source: v.ga4gh ? joinPath(v.outdir, v.family + '_ga4gh-pedigree.json') : ped, mode: v.mode, allele: Number(v.freq), penetrance: 100, phenocopy: 0, mutation: 0 })]
        ];
      }
    }
  ];
  const TOOL = Object.fromEntries(TOOLS.map((t) => [t.id, t]));
  MG.pedTools = TOOLS;

  /* the common tasks, on the first page: [icon, what you want, [tool ids in order], a walkthrough] */
  const TASKS = [
    ['eyeOff', 'Share a family’s pedigree in the GA4GH standard', ['terms', 'studio2ga4gh', 'validate', 'deidentify'], 'h-walk-ga4gh'],
    ['table', 'Make a PED file for a linkage program', ['studio2ped', 'mped-extract'], 'h-walk-ped'],
    ['pedigree', 'Draw a PED file I have been sent', ['ped2studio'], 'h-walk-draw-ped'],
    ['pedigree', 'Draw a GA4GH or Phenopackets file', ['ga4gh2studio'], 'h-walk-draw-ga4gh'],
    ['badgeCheck', 'Check a GA4GH file, or update an old one', ['validate', 'upgrade'], 'h-walk-check'],
    ['tag', 'Give the conditions ontology terms', ['terms', 'normalise'], 'h-walk-terms'],
    ['image', 'Turn a picture of a pedigree into a PED file and a drawing', ['pedinterp', 'ped2studio'], 'h-walk-picture'],
    ['network', 'Weigh up the mode of inheritance, and rank candidate variants', ['pednet-graph', 'pednet-mode', 'pednet-rank'], 'h-walk-pednet']
  ];

  /* ------------------------------------------------------------------ files for the pickers */
  function filesOfKinds(kinds) {
    const fs = MG.app.fs;
    const mine = [], ex = [];
    for (const [p, e] of fs.entries) {
      if (e.kind === 'dir') continue;
      const inHome = p.startsWith(HOME() + '/'), inEx = p.startsWith('/data/examples/');
      if (!inHome && !inEx) continue;
      if (/\/\.[^/]*$/.test(p) || p.includes('/.cache/')) continue;
      const k = MG.app.pedKind(p);
      if (!kinds.includes(k) && !(kinds.includes('json') && k === 'json')) continue;
      (inHome ? mine : ex).push({ path: p, kind: k, mtime: e.mtime || 0 });
    }
    mine.sort((a, b) => b.mtime - a.mtime);
    ex.sort((a, b) => (a.path < b.path ? -1 : 1));
    return { mine, ex };
  }
  /** the file of some kinds that goes with path: the same name in the same folder with another ending, as a PED file
      and its variants (dominant.ped and dominant.vcf, or FAM1.ped and FAM1-genotypes.tsv) – or '' */
  const pairStem = (p) => String(p || '').replace(/(-genotypes)?\.(ped|mped|fam|vcf|vcf\.gz|tsv|csv|txt)$/i, '');
  function pairOf(path, kinds) {
    if (!path) return '';
    const stem = pairStem(path);
    const { mine, ex } = filesOfKinds(kinds);
    const hit = mine.concat(ex).find((x) => x.path !== path && pairStem(x.path) === stem);
    return hit ? hit.path : '';
  }
  /** where an upload of a kind goes */
  const uploadDir = (kinds) => HOME() + '/' + (kinds.includes('studio') ? 'pedigrees' : kinds.includes('terms') ? 'terms' : kinds.includes('obo') ? 'ontologies' : kinds.includes('image') ? 'pictures' : 'data');

  /* ------------------------------------------------------------------ the tab */
  class ToolsTab {
    constructor(root, opts) {
      this.root = root;
      this.fs = opts.fs;
      this.values = {}; // tool id → the values last used
      this._build();
      this.go(store.get('toolsPage', null) || { page: 'start' });
      bus.on('kernel:state', () => this._pyPill());
      bus.on('kernel:status', () => this._pyPill());
      this._pyPill();
      // file lists follow the files (debounced)
      this.fs.onChange(() => {
        clearTimeout(this._ft);
        this._ft = setTimeout(() => this._refreshPickers(), 300);
      });
    }
    _build() {
      this.nav = h('nav.tl-nav', { 'aria-label': 'Tools' });
      this.main = h('div.tl-main', { tabindex: '-1' });
      this.pill = h('button.tl-py', { type: 'button', title: 'The Python that runs the tools' });
      this.pill.addEventListener('click', () => this._pyMenu());
      this.navBtn = h('button.tbtn.tl-navbtn', { type: 'button', html: icon('list') + '<span>All tools</span>', 'aria-expanded': 'false' });
      this.navBtn.addEventListener('click', () => this._toggleNav());
      const head = h('div.tl-head', this.navBtn, h('span.tl-crumb'), h('span.grow'), this.pill);
      this.crumb = head.querySelector('.tl-crumb');
      this.root.append(h('div.tl-wrap', head, h('div.tl-body', this.nav, this.main)));
      for (const [g, label, ic] of GROUPS) {
        const sec = h('div.tl-group', h('div.tl-gh', { html: icon(ic) + `<span>${esc(label)}</span>` }));
        if (g === 'start') {
          const b = h('button.tl-item', { type: 'button', dataset: { page: 'start' } }, h('span', 'The map, and where to begin'));
          b.addEventListener('click', () => this.go({ page: 'start' }));
          sec.appendChild(b);
        }
        for (const t of TOOLS.filter((x) => x.group === g)) {
          const b = h('button.tl-item', { type: 'button', dataset: { tool: t.id } }, h('span', t.title), h('small', t.pkg));
          b.addEventListener('click', () => this.choose(t.id));
          sec.appendChild(b);
        }
        this.nav.appendChild(sec);
      }
    }
    _toggleNav(open) {
      const on = open == null ? !this.root.classList.contains('nav-open') : open;
      this.root.classList.toggle('nav-open', on);
      this.navBtn.setAttribute('aria-expanded', on ? 'true' : 'false');
    }
    shown() {
      this._refreshPickers();
    }
    _mark(sel) {
      this.nav.querySelectorAll('.tl-item').forEach((b) => b.classList.toggle('on', b.matches(sel)));
    }
    /** show a page: {page: 'start'} | {page: 'tool', id, values} | {page: 'file', path} */
    go(where) {
      this._toggleNav(false);
      this.where = where;
      store.set('toolsPage', where.page === 'tool' ? { page: 'tool', id: where.id } : where.page === 'file' ? where : { page: 'start' });
      this.main.innerHTML = '';
      this.main.scrollTop = 0;
      this.pickers = [];
      if (where.page === 'tool' && TOOL[where.id]) return this._toolPage(TOOL[where.id], where.values || {});
      if (where.page === 'file' && where.path && this.fs.exists(where.path)) return this._filePage(where.path);
      return this._startPage(where.kind);
    }
    /** a tool, with its fields filled in from values ({input: path, …}) */
    choose(id, values = {}) {
      if (id === 'start') return this.go({ page: 'start', kind: values.kind });
      if (!TOOL[id]) return;
      this.go({ page: 'tool', id, values });
    }
    forFile(path) {
      this.go({ page: 'file', path });
    }

    /* ---------------- Python's state, at the top right ---------------- */
    _pyPill() {
      const K = MG.kernels.peek();
      let state = 'off', text = 'Python starts when you run a tool';
      if (K) {
        if (K.state === 'ready') {
          state = 'ok';
          text = `Python ${(K.versions && K.versions.python) || ''} ready`;
        } else if (K.state === 'loading') {
          state = 'busy';
          text = K.statusText || 'Starting Python…';
        } else if (K.state === 'failed') {
          state = 'bad';
          text = 'Python couldn’t start';
        }
      }
      this.pill.innerHTML = `<span class="kdot ${state === 'ok' ? 'ok' : state === 'busy' ? 'busy' : state === 'bad' ? 'bad' : 'off'}"></span><span>${esc(text)}</span>`;
    }
    _pyMenu() {
      const K = MG.kernels.get();
      const v = (K.versions && K.versions.packages) || (window.WB_BUNDLE && window.WB_BUNDLE.packages) || {};
      const later = (window.WB_BUNDLE && window.WB_BUNDLE.analysis && window.WB_BUNDLE.analysis.packages) || {};
      const rows = Object.entries(v)
        .filter(([n]) => n !== 'pedwb' && n !== 'error')
        .map(([n, ver]) => `<tr><td><code>${esc(n)}</code></td><td>${esc(ver || '')}</td></tr>`)
        .concat(Object.entries(later).map(([n, ver]) => `<tr><td><code>${esc(n)}</code> <small class="muted">loaded when first used</small></td><td>${esc(ver || '')}</td></tr>`))
        .join('');
      const m = MG.modal(
        'Python for the tools',
        `<p>The tools run in Python ${esc((K.versions && K.versions.python) || '')} (Pyodide${K.versions && K.versions.pyodide ? ' ' + esc(K.versions.pyodide) : ''}) here in your browser. Nothing is sent anywhere, except the names you choose to look up on EBI’s Ontology Lookup Service. The Notebook and Terminal tabs use the same Python, and so does the Risk tab, to read GA4GH files.</p>
         <table class="table small"><tr><th>Package</th><th>Version</th></tr>${rows}</table>
         <p class="muted small">These are the versions released on PyPI, so <code>pip install</code> gives you the same code on your own computer, except PedGen and PedInterp, whose changes for the workbench aren’t released yet (see the help: Reference → Versions, and how to cite).</p>
         <div class="prompt-actions"><button class="btn" data-x="start" type="button">${K.state === 'ready' ? 'Restart Python' : 'Start Python now'}</button></div>`
      );
      m.box.querySelector('[data-x="start"]').addEventListener('click', () => {
        m.close();
        if (K.state === 'ready') K.restart();
        else K.ensure().catch(() => {});
      });
    }

    /* ---------------- the first page: the map, and the common tasks ---------------- */
    _startPage(kind) {
      this._mark('[data-page="start"]');
      this.crumb.textContent = 'Tools';
      const M = this.main;
      M.appendChild(h('h2.tl-title', 'What would you like to do?'));
      M.appendChild(h('p.tl-lead', 'Each tool runs a command from one of our Python packages on one of your files or an example. It also shows you that command, and the same job in Python, so you can do it again in the terminal or a notebook. Click an arrow on the map to open the tool for that step, or click a box to see what you can do with that kind of file.'));
      const mapBox = h('div.tl-mapbox');
      M.appendChild(mapBox);
      const hint = h('p.tl-maphint', ' ');
      M.appendChild(hint);
      this.map = MG.pedMap(mapBox, {
        onTool: (id) => this.choose(id),
        onFormat: (k) => this._kindPanel(k, panel),
        onHover: (name) => {
          const t = TOOL[name];
          hint.textContent = t ? `${t.title} – ${t.what}` : name && KIND()[name] ? `${KIND()[name]}: click to see what you can do with it` : ' ';
        }
      });
      const panel = h('div.tl-kindpanel');
      M.appendChild(panel);
      if (kind) this._kindPanel(kind, panel);
      M.appendChild(h('h3.tl-sub', 'Common tasks'));
      const grid = h('div.tl-tasks');
      for (const [ic, what, ids, walk] of TASKS) {
        const card = h('div.tl-task', h('div.tl-task-h', { html: icon(ic) + `<b>${esc(what)}</b>` }));
        const steps = h('ol.tl-steps');
        ids.forEach((id) => {
          const b = h('button.linkbtn', { type: 'button' }, TOOL[id].title);
          b.addEventListener('click', () => this.choose(id));
          steps.appendChild(h('li', b));
        });
        card.appendChild(steps);
        if (walk) {
          const w = h('button.linkbtn.tl-walk', { type: 'button', html: icon('book') + '<span>Walkthrough</span>' });
          w.addEventListener('click', () => MG.app.showHelp(walk));
          card.appendChild(w);
        }
        grid.appendChild(card);
      }
      M.appendChild(grid);
      M.appendChild(h('p.tl-foot.muted', 'Python starts in your browser the first time you run a tool on each visit. The very first time, it downloads about 10 MB, which your browser then keeps. The tools for analysing and simulating, and Picture → PED file, need more, which Python downloads the first time one of them runs: about 4 MB for PedNet’s tools, and about 21 MB in all. Your files never leave this computer.'));
    }
    /** under the map: what can be done with a kind of file */
    _kindPanel(kind, panel) {
      panel.innerHTML = '';
      const kinds = kind === 'ped' ? ['ped', 'mped'] : kind === 'terms' ? ['terms', 'obo'] : [kind];
      const tools = TOOLS.filter((t) => !t.custom && (t.fields || []).some((f) => (f.type === 'file' || f.type === 'files') && !f.optional && f.kinds.some((k) => kinds.includes(k))));
      if (kind === 'terms' || kind === 'studio') tools.unshift(TOOL.terms);
      panel.appendChild(h('h3.tl-sub', `With a ${KIND()[kind] || kind}`));
      const list = h('div.tl-chooser');
      tools.forEach((t) => {
        const b = h('button.tl-choice', { type: 'button' }, h('b', t.title), h('small', t.what));
        b.addEventListener('click', () => this.choose(t.id));
        list.appendChild(b);
      });
      if (kind === 'studio') {
        const b = h('button.tl-choice', { type: 'button' }, h('b', 'Draw or change it in the Studio tab'), h('small', 'Draw people, couples, children and twins, and name the conditions in the colour key.'));
        b.addEventListener('click', () => MG.app.showWorkbench('studio'));
        list.prepend(b);
      }
      if (RISK_KINDS.includes(kind)) {
        const b = h('button.tl-choice', { type: 'button' }, h('b', 'Work out genetic risks'), h('small', 'The chance that each person carries the family’s variant, and that a couple’s child will be affected, in the Risk tab.'));
        b.addEventListener('click', () => (kind === 'studio' ? MG.app.riskOpen({ source: 'studio' }) : MG.app.showWorkbench('risk')));
        list.appendChild(b);
      }
      panel.appendChild(list);
      panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    /* ---------------- a file's page: what it is, and what can be done with it ---------------- */
    async _filePage(path) {
      this._mark('.none');
      this.crumb.textContent = 'Tools › ' + base(path);
      const M = this.main;
      const kind = MG.app.pedKind(path);
      M.appendChild(h('h2.tl-title', { html: icon('file') + `<span>${esc(base(path))}</span>` }));
      M.appendChild(h('p.tl-lead', h('code', tilde(path)), ' · ', KIND()[kind] || 'file'));
      const info = h('div.tl-info', h('span.spinner.small'), ' Reading the file…');
      M.appendChild(info);
      const panel = h('div.tl-kindpanel');
      M.appendChild(panel);
      const kinds = kind === 'mped' ? ['mped', 'ped'] : [kind];
      const mainField = (t) => (t.fields || []).find((f) => (f.key === 'input' || f.primary) && f.kinds.some((k) => kinds.includes(k)));
      const tools = TOOLS.filter((t) => !t.custom && mainField(t));
      panel.appendChild(h('h3.tl-sub', 'What you can do with it'));
      const list = h('div.tl-chooser');
      if (kind === 'studio') {
        const b = h('button.tl-choice', { type: 'button' }, h('b', 'Open it in the Studio tab'), h('small', 'Look at it, change it, tidy it.'));
        b.addEventListener('click', () => MG.app.studioOpen(path));
        list.appendChild(b);
        tools.unshift(TOOL.terms);
      }
      tools.forEach((t) => {
        const b = h('button.tl-choice', { type: 'button' }, h('b', t.title), h('small', t.what));
        b.addEventListener('click', () => this.choose(t.id, t.id === 'terms' ? { drawing: path } : { [mainField(t).key]: path }));
        list.appendChild(b);
      });
      if (RISK_KINDS.includes(kind)) {
        const b = h('button.tl-choice', { type: 'button' }, h('b', 'Work out genetic risks'), h('small', 'The chance that each person carries the family’s variant, and that a couple’s child will be affected, in the Risk tab.'));
        b.addEventListener('click', () => MG.app.riskOpen({ source: path }));
        list.appendChild(b);
      }
      if (!tools.length) list.appendChild(h('p.muted', 'None of the tools reads this kind of file, but you can open it in the Files tab to look at it.'));
      panel.appendChild(list);
      // what is in it: a picture's size, from the browser; anything else, from Python
      if (kind === 'image') {
        const size = await pictureSize(this.fs, path).catch(() => null);
        info.innerHTML = '';
        info.appendChild(fileSummary({ kind, name: KIND().image || 'picture', size }));
        return;
      }
      try {
        const r = await pyCall('pedwb.gui.inspect', { path });
        if (!r.ok) throw new Error(r.error);
        info.innerHTML = '';
        info.appendChild(fileSummary(r.result));
      } catch (e) {
        info.innerHTML = '';
        info.appendChild(h('p.muted', 'Couldn’t read this file: ' + (e.message || e)));
      }
    }

    /* ---------------- a tool's page ---------------- */
    _toolPage(tool, given) {
      this._mark(`[data-tool="${tool.id}"]`);
      this.crumb.textContent = 'Tools › ' + tool.title;
      if (tool.custom) {
        this.custom = new TermsTool(this, this.main, given);
        return;
      }
      const M = this.main;
      M.appendChild(h('div.tl-toolhead', h('h2.tl-title', tool.title), h('span.tl-pkg', { title: 'The Python package that does this' }, tool.pkg)));
      M.appendChild(h('p.tl-lead', tool.what));
      if (tool.about) {
        const more = h('details.tl-about', h('summary', 'More about this tool'), h('p', { html: tool.about }));
        if (tool.help) {
          const hb = h('button.linkbtn', { type: 'button', html: icon('book') + '<span>Help and a walkthrough</span>' });
          hb.addEventListener('click', () => MG.app.showHelp(tool.help));
          more.appendChild(h('p', hb));
        }
        M.appendChild(more);
      }
      // the values: those given, else those last used, else the defaults
      const last = this.values[tool.id] || {};
      const v = {};
      const touched = new Set(Object.keys(given));
      const form = h('form.tl-form', { autocomplete: 'off' });
      const rows = {};
      const defOf = (f) => (typeof f.def === 'function' ? f.def(v) : f.def);
      const refreshDerived = (except) => {
        for (const f of tool.fields) {
          if (f.key === except || touched.has(f.key)) continue;
          // (a file that goes with the one just chosen: the variants of a PED file)
          if (f.type === 'file' && f.pair && f.pair === except) {
            const paired = pairOf(v[except], f.kinds);
            if (paired && rows[f.key] && rows[f.key].set) {
              v[f.key] = paired;
              rows[f.key].set(paired);
            }
            continue;
          }
          if (typeof f.def !== 'function') continue;
          v[f.key] = defOf(f);
          if (rows[f.key] && rows[f.key].set) rows[f.key].set(v[f.key]);
        }
        for (const f of tool.fields) if (rows[f.key]) rows[f.key].row.hidden = !!(f.show && !f.show(v));
        update();
      };
      for (const f of tool.fields) {
        if (given[f.key] != null) v[f.key] = given[f.key];
        else if (last[f.key] != null && f.type !== 'file' && f.type !== 'files' && typeof f.def !== 'function') v[f.key] = last[f.key];
        else v[f.key] = f.type === 'files' ? [] : f.type === 'file' ? '' : defOf(f);
      }
      // a file not given: the last one used, if it is still there; else the first that fits – and for a tool that takes
      // two files that go together (a PED file and its variants), the first that has its pair, and then that pair
      const fieldOf = (key) => tool.fields.find((x) => x.key === key);
      for (const f of tool.fields.filter((x) => x.type === 'file')) {
        if (v[f.key]) continue;
        const paired = f.pair && v[f.pair] ? pairOf(v[f.pair], f.kinds) : '';
        if (paired) v[f.key] = paired;
        else if (last[f.key] && this.fs.exists(last[f.key])) v[f.key] = last[f.key];
        else if (!f.optional) {
          const { mine, ex } = filesOfKinds(f.kinds);
          const all = mine.concat(ex);
          v[f.key] = ((f.pair && all.find((x) => pairOf(x.path, fieldOf(f.pair).kinds))) || all[0] || {}).path || '';
        }
      }
      const onChange = (key, val) => {
        v[key] = val;
        touched.add(key);
        refreshDerived(key);
      };
      for (const f of tool.fields) {
        const r = fieldRow(this, f, v, onChange);
        rows[f.key] = r;
        form.appendChild(r.row);
      }
      // the drawing's conditions, under the terms file (studio2ga4gh)
      const condBox = tool.fields.some((f) => f.conditions) ? h('div.tl-conds') : null;
      if (condBox) rows.terms.row.appendChild(condBox);
      const run = h('button.btn.primary.tl-run', { type: 'submit', html: icon('play') + '<span>Run</span>' });
      const msg = h('span.tl-check', { role: 'status' });
      form.appendChild(h('div.tl-actions', run, msg));
      M.appendChild(form);
      const result = h('div.tl-result', { 'aria-live': 'polite' });
      M.appendChild(result);
      // the same command for the terminal and for Python
      const same = h('div.tl-same');
      M.appendChild(same);
      const full = () => {
        const x = Object.assign({}, v);
        for (const f of tool.fields) {
          if ((f.type === 'file' || f.type === 'folder' || f.type === 'path') && x[f.key]) x[f.key] = expand(x[f.key]);
          if (f.type === 'files') x[f.key] = (x[f.key] || []).map(expand);
          if (f.show && !f.show(v)) x[f.key] = f.type === 'check' ? false : f.type === 'files' ? [] : '';
        }
        return x;
      };
      let condT = null;
      const update = () => {
        const x = full();
        const problem = missing(tool, x);
        msg.textContent = problem;
        run.disabled = !!problem;
        same.innerHTML = '';
        if (!problem) renderSame(same, tool, x);
        if (condBox) {
          clearTimeout(condT);
          condT = setTimeout(() => showConditions(condBox, x, this), 250);
        }
      };
      refreshDerived(null);
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const x = full();
        if (missing(tool, x)) return;
        this.values[tool.id] = Object.assign({}, v);
        await this._run(tool, x, result, run);
      });
    }
    async _run(tool, x, result, runBtn) {
      // files it would replace
      const outs = tool.outputs ? tool.outputs(x).filter((p) => p && this.fs.exists(p)) : [];
      if (outs.length && !(await MG.confirmBox('Replace these files?', `<p>Running the tool will replace:</p><ul>${outs.map((p) => `<li><code>${esc(tilde(p))}</code></li>`).join('')}</ul>`, 'Replace them'))) return;
      // the folders it writes into
      for (const f of tool.fields) {
        if (f.type === 'folder' && x[f.key]) this.fs.mkdirp(x[f.key]);
        if (f.type === 'path' && x[f.key]) this.fs.mkdirp(dirOf(x[f.key]));
      }
      if (tool.prepare) tool.prepare(x, this.fs);
      runBtn.disabled = true;
      runBtn.classList.add('running');
      result.innerHTML = '';
      const K = kernel();
      const status = h('div.tl-status', h('span.spinner.small'), h('span', K.state === 'ready' ? (K.cellRunning ? 'Waiting for Python, which is busy with a notebook cell…' : 'Running…') : 'Starting Python in your browser (about 10 MB to download the first time)…'));
      result.appendChild(status);
      // (PedNet, PedGen and PedInterp are loaded the first time one of their tools runs: Python says what it loads)
      const onStatus = (text) => (status.lastChild.textContent = text || 'Running…');
      const t0 = performance.now();
      try {
        let res;
        if (tool.call) {
          const r = await pyCall(tool.call.fn, tool.call.args(x), onStatus);
          if (!r.ok && r.kind === 'LoadError') throw new Error(r.error);
          res = { ok: r.ok, code: r.ok ? 0 : 1, stdout: r.stdout || '', stderr: r.stderr || '', files: r.files, result: r.result, error: r.error, traceback: r.traceback };
        } else {
          const list = Array.isArray(tool.argv(x)[0]) ? tool.argv(x) : [tool.argv(x)];
          res = { ok: true, code: 0, stdout: '', stderr: '', files: [] };
          for (const argv of list) {
            const r = await runArgv(argv, onStatus);
            res.stdout += r.stdout;
            res.stderr += r.stderr;
            res.files = res.files.concat(r.files || []);
            res.code = Math.max(res.code, r.code);
            if (r.error) res.error = r.error;
            if (r.traceback) res.traceback = r.traceback;
          }
          res.ok = (tool.okCodes || [0]).includes(res.code) && !res.error;
        }
        const secs = (performance.now() - t0) / 1000;
        status.remove();
        await this._result(tool, x, res, result, secs);
      } catch (e) {
        status.remove();
        result.appendChild(h('div.tl-fail', h('b', 'The tool couldn’t run: '), String((e && e.message) || e)));
      } finally {
        runBtn.disabled = false;
        runBtn.classList.remove('running');
      }
    }
    async _result(tool, x, res, out, secs) {
      const ok = res.ok;
      out.appendChild(h('div.tl-done.' + (ok ? 'ok' : 'bad'), { html: icon(ok ? 'check' : 'warning') + `<span>${ok ? 'Done' : `It stopped with an error${res.code ? ` (exit status ${res.code})` : ''}`}${secs > 0.5 ? ` · ${secs.toFixed(1)} s` : ''}</span>` }));
      if (tool.render && res.result) tool.render(res, x, out);
      else {
        const text = (res.stdout || '').replace(/\s+$/, '');
        if (text) out.appendChild(h(tool.stdoutIsResult ? 'pre.tl-pre.tl-main-out' : 'pre.tl-pre', text));
      }
      const err = (res.stderr || '').replace(/\s+$/, '');
      if (err) out.appendChild(h('pre.tl-pre.err', err));
      if (res.traceback && !ok) {
        const d = h('details.tl-tb', h('summary', 'Python’s traceback (for reporting a fault)'), h('pre.tl-pre', res.traceback));
        out.appendChild(d);
      }
      // the files it wrote
      const files = Array.from(new Set(res.files || [])).filter((p) => !/\/\.[^/]*$/.test(p) && this.fs.exists(p));
      if (files.length) {
        out.appendChild(h('h4.tl-h4', files.length === 1 ? 'The file it wrote' : `The ${files.length} files it wrote`));
        const list = h('div.tl-files');
        files.forEach((p) => list.appendChild(fileChip(p)));
        out.appendChild(list);
      }
      if (tool.after && ok) await tool.after(res, x, out);
      const next = ok && tool.next ? tool.next(res, x) : [];
      if (next.length) {
        const row = h('div.tl-next');
        next.forEach(([ic, label, fn]) => {
          const b = h('button.btn', { type: 'button', html: icon(ic) + `<span>${esc(label)}</span>` });
          b.addEventListener('click', fn);
          row.appendChild(b);
        });
        out.appendChild(row);
      }
      out.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      bus.emit('tools:run', { tool: tool.id, ok, files });
    }
    _refreshPickers() {
      (this.pickers || []).forEach((p) => p.refresh && p.refresh());
    }
  }

  /* ------------------------------------------------------------------ a field of a form */
  function fieldRow(tab, f, v, onChange) {
    const id = 'tf-' + f.key + '-' + Math.random().toString(36).slice(2, 6);
    const row = h('div.tl-field', { dataset: { key: f.key } });
    const label = h('label.tl-label', { for: id }, f.label);
    let set = null;
    if (f.type === 'file') {
      const pk = filePicker(tab, f, v[f.key], (val) => onChange(f.key, val), id);
      row.append(label, pk.el);
      set = pk.set;
      tab.pickers.push(pk);
    } else if (f.type === 'files') {
      const pk = filesPicker(tab, f, v[f.key] || [], (val) => onChange(f.key, val), id);
      row.append(label, pk.el);
      tab.pickers.push(pk);
    } else if (f.type === 'select') {
      const s = h('select.tl-input', { id });
      f.options.forEach(([val, lab]) => s.appendChild(h('option', { value: val }, lab)));
      s.value = v[f.key];
      s.addEventListener('change', () => onChange(f.key, s.value));
      row.append(label, s);
      set = (val) => (s.value = val);
    } else if (f.type === 'check') {
      const c = h('input', { type: 'checkbox', id });
      c.checked = !!v[f.key];
      c.addEventListener('change', () => onChange(f.key, c.checked));
      row.classList.add('check');
      row.append(h('label.tl-checkline', { for: id }, c, h('span', f.label)));
      set = (val) => (c.checked = !!val);
    } else if (f.type === 'textarea') {
      const t = h('textarea.tl-input', { id, rows: 3, placeholder: f.placeholder || '', spellcheck: 'false' });
      t.value = v[f.key] || '';
      t.addEventListener('input', () => onChange(f.key, t.value));
      row.append(label, t);
      set = (val) => (t.value = val);
    } else if (f.type === 'colour') {
      const c = h('input.tl-colour', { type: 'color', id, value: v[f.key] || '#1a2332' });
      c.addEventListener('input', () => onChange(f.key, c.value));
      row.append(label, c);
      set = (val) => (c.value = val);
    } else {
      // text, number, folder, path
      const t = h('input.tl-input' + (f.type === 'folder' || f.type === 'path' ? '.mono' : ''), { id, type: f.type === 'number' ? 'number' : 'text', placeholder: f.placeholder || '', spellcheck: 'false', autocapitalize: 'off' });
      if (f.type === 'number') Object.assign(t, { min: f.min, max: f.max, step: f.step });
      t.value = v[f.key] == null ? '' : String(v[f.key]);
      t.addEventListener('input', () => onChange(f.key, f.type === 'number' ? t.value : t.value));
      row.append(label, t);
      set = (val) => (t.value = val == null ? '' : String(val));
    }
    if (f.help) row.appendChild(h('div.tl-help', f.help));
    if (f.show && !f.show(v)) row.hidden = true;
    return { row, set };
  }

  /** a file of some kinds: from your files or the examples, uploaded, or the drawing in the Studio tab */
  function filePicker(tab, f, value, onChange, id) {
    const sel = h('select.tl-input.tl-file', { id });
    const el = h('div.tl-picker', sel);
    const btns = h('div.tl-pickbtns');
    const up = h('button.linkbtn', { type: 'button', html: icon('upload') + '<span>From my computer…</span>' });
    up.addEventListener('click', async () => {
      const paths = await MG.app.pickFiles(uploadDir(f.kinds), false);
      if (paths && paths[0]) {
        refresh(paths[0]);
        onChange(paths[0]);
      }
    });
    btns.appendChild(up);
    if (f.studio) {
      const st = h('button.linkbtn', { type: 'button', html: icon('pedigree') + '<span>The drawing in the Studio tab</span>' });
      st.addEventListener('click', async () => {
        const p = await MG.app.studioSnapshot();
        await MG.app.showWorkbench('tools');
        if (p) {
          refresh(p);
          onChange(p);
        }
      });
      btns.appendChild(st);
    }
    const open = h('button.linkbtn', { type: 'button', html: icon('eye') + '<span>Look at it</span>' });
    open.addEventListener('click', () => sel.value && MG.app.openFile(sel.value, { edit: MG.app.pedKind(sel.value) !== 'studio' }));
    btns.appendChild(open);
    el.appendChild(btns);
    let current = value || '';
    function refresh(want) {
      if (want != null) current = want;
      const { mine, ex } = filesOfKinds(f.kinds);
      sel.innerHTML = '';
      if (f.optional) sel.appendChild(h('option', { value: '' }, f.none || 'none'));
      else if (!mine.length && !ex.length) sel.appendChild(h('option', { value: '' }, 'none of your files is of this kind – add one from your computer'));
      const add = (label, list) => {
        if (!list.length) return;
        const g = h('optgroup', { label });
        list.forEach((x) => g.appendChild(h('option', { value: x.path }, tilde(x.path) + (f.kinds.length > 1 && KIND()[x.kind] ? `  (${KIND()[x.kind]})` : ''))));
        sel.appendChild(g);
      };
      // (a file chosen that is not of the kinds – given by another tab – is offered as it is)
      if (current && ![...mine, ...ex].some((x) => x.path === current) && MG.app.fs.exists(current)) mine.unshift({ path: current, kind: MG.app.pedKind(current) });
      add('Your files', mine);
      add('Examples (read-only)', ex);
      sel.value = current;
      if (sel.value !== current) {
        current = sel.value;
        if (current !== value) onChange(current);
      }
      open.hidden = !sel.value;
    }
    sel.addEventListener('change', () => {
      current = sel.value;
      open.hidden = !current;
      onChange(current);
    });
    refresh();
    return { el, refresh: () => refresh(), set: (p) => refresh(p) };
  }

  /** several files (merge): a list, with Add and remove */
  function filesPicker(tab, f, value, onChange, id) {
    const el = h('div.tl-multi');
    const list = h('ul.tl-multilist', { id });
    const sel = h('select.tl-input');
    const add = h('button.btn.small', { type: 'button' }, 'Add');
    let items = value.slice();
    const render = () => {
      list.innerHTML = '';
      items.forEach((p, i) => {
        const x = h('button.icon-btn', { type: 'button', 'aria-label': 'Take ' + base(p) + ' out', html: icon('x') });
        x.addEventListener('click', () => {
          items.splice(i, 1);
          render();
          onChange(items.slice());
        });
        list.appendChild(h('li', h('code', tilde(p)), x));
      });
      if (!items.length) list.appendChild(h('li.muted', 'No files chosen yet. Add them one by one below.'));
    };
    const refresh = () => {
      const { mine, ex } = filesOfKinds(f.kinds);
      sel.innerHTML = '';
      const g1 = h('optgroup', { label: 'Your files' }), g2 = h('optgroup', { label: 'Examples (read-only)' });
      mine.forEach((x) => g1.appendChild(h('option', { value: x.path }, tilde(x.path))));
      ex.forEach((x) => g2.appendChild(h('option', { value: x.path }, tilde(x.path))));
      if (mine.length) sel.appendChild(g1);
      if (ex.length) sel.appendChild(g2);
    };
    add.addEventListener('click', () => {
      if (sel.value && !items.includes(sel.value)) {
        items.push(sel.value);
        render();
        onChange(items.slice());
      }
    });
    el.append(list, h('div.tl-multiadd', sel, add));
    refresh();
    render();
    return { el, refresh };
  }

  /** what the form still needs, in words ('' when it can run) */
  function missing(tool, x) {
    for (const f of tool.fields) {
      if (f.show && !f.show(x)) continue;
      if ((f.type === 'file' && !f.optional && !x[f.key]) || (f.type === 'files' && !(x[f.key] || []).length)) return `Choose ${f.label.replace(/^The /, 'the ')}.`;
      if ((f.type === 'folder' || f.type === 'path') && !f.optional && !x[f.key]) return `Fill in “${f.label}”.`;
      if ((f.type === 'folder' || f.type === 'path') && x[f.key] && !(x[f.key] === HOME() || x[f.key].startsWith(HOME() + '/'))) return 'Results can only be saved in your home folder (~).';
      if (f.type === 'files' && f.key === 'inputs' && tool.id.endsWith('merge') && (x[f.key] || []).length < 2) return 'Choose at least two files.';
    }
    if (tool.id === 'diff' && x.input && x.input === x.input2) return 'Choose two different files.';
    return tool.check ? tool.check(x) : '';
  }

  /** the same command for the terminal, and the same in Python */
  function renderSame(box, tool, x) {
    let argvs = tool.argv(x);
    if (!Array.isArray(argvs[0])) argvs = [argvs];
    const cmd = argvs.map((a) => a.map(shArg).join(' ')).join('\n');
    const code = tool.python ? tool.python(x) : '';
    const details = h('details.tl-samebox', { open: store.get('toolsSameOpen', false) ? '' : null });
    details.addEventListener('toggle', () => store.set('toolsSameOpen', details.open));
    details.appendChild(h('summary', { html: icon('code') + '<span>The same in the terminal, and in Python</span>' }));
    const block = (title, text, kind) => {
      const pre = h('pre.code', { dataset: { run: kind } }, h('code', text));
      const wrap = h('div.tl-code', h('div.tl-code-t', title), pre);
      details.appendChild(wrap);
      MG.app.decorateCode(pre);
    };
    block('Terminal', cmd, 'term');
    if (code) block('Python (a notebook cell)', code, 'py');
    box.appendChild(details);
  }

  /** a file the tool wrote: its name, and buttons to open it where it belongs */
  function fileChip(p) {
    const kind = MG.app.pedKind(p);
    const chip = h('div.tl-filechip', h('span.tl-fname', { html: icon(kind === 'studio' ? 'pedigree' : kind === 'ped' || kind === 'mped' ? 'table' : kind === 'image' ? 'image' : kind === 'vcf' || kind === 'variants' ? 'dna' : 'file') + `<code>${esc(tilde(p))}</code>` }), h('span.tl-fkind', KIND()[kind] || ''));
    const acts = h('span.tl-facts');
    const add = (ic, label, fn) => {
      const b = h('button.linkbtn', { type: 'button', html: icon(ic) + `<span>${esc(label)}</span>` });
      b.addEventListener('click', fn);
      acts.appendChild(b);
    };
    if (kind === 'studio') add('pedigree', 'Open in Studio', () => MG.app.studioOpen(p));
    add('eye', 'Look at it', () => MG.app.editFile(p));
    if (GA4GH.includes(kind)) add('badgeCheck', 'Check', () => MG.app.useTool('validate', { input: p }));
    if (RISK_KINDS.includes(kind)) add('percent', 'Risks', () => MG.app.riskOpen({ source: p }));
    if (kind !== 'other') add('convert', 'More…', () => MG.app.toolsFor(p));
    add('download', 'Download', () => downloadFile(p));
    chip.appendChild(acts);
    return chip;
  }
  async function downloadFile(p) {
    const blob = await MG.app.fs.toBlob(p);
    MG.downloadBlob(blob, base(p));
  }

  /** what pedwb.gui.inspect said of a file, as a few lines */
  function fileSummary(info) {
    const box = h('dl.tl-summary');
    const row = (k, val) => val != null && val !== '' && box.append(h('dt', k), h('dd', val));
    row('Kind', info.name);
    if (info.error) row('Problem', info.error);
    if (info.kind === 'studio') {
      row('People', String(info.people));
      row('Families', String(info.families));
      row('Conditions in the key', info.conditions && info.conditions.length ? info.conditions.join(', ') : 'none');
    } else if (GA4GH.includes(info.kind)) {
      row('Id', info.id);
      row('People', String(info.people));
      if (info.relationships != null) row('Relationships', String(info.relationships));
      if (info.indexPatients && info.indexPatients.length) row('Index patient', info.indexPatients.join(', '));
      if (info.proband) row('Proband', info.proband);
      if (info.legacy) row(info.legacy.upgradable === false ? 'Draft form' : 'Older form', info.legacy.description + (info.legacy.upgradable === false ? '' : ' Upgrade it before using it with the other tools.'));
    } else if (info.kind === 'ped' || info.kind === 'mped') {
      row('People', String(info.people));
      row('Families', (info.families || []).join(', '));
      row('Conditions', (info.phenotypes || []).join(', '));
      row('Affected', String(info.affected));
    } else if (info.kind === 'vcf') {
      row('Variants', String(info.variants));
      row('Samples', String(info.samples));
      if (info.chromosomes && info.chromosomes.length) row('Chromosomes', info.chromosomes.join(', '));
    } else if (info.kind === 'variants') {
      row('Variants', String(info.variants));
      row('People', String(info.people));
    } else if (info.kind === 'image') {
      row('Size', info.size ? `${info.size.width.toLocaleString('en-GB')} × ${info.size.height.toLocaleString('en-GB')} pixels` : 'not known: your browser can’t show this picture');
    } else if (info.kind === 'terms') row('Names matched', String(info.terms));
    else if (info.kind === 'obo') {
      row('Ontology', info.ontology);
      row('Release', info.version);
      row('Terms', String(info.terms));
    }
    return box;
  }

  /** a terms file's effect on a drawing, under the terms field of Drawing → GA4GH */
  async function showConditions(box, x, tab) {
    if (!x.input || MG.app.pedKind(x.input) !== 'studio') {
      box.innerHTML = '';
      return;
    }
    const K = MG.kernels.peek();
    if (!K || K.state !== 'ready') {
      box.innerHTML = '';
      const b = h('button.linkbtn', { type: 'button', html: icon('tag') + '<span>Show which conditions have terms (starts Python)</span>' });
      b.addEventListener('click', () => {
        box.innerHTML = '<span class="spinner small"></span> Starting Python…';
        kernel()
          .ensure()
          .then(() => showConditions(box, x, tab))
          .catch(() => (box.textContent = 'Python couldn’t start.'));
      });
      box.appendChild(b);
      return;
    }
    const r = await pyCall('pedwb.gui.conditions', { path: x.input, terms: x.terms || null });
    box.innerHTML = '';
    if (!r.ok) {
      box.appendChild(h('p.muted', r.error));
      return;
    }
    const rows = r.result.conditions;
    if (!rows.length) {
      box.appendChild(h('p.muted', 'The drawing’s colour key doesn’t name any conditions.'));
      return;
    }
    const t = h('table.tl-condtable', h('tr', h('th', 'Condition in the key'), h('th', 'Term'), h('th', '')));
    let gaps = 0;
    rows.forEach((c) => {
      const term = c.id ? h('span', h('code', c.id), ' ', c.label && c.label !== c.name ? c.label : '', c.from === 'key' ? h('small.muted', ' (written in the key)') : '') : h('span.tl-gap', 'none, so it will be left out');
      if (!c.id) gaps++;
      t.appendChild(h('tr', h('td', c.name, h('small.muted', ` · ${c.people} ${c.people === 1 ? 'person' : 'people'}`)), h('td', term), h('td', c.id ? h('span.tl-okmark', { html: icon('check') }) : '')));
    });
    box.appendChild(t);
    if (gaps) {
      const b = h('button.btn.small', { type: 'button', html: icon('tag') + `<span>Match ${gaps === 1 ? 'it' : 'them'} to terms…</span>` });
      b.addEventListener('click', () => tab.choose('terms', { drawing: x.input, terms: x.terms }));
      box.appendChild(h('div.tl-condnote', `${gaps} of the ${rows.length} conditions ${gaps === 1 ? 'has' : 'have'} no term. `, b));
    }
    if (r.result.unnamed && r.result.unnamed.length) box.appendChild(h('p.tl-help', `Some symbols are coloured ${r.result.unnamed.join(', ')}, which the key doesn’t name. To include ${r.result.unnamed.length === 1 ? 'that colour' : 'those colours'}, name ${r.result.unnamed.length === 1 ? 'it' : 'them'} in the Studio’s key.`));
  }

  /** the findings of a check, as a table */
  function renderFindings(res, x, out) {
    const head = h('div.tl-verdict.' + (res.valid ? 'ok' : 'bad'), h('b', res.valid ? `Valid: a correct ${res.name}.` : `Not valid: ${res.errors} error${res.errors === 1 ? '' : 's'}.`), res.warnings ? ` ${res.warnings} warning${res.warnings === 1 ? '' : 's'}.` : '');
    out.appendChild(head);
    if (res.legacy && res.legacy.upgradable === false) out.appendChild(h('div.tl-warn', res.legacy.description));
    else if (res.legacy) {
      const b = h('button.btn.small', { type: 'button', html: icon('wand') + '<span>Upgrade it</span>' });
      b.addEventListener('click', () => MG.app.useTool('upgrade', { input: x.input }));
      out.appendChild(h('div.tl-warn', res.legacy.description + ' ', b));
    }
    if (!res.findings.length) return;
    const t = h('table.tl-findings', h('tr', h('th', ''), h('th', 'What'), h('th', 'Where'), h('th', 'How to fix it')));
    const SEV = { error: ['warning', 'Error'], warning: ['info', 'Warning'], info: ['info', 'Note'] };
    res.findings.forEach((f) => {
      const [ic, word] = SEV[f.severity] || ['info', f.severity];
      t.appendChild(h('tr.' + f.severity, h('td', { html: icon(ic) + `<span class="sr-only">${word}</span>`, title: word }), h('td', f.message, h('small.muted', ' ' + f.code)), h('td', h('code', f.path || '')), h('td', f.fix || '')));
    });
    out.appendChild(h('div.table-scroll', t));
  }

  /* ==================================================================
     Match conditions to terms
     ================================================================== */
  const SOURCES = [
    ['ols', 'EBI’s Ontology Lookup Service (online, the latest releases)'],
    ['local', 'Copies of the ontologies on this computer (works offline)']
  ];
  class TermsTool {
    constructor(tab, root, given) {
      this.tab = tab;
      this.fs = tab.fs;
      this.root = root;
      this.rows = [];
      const last = store.get('termsTool', {});
      this.source = given.obo ? 'local' : last.source || 'ols';
      this.hpo = (given.obo && /hp/i.test(base(given.obo)) && given.obo) || last.hpo || '';
      this.mondo = (given.obo && /mondo/i.test(base(given.obo)) && given.obo) || last.mondo || '';
      this.drawing = given.drawing || given.input || '';
      this.termsIn = given.terms || '';
      this._build();
    }
    _remember() {
      store.set('termsTool', { source: this.source, hpo: this.hpo, mondo: this.mondo });
    }
    _build() {
      const R = this.root;
      R.appendChild(h('div.tl-toolhead', h('h2.tl-title', 'Match conditions to terms'), h('span.tl-pkg', 'hponorm · mondonorm')));
      R.appendChild(h('p.tl-lead', 'GA4GH and Phenopackets files name conditions by ontology terms, using Mondo for diseases and the Human Phenotype Ontology (HPO) for signs and symptoms. Here you can find the term for each condition in a drawing’s colour key, and keep the matches in a terms file for Drawing → GA4GH to use.'));
      const more = h('details.tl-about', h('summary', 'More about matching'), h('p', { html: 'The searches are the ones hponorm and mondonorm use. EBI’s Ontology Lookup Service has the latest releases and finds terms that a local search can miss. But it needs the internet, and it sends the names you search for to EBI, though not the drawing. A copy of an ontology on this computer works offline. You can download the HPO here (about 11 MB). Mondo’s file, which is about 50 MB, has to be downloaded with your browser from its download page and then added, because its host doesn’t let web pages download it.' }));
      const hb = h('button.linkbtn', { type: 'button', html: icon('book') + '<span>Help and a walkthrough</span>' });
      hb.addEventListener('click', () => MG.app.showHelp('h-tool-terms'));
      more.appendChild(h('p', hb));
      R.appendChild(more);
      // 1. the drawing (and a terms file to start from)
      const f1 = h('div.tl-form');
      const fDraw = { key: 'drawing', type: 'file', label: '1 · The drawing', kinds: ['studio'], studio: true };
      const fTerms = { key: 'terms', type: 'file', label: 'Start from a terms file (optional)', kinds: ['terms'], optional: true, none: 'none (start with an empty list)' };
      const v = { drawing: this.drawing, terms: this.termsIn };
      if (!v.drawing) {
        const { mine, ex } = filesOfKinds(['studio']);
        v.drawing = (mine[0] || ex[0] || {}).path || '';
      }
      this.tab.pickers = [];
      const r1 = fieldRow(this.tab, fDraw, v, (k, val) => {
        this.drawing = val;
        this.load();
      });
      const r2 = fieldRow(this.tab, fTerms, v, (k, val) => {
        this.termsIn = val;
        this.load();
      });
      this.drawing = v.drawing;
      f1.append(r1.row, r2.row);
      R.appendChild(f1);
      // 2. where to search
      const f2 = h('div.tl-form');
      const srcRow = h('div.tl-field', h('div.tl-label', '2 · Search in'));
      SOURCES.forEach(([val, lab]) => {
        const id = 'src-' + val;
        const r = h('input', { type: 'radio', name: 'tl-src', id, value: val });
        r.checked = this.source === val;
        r.addEventListener('change', () => {
          this.source = val;
          this._remember();
          this._srcShow();
        });
        srcRow.appendChild(h('label.tl-checkline', { for: id }, r, h('span', lab)));
      });
      f2.appendChild(srcRow);
      this.localBox = h('div.tl-localbox');
      f2.appendChild(this.localBox);
      R.appendChild(f2);
      this._localPickers();
      this._srcShow();
      // 3. the conditions
      R.appendChild(h('h3.tl-sub', '3 · The conditions'));
      this.table = h('div.tl-terms');
      R.appendChild(this.table);
      // 4. save
      R.appendChild(h('h3.tl-sub', '4 · Keep the matches'));
      const f4 = h('div.tl-form');
      this.outIn = h('input.tl-input.mono', { type: 'text', spellcheck: 'false', id: 'tl-terms-out' });
      f4.appendChild(h('div.tl-field', h('label.tl-label', { for: 'tl-terms-out' }, 'Save the terms file as'), this.outIn));
      this.writeKey = h('input', { type: 'checkbox', id: 'tl-writekey' });
      f4.appendChild(h('div.tl-field.check', h('label.tl-checkline', { for: 'tl-writekey' }, this.writeKey, h('span', 'Also write the ids into the drawing’s colour key (“Breast cancer [MONDO:0007254]”), in a copy of the drawing'))));
      const save = h('button.btn.primary', { type: 'button', html: icon('save') + '<span>Save</span>' });
      save.addEventListener('click', () => this.save());
      this.saveMsg = h('span.tl-check');
      f4.appendChild(h('div.tl-actions', save, this.saveMsg));
      R.appendChild(f4);
      this.after = h('div.tl-result');
      R.appendChild(this.after);
      this.same = h('div.tl-same');
      R.appendChild(this.same);
      this.load();
    }
    _localPickers() {
      const B = this.localBox;
      B.innerHTML = '';
      const v = { hpo: this.hpo, mondo: this.mondo };
      const fH = { key: 'hpo', type: 'file', label: 'HPO (hp.obo)', kinds: ['obo'], optional: true, none: 'none yet' };
      const fM = { key: 'mondo', type: 'file', label: 'Mondo (mondo.obo)', kinds: ['obo'], optional: true, none: 'none yet' };
      const rH = fieldRow(this.tab, fH, v, (k, val) => {
        this.hpo = val;
        this._remember();
      });
      const rM = fieldRow(this.tab, fM, v, (k, val) => {
        this.mondo = val;
        this._remember();
      });
      const dl = h('button.btn.small', { type: 'button', html: icon('download') + '<span>Download the HPO here (11 MB)</span>' });
      dl.addEventListener('click', () => this.downloadHpo(dl, rH));
      rH.row.appendChild(h('div.tl-help', dl, ' (from github.com/obophenotype/human-phenotype-ontology, saved in ~/ontologies).'));
      rM.row.appendChild(h('div.tl-help', { html: 'Download <code>mondo.obo</code> with your browser from <a href="https://mondo.monarchinitiative.org/pages/download/" target="_blank" rel="noopener">Mondo’s download page</a>, then add it with “From my computer…” above.' }));
      B.append(rH.row, rM.row);
      this.hpoRow = rH;
    }
    _srcShow() {
      this.localBox.hidden = this.source !== 'local';
    }
    async downloadHpo(btn, row) {
      btn.disabled = true;
      const lab = btn.querySelector('span');
      lab.textContent = 'Downloading…';
      try {
        const r = await fetch(MG.config.hpoDownload, { credentials: 'omit' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const text = await r.text();
        if (!text.startsWith('format-version:')) throw new Error('what came back is not an OBO file');
        const p = HOME() + '/ontologies/hp.obo';
        this.fs.mkdirp(dirOf(p));
        this.fs.writeText(p, text);
        this.hpo = p;
        this._remember();
        this._localPickers();
        toast(`Saved the HPO as <b>${esc(tilde(p))}</b> (${(text.length / 1048576).toFixed(1)} MB).`, 'ok', 4000);
      } catch (e) {
        lab.textContent = 'Download the HPO here (11 MB)';
        btn.disabled = false;
        toast('The HPO couldn’t be downloaded (' + esc(e.message) + '). Check your internet connection.', 'error', 8000);
      }
    }
    /** the drawing's conditions, with the terms they have already */
    async load() {
      const T = this.table;
      this.rows = [];
      T.innerHTML = '';
      if (!this.drawing) {
        T.appendChild(h('p.muted', 'Choose a drawing above.'));
        return;
      }
      this.outIn.value = this.termsIn && this.termsIn.startsWith(HOME() + '/') ? tilde(this.termsIn) : `~/terms/${stemOf(this.drawing)}-terms.json`;
      T.appendChild(h('div.tl-status', h('span.spinner.small'), h('span', kernel().state === 'ready' ? 'Reading the colour key…' : 'Starting Python in your browser (about 10 MB to download the first time)…')));
      const r = await pyCall('pedwb.gui.conditions', { path: this.drawing, terms: this.termsIn || null });
      T.innerHTML = '';
      if (!r.ok) {
        T.appendChild(h('div.tl-fail', r.error));
        return;
      }
      const conds = r.result.conditions;
      if (!conds.length) {
        T.appendChild(h('p', 'The drawing’s colour key doesn’t name any conditions. Name them in the Studio with the Key button, then come back.'));
        return;
      }
      const all = h('button.btn.small', { type: 'button', html: icon('search') + '<span>Suggest terms for all</span>' });
      all.addEventListener('click', async () => {
        all.disabled = true;
        for (const row of this.rows) if (!row.chosen) await row.suggest();
        all.disabled = false;
      });
      T.appendChild(h('div.tl-termsbar', all, h('span.muted', ' or match them one at a time below.')));
      conds.forEach((c) => this.rows.push(this._row(c)));
      this._same();
    }
    _row(c) {
      const T = this.table;
      const guessHp = /loss|impair|disab|delay|seizure|deaf|blind|short stature|tall|hypo|hyper|abnormal|anomal|defect|syndactyly|polydactyly|cleft|murmur/i.test(c.name);
      const row = { c, ontology: c.id ? (c.id.startsWith('HP:') ? 'HP' : 'MONDO') : guessHp ? 'HP' : 'MONDO', chosen: c.id ? { id: c.id, label: c.label || c.name, version: c.version || '' } : null };
      const box = h('div.tl-cond');
      const title = h('div.tl-condh', h('b', c.name), h('small.muted', ` · ${c.people} ${c.people === 1 ? 'person' : 'people'} in the drawing`));
      const ont = h('select.tl-input.small', { 'aria-label': 'Which ontology to search for ' + c.name }, h('option', { value: 'MONDO' }, 'a disease (Mondo)'), h('option', { value: 'HP' }, 'a sign or symptom (HPO)'));
      ont.value = row.ontology;
      ont.addEventListener('change', () => {
        row.ontology = ont.value;
        row.cands.innerHTML = '';
      });
      const q = h('input.tl-input.small', { type: 'text', value: c.name, 'aria-label': 'Words to search for', spellcheck: 'false' });
      const go = h('button.btn.small', { type: 'button', html: icon('search') + '<span>Suggest</span>' });
      const typed = h('input.tl-input.small.mono', { type: 'text', placeholder: 'or type an id: MONDO:0007254', 'aria-label': 'An ontology id typed by hand', spellcheck: 'false' });
      const check = h('button.btn.small', { type: 'button' }, 'Use this id');
      const chosenEl = h('div.tl-chosen');
      row.cands = h('div.tl-cands');
      box.append(title, h('div.tl-condrow', h('span.muted', 'Search for '), ont, q, go), h('div.tl-condrow', typed, check), row.cands, chosenEl);
      T.appendChild(box);
      const showChosen = () => {
        chosenEl.innerHTML = '';
        if (row.chosen) {
          const clear = h('button.linkbtn', { type: 'button' }, 'clear');
          clear.addEventListener('click', () => {
            row.chosen = null;
            showChosen();
            this._same();
          });
          chosenEl.append(h('span.tl-okmark', { html: icon('check') }), ' ', h('code', row.chosen.id), ' ', row.chosen.label, row.chosen.version ? h('small.muted', ` (release ${row.chosen.version})`) : '', ' · ', clear);
          box.classList.add('done');
        } else {
          chosenEl.appendChild(h('span.muted', 'No term yet, so this condition would be left out of the GA4GH files.'));
          box.classList.remove('done');
        }
      };
      row.suggest = async () => {
        const src = this.source;
        const file = src === 'local' ? (row.ontology === 'HP' ? this.hpo : this.mondo) : null;
        if (src === 'local' && !file) {
          row.cands.innerHTML = '';
          row.cands.appendChild(h('p.tl-warn', `Choose a copy of ${row.ontology === 'HP' ? 'the HPO' : 'Mondo'} above (2 · Search in), or search EBI’s service instead.`));
          return;
        }
        go.disabled = true;
        row.cands.innerHTML = '';
        row.cands.appendChild(h('div.tl-status', h('span.spinner.small'), h('span', src === 'local' ? `Searching ${base(file)} (the first search reads the whole file, which takes a few seconds)…` : 'Asking EBI’s Ontology Lookup Service…')));
        const r = await pyCall('pedwb.gui.suggest', { names: [q.value.trim() || c.name], ontology: row.ontology, source: src, file, limit: 6 });
        go.disabled = false;
        row.cands.innerHTML = '';
        if (!r.ok) {
          row.cands.appendChild(h('div.tl-fail', r.error));
          return;
        }
        const name = q.value.trim() || c.name;
        const err = r.result.errors[name];
        const list = r.result.results[name] || [];
        if (err) row.cands.appendChild(h('div.tl-fail', err));
        else if (!list.length) row.cands.appendChild(h('p.muted', 'Nothing found. Try other words, or the other ontology.'));
        list.forEach((cand, i) => {
          const id = `cand-${Math.random().toString(36).slice(2, 7)}`;
          const radio = h('input', { type: 'radio', name: 'c-' + c.name, id });
          radio.checked = row.chosen && row.chosen.id === cand.id;
          radio.addEventListener('change', () => {
            row.chosen = { id: cand.id, label: cand.label, version: r.result.version || '' };
            showChosen();
            this._same();
          });
          row.cands.appendChild(h('label.tl-cand', { for: id }, radio, h('span', h('code', cand.id), ' ', h('b', cand.label), h('small.muted', ` · ${cand.matchedOn} · ${cand.score}`), cand.definition ? h('small.tl-def', cand.definition) : '')));
          void i;
        });
        if (list.length) row.cands.appendChild(h('small.muted', `From ${r.result.source}${r.result.version ? ', release ' + r.result.version : ''}.`));
      };
      go.addEventListener('click', row.suggest);
      q.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          row.suggest();
        }
      });
      check.addEventListener('click', async () => {
        const id = typed.value.trim();
        if (!id) return;
        check.disabled = true;
        const src = this.source;
        const ontology = /^hp[:_]/i.test(id) ? 'HP' : /^mondo[:_]/i.test(id) ? 'MONDO' : null;
        const file = src === 'local' ? (ontology === 'HP' ? this.hpo : this.mondo) : null;
        let r = null;
        if (ontology && (src === 'ols' || file)) r = await pyCall('pedwb.gui.lookup', { curie: id, ontology, source: src, file });
        check.disabled = false;
        if (r && r.ok && r.result.found) {
          row.chosen = { id: r.result.id, label: r.result.label, version: r.result.version || '' };
          if (r.result.obsolete) toast(`${esc(r.result.id)} is obsolete in this release. Look for the term that replaces it.`, 'warn', 8000);
        } else if (r && r.ok && !r.result.found && !/did not answer/.test(r.result.error || '')) {
          toast(esc(r.result.error), 'warn', 7000);
          return;
        } else {
          // (not checked: no copy of that ontology here, or the service did not answer) – kept as typed, with the name
          if (!/^[A-Za-z][\w.-]*:\S+$/.test(id)) {
            toast('That isn’t an ontology id. Ontology ids look like MONDO:0007254 or HP:0000365.', 'warn', 6000);
            return;
          }
          row.chosen = { id, label: c.name, version: '' };
          toast(`${esc(id)} couldn’t be checked here, so it’s used as you typed it, with the label “${esc(c.name)}”.`, null, 6000);
        }
        showChosen();
        this._same();
      });
      showChosen();
      return row;
    }
    /** the matches as a terms file: {"Name": {"id", "label", "version"}} */
    _termsObject() {
      const out = {};
      for (const r of this.rows) if (r.chosen) out[r.c.name] = Object.assign({ id: r.chosen.id, label: r.chosen.label }, r.chosen.version ? { version: r.chosen.version } : {});
      return out;
    }
    _same() {
      const box = this.same;
      box.innerHTML = '';
      const names = this.rows.map((r) => r.c.name);
      if (!names.length) return;
      const out = expand(this.outIn.value.trim() || `~/terms/${stemOf(this.drawing)}-terms.json`);
      const ont = (this.rows[0] || {}).ontology === 'HP' ? 'HP' : 'MONDO';
      const code =
        this.source === 'local'
          ? [
              ont === 'HP' ? 'from hponorm.hpo import HpoIndex as Index' : 'from mondonorm.mondo import MondoIndex as Index',
              '',
              `index = Index.load(${pyq((ont === 'HP' ? this.hpo : this.mondo) || '/home/user/ontologies/' + (ont === 'HP' ? 'hp.obo' : 'mondo.obo'))}, allow_download=False)`,
              `for c in index.search(${pyq(names[0])}, limit=6):`,
              '    print(c.id, c.label, c.score)'
            ]
          : [ont === 'HP' ? 'from hponorm.ols import OlsClient' : 'from mondonorm.ols import OlsClient', '', `for c in OlsClient().search(${pyq(names[0])}, limit=6):`, '    print(c.id, c.label, c.score)'];
      code.push('', '# the matches, kept as a terms file for studio2ga4gh -t', 'import json', `terms = ${JSON.stringify(this._termsObject(), null, 4).replace(/\n/g, '\n')}`, `json.dump(terms, open(${pyq(out)}, "w"), indent=2)`);
      const details = h('details.tl-samebox', h('summary', { html: icon('code') + '<span>The same in Python</span>' }));
      const pre = h('pre.code', { dataset: { run: 'py' } }, h('code', code.join('\n')));
      details.appendChild(h('div.tl-code', h('div.tl-code-t', 'Python (a notebook cell)'), pre));
      details.appendChild(h('p.tl-help', { html: 'There’s no terminal command that reads a drawing’s key. hponorm and mondonorm match the names in GA4GH and Phenopackets files, and they ask you questions as they go. This terminal can’t pass your answers to them, so here they take their answers from a file instead: <code>hponorm FILE.json --mapping answers.json --auto-remembered</code>.' }));
      box.appendChild(details);
      MG.app.decorateCode(pre);
    }
    async save() {
      const terms = this._termsObject();
      const n = Object.keys(terms).length;
      if (!n) {
        this.saveMsg.textContent = 'Match at least one condition first.';
        return;
      }
      const out = expand(this.outIn.value.trim());
      if (!out.startsWith(HOME() + '/')) {
        this.saveMsg.textContent = 'Save it in your home folder (~).';
        return;
      }
      this.saveMsg.textContent = '';
      // what the file had already (names not in this drawing are kept)
      let old = {};
      try {
        const e = this.fs.get(out);
        if (e && e.kind === 'text') old = JSON.parse(e.text) || {};
        if (old.resolved) old = old.resolved;
      } catch (err) {
        old = {};
      }
      const merged = Object.assign({}, old, terms);
      this.fs.mkdirp(dirOf(out));
      this.fs.writeText(out, JSON.stringify(merged, null, 2) + '\n');
      this.after.innerHTML = '';
      this.after.appendChild(h('div.tl-done.ok', { html: icon('check') + `<span>Saved ${n} match${n === 1 ? '' : 'es'} in ${esc(tilde(out))}</span>` }));
      const files = [out];
      if (this.writeKey.checked) {
        const p = await this._writeKey(terms);
        if (p) files.push(p);
      }
      const list = h('div.tl-files');
      files.forEach((p) => list.appendChild(fileChip(p)));
      this.after.appendChild(list);
      const next = h('button.btn.primary', { type: 'button', html: icon('convert') + '<span>Next: Drawing → GA4GH, with these terms</span>' });
      next.addEventListener('click', () => this.tab.choose('studio2ga4gh', { input: files[1] || this.drawing, terms: out }));
      this.after.appendChild(h('div.tl-next', next));
      this.unmatched = this.rows.filter((r) => !r.chosen).map((r) => r.c.name);
      if (this.unmatched.length) this.after.appendChild(h('p.tl-warn', `Not matched yet: ${this.unmatched.join(', ')}. ${this.unmatched.length === 1 ? 'It' : 'They'} will be left out of the GA4GH files until ${this.unmatched.length === 1 ? 'it has' : 'they have'} a term.`));
    }
    /** a copy of the drawing with the ids in its key → its path */
    async _writeKey(terms) {
      let doc;
      try {
        doc = JSON.parse(await this.fs.readText(this.drawing));
      } catch (err) {
        toast('The drawing couldn’t be read: ' + esc(err.message), 'warn', 6000);
        return null;
      }
      const lower = Object.fromEntries(Object.entries(terms).map(([k, val]) => [k.toLowerCase(), val]));
      for (const [k, lab] of Object.entries(doc.legendLabels || {})) {
        const name = String(lab || '').replace(/\s*[[(][A-Za-z][\w.-]*:[^\])]+[\])]\s*$/, '').trim();
        const t = lower[name.toLowerCase()];
        if (t) doc.legendLabels[k] = `${name} [${t.id}]`;
      }
      const p = HOME() + '/pedigrees/' + stemOf(this.drawing) + '-with-terms.studio.json';
      this.fs.mkdirp(dirOf(p));
      this.fs.writeText(p, JSON.stringify(doc, null, 2) + '\n');
      return p;
    }
  }

  MG.ToolsTab = ToolsTab;
})();
