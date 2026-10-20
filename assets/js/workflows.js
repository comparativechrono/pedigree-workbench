/* =====================================================================
   Workflows: tools of the Tools tab chained together and run in one go,
   after the workflows of the Galaxy emulator in the bioinformatics
   workbench.

   A workflow is a file of your own, ~/workflows/NAME.workflow.json. Its
   steps are the workflow's input files and tools, and each tool's input
   files are connected to an input of the workflow or to a file that an
   earlier step writes. The editor draws the steps as boxes, with a
   tool's input files on its left and the files it writes on its right:
   dragging from a file to an input connects them (only files of a kind
   the input takes), and the + by a file offers the tools that read it.

   A run runs the steps in order, in the workbench's Python, exactly as
   the Tools tab runs them (MG.toolsKit.runTool), each with the files the
   steps before it wrote. Its files go into a folder of their own – by
   default ~/results/WORKFLOW/INPUT – with a record of the run
   (workflow-run.json) and its commands as a script (commands.sh).

   What each tool reads and writes in a workflow is in tools.js, beside
   the tool (its wf: the files it writes, and which of its fields only
   say where they go, which a run chooses).

   The first half of this file, the engine (MG.workflowEngine), uses no
   web page, so that the tests run it in Node (tests/workflows); the
   second half is the pages of the Tools tab (MG.WorkflowsUI).
   ===================================================================== */
(function () {
  'use strict';
  const MG = window.MG;
  const { h, esc, toast, store, bus } = MG;
  const K = () => MG.toolsKit;
  const HOME = () => K().HOME();

  /* ================================================================== the engine */
  const FORMAT = 'pedigree_workbench_workflow';
  const RUN_FORMAT = 'pedigree_workbench_workflow_run';
  const RUN_FILE = 'workflow-run.json';
  const EX_DIR = '/data/examples/workflows';
  const WF_DIR = () => HOME() + '/workflows';
  const isWorkflowPath = (p) => /\.workflow\.json$/i.test(String(p || ''));

  /** names of the kinds of file that no tool reads, but some write */
  const MORE_KINDS = { tsv: 'table (TSV)', graphml: 'graph (GraphML)', yaml: 'YAML file', jsonl: 'JSON Lines file' };
  const kindName = (k) => (MG.app.kindNames && MG.app.kindNames[k]) || MORE_KINDS[k] || k;
  /** a list of kinds in words: PED file, MPED file or GA4GH Pedigree */
  function kindsLabel(kinds) {
    const names = Array.from(new Set((kinds || []).map(kindName)));
    return names.length <= 1 ? names.join('') : names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1];
  }
  /** the kinds of input a workflow can have, for an input's settings: [kinds, what they are called] */
  const INPUT_KINDS = [
    [['studio'], 'a Pedigree Studio drawing'],
    [['image'], 'a picture of a pedigree'],
    [['ped', 'mped'], 'a PED or MPED file'],
    [['ped'], 'a PED file'],
    [['mped'], 'an MPED file'],
    [['pedigree', 'family'], 'a GA4GH Pedigree or Phenopackets Family'],
    [['pedigree'], 'a GA4GH Pedigree'],
    [['family'], 'a Phenopackets Family'],
    [['pedigree', 'family', 'cohort', 'phenopacket'], 'a GA4GH or Phenopackets file of any kind'],
    [['pedigree', 'family', 'cohort', 'phenopacket', 'json'], 'a GA4GH file, or one from an older tool to upgrade'],
    [['ped', 'mped', 'pedigree', 'family'], 'a PED, MPED or GA4GH file'],
    [['vcf', 'variants'], 'a VCF file, or a table of genotypes'],
    [['terms'], 'a terms file'],
    [['obo'], 'an ontology (OBO)']
  ];
  const sameKinds = (a, b) => a.length === b.length && a.every((k) => b.includes(k));
  /** kinds in words, as a thing: a PED or MPED file, an ontology (OBO) */
  const inputKindsLabel = (kinds) => {
    const known = INPUT_KINDS.find(([ks]) => sameKinds(ks, kinds));
    if (known) return known[1];
    const words = kindsLabel(kinds);
    return words ? (/^[aeiou]/i.test(words) ? 'an ' : 'a ') + words : 'nothing';
  };

  /** where a file of a kind would be, for a step's form before it runs (the kind of a file is read from its name) */
  const SUFFIX = { studio: '.studio.json', pedigree: '_ga4gh-pedigree.json', family: '_phenopackets-family.json', ped: '.ped', mped: '.mped', image: '.png', vcf: '.vcf', variants: '-genotypes.tsv', terms: '-terms.json', obo: '.obo', tsv: '.tsv', graphml: '.graphml', yaml: '.yaml', jsonl: '.jsonl' };
  const samplePath = (kind, stem) => `${HOME()}/workflow-input/${stem || 'input'}${SUFFIX[kind] || '.json'}`;

  /** a name as a file name: Share a drawing! → share-a-drawing */
  const slug = (s) =>
    String(s || '')
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'workflow';
  const clone = (x) => JSON.parse(JSON.stringify(x));

  /* ---------------- the tools, as steps ---------------- */
  const toolOf = (id) => K().TOOL[id];
  /** a tool can be a step if it says what it writes (Match conditions to terms, which asks as it goes, can't) */
  const usable = (t) => !!(t && t.wf && !t.custom && t.fields);
  const fileFields = (t) => t.fields.filter((f) => f.type === 'file' || f.type === 'files');
  /** the fields that only say where its files go, which a run chooses */
  const isAuto = (t, f) => f.type === 'path' || f.type === 'folder' || ((t.wf && t.wf.auto) || []).includes(f.key);
  /** the fields of a step's settings (the rest are its files, or where they go, or the Studio tab's) */
  const settingFields = (t) => t.fields.filter((f) => f.type !== 'file' && f.type !== 'files' && !isAuto(t, f) && !f.gui);

  /** a tool step's values, as its form would give them to the tool: its settings (params), the rest their defaults;
      its input files ({key: path, or [paths] for several}); and the fields that say where it writes, from
      place(field, default, values) – where a run puts them (or, without place, their defaults) */
  function valuesOf(t, params, files, place) {
    const v = {};
    const defOf = (f) => (typeof f.def === 'function' ? f.def(v) : f.def);
    // (a setting as its field holds it, whatever a workflow's file gives: a tick true or false, a number as a number
    // or text, and the rest as text)
    const asType = (f, x) => (f.type === 'check' ? x === true || x === 'true' : typeof x === 'string' || (f.type === 'number' && typeof x === 'number') ? x : String(x));
    for (const f of t.fields) {
      if (f.type === 'file') v[f.key] = (files && files[f.key]) || '';
      else if (f.type === 'files') v[f.key] = (files && files[f.key]) || [];
      else if (params && params[f.key] != null && !isAuto(t, f) && !(params[f.key] === '' && typeof f.def === 'function')) v[f.key] = asType(f, params[f.key]);
      else v[f.key] = defOf(f);
    }
    // (where it writes: the whole form is known by now – a folder may be named after the start of the file names)
    if (place) for (const f of t.fields) if (isAuto(t, f)) v[f.key] = place(f, v[f.key], v);
    // as the Tools tab gives them: paths in full, and the fields the form hides left out
    const x = Object.assign({}, v);
    for (const f of t.fields) {
      if ((f.type === 'file' || f.type === 'folder' || f.type === 'path') && x[f.key]) x[f.key] = K().expand(x[f.key]);
      if (f.type === 'files') x[f.key] = (x[f.key] || []).map(K().expand);
      if (f.show && !f.show(v)) x[f.key] = f.type === 'check' ? false : f.type === 'files' ? [] : '';
    }
    return x;
  }
  /** a step's settings that aren't their defaults, from the values a tool ran with (for a workflow made from runs) */
  function paramsFrom(t, values) {
    const files = {};
    fileFields(t).forEach((f) => (files[f.key] = values[f.key]));
    const params = {};
    // (in the form's order: a default that follows a setting before it – PedGen's generations, its mode – is no setting)
    for (const f of settingFields(t)) {
      if (values[f.key] == null || (f.show && !f.show(values))) continue;
      if (String(values[f.key]) !== String(valuesOf(t, params, files, null)[f.key])) params[f.key] = values[f.key];
    }
    return params;
  }
  /** a setting whose default comes from the name of an input file (the family id of PedInterp, say), which a
      workflow leaves to be worked out when it runs, unless it is given */
  function fromInputName(t, f) {
    if (typeof f.def !== 'function') return false;
    const a = {}, b = {};
    fileFields(t).forEach((x) => {
      const kind = x.kinds[0];
      a[x.key] = x.type === 'files' ? [samplePath(kind, 'alpha')] : samplePath(kind, 'alpha');
      b[x.key] = x.type === 'files' ? [samplePath(kind, 'bravo')] : samplePath(kind, 'bravo');
    });
    try {
      return String(valuesOf(t, {}, a, null)[f.key]) !== String(valuesOf(t, {}, b, null)[f.key]);
    } catch (e) {
      return false;
    }
  }
  /** where a step writes in a run's folder R: a file by its default name; a folder as R itself, or by its own name
      (a Phenopacket for each person: R/okafor-people), or as the tool says (a PED file for each condition) */
  function placer(t, R) {
    return (f, def, v) => {
      if (f.type === 'folder') {
        const sub = t.wf.subdir ? t.wf.subdir(v) : '';
        if (sub) return R + '/' + sub;
        const d = K().expand(def || '');
        return !d || d === HOME() + '/results' || d === HOME() ? R : R + '/' + K().base(d);
      }
      if (f.type === 'path') return R + '/' + K().base(K().expand(def || f.key));
      return def;
    };
  }
  /** the files a tool step writes with these values: [{name, label, kinds | from, path | find, many, guess}] */
  const outputsOf = (t, v) => ((t.wf && t.wf.outputs(v)) || []).filter(Boolean);

  /* ---------------- a workflow: its steps, and how they are connected ---------------- */
  function newWorkflow(name) {
    const now = new Date().toISOString();
    return { [FORMAT]: 1, name: name || 'New workflow', annotation: '', steps: [], created: now, updated: now };
  }
  /** a workflow from the text of its file (or an error that says what is wrong with it) */
  function parse(text) {
    let w;
    try {
      w = JSON.parse(text);
    } catch (e) {
      throw new Error('It isn’t a workflow: it isn’t JSON (' + e.message + ').');
    }
    if (!w || typeof w !== 'object' || !w[FORMAT] || !Array.isArray(w.steps)) throw new Error('It isn’t a workflow of the Pedigree workbench.');
    for (const s of w.steps) {
      if (!s || typeof s.id !== 'string' || !['input', 'tool'].includes(s.type)) throw new Error('One of its steps isn’t a step it knows.');
      if (s.type === 'input') s.kinds = Array.isArray(s.kinds) && s.kinds.length ? s.kinds.map(String) : ['studio'];
      if (s.type === 'tool') {
        s.params = s.params && typeof s.params === 'object' ? s.params : {};
        s.connections = s.connections && typeof s.connections === 'object' ? s.connections : {};
      }
      s.x = Number(s.x) || 0;
      s.y = Number(s.y) || 0;
    }
    w.name = String(w.name || 'Workflow');
    w.annotation = String(w.annotation || '');
    return w;
  }
  const serialise = (w) => JSON.stringify(w, null, 2) + '\n';
  const stepOf = (w, id) => w.steps.find((s) => s.id === id);
  const nextId = (w) => 's' + (Math.max(0, ...w.steps.map((s) => Number(String(s.id).replace(/\D/g, '')) || 0)) + 1);
  /** a step's connections to one of its inputs, as a list (several for a tool that reads several files) */
  const connsOf = (s, key) => {
    const c = s.connections && s.connections[key];
    return !c ? [] : Array.isArray(c) ? c.filter(Boolean) : [c];
  };
  const allConns = (s) => (s.type === 'tool' ? Object.keys(s.connections || {}).flatMap((k) => connsOf(s, k).map((c) => Object.assign({ key: k }, c))) : []);

  /** what every step writes, as the workflow stands, worked out once, in the order the steps run, each from the files
      of the steps before it: {stepId: [{name, label, kinds, many}]} (an input step: the file given to it). The
      functions below take it as `out`, or work it out themselves. */
  function outputsAll(w) {
    const out = {};
    for (const s of orderSteps(w)) {
      if (s.type === 'input') {
        out[s.id] = [{ name: 'file', label: inputKindsLabel(s.kinds).replace(/^an? /, ''), kinds: s.kinds }];
        continue;
      }
      const t = toolOf(s.tool);
      out[s.id] = [];
      if (!usable(t)) continue;
      try {
        out[s.id] = outputsOf(t, designValues(w, s, out)).map((o) => ({ name: o.name, label: o.label, many: !!o.many, kinds: o.from ? fromKinds(w, s, o, out) : o.kinds }));
      } catch (e) {
        /* settings it can't read: it writes nothing anyone can connect to (problems says why) */
      }
    }
    return out;
  }
  /** the file a connection carries: {name, label, kinds, many}, or null */
  const connOut = (w, c, out) => ((out || outputsAll(w))[c.step] || []).find((x) => x.name === c.output) || null;
  /** a tool step's values before it runs: its input files as files of the kinds they are connected to, each with a
      name of its own and a set of files as two, so that the form's checks see them as they will be */
  function designValues(w, s, out) {
    out = out || outputsAll(w);
    const t = toolOf(s.tool);
    const files = {};
    for (const f of fileFields(t)) {
      const paths = connsOf(s, f.key).flatMap((c) => {
        const o = connOut(w, c, out);
        const kind = (o && o.kinds[0]) || f.kinds[0];
        const stem = `${c.step}-${c.output}`;
        return o && o.many ? [samplePath(kind, stem + '-1'), samplePath(kind, stem + '-2')] : [samplePath(kind, stem)];
      });
      files[f.key] = f.type === 'files' ? paths : paths[0] || '';
    }
    return valuesOf(t, s.params, files, placer(t, `${HOME()}/results/${slug(w.name)}/input`));
  }
  /** the files a step writes, as it stands: [{name, label, kinds, many}] (an input step: the file given to it) */
  const stepOutputs = (w, s, out) => (out || outputsAll(w))[s.id] || [];
  /** the kinds of a file a step writes that is of the kind of one it reads (Fill in missing terms, De-identify …) */
  function fromKinds(w, s, o, out) {
    const f = toolOf(s.tool).fields.find((x) => x.key === o.from);
    const conns = connsOf(s, o.from);
    const kinds = conns.length ? Array.from(new Set(conns.flatMap((c) => outKinds(w, c, out)))) : f ? f.kinds : [];
    return Array.from(new Set(kinds.flatMap((k) => (o.map && o.map[k]) || [k])));
  }
  /** the kinds of file a connection carries */
  function outKinds(w, c, out) {
    const o = connOut(w, c, out);
    return o ? o.kinds : [];
  }
  const isMany = (w, c, out) => {
    const o = connOut(w, c, out);
    return !!(o && o.many);
  };
  /** a tool step's input files, as they stand: [{key, label, kinds, many, optional}] – the ones its form shows */
  function stepInputs(w, s, out) {
    const t = toolOf(s.tool);
    if (!usable(t)) return [];
    const v = designValues(w, s, out);
    return fileFields(t)
      .filter((f) => !f.show || f.show(v))
      .map((f) => ({ key: f.key, label: f.label, kinds: f.kinds, many: f.type === 'files', optional: !!f.optional }));
  }
  /** does step `from` lead, through the files it writes, to step `to`? */
  function reaches(w, from, to) {
    const seen = new Set();
    const go = (id) => {
      if (id === to) return true;
      if (seen.has(id)) return false;
      seen.add(id);
      return w.steps.filter((s) => allConns(s).some((c) => c.step === id)).some((s) => go(s.id));
    };
    return go(from);
  }
  /** why a file can't be connected to an input ('' if it can) */
  function whyNot(w, fromId, output, toId, key) {
    const a = stepOf(w, fromId), b = stepOf(w, toId);
    if (!a || !b) return 'That step isn’t there any more.';
    if (a === b) return 'A step can’t read a file it writes itself.';
    if (b.type !== 'tool') return 'Only a tool reads files.';
    const t = toolOf(b.tool);
    const f = t && fileFields(t).find((x) => x.key === key);
    if (!f) return 'That tool has no such input.';
    const out = outputsAll(w);
    // (an input its settings hide – an ontology for Fill in missing terms, unless it looks terms up here – reads nothing)
    if (!stepInputs(w, b, out).some((x) => x.key === key)) return `With its settings as they are, ${t.title} doesn’t read “${f.label}”.`;
    const kinds = outKinds(w, { step: fromId, output }, out);
    if (!kinds.some((k) => f.kinds.includes(k))) return `${t.title} reads ${inputKindsLabel(f.kinds)} there, and this is ${kinds.length ? inputKindsLabel(kinds) : 'nothing it knows'}.`;
    if (isMany(w, { step: fromId, output }, out) && f.type !== 'files') return `This is a set of files, and ${t.title} reads one file there.`;
    if (connsOf(b, key).some((c) => c.step === fromId && c.output === output)) return 'They are connected already.';
    if (reaches(w, toId, fromId)) return 'That would make a loop: a step can’t read a file that comes from its own.';
    return '';
  }
  /** connect a file to a tool's input (one more, for a tool that reads several files) → '' or why it can't be */
  function connect(w, fromId, output, toId, key) {
    const why = whyNot(w, fromId, output, toId, key);
    if (why) return why;
    const b = stepOf(w, toId);
    const f = fileFields(toolOf(b.tool)).find((x) => x.key === key);
    b.connections = b.connections || {};
    if (f.type === 'files') b.connections[key] = connsOf(b, key).concat([{ step: fromId, output }]);
    else b.connections[key] = { step: fromId, output };
    return '';
  }
  function disconnect(w, toId, key, fromId, output) {
    const b = stepOf(w, toId);
    if (!b || !b.connections) return;
    const left = connsOf(b, key).filter((c) => !(c.step === fromId && (output == null || c.output === output)));
    if (Array.isArray(b.connections[key]) && left.length) b.connections[key] = left;
    else if (left.length) b.connections[key] = left[0];
    else delete b.connections[key];
  }
  function removeStep(w, id) {
    w.steps = w.steps.filter((s) => s.id !== id);
    w.steps.forEach((s) => Object.keys(s.connections || {}).forEach((k) => disconnect(w, s.id, k, id)));
  }
  /** the steps in the order they run: each after the steps whose files it reads, column by column, then from the top */
  function orderSteps(w) {
    const depth = depths(w);
    return w.steps.slice().sort((a, b) => depth[a.id] - depth[b.id] || (a.type === 'input' ? 0 : 1) - (b.type === 'input' ? 0 : 1) || a.y - b.y || a.x - b.x);
  }
  /** each step's distance from the inputs: 0 for an input, or one more than the furthest step it reads from */
  function depths(w) {
    const d = {};
    const go = (s, seen) => {
      if (d[s.id] != null) return d[s.id];
      if (seen.has(s.id)) return 0;
      seen.add(s.id);
      const ins = allConns(s).map((c) => stepOf(w, c.step)).filter(Boolean);
      d[s.id] = ins.length ? Math.max(...ins.map((x) => go(x, seen) + 1)) : s.type === 'input' ? 0 : 1;
      return d[s.id];
    };
    w.steps.forEach((s) => go(s, new Set()));
    return d;
  }
  /** the steps arranged in columns, the inputs on the left and each step to the right of the ones it reads */
  function autoLayout(w) {
    const depth = depths(w);
    const out = outputsAll(w);
    const title = (s) => (s.type === 'input' ? s.label || '' : toolOf(s.tool) ? toolOf(s.tool).title : s.tool);
    const tall = (s) => 54 + (title(s).length > 24 ? 18 : 0) + 23 * ((s.type === 'input' ? 0 : stepInputs(w, s, out).length) + stepOutputs(w, s, out).length);
    const cols = {};
    orderSteps(w).forEach((s) => {
      const c = depth[s.id] || 0;
      cols[c] = cols[c] || 16;
      s.x = 16 + c * 270;
      s.y = cols[c];
      cols[c] += tall(s) + 34;
    });
  }
  /** what stops a workflow running, in words: [{step, text}] (step: the id of the step it is about, or null) */
  function problems(w) {
    const list = [];
    const add = (step, text) => list.push({ step, text });
    if (!w.steps.some((s) => s.type === 'tool')) add(null, 'It has no steps yet: add a tool with Add a step.');
    const n = numbers(w);
    const out = outputsAll(w);
    for (const s of w.steps) {
      const name = `${n[s.id]}. ${s.type === 'input' ? s.label || 'Input' : toolOf(s.tool) ? toolOf(s.tool).title : s.tool}`;
      if (s.type === 'input') {
        if (!w.steps.some((x) => allConns(x).some((c) => c.step === s.id))) add(s.id, `${name}: no step reads it.`);
        continue;
      }
      const t = toolOf(s.tool);
      if (!usable(t)) {
        add(s.id, `${name}: the workbench has no such tool${s.tool === 'terms' ? ' in a workflow (Match conditions to terms asks as it goes: give its terms file to the workflow as an input)' : ''}.`);
        continue;
      }
      for (const f of stepInputs(w, s, out)) {
        const cs = connsOf(s, f.key);
        if (!cs.length && !f.optional) add(s.id, `${name}: “${f.label}” isn’t connected.`);
        for (const c of cs) {
          const src = stepOf(w, c.step);
          const o = src && connOut(w, c, out);
          if (!src) add(s.id, `${name}: “${f.label}” is connected to a step that was removed.`);
          else if (!o) add(s.id, `${name}: “${f.label}” is connected to a file that step ${n[src.id]} doesn’t write with its settings as they are.`);
          else if (!o.kinds.some((k) => f.kinds.includes(k))) add(s.id, `${name}: “${f.label}” takes ${kindsLabel(f.kinds)}, and step ${n[src.id]} writes ${kindsLabel(o.kinds)} there.`);
          else if (o.many && !f.many) add(s.id, `${name}: “${f.label}” takes one file, and step ${n[src.id]} writes a set of them.`);
          // (an input that can be left as none can't give a step a file it needs)
          else if (src.type === 'input' && src.optional && !f.optional) add(s.id, `${name}: it needs “${f.label}”, and input ${n[src.id]} can be left as none: untick Optional in its settings.`);
        }
        if (f.many && s.tool.endsWith('merge') && cs.length === 1 && !isMany(w, cs[0], out)) add(s.id, `${name}: “${f.label}” needs two files or more.`);
      }
      // the form's own checks, with files of the kinds connected (and for a file not connected, one of its own)
      try {
        const v = designValues(w, s, out);
        const ready = {};
        for (const f of fileFields(t)) {
          const own = (i) => samplePath(f.kinds[0], `${s.id}-${f.key}-${i}`);
          // (one file where a tool reads several: two for the form, as “needs two files or more” above says so)
          if (f.type === 'files') ready[f.key] = (v[f.key] || []).concat([own(1), own(2)]).slice(0, Math.max(2, (v[f.key] || []).length));
          else ready[f.key] = v[f.key] || own(1);
        }
        const why = K().missing(t, Object.assign({}, v, ready));
        if (why) add(s.id, `${name}: ${why}`);
      } catch (e) {
        add(s.id, `${name}: its settings can’t be read (${e.message}).`);
      }
    }
    return list;
  }
  /** each step's number, in the order they run */
  const numbers = (w) => Object.fromEntries(orderSteps(w).map((s, i) => [s.id, i + 1]));
  /** the tools that can read a file of these kinds: [{t, f, params}] – the input each would read it as, and a setting
      it needs for that input to be read (Fill in missing terms reads an ontology only when it looks terms up in
      copies here), if any */
  function readersOf(kinds, many) {
    const out = [];
    for (const t of K().TOOLS.filter(usable)) {
      const fits = (f) => f.kinds.some((k) => kinds.includes(k)) && (!many || f.type === 'files');
      const shown = (params) => {
        const v = valuesOf(t, params, {}, null);
        return fileFields(t).filter((f) => !f.show || f.show(v));
      };
      let pick = shown({}).find(fits) ? { f: shown({}).find(fits), params: {} } : null;
      for (const sel of settingFields(t).filter((x) => x.type === 'select')) {
        for (const [val] of pick ? [] : sel.options) {
          const f = shown({ [sel.key]: val }).find(fits);
          if (f && !pick) pick = { f, params: { [sel.key]: val } };
        }
      }
      if (pick) out.push(Object.assign({ t }, pick));
    }
    return out;
  }
  /** a new tool step, with no settings of its own yet */
  function addTool(w, toolId, x, y) {
    const s = { id: nextId(w), type: 'tool', tool: toolId, params: {}, connections: {}, x: Math.max(0, Math.round(x || 16)), y: Math.max(0, Math.round(y || 16)) };
    w.steps.push(s);
    return s;
  }
  function addInput(w, kinds, label, x, y) {
    const s = { id: nextId(w), type: 'input', label: label || 'Input file', kinds: kinds || ['studio'], x: Math.max(0, Math.round(x || 16)), y: Math.max(0, Math.round(y || 16)) };
    w.steps.push(s);
    return s;
  }

  /* ---------------- running a workflow ---------------- */
  /** a run's folder: ~/results/WORKFLOW/INPUT, or INPUT-2 … if that is taken */
  function runFolder(fs, w, inputs) {
    const first = orderSteps(w).find((s) => s.type === 'input' && inputs[s.id]);
    const stem = first ? slug(K().stemOf(inputs[first.id])) : 'run';
    const base = `${HOME()}/results/${slug(w.name)}`;
    let p = `${base}/${stem}`;
    for (let n = 2; fs.exists(p); n++) p = `${base}/${stem}-${n}`;
    return p;
  }
  /** what a tool step will run with in a run: its input files, from the files the steps before it wrote (got:
      {stepId: {output: path, or [paths]}}); its files in the run's folder R – or, if a step before it writes a file
      of the same name, in a folder of its own – and the files it will write. → {t, v, outs, problem} */
  function planStep(w, s, got, R, claimed, fs) {
    const t = toolOf(s.tool);
    const n = numbers(w)[s.id];
    const files = {};
    let problem = '';
    for (const f of fileFields(t)) {
      const conns = connsOf(s, f.key);
      const vals = conns.map((c) => got[c.step] && got[c.step][c.output]);
      if (vals.some((x) => x == null)) {
        const src = stepOf(w, conns[vals.findIndex((x) => x == null)].step);
        if (!f.optional) problem = problem || (src && src.type === 'input' ? `“${f.label}” has no file: input ${numbers(w)[src.id]} was left as none.` : `“${f.label}” has no file: a step before it didn’t write one.`);
        continue;
      }
      const flat = [].concat(...vals);
      if (f.type === 'files') files[f.key] = flat;
      else if (flat.length > 1) problem = problem || `“${f.label}” is given ${flat.length} files (${flat.map(K().base).join(', ')}), and ${t.title} reads one.`;
      else files[f.key] = flat[0] || '';
      for (const p of flat) {
        const k = MG.app.pedKind(p);
        if (!f.kinds.includes(k) && !['json', 'other'].includes(k)) problem = problem || `“${f.label}” is ${K().base(p)}, ${/^[aeiou]/i.test(kindName(k)) ? 'an' : 'a'} ${kindName(k)}, and ${t.title} reads ${kindsLabel(f.kinds)} there.`;
      }
    }
    // (a choice whose default follows the kind of file the step is given – what to convert it to – is made as the
    // editor shows it, from the kinds connected, so that the step writes the kind of file it said it would)
    const params = Object.assign({}, s.params);
    const follows = settingFields(t).filter((f) => f.type === 'select' && typeof f.def === 'function' && params[f.key] == null && !fromInputName(t, f));
    if (follows.length) {
      const design = designValues(w, s);
      follows.forEach((f) => (params[f.key] = design[f.key]));
    }
    const plan = (dir) => {
      const v = valuesOf(t, params, files, placer(t, dir));
      return { v, outs: outputsOf(t, v) };
    };
    let p = plan(R);
    const marks = (outs, v) => outs.flatMap((o) => (o.path ? [o.path] : o.guess ? o.guess : [(v.outdir || R) + '/*' + String(o.find)]));
    if (marks(p.outs, p.v).some((m) => claimed.has(m))) p = plan(`${R}/${n}-${slug(t.title)}`);
    marks(p.outs, p.v).forEach((m) => claimed.add(m));
    if (!problem) problem = K().missing(t, p.v);
    if (!problem && fs) {
      for (const f of fileFields(t)) for (const x of [].concat(p.v[f.key] || [])) if (x && !fs.exists(x)) problem = problem || `“${f.label}” is ${K().tilde(x)}, which isn’t there.`;
    }
    return { t, v: p.v, outs: p.outs, problem };
  }
  /** the files a step wrote, as the files it says it writes: {got: {name: path, or [paths]}, lost: [outputs]} (only
      files it wrote this time: one there from an earlier run in the same folder is no file of this step's) */
  function collect(outs, written, fs) {
    const got = {}, lost = [];
    const files = Array.from(new Set(written || [])).filter((p) => fs.exists(p));
    for (const o of outs) {
      if (o.path) {
        if (files.includes(o.path)) got[o.name] = o.path;
        else lost.push(o);
      } else if (o.find) {
        const hits = files.filter((p) => o.find.test(p)).sort();
        if (!hits.length) lost.push(o);
        else got[o.name] = o.many || hits.length > 1 ? hits : hits[0];
      }
    }
    return { got, lost };
  }
  const cap = (s, n = 20000) => (s && s.length > n ? s.slice(0, n / 2) + '\n… (shortened) …\n' + s.slice(-n / 2) : s || '');
  /** the commands of a tool step, one list of words for each */
  const argvsOf = (t, v) => (Array.isArray(t.argv(v)[0]) ? t.argv(v) : [t.argv(v)]);

  /** a workflow's run: its steps one after another, each with the files the steps before it wrote, into folder.
      opts: {w, source (the workflow's file), inputs: {inputStepId: path}, folder, fs, run: (tool, values, onStatus) →
      result (MG.toolsKit.runTool), onChange(record), onStatus(stepId, text)} */
  class Run {
    constructor(opts) {
      this.o = opts;
      this.fs = opts.fs;
      this.stopping = false;
      const w = opts.w;
      const n = numbers(w);
      this.record = {
        [RUN_FORMAT]: 1,
        name: w.name,
        source: opts.source || null,
        folder: opts.folder,
        started: new Date().toISOString(),
        finished: null,
        state: 'running',
        inputs: orderSteps(w)
          .filter((s) => s.type === 'input')
          .map((s) => ({ id: s.id, n: n[s.id], label: s.label, path: opts.inputs[s.id] || '' })),
        steps: orderSteps(w)
          .filter((s) => s.type === 'tool')
          .map((s) => ({ id: s.id, n: n[s.id], tool: s.tool, title: toolOf(s.tool) ? toolOf(s.tool).title : s.tool, state: 'waiting' })),
        workflow: clone(w)
      };
    }
    stop() {
      this.stopping = true;
    }
    _save() {
      try {
        this.fs.mkdirp(this.record.folder);
        this.fs.writeText(this.record.folder + '/' + RUN_FILE, JSON.stringify(this.record, null, 1) + '\n');
      } catch (e) {
        console.error(e);
      }
      if (this.o.onChange) this.o.onChange(this.record);
    }
    async start() {
      const fs = this.fs;
      const R = this.record.folder;
      const got = {};
      const claimed = new Set();
      for (const i of this.record.inputs) got[i.id] = i.path ? { file: i.path } : {};
      // the run's folder (which a file of that name, say, can stop it making)
      let cant = '';
      try {
        if (fs.exists(R) && fs.isDir && !fs.isDir(R)) throw new Error('there is a file of that name');
        fs.mkdirp(R);
      } catch (err) {
        cant = `The folder for the results, ${K().tilde(R)}, couldn’t be made: ${(err && err.message) || err}.`;
      }
      if (cant) {
        this.record.steps.forEach((e, i) => Object.assign(e, i ? { state: 'skipped', error: 'The run couldn’t start.' } : { state: 'failed', error: cant }));
        return this._end(false);
      }
      this._save();
      for (const e of this.record.steps) {
        if (this.stopping) {
          e.state = 'stopped';
          continue;
        }
        try {
          await this._step(e, got, claimed);
        } catch (err) {
          // (anything a step's settings or files make go wrong: that step failed, and the run goes on)
          console.error(err);
          e.state = 'failed';
          e.error = `It couldn’t run: ${(err && err.message) || err}`;
        }
        this._save();
      }
      return this._end(true);
    }
    /** one step: run it (unless it can't be), and record what it did */
    async _step(e, got, claimed) {
      const { w } = this.o;
      const fs = this.fs;
      const R = this.record.folder;
      const s = stepOf(w, e.id);
      const t = toolOf(s.tool);
      if (!usable(t)) {
        e.state = 'failed';
        e.error = `The workbench has no such tool (${s.tool}).`;
        return;
      }
      // (a step that reads a file a failed step should have written doesn't run)
      const before = allConns(s).map((c) => this.record.steps.find((x) => x.id === c.step)).filter(Boolean);
      if (before.some((x) => x.state !== 'ok')) {
        e.state = 'skipped';
        e.error = `It reads what step ${before.find((x) => x.state !== 'ok').n} writes, which didn’t finish.`;
        return;
      }
      const plan = planStep(w, s, got, R, claimed, fs);
      e.values = plan.v;
      try {
        e.argv = argvsOf(t, plan.v);
      } catch (err) {
        e.argv = [];
      }
      if (plan.problem) {
        e.state = 'failed';
        e.error = plan.problem;
        return;
      }
      // the folders it writes in, and any file it needs written first (the ids for Keep some people)
      for (const f of t.fields) {
        if (f.type === 'folder' && plan.v[f.key]) fs.mkdirp(plan.v[f.key]);
        if (f.type === 'path' && plan.v[f.key]) fs.mkdirp(MG.path.dirname(plan.v[f.key]));
      }
      if (t.prepare) {
        e.prepared = [];
        t.prepare(plan.v, { writeText: (p, text) => (fs.writeText(p, text), e.prepared.push({ path: p, text })) });
      }
      e.state = 'running';
      this._save();
      const t0 = Date.now();
      let res;
      try {
        res = await this.o.run(t, plan.v, (text) => this.o.onStatus && this.o.onStatus(e.id, text));
      } catch (err) {
        res = { ok: false, code: 1, stdout: '', stderr: '', files: [], error: String((err && err.message) || err) };
      }
      e.seconds = (Date.now() - t0) / 1000;
      e.code = res.code;
      e.stdout = cap(res.stdout);
      e.stderr = cap(res.stderr);
      if (res.result != null) e.result = res.result;
      if (res.traceback) e.traceback = cap(res.traceback, 8000);
      e.files = Array.from(new Set(res.files || [])).filter((p) => fs.exists(p) && !/\/\.[^/]*$/.test(p));
      if (!res.ok) {
        e.state = 'failed';
        e.error = res.error || `It stopped with an error${res.code ? ` (exit status ${res.code})` : ''}.`;
      } else {
        const c = collect(plan.outs, res.files, fs);
        got[s.id] = c.got;
        e.outputs = c.got;
        if (c.lost.length) {
          e.state = 'failed';
          e.error = `It didn’t write ${c.lost.map((o) => 'the ' + o.label).join(' or ')}.`;
        } else e.state = 'ok';
      }
      try {
        e.summary = summaryOf(t, res, e) || '';
      } catch (err) {
        e.summary = '';
      }
    }
    /** the run is over: its state, and its commands as a script (if it got as far as its folder) */
    _end(script) {
      const states = this.record.steps.map((e) => e.state);
      this.record.state = states.every((x) => x === 'ok') ? 'ok' : states.includes('stopped') && !states.includes('failed') ? 'stopped' : 'failed';
      this.record.finished = new Date().toISOString();
      if (script) {
        try {
          this.fs.writeText(this.record.folder + '/commands.sh', scriptOf(this.record));
        } catch (e) {
          console.error(e);
        }
      }
      this._save();
      return this.record;
    }
  }
  /** one line on what a step did: what the tool says (a check: valid or not), or the files it wrote */
  function summaryOf(t, res, e) {
    if (t.wf.summary) {
      const s = t.wf.summary(res, e.values);
      if (s) return s;
    }
    if (e.state !== 'ok') return '';
    const n = Object.values(e.outputs || {}).reduce((a, x) => a + [].concat(x).length, 0);
    if (n) return `Wrote ${n === 1 ? K().base([].concat(Object.values(e.outputs)[0])[0]) : n + ' files'}.`;
    const line = String(res.stdout || '')
      .split('\n')
      .map((l) => l.trim())
      .find(Boolean);
    return line ? (line.length > 110 ? line.slice(0, 107) + '…' : line) : '';
  }
  /** a run's commands, as a script for the terminal (bash commands.sh), or for a computer with the packages */
  function scriptOf(record) {
    const sh = K().shArg;
    // (a name in a comment stays on its line: a workflow's name, or a step's, can't start a command of its own)
    const line = (s) => String(s == null ? '' : s).replace(/[\r\n\u2028\u2029\u0085]+/g, ' ');
    const when = new Date(record.started);
    const lines = [
      '#!/bin/bash',
      `# “${line(record.name)}”, a workflow of the Pedigree workbench, run on ${when.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })} at ${when.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}.`,
      '# Its steps as commands: run it in the workbench’s terminal (bash commands.sh), or on a computer with the',
      '# packages installed (see the help: On your own computer). Each command runs whether or not the one before it',
      '# succeeded; a step that failed in the run is marked.',
      '',
      `mkdir -p ${sh(record.folder)}`
    ];
    for (const e of record.steps) {
      if (!e.argv || !e.argv.length) continue;
      lines.push('', `# ${e.n}. ${line(e.title)}${e.state === 'ok' ? '' : e.state === 'failed' ? ' (it failed in the run)' : ` (${line(e.state)} in the run)`}`);
      const t = toolOf(e.tool);
      for (const f of (t && t.fields) || []) {
        const p = e.values && e.values[f.key];
        if (f.type === 'folder' && p && p !== record.folder) lines.push(`mkdir -p ${sh(p)}`);
        if (f.type === 'path' && p && MG.path.dirname(p) !== record.folder) lines.push(`mkdir -p ${sh(MG.path.dirname(p))}`);
      }
      // (a file the step needs written first, word for word: its here-document ends at a line that isn't in it)
      for (const pr of e.prepared || []) {
        const body = String(pr.text).replace(/\n$/, '');
        let end = 'EOF';
        while (body.split('\n').some((l) => l.trim() === end)) end += '_';
        lines.push(`cat > ${sh(pr.path)} <<'${end}'`, body, end);
      }
      for (const a of e.argv) lines.push(a.map(sh).join(' '));
    }
    return dedupeMkdir(lines).join('\n') + '\n';
  }
  /** (each folder made once) */
  function dedupeMkdir(lines) {
    const seen = new Set();
    return lines.filter((l) => {
      if (!l.startsWith('mkdir -p ')) return true;
      if (seen.has(l)) return false;
      seen.add(l);
      return true;
    });
  }
  /** a run's steps as a notebook: each step's Python, as the Tools tab shows it under the tool */
  function notebookOf(record) {
    const cells = [];
    const src = (text) => {
      const ls = String(text).split('\n');
      return ls.map((l, i) => (i < ls.length - 1 ? l + '\n' : l));
    };
    const md = (text) => cells.push({ cell_type: 'markdown', id: 'c' + String(cells.length).padStart(2, '0'), metadata: {}, source: src(text) });
    const code = (text) => cells.push({ cell_type: 'code', id: 'c' + String(cells.length).padStart(2, '0'), metadata: {}, source: src(text), execution_count: null, outputs: [] });
    const when = new Date(record.started);
    md(
      `# ${record.name}\n\nThe steps of a workflow run in the Tools tab on ${when.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}, as Python: each cell does what one step did, ` +
        `with the files the steps before it wrote. Run the cells in order from the top (Shift+Enter). The files go into \`${K().tilde(record.folder)}\`.` +
        (record.inputs.length ? '\n\nThe workflow’s input files:\n\n' + record.inputs.map((i) => `- ${i.label}: \`${i.path ? K().tilde(i.path) : 'none'}\``).join('\n') : '')
    );
    const dirs = new Set([record.folder]);
    for (const e of record.steps) {
      const t = toolOf(e.tool);
      for (const f of (t && t.fields) || []) {
        const p = e.values && e.values[f.key];
        if (f.type === 'folder' && p) dirs.add(p);
        if (f.type === 'path' && p) dirs.add(MG.path.dirname(p));
      }
    }
    code(`import os\n\n# the folders the steps write in\nfor folder in ${JSON.stringify(Array.from(dirs))}:\n    os.makedirs(folder, exist_ok=True)`);
    for (const e of record.steps) {
      const t = toolOf(e.tool);
      if (!t || !t.python || !e.values) continue;
      md(`## ${e.n}. ${e.title}${e.state === 'ok' ? '' : ` (it ${e.state === 'failed' ? 'failed' : 'was ' + e.state} in the run)`}`);
      code(t.python(e.values));
    }
    return {
      cells,
      metadata: {
        kernelspec: { name: 'python3', display_name: 'Python 3 (ipykernel)', language: 'python' },
        language_info: { name: 'python', file_extension: '.py', mimetype: 'text/x-python' },
        workbench: { made_with: 'Pedigree workbench (in the browser)', workflow: record.name }
      },
      nbformat: 4,
      nbformat_minor: 5
    };
  }

  /* ---------------- a workflow made from the tools that were run ---------------- */
  /** the tools run in the Tools tab (entries of its log, oldest first) as a workflow: a file one of them wrote and a
      later one read becomes a connection, and any other file it read an input of the workflow */
  function fromRuns(entries, name) {
    const w = newWorkflow(name);
    const made = new Map(); // path → {step, output, many}
    const sets = new Map(); // 'step output' → [paths]: the files of a set a step wrote
    const given = new Map(); // path → input step id
    for (const e of entries) {
      const t = toolOf(e.tool);
      if (!usable(t) || !e.values) continue;
      const s = addTool(w, t.id);
      s.params = paramsFrom(t, e.values);
      for (const f of fileFields(t)) {
        const val = e.values[f.key];
        const paths = (f.type === 'files' ? val || [] : val ? [val] : []).filter(Boolean);
        const give = (p) => {
          if (!given.has(p)) {
            // (one of several files a tool read at once is named after its file)
            const i = addInput(w, f.kinds, f.type === 'files' ? 'The file ' + K().base(p) : f.label);
            i.default = p;
            // (a file the tool can do without, such as a terms file, the workflow can do without too)
            if (f.optional) i.optional = true;
            given.set(p, i.id);
          }
          return { step: given.get(p), output: 'file' };
        };
        const conns = [];
        for (const p of paths) {
          const m = made.get(p);
          // a file of a set is the whole set where the tool read all of it, several at once; otherwise (two
          // people's files of five, or one of them) the files it read are inputs of the workflow
          const c = !m ? give(p) : !m.many ? m : f.type === 'files' && sets.get(m.step + ' ' + m.output).every((x) => paths.includes(x)) ? m : give(p);
          if (!conns.some((x) => x.step === c.step && x.output === c.output)) conns.push({ step: c.step, output: c.output });
        }
        if (conns.length) s.connections[f.key] = f.type === 'files' ? conns : conns[0];
      }
      // what it wrote, by the files it says it writes
      for (const o of outputsOf(t, e.values)) {
        if (o.path) made.set(K().expand(o.path), { step: s.id, output: o.name, many: false });
        else if (o.find) {
          const hits = (e.files || []).filter((p) => o.find.test(p));
          hits.forEach((p) => made.set(p, { step: s.id, output: o.name, many: !!o.many }));
          if (o.many) sets.set(s.id + ' ' + o.name, hits);
        }
      }
    }
    // an input given to several steps is one input; it is named after the file, if steps read it differently
    for (const i of w.steps.filter((s) => s.type === 'input')) {
      const readers = w.steps.filter((s) => allConns(s).some((c) => c.step === i.id));
      if (readers.length > 1) i.label = 'The file ' + K().base(i.default);
      // (optional only if every step that reads it can do without it)
      const needed = readers.some((s) => allConns(s).some((c) => c.step === i.id && !fileFields(toolOf(s.tool)).find((f) => f.key === c.key).optional));
      if (needed) delete i.optional;
    }
    autoLayout(w);
    return w;
  }

  MG.workflowEngine = {
    FORMAT, RUN_FORMAT, RUN_FILE, EX_DIR, WF_DIR, INPUT_KINDS,
    kindName, kindsLabel, inputKindsLabel, slug, samplePath, isWorkflowPath,
    toolOf, usable, fileFields, settingFields, isAuto, valuesOf, paramsFrom, fromInputName, placer, outputsOf,
    newWorkflow, parse, serialise, stepOf, nextId, connsOf, allConns, outputsAll, connOut, designValues, stepOutputs,
    stepInputs, outKinds, isMany, whyNot, connect, disconnect, removeStep, orderSteps, numbers, autoLayout, problems, readersOf, addTool, addInput,
    runFolder, planStep, collect, Run, summaryOf, scriptOf, notebookOf, fromRuns
  };

  /* ================================================================== the pages */
  const E = MG.workflowEngine;
  const SVG = 'http://www.w3.org/2000/svg';
  const icon = (n) => MG.icon(n);
  /** a button: btn('btn.small', 'play', 'Run', fn) */
  const btn = (cls, ic, label, fn, attrs) => {
    const b = h('button.' + cls, Object.assign({ type: 'button', html: (ic ? icon(ic) : '') + (label ? `<span>${esc(label)}</span>` : '') }, attrs || {}));
    if (fn) b.addEventListener('click', fn);
    return b;
  };
  const stamp = (iso) => (iso ? new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');
  const stepTitle = (s) => (s.type === 'input' ? s.label || 'Input file' : E.toolOf(s.tool) ? E.toolOf(s.tool).title : s.tool);
  /** a field's label, short enough for a box: The drawing → drawing */
  const short = (label) => String(label || '').replace(/^The /, '').replace(/ \((optional|several)\)$/, '');
  const STATE = {
    waiting: ['dots', 'waiting'],
    running: ['spin', 'running'],
    ok: ['check', 'done'],
    failed: ['warning', 'failed'],
    skipped: ['minus', 'not run'],
    stopped: ['stop', 'stopped']
  };
  /** a state from a record (a file, which could say anything) as one of those */
  const known = (x) => (Object.prototype.hasOwnProperty.call(STATE, x) ? x : 'waiting');
  /** a record read from a file, in the shape the pages draw (its parts that aren't are left out) */
  function tidyRecord(rec, path) {
    const text = (x) => (x == null ? '' : String(x));
    rec.folder = text(rec.folder) || MG.path.dirname(path);
    rec.inputs = (Array.isArray(rec.inputs) ? rec.inputs : []).filter((i) => i && typeof i === 'object');
    rec.steps = rec.steps
      .filter((e) => e && typeof e === 'object')
      .map((e) =>
        Object.assign(e, {
          files: Array.isArray(e.files) ? e.files.filter((p) => typeof p === 'string') : [],
          argv: Array.isArray(e.argv) ? e.argv.filter(Array.isArray).map((a) => a.map(text)) : [],
          stdout: text(e.stdout),
          stderr: text(e.stderr),
          traceback: e.traceback == null ? undefined : text(e.traceback)
        })
      );
    return rec;
  }

  class WorkflowsUI {
    constructor(tab) {
      this.tab = tab;
      this.fs = tab.fs;
      this.active = null; // the run going on: {run, path}
      this.ed = null; // the editor: {path, w, canvas, wrap, side, sel, state}
      this.gen = 0; // one more for each page shown or left
    }
    get main() {
      return this.tab.main;
    }
    /** → a function that says whether the page shown now is still the one shown then (a page that reads files
        before it is drawn stops drawing if another page has taken its place in the meantime) */
    still() {
      const gen = this.gen;
      return () => gen === this.gen;
    }
    crumb(...parts) {
      this.tab.crumb.textContent = ['Tools', 'Workflows'].concat(parts.filter(Boolean)).join(' › ');
    }
    go(view, path, extra) {
      this.tab.go(Object.assign({ page: 'workflows', view, path: path || null }, extra || {}));
    }
    /** show a page: where.view is list, edit, run, record (a run's record) or extract */
    show(where) {
      this.gen++;
      const v = where.view || 'list';
      if (v === 'edit' && where.path) return this.showEditor(where.path);
      if (v === 'run' && where.path) return this.showRun(where.path, where);
      if (v === 'record' && where.path) return this.showRecord(where.path);
      if (v === 'extract') return this.showExtract();
      return this.showList();
    }
    /** another page of the Tools tab is shown: keep any change to the workflow in the editor */
    leave() {
      this.gen++;
      this._flush();
      if (this._ro) this._ro.disconnect();
      this._ro = null;
      this.ed = null;
      this.liveBox = null;
    }
    shown() {
      if (this.ed) requestAnimationFrame(() => this._wires());
    }

    /* ---------------- the workflows there are ---------------- */
    /** the workflow files: your own (mine) or the examples → [path], newest first */
    files(mine) {
      const out = [];
      for (const [p, e] of this.fs.entries) {
        if (e.kind === 'dir' || !E.isWorkflowPath(p)) continue;
        if (mine ? p.startsWith(HOME() + '/') : p.startsWith(E.EX_DIR + '/')) out.push({ p, t: e.mtime || 0 });
      }
      return out.sort((a, b) => (mine ? b.t - a.t : a.p < b.p ? -1 : 1)).map((x) => x.p);
    }
    async read(path) {
      return E.parse(await this.fs.readText(path));
    }
    /** a new file in ~/workflows for a workflow named name (name-2 … if it is taken) */
    newPath(name) {
      const dir = E.WF_DIR();
      let p = `${dir}/${E.slug(name)}.workflow.json`;
      for (let n = 2; this.fs.exists(p); n++) p = `${dir}/${E.slug(name)}-${n}.workflow.json`;
      return p;
    }
    write(path, w) {
      this.fs.mkdirp(MG.path.dirname(path));
      this.fs.writeText(path, E.serialise(w));
    }
    create() {
      const names = new Set();
      this.files(true).forEach((p) => names.add(K().base(p)));
      let name = 'New workflow';
      for (let n = 2; this.fs.exists(this.newPath(name).replace(/-\d+\.workflow\.json$/, '.workflow.json')) && this.fs.exists(`${E.WF_DIR()}/${E.slug(name)}.workflow.json`); n++) name = 'New workflow ' + n;
      const w = E.newWorkflow(name);
      const p = this.newPath(name);
      this.write(p, w);
      bus.emit('wf:new', { path: p });
      this.go('edit', p);
      return p;
    }
    /** an example (or any workflow not in your folder) as one of your own, to change */
    async copy(path) {
      const w = await this.read(path);
      w.created = w.updated = new Date().toISOString();
      const p = this.newPath(w.name);
      this.write(p, w);
      toast(`Copied “${esc(w.name)}” into <b>${esc(K().tilde(p))}</b>. This copy is yours to change.`, 'ok', 5000);
      return p;
    }
    /** workflow files from the computer, each into ~/workflows under a name of its own (named after the workflow, so
        that one there already, perhaps a copy of the same example, is kept) */
    upload() {
      const inp = h('input', { type: 'file', accept: '.json,application/json', multiple: true, style: { display: 'none' } });
      document.body.appendChild(inp);
      inp.addEventListener('change', async () => {
        const chosen = Array.from(inp.files || []);
        inp.remove();
        const added = [];
        for (const f of chosen) {
          try {
            const w = E.parse(await f.text());
            const p = this.newPath(w.name);
            this.write(p, w);
            added.push(p);
            toast(`Added the workflow “${esc(w.name)}” as <b>${esc(K().tilde(p))}</b>.`, 'ok', 6000);
          } catch (e) {
            toast(`${esc(f.name)}: ${esc(e.message)}`, 'error', 8000);
          }
        }
        if (added.length === 1) this.go('edit', added[0]);
        else if (added.length) this.go('list');
      });
      inp.click();
    }
    async remove(path) {
      let name = K().base(path);
      try {
        name = (await this.read(path)).name;
      } catch (e) {
        /* its file name will do */
      }
      if (!(await MG.confirmBox('Delete the workflow?', `<p>“${esc(name)}” (<code>${esc(K().tilde(path))}</code>) will be deleted. The results of its runs stay in your files.</p>`, 'Delete', { danger: true }))) return;
      this.fs.remove(path);
      this.go('list');
    }
    /** the records of runs: [path], in your files */
    runFiles() {
      const out = [];
      for (const [p, e] of this.fs.entries) if (e.kind !== 'dir' && p.endsWith('/' + E.RUN_FILE) && p.startsWith(HOME() + '/')) out.push(p);
      return out;
    }

    /* ---------------- the first page: the workflows, and their runs ---------------- */
    async showList() {
      const still = this.still();
      this.crumb();
      const M = this.main;
      M.appendChild(h('h2.tl-title', { html: icon('workflow') + '<span>Workflows</span>' }));
      M.appendChild(h('p.tl-lead', 'A workflow chains tools together: each step reads the files the steps before it wrote, so a job of several steps runs in one go, on the same files again or on new ones. Draw one in the editor, start from an example, or make one from the tools you’ve run.'));
      M.appendChild(h('div.wf-actions', btn('btn.primary', 'plus', 'New workflow', () => this.create()), btn('btn', 'rerun', 'Make one from the tools you’ve run', () => this.go('extract')), btn('btn', 'upload', 'Add a workflow file…', () => this.upload(), { title: 'A .workflow.json file from your computer, such as one someone has sent you' }), btn('linkbtn.wf-helpbtn', 'book', 'Help', () => MG.app.showHelp('h-workflows'))));
      if (this.active) {
        const a = this.active;
        M.appendChild(h('div.tl-warn.wf-going', h('span', { html: `<b>Running:</b> “${esc(a.run.record.name)}”, step ${a.run.record.steps.filter((e) => e.state !== 'waiting').length} of ${a.run.record.steps.length}. ` }), btn('btn.small', 'eye', 'Watch it', () => this.go('run', a.path))));
      }
      const section = async (title, paths, mine, empty) => {
        M.appendChild(h('h3.tl-sub', title));
        if (!paths.length) return M.appendChild(h('p.muted', empty));
        const grid = h('div.wf-cards');
        M.appendChild(grid);
        for (const p of paths) {
          let w;
          try {
            w = await this.read(p);
          } catch (e) {
            if (!still()) return;
            grid.appendChild(h('div.wf-card.bad', h('b', K().base(p)), h('p.muted', e.message), mine ? h('div.wf-card-f', btn('linkbtn', 'trash', 'Delete', () => this.remove(p))) : null));
            continue;
          }
          if (!still()) return;
          const steps = w.steps.filter((s) => s.type === 'tool').length;
          const foot = h('div.wf-card-f', btn('btn.small.primary', 'play', 'Run', () => this.go('run', p)));
          if (mine) foot.append(btn('btn.small', 'pencil', 'Edit', () => this.go('edit', p)), btn('linkbtn', 'download', 'Download', () => K().downloadFile(p)), btn('linkbtn', 'trash', 'Delete', () => this.remove(p)));
          else foot.append(btn('btn.small', 'pencil', 'Edit a copy', async () => this.go('edit', await this.copy(p))));
          grid.appendChild(h('div.wf-card', { dataset: { path: p } }, h('div.wf-card-h', h('b', w.name), h('small.muted', `${steps} step${steps === 1 ? '' : 's'}${mine && w.updated ? ' · changed ' + stamp(w.updated) : ''}`)), w.annotation ? h('p', w.annotation) : null, mine ? h('code.wf-card-p', K().tilde(p)) : null, foot));
        }
      };
      await section('Your workflows', this.files(true), true, 'You have no workflows yet. Make a new one, or start from an example: Edit a copy makes it yours to change.');
      if (!still()) return;
      await section('Examples', this.files(false), false, 'There are no examples.');
      if (!still()) return;
      // the runs, newest first
      const recs = [];
      for (const p of this.runFiles()) {
        try {
          const r = JSON.parse(await this.fs.readText(p));
          if (r && r[E.RUN_FORMAT] && Array.isArray(r.steps)) recs.push(Object.assign({}, r, { path: p, inputs: Array.isArray(r.inputs) ? r.inputs : [], folder: String(r.folder || MG.path.dirname(p)) }));
        } catch (e) {
          /* not a record */
        }
      }
      if (!still()) return;
      M.appendChild(h('h3.tl-sub', 'Runs'));
      recs.sort((a, b) => String(b.started).localeCompare(String(a.started)));
      if (!recs.length) return M.appendChild(h('p.muted', 'No workflow has been run yet. Each run keeps its files, with a record of how they were made, in a folder of its own.'));
      const t = h('table.table.small.wf-runs', h('tr', h('th', 'Workflow'), h('th', 'Input'), h('th', 'Started'), h('th', 'State'), h('th', '')));
      recs.slice(0, 30).forEach((r) => {
        const live = this.active && this.active.run.record.folder === r.folder;
        const state = live ? 'running' : r.state === 'running' ? 'stopped' : r.state;
        const first = r.inputs.find((i) => i && typeof i.path === 'string' && i.path);
        t.appendChild(h('tr', h('td', r.name), h('td', first ? h('code', K().base(first.path)) : ''), h('td.nowrap', stamp(r.started)), h('td', h('span.wf-state.' + known(state), STATE[known(state)][1])), h('td.nowrap', btn('btn.small', 'eye', 'View', () => (live ? this.go('run', this.active.path) : this.go('record', r.path))), ' ', btn('linkbtn', 'folder', 'Folder', () => MG.app.revealFile(r.folder)))));
      });
      M.appendChild(h('div.table-scroll', t));
    }

    /* ---------------- the editor ---------------- */
    async showEditor(path) {
      const still = this.still();
      let w;
      try {
        w = await this.read(path);
      } catch (e) {
        toast(`${esc(K().tilde(path))}: ${esc(e.message)}`, 'error', 8000);
        return still() && this.go('list');
      }
      if (!still()) return;
      // (an example is changed in a copy of your own)
      if (!path.startsWith(HOME() + '/')) {
        const p = await this.copy(path);
        return still() && this.go('edit', p);
      }
      this.ed = { path, w, sel: null };
      this.crumb(w.name);
      this.tab.root.classList.add('wf-wide');
      const nameIn = h('input.tl-input.wf-name', { type: 'text', value: w.name, 'aria-label': 'The workflow’s name', spellcheck: 'false' });
      nameIn.addEventListener('input', () => {
        w.name = nameIn.value;
        this.crumb(w.name);
        this.touch();
      });
      nameIn.addEventListener('change', () => this._rename());
      const state = h('span.wf-saved', { role: 'status' }, 'Saved');
      const bar = h(
        'div.wf-edbar',
        btn('btn.small.wf-shrink', 'arrowL', 'Workflows', () => this.go('list'), { 'aria-label': 'Back to the workflows' }),
        nameIn,
        state,
        h('span.grow'),
        btn('btn.small', 'plus', 'Input file', () => this.addInputHere(), { title: 'A file the workflow is given when it runs' }),
        btn('btn.small', 'plus', 'Add a step', () => this.chooseStep(null, (t) => this.addStepHere(t)), { title: 'A tool' }),
        btn('btn.small.wf-shrink', 'wand', 'Tidy', () => this.tidy(), { title: 'Arrange the boxes in columns, the inputs on the left', 'aria-label': 'Tidy: arrange the boxes in columns' }),
        btn('btn.small.wf-iconly', 'download', '', () => {
          this._flush();
          K().downloadFile(this.ed.path);
        }, { title: 'Download the workflow file, to keep or to send to someone', 'aria-label': 'Download the workflow file' }),
        btn('btn.small.primary', 'play', 'Run', () => {
          this._flush();
          this.go('run', this.ed.path);
        })
      );
      const canvas = h('div.gx-canvas.wf-canvas');
      const wrap = h('div.wf-canvaswrap', canvas);
      const side = h('aside.wf-side', { 'aria-label': 'Step settings' });
      Object.assign(this.ed, { canvas, wrap, side, state, nameIn });
      this.main.appendChild(h('div.wf-ed', bar, h('p.wf-hint', { html: 'Drag from a file a step writes (<i class="wf-dotkey"></i> on the right of a box) to an input of another (on the left) to connect them, or use the <b>+</b> by a file to add a step that reads it. Click a box for its settings. Changes are saved as you go.' }), h('div.wf-edbody', wrap, side)));
      canvas.addEventListener('click', (e) => {
        if (!e.target.closest('.gx-node') && !e.target.closest('.gx-wire')) this.select(null);
      });
      this.draw();
      if ('ResizeObserver' in window) {
        this._ro = new ResizeObserver(() => this._wires());
        this._ro.observe(wrap);
      }
      bus.emit('wf:editor', { path, name: w.name });
    }
    /** a change: saved soon (and the boxes and checks drawn again by the caller) */
    touch() {
      if (!this.ed) return;
      this.ed.w.updated = new Date().toISOString();
      this.ed.state.textContent = 'Saving…';
      clearTimeout(this._saveT);
      this._pending = this.ed;
      this._saveT = setTimeout(() => this._flush(), 350);
    }
    _flush() {
      clearTimeout(this._saveT);
      const ed = this._pending;
      this._pending = null;
      if (!ed) return;
      try {
        this.write(ed.path, ed.w);
        if (ed.state) ed.state.textContent = 'Saved';
      } catch (e) {
        toast('The workflow couldn’t be saved: ' + esc(e.message), 'error', 8000);
      }
    }
    /** the file is named after the workflow (when its name is changed, and the new file name is free) */
    _rename() {
      const ed = this.ed;
      if (!ed) return;
      this._flush();
      const want = `${MG.path.dirname(ed.path)}/${E.slug(ed.w.name)}.workflow.json`;
      if (want === ed.path || this.fs.exists(want)) return;
      try {
        this.fs.rename(ed.path, want);
        ed.path = want;
        store.set('toolsPage', { page: 'workflows', view: 'edit', path: want });
      } catch (e) {
        /* it keeps its name */
      }
    }
    tidy() {
      E.autoLayout(this.ed.w);
      this.touch();
      this.draw();
      this.ed.wrap.scrollTo({ left: 0, top: 0 });
    }
    /** the boxes, the wires and the side column, as the workflow is now */
    draw() {
      if (!this.ed) return;
      this.drawCanvas();
      this.drawSide();
    }
    /** the boxes and the wires */
    drawCanvas() {
      const ed = this.ed;
      if (!ed) return;
      const { w, canvas } = ed;
      canvas.innerHTML = '';
      const svg = document.createElementNS(SVG, 'svg');
      svg.setAttribute('class', 'gx-wires');
      canvas.appendChild(svg);
      const n = E.numbers(w);
      const probs = E.problems(w);
      const flagged = new Set(probs.map((p) => p.step).filter(Boolean));
      const out = E.outputsAll(w);
      if (!w.steps.length) canvas.appendChild(h('div.gx-canvas-empty', h('p', { html: 'An empty workflow. Start with <b>+ Input file</b> for a file it is given, or <b>+ Add a step</b> for a tool.' })));
      for (const s of w.steps) canvas.appendChild(this.node(s, n, flagged, out));
      this._size();
      requestAnimationFrame(() => this._wires());
    }
    _size() {
      const { canvas, w } = this.ed;
      let maxX = 640, maxY = 380;
      canvas.querySelectorAll('.gx-node').forEach((el) => {
        const s = E.stepOf(w, el.dataset.id);
        if (!s) return;
        maxX = Math.max(maxX, s.x + el.offsetWidth + 60);
        maxY = Math.max(maxY, s.y + el.offsetHeight + 60);
      });
      canvas.style.width = maxX + 'px';
      canvas.style.height = maxY + 'px';
    }
    node(s, n, flagged, out) {
      const { w } = this.ed;
      out = out || E.outputsAll(w);
      const t = s.type === 'tool' ? E.toolOf(s.tool) : null;
      const title = stepTitle(s) + (s.type === 'tool' && !E.usable(t) ? ' (not a tool here)' : '');
      const el = h('div.gx-node.wf-node' + (s.type === 'input' ? '.input' : '') + (flagged.has(s.id) ? '.flag' : '') + (this.ed.sel === s.id ? '.sel' : ''), { dataset: { id: s.id }, tabindex: '0', 'aria-label': `Step ${n[s.id]}: ${title}` });
      el.style.left = s.x + 'px';
      el.style.top = s.y + 'px';
      const del = h('button.gx-node-x', { type: 'button', title: 'Remove this step', 'aria-label': `Remove step ${n[s.id]}`, html: icon('x') });
      del.addEventListener('pointerdown', (e) => e.stopPropagation());
      del.addEventListener('click', (e) => {
        e.stopPropagation();
        this.removeStep(s.id);
      });
      el.appendChild(h('div.gx-node-t', h('b.wf-n', String(n[s.id])), h('span', { title }, title), del));
      if (s.type === 'input') el.appendChild(h('div.wf-node-sub', E.inputKindsLabel(s.kinds) + (s.optional ? ' (optional)' : '')));
      else if (t) el.appendChild(h('div.wf-node-sub', t.pkg));
      const ins = h('div.gx-ports.in');
      if (s.type === 'tool' && E.usable(t)) {
        for (const f of E.stepInputs(w, s, out)) {
          const on = E.connsOf(s, f.key).length > 0;
          ins.appendChild(h('div.gx-port.in' + (on ? '.on' : ''), { dataset: { step: s.id, key: f.key }, title: `${f.label}: ${E.kindsLabel(f.kinds)}${f.many ? ' (several files)' : ''}${f.optional ? ' (optional)' : ''}` }, h('i.dot'), h('span', short(f.label) + (f.optional ? ' (opt.)' : f.many ? ' (several)' : ''))));
        }
      }
      const outs = h('div.gx-ports.out');
      for (const o of E.stepOutputs(w, s, out)) {
        const plus = h('button.wf-plus', { type: 'button', title: `Add a step that reads the ${o.label}`, 'aria-label': `Add a step that reads the ${o.label} of step ${n[s.id]}`, html: icon('plus') });
        plus.addEventListener('pointerdown', (e) => e.stopPropagation());
        plus.addEventListener('click', (e) => {
          e.stopPropagation();
          this.chooseStep({ kinds: o.kinds, many: o.many, label: o.label }, (tool, f) => this.addAfter(s, o, tool, f));
        });
        const p = h('div.gx-port.out', { dataset: { step: s.id, name: o.name }, title: `${o.label}: ${E.kindsLabel(o.kinds)}${o.many ? ' (several files)' : ''}. Drag from the dot to an input, or click + to add a step that reads it.` }, plus, h('span', o.label + (o.many ? ' (set)' : '')), h('i.dot'));
        p.querySelector('.dot').addEventListener('pointerdown', (e) => this._startWire(e, s, o));
        outs.appendChild(p);
      }
      el.append(ins, outs);
      this._draggable(el, s);
      el.addEventListener('click', () => this.select(s.id));
      el.addEventListener('keydown', (e) => {
        if (e.target !== el) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          this.select(s.id);
        }
      });
      return el;
    }
    _wires() {
      const ed = this.ed;
      if (!ed || !ed.canvas.isConnected) return;
      const svg = ed.canvas.querySelector('svg.gx-wires');
      if (!svg) return;
      svg.querySelectorAll('path').forEach((p) => p.remove());
      svg.setAttribute('width', ed.canvas.offsetWidth);
      svg.setAttribute('height', ed.canvas.offsetHeight);
      const c = ed.canvas.getBoundingClientRect();
      const pos = (sel) => {
        const d = ed.canvas.querySelector(sel);
        if (!d) return null;
        const r = d.getBoundingClientRect();
        return { x: r.left - c.left + r.width / 2, y: r.top - c.top + r.height / 2 };
      };
      for (const s of ed.w.steps) {
        for (const conn of E.allConns(s)) {
          const a = pos(`.gx-port.out[data-step="${CSS.escape(conn.step)}"][data-name="${CSS.escape(conn.output)}"] .dot`);
          const b = pos(`.gx-port.in[data-step="${CSS.escape(s.id)}"][data-key="${CSS.escape(conn.key)}"] .dot`);
          if (!a || !b) continue;
          const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
          const path = document.createElementNS(SVG, 'path');
          path.setAttribute('d', `M${a.x} ${a.y} C${a.x + dx} ${a.y} ${b.x - dx} ${b.y} ${b.x} ${b.y}`);
          path.setAttribute('class', 'gx-wire');
          const tt = document.createElementNS(SVG, 'title');
          tt.textContent = 'Click to take this connection away';
          path.appendChild(tt);
          path.addEventListener('click', (e) => {
            e.stopPropagation();
            E.disconnect(ed.w, s.id, conn.key, conn.step, conn.output);
            this.touch();
            this.draw();
          });
          svg.appendChild(path);
        }
      }
    }
    _draggable(el, s) {
      let start = null;
      el.addEventListener('pointerdown', (e) => {
        if (e.button > 0 || e.target.closest('.dot') || e.target.closest('button')) return;
        start = { x: e.clientX, y: e.clientY, sx: s.x, sy: s.y, moved: false };
        el.setPointerCapture(e.pointerId);
      });
      el.addEventListener('pointermove', (e) => {
        if (!start) return;
        const dx = e.clientX - start.x, dy = e.clientY - start.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) start.moved = true;
        if (!start.moved) return;
        s.x = Math.max(0, Math.round(start.sx + dx));
        s.y = Math.max(0, Math.round(start.sy + dy));
        el.style.left = s.x + 'px';
        el.style.top = s.y + 'px';
        this._wires();
      });
      const end = () => {
        if (start && start.moved) {
          this.touch();
          this._size();
          this._wires();
        }
        start = null;
      };
      el.addEventListener('pointerup', end);
      el.addEventListener('pointercancel', end);
    }
    _startWire(e, s, o) {
      e.preventDefault();
      e.stopPropagation();
      const ed = this.ed;
      const svg = ed.canvas.querySelector('svg.gx-wires');
      const c = ed.canvas.getBoundingClientRect();
      const d = e.target.getBoundingClientRect();
      const a = { x: d.left - c.left + d.width / 2, y: d.top - c.top + d.height / 2 };
      const tmp = document.createElementNS(SVG, 'path');
      tmp.setAttribute('class', 'gx-wire tmp');
      svg.appendChild(tmp);
      ed.canvas.querySelectorAll('.gx-port.in').forEach((p) => p.classList.add(E.whyNot(ed.w, s.id, o.name, p.dataset.step, p.dataset.key) ? 'bad' : 'ok'));
      const move = (ev) => {
        const x = ev.clientX - c.left, y = ev.clientY - c.top;
        const dx = Math.max(40, Math.abs(x - a.x) / 2);
        tmp.setAttribute('d', `M${a.x} ${a.y} C${a.x + dx} ${a.y} ${x - dx} ${y} ${x} ${y}`);
      };
      const up = (ev) => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        tmp.remove();
        ed.canvas.querySelectorAll('.gx-port.in').forEach((p) => p.classList.remove('ok', 'bad'));
        const target = document.elementFromPoint(ev.clientX, ev.clientY);
        const port = target && target.closest('.gx-port.in');
        if (port) this.connect(s.id, o.name, port.dataset.step, port.dataset.key);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    }
    /** connect a file to an input (by dragging, from the side column, and in the tests) → true if it could */
    connect(fromId, output, toId, key) {
      const why = E.connect(this.ed.w, fromId, output, toId, key);
      if (why) {
        toast('Can’t connect them: ' + esc(why), 'warn', 6000);
        return false;
      }
      this.touch();
      this.draw();
      bus.emit('wf:wire', { from: fromId, to: toId, key });
      return true;
    }
    removeStep(id) {
      if (this.ed.sel === id) this.ed.sel = null;
      E.removeStep(this.ed.w, id);
      this.touch();
      this.draw();
    }
    select(id) {
      if (!this.ed) return;
      this.ed.sel = id;
      this.ed.canvas.querySelectorAll('.gx-node').forEach((el) => el.classList.toggle('sel', el.dataset.id === id));
      this.drawSide();
    }
    /** a tool chosen from a list, in groups as in the Tools tab: all of them, or (from) those that read a kind of file */
    chooseStep(from, onPick) {
      const m = MG.modal(from ? `Add a step that reads the ${from.label}` : 'Add a step', '');
      const body = m.box.querySelector('.modal-b');
      m.box.classList.add('wf-modal');
      const readers = from ? new Map(E.readersOf(from.kinds, from.many).map((x) => [x.t.id, x])) : null;
      body.appendChild(h('p.muted', from ? `The tools that read ${E.kindsLabel(from.kinds)}${from.many ? ', several at once' : ''}:` : 'Each step is a tool of the Tools tab. Match conditions to terms isn’t among them, as it asks as it goes: make the terms file first, and give it to the workflow as an input.'));
      let any = false;
      for (const [g, label, ic] of K().GROUPS) {
        const tools = K().TOOLS.filter((t) => t.group === g && E.usable(t) && (!readers || readers.has(t.id)));
        if (!tools.length) continue;
        any = true;
        body.appendChild(h('h4.wf-gh', { html: icon(ic) + `<span>${esc(label)}</span>` }));
        const list = h('div.tl-chooser.wf-chooser');
        tools.forEach((t) => {
          // (data-wf-tool: a button with data-tool opens that tool, wherever it is – workbench.js)
          const b = h('button.tl-choice', { type: 'button', dataset: { wfTool: t.id } }, h('b', t.title), h('small', t.what));
          b.addEventListener('click', () => {
            m.close();
            onPick(t, readers ? readers.get(t.id) : null);
          });
          list.appendChild(b);
        });
        body.appendChild(list);
      }
      if (!any) body.appendChild(h('p', 'None of the tools reads this kind of file.'));
    }
    /** a step added from the bar: after the step chosen in the editor, reading a file of it if it can */
    addStepHere(t) {
      const { w } = this.ed;
      const after = this.ed.sel && E.stepOf(w, this.ed.sel);
      const x = after ? after.x + 270 : w.steps.length ? Math.max(...w.steps.map((s) => s.x)) + 270 : 16;
      const s = E.addTool(w, t.id, x, this._freeY(x, after ? after.y : 16));
      if (after) {
        for (const o of E.stepOutputs(w, after)) {
          const f = E.fileFields(t).find((ff) => !E.whyNot(w, after.id, o.name, s.id, ff.key));
          if (f) {
            E.connect(w, after.id, o.name, s.id, f.key);
            break;
          }
        }
      }
      this.ed.sel = s.id;
      this.touch();
      this.draw();
      bus.emit('wf:added', { tool: t.id, step: s.id });
      return s;
    }
    /** where a new box can go in the column at x: under the boxes there (or at y, if that is free) */
    _freeY(x, y) {
      const { w, canvas } = this.ed;
      let low = y;
      for (const s of w.steps) {
        if (s.x + 236 < x - 20 || s.x > x + 236 + 20) continue;
        const el = canvas.querySelector(`.gx-node[data-id="${CSS.escape(s.id)}"]`);
        const bottom = s.y + (el ? el.offsetHeight : 140) + 24;
        if (s.y < low + 120 && bottom > low) low = bottom;
      }
      return low;
    }
    /** a step that reads a file of another, to its right (pick: the input that reads it, and a setting that input
        needs, from readersOf) */
    addAfter(src, o, t, pick) {
      const { w } = this.ed;
      const s = E.addTool(w, t.id, src.x + 270, this._freeY(src.x + 270, src.y));
      if (pick && pick.params) Object.assign(s.params, pick.params);
      const fits = (ff) => ff && !E.whyNot(w, src.id, o.name, s.id, ff.key);
      const field = fits(pick && pick.f) ? pick.f : E.fileFields(t).find(fits);
      if (field) E.connect(w, src.id, o.name, s.id, field.key);
      this.ed.sel = s.id;
      this.touch();
      this.draw();
      bus.emit('wf:added', { tool: t.id, step: s.id });
      return s;
    }
    addInputHere() {
      const { w } = this.ed;
      const ins = w.steps.filter((s) => s.type === 'input');
      const s = E.addInput(w, ['studio'], 'Input file ' + (ins.length + 1), 16, this._freeY(16, 16));
      this.ed.sel = s.id;
      this.touch();
      this.draw();
      return s;
    }
    /** an input of the workflow for a tool's input that isn't connected, to its left */
    inputFor(s, f) {
      const { w } = this.ed;
      const x = Math.max(16, s.x - 270);
      const i = E.addInput(w, f.kinds, f.label, x, this._freeY(x, s.y));
      E.connect(w, i.id, 'file', s.id, f.key);
      this.touch();
      this.draw();
      return i;
    }

    /* ---------------- the side column: the step chosen, or the workflow and its checks ---------------- */
    drawSide() {
      const ed = this.ed;
      if (!ed) return;
      const S = ed.side;
      S.innerHTML = '';
      this.tab.pickers = (this.tab.pickers || []).filter((p) => !p.wfSide);
      const s = ed.sel && E.stepOf(ed.w, ed.sel);
      if (!s) return this._sideWorkflow(S);
      if (s.type === 'input') return this._sideInput(S, s);
      return this._sideTool(S, s);
    }
    _sideWorkflow(S) {
      const { w } = this.ed;
      S.appendChild(h('h4', 'This workflow'));
      const about = h('textarea.tl-input.wf-about', { rows: 4, placeholder: 'What it does, in a sentence or two', 'aria-label': 'What the workflow does' });
      about.value = w.annotation || '';
      about.addEventListener('input', () => {
        w.annotation = about.value;
        this.touch();
      });
      S.appendChild(h('div.tl-field', h('label.tl-label', 'What it does'), about));
      S.appendChild(h('h4', 'Checks'));
      const probs = E.problems(w);
      if (!probs.length) {
        S.appendChild(h('p.wf-ready', { html: icon('check') + '<span>Ready to run.</span>' }));
        S.appendChild(btn('btn.primary', 'play', 'Run it', () => {
          this._flush();
          this.go('run', this.ed.path);
        }));
      } else {
        const ul = h('ul.wf-probs');
        probs.forEach((p) => {
          const li = h('li', p.text);
          if (p.step) {
            li.classList.add('link');
            li.addEventListener('click', () => this.select(p.step));
          }
          ul.appendChild(li);
        });
        S.appendChild(ul);
      }
      S.appendChild(h('p.tl-help', 'Click a box for its settings, or drag it to move it.'));
    }
    _sideInput(S, s) {
      const { w } = this.ed;
      const n = E.numbers(w);
      S.appendChild(h('h4', `${n[s.id]}. Input file`));
      S.appendChild(h('p.tl-help', 'A file the workflow is given when it runs: you choose it then, from your files or the examples.'));
      const lab = h('input.tl-input', { type: 'text', value: s.label || '', spellcheck: 'false' });
      lab.addEventListener('input', () => {
        s.label = lab.value;
        const t = this.ed.canvas.querySelector(`.gx-node[data-id="${CSS.escape(s.id)}"] .gx-node-t span`);
        if (t) t.textContent = s.label || 'Input file';
        this.touch();
      });
      S.appendChild(h('div.tl-field', h('label.tl-label', 'Its name'), lab));
      const kind = h('select.tl-input');
      const opts = E.INPUT_KINDS.slice();
      if (!opts.some(([ks]) => ks.length === s.kinds.length && ks.every((k) => s.kinds.includes(k)))) opts.push([s.kinds, E.kindsLabel(s.kinds)]);
      opts.forEach(([ks, label], i) => kind.appendChild(h('option', { value: String(i) }, label)));
      kind.value = String(opts.findIndex(([ks]) => ks.length === s.kinds.length && ks.every((k) => s.kinds.includes(k))));
      kind.addEventListener('change', () => {
        s.kinds = opts[Number(kind.value)][0].slice();
        if (s.default && !s.kinds.includes(MG.app.pedKind(s.default))) delete s.default;
        this.touch();
        this.draw();
      });
      S.appendChild(h('div.tl-field', h('label.tl-label', 'It is'), kind));
      // a file to suggest when it runs
      const v = { def: s.default || '' };
      const r = K().fieldRow(this.tab, { key: 'def', type: 'file', label: 'Suggest this file when it runs', kinds: s.kinds, optional: true, none: 'none: the first that fits' }, v, (key, val) => {
        if (val) s.default = val;
        else delete s.default;
        this.touch();
      });
      if (this.tab.pickers.length) this.tab.pickers[this.tab.pickers.length - 1].wfSide = true;
      S.appendChild(r.row);
      const opt = h('input', { type: 'checkbox' });
      opt.checked = !!s.optional;
      opt.addEventListener('change', () => {
        s.optional = opt.checked;
        if (!s.optional) delete s.optional;
        this.touch();
        this.draw();
      });
      S.appendChild(h('div.tl-field.check', h('label.tl-checkline', opt, h('span', 'Optional: it can run without it')), h('div.tl-help', 'Only for files the steps that read it can do without, such as a terms file.')));
      const readers = w.steps.filter((x) => E.allConns(x).some((c) => c.step === s.id));
      S.appendChild(h('p.tl-help', readers.length ? `Read by step${readers.length === 1 ? '' : 's'} ${readers.map((x) => n[x.id]).sort((a, b) => a - b).join(', ')}.` : 'No step reads it yet: drag from its dot to a step’s input.'));
      S.appendChild(btn('linkbtn.wf-remove', 'trash', 'Remove this input', () => this.removeStep(s.id)));
    }
    _sideTool(S, s) {
      const { w } = this.ed;
      const n = E.numbers(w);
      const t = E.toolOf(s.tool);
      if (!E.usable(t)) {
        S.appendChild(h('h4', `${n[s.id]}. ${s.tool}`));
        S.appendChild(h('p.tl-warn', s.tool === 'terms' ? 'Match conditions to terms can’t be a step, as it asks as it goes. Make the terms file with it in the Tools tab, and give the file to the workflow as an input.' : 'The workbench has no such tool. Remove this step.'));
        S.appendChild(btn('linkbtn.wf-remove', 'trash', 'Remove this step', () => this.removeStep(s.id)));
        return;
      }
      S.appendChild(h('h4', `${n[s.id]}. ${t.title}`, ' ', h('span.tl-pkg', t.pkg)));
      S.appendChild(h('p.tl-help', t.what));
      if (t.help) S.appendChild(btn('linkbtn.wf-toolhelp', 'book', 'Help for this tool', () => MG.app.showHelp(t.help)));
      // its input files: where each comes from
      S.appendChild(h('h5', 'Its input files'));
      for (const f of E.stepInputs(w, s)) S.appendChild(this._sourceRow(s, f));
      // its settings
      const fields = E.settingFields(t);
      const v = E.designValues(w, s);
      const shown = fields.filter((f) => !f.show || f.show(v));
      if (shown.length) S.appendChild(h('h5', 'Settings'));
      const rows = {};
      for (const f of fields) {
        const derived = E.fromInputName(t, f);
        const ff = derived ? Object.assign({}, f, { placeholder: 'from the name of its input file, when it runs', help: f.help }) : f;
        const vals = Object.assign({}, v, derived ? { [f.key]: s.params[f.key] || '' } : {});
        const r = K().fieldRow(this.tab, ff, vals, (key, val) => {
          // (what the step reads and writes, and the settings shown, as they are before the change)
          const shape = () => {
            const out = E.outputsAll(w);
            const x = E.designValues(w, s, out);
            return JSON.stringify([E.stepOutputs(w, s, out).map((o) => [o.name, o.kinds, o.many]), E.stepInputs(w, s, out).map((i) => i.key), fields.map((g) => !g.show || g.show(x))]);
          };
          const before = shape();
          s.params[key] = val;
          // (a value that is the default is no setting of the step's own: it follows the defaults)
          const plain = Object.assign({}, s.params);
          delete plain[key];
          const d = E.valuesOf(t, plain, {}, null);
          if ((derived && val === '') || (!derived && typeof f.def !== 'function' && String(d[key]) === String(val))) delete s.params[key];
          this.touch();
          // a choice redraws the step and its settings; typing redraws the boxes only if what the step reads or
          // writes has changed (Take one condition out: one PED file, or a set), and leaves the box being typed in
          if (f.type === 'select' || f.type === 'check') return this.draw();
          if (shape() !== before) this.drawCanvas();
          const after = E.designValues(w, s);
          for (const g of fields) if (rows[g.key]) rows[g.key].row.hidden = !!(g.show && !g.show(after));
        });
        rows[f.key] = r;
        if (f.show && !f.show(v)) r.row.hidden = true;
        S.appendChild(r.row);
      }
      // where its files go
      const outs = E.stepOutputs(w, s);
      if (outs.length) S.appendChild(h('p.tl-help.wf-where', `It writes ${outs.map((o) => 'the ' + o.label + (o.many ? ' (a set of files)' : '')).join(', ')}, in the folder of each run, named as the tool names them.`));
      S.appendChild(btn('linkbtn.wf-remove', 'trash', 'Remove this step', () => this.removeStep(s.id)));
    }
    /** one of a tool's input files: where it comes from (an input of the workflow, or a file a step writes) */
    _sourceRow(s, f) {
      const { w } = this.ed;
      const n = E.numbers(w);
      const row = h('div.tl-field.wf-source');
      row.appendChild(h('label.tl-label', f.label + (f.optional ? ' (optional)' : f.many ? ' (several)' : '')));
      const key = (c) => c.step + '\u0000' + c.output;
      const cands = [];
      for (const src of E.orderSteps(w)) {
        if (src.id === s.id) continue;
        for (const o of E.stepOutputs(w, src)) {
          const on = E.connsOf(s, f.key).some((c) => c.step === src.id && c.output === o.name);
          if (on || !E.whyNot(w, src.id, o.name, s.id, f.key)) cands.push({ step: src.id, output: o.name, on, label: `${n[src.id]}. ${stepTitle(src)}${src.type === 'tool' ? ' – ' + o.label : ''}` });
        }
      }
      const conns = E.connsOf(s, f.key);
      if (f.many) {
        const ul = h('ul.tl-multilist');
        conns.forEach((c) => {
          const cand = cands.find((x) => x.step === c.step && x.output === c.output);
          const x = h('button.icon-btn', { type: 'button', 'aria-label': 'Take it away', html: icon('x') });
          x.addEventListener('click', () => {
            E.disconnect(w, s.id, f.key, c.step, c.output);
            this.touch();
            this.draw();
          });
          ul.appendChild(h('li', h('span', cand ? cand.label : `step ${n[c.step] || '?'}`), x));
        });
        if (!conns.length) ul.appendChild(h('li.muted', 'None yet.'));
        row.appendChild(ul);
        const add = h('select.tl-input.small', { 'aria-label': 'Add a file' });
        add.appendChild(h('option', { value: '' }, 'add a file from…'));
        cands.filter((c) => !c.on).forEach((c) => add.appendChild(h('option', { value: key(c) }, c.label)));
        add.addEventListener('change', () => {
          const c = cands.find((x) => key(x) === add.value);
          if (c) this.connect(c.step, c.output, s.id, f.key);
        });
        row.appendChild(add);
      } else {
        const sel = h('select.tl-input', { 'aria-label': f.label });
        sel.appendChild(h('option', { value: '' }, f.optional ? 'none' : 'not connected'));
        cands.forEach((c) => sel.appendChild(h('option', { value: key(c) }, c.label)));
        sel.value = conns[0] ? key(conns[0]) : '';
        sel.addEventListener('change', () => {
          conns.forEach((c) => E.disconnect(w, s.id, f.key, c.step, c.output));
          const c = cands.find((x) => key(x) === sel.value);
          if (c) this.connect(c.step, c.output, s.id, f.key);
          else {
            this.touch();
            this.draw();
          }
        });
        row.appendChild(sel);
      }
      if (!conns.length) row.appendChild(btn('linkbtn.wf-newinput', 'plus', 'Make it an input of the workflow', () => this.inputFor(s, f)));
      row.appendChild(h('div.tl-help', E.inputKindsLabel(f.kinds).replace(/^./, (c) => c.toUpperCase()) + (f.many ? ', several' : '') + '.'));
      return row;
    }

    /* ---------------- running a workflow ---------------- */
    async showRun(path, where = {}) {
      const still = this.still();
      let w;
      try {
        w = await this.read(path);
      } catch (e) {
        toast(`${esc(K().tilde(path))}: ${esc(e.message)}`, 'error', 8000);
        return still() && this.go('list');
      }
      if (!still()) return;
      this.crumb(w.name, 'Run');
      const M = this.main;
      M.appendChild(h('div.tl-toolhead', h('h2.tl-title', { html: icon('play') + `<span>Run “${esc(w.name)}”</span>` }), h('span.tl-pkg', 'workflow')));
      if (w.annotation) M.appendChild(h('p.tl-lead', w.annotation));
      const result = h('div.wf-result', { 'aria-live': 'polite' });
      // (a run of it going on: its progress)
      if (this.active && this.active.path === path) {
        M.appendChild(result);
        this.liveBox = result;
        this.renderRecord(this.active.run.record, result, true);
        return;
      }
      const probs = E.problems(w);
      if (probs.length) {
        M.appendChild(h('div.tl-warn', h('b', 'It can’t run yet:'), h('ul.wf-probs', ...probs.map((p) => h('li', p.text)))));
        if (path.startsWith(HOME() + '/')) M.appendChild(h('div.tl-next', btn('btn', 'pencil', 'Open it in the editor', () => this.go('edit', path))));
        return;
      }
      const form = h('form.tl-form', { autocomplete: 'off' });
      const ins = E.orderSteps(w).filter((s) => s.type === 'input');
      const last = (store.get('wfInputs', {}) || {})[path] || {};
      const vals = {};
      const ok = (p, kinds) => p && this.fs.exists(p) && kinds.includes(MG.app.pedKind(p));
      const folderIn = h('input.tl-input.mono', { type: 'text', spellcheck: 'false', 'aria-label': 'The folder for the results' });
      let folderTouched = false;
      const folderAuto = () => {
        if (!folderTouched) folderIn.value = K().tilde(E.runFolder(this.fs, w, vals));
      };
      // (a file to run it on, from a button of the help: for the first input that takes it)
      const onto = where.input && ins.find((s) => ok(where.input, s.kinds));
      for (const s of ins) {
        const given = (where.inputs && where.inputs[s.id]) || (onto === s ? where.input : null);
        // (an optional input left as none last time is none again, rather than the file the workflow suggests)
        const noneAgain = s.optional && Object.prototype.hasOwnProperty.call(last, s.id) && last[s.id] === '';
        vals[s.id] = [given, last[s.id], noneAgain ? null : s.default].find((p) => ok(p, s.kinds)) || '';
        if (!vals[s.id] && !s.optional) {
          const { mine, ex } = K().filesOfKinds(s.kinds);
          vals[s.id] = (mine[0] || ex[0] || {}).path || '';
        }
        const r = K().fieldRow(this.tab, { key: s.id, type: 'file', label: `${E.numbers(w)[s.id]}. ${s.label || 'Input file'}`, kinds: s.kinds, optional: !!s.optional, none: 'none', help: E.inputKindsLabel(s.kinds).replace(/^./, (c) => c.toUpperCase()) + (s.optional ? ', or none.' : '.') }, vals, (key, val) => {
          vals[key] = val;
          folderAuto();
        });
        form.appendChild(r.row);
      }
      folderIn.addEventListener('input', () => (folderTouched = true));
      folderAuto();
      form.appendChild(h('div.tl-field', h('label.tl-label', 'Put the results in'), folderIn, h('div.tl-help', 'Each run has a folder of its own, for the files its steps write, a record of the run (workflow-run.json) and its commands for the terminal (commands.sh).')));
      const steps = h('ol.wf-plan');
      const n = E.numbers(w);
      E.orderSteps(w)
        .filter((s) => s.type === 'tool')
        .forEach((s) => {
          const t = E.toolOf(s.tool);
          const set = Object.keys(s.params || {})
            .map((k) => {
              const f = t.fields.find((x) => x.key === k);
              if (!f) return '';
              const val = s.params[k];
              const shown = f.type === 'select' ? (f.options.find((o) => o[0] === val) || [val, val])[1] : f.type === 'check' ? (val ? 'yes' : 'no') : String(val);
              return `${short(f.label).replace(/^./, (c) => c.toUpperCase())}: ${shown}`;
            })
            .filter(Boolean);
          steps.appendChild(h('li', { value: n[s.id] }, h('b', t.title), set.length ? h('span.muted', ' – ' + set.join(' · ')) : null));
        });
      form.appendChild(h('div.tl-field', h('label.tl-label', 'The steps'), steps));
      const run = h('button.btn.primary.tl-run', { type: 'submit', html: icon('play') + '<span>Run</span>' });
      const msg = h('span.tl-check', { role: 'status' });
      const acts = h('div.tl-actions', run, msg);
      if (path.startsWith(HOME() + '/')) acts.appendChild(btn('btn', 'pencil', 'Edit the workflow', () => this.go('edit', path)));
      else acts.appendChild(btn('btn', 'pencil', 'Edit a copy', async () => this.go('edit', await this.copy(path))));
      form.appendChild(acts);
      M.append(form, result);
      const busy = 'A workflow is running already: wait for it to finish, or stop it.';
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (this.active) return (msg.textContent = busy);
        const missing = ins.find((s) => !s.optional && !vals[s.id]);
        if (missing) return (msg.textContent = `Choose ${String(missing.label || 'the input file').replace(/^The /, 'the ')}.`);
        const folder = K().expand(folderIn.value.trim().replace(/\/+$/, ''));
        if (!folder || !folder.startsWith(HOME() + '/')) return (msg.textContent = 'The results can only go in your home folder (~).');
        if (this.fs.exists(folder) && !this.fs.isDir(folder)) return (msg.textContent = `${K().tilde(folder)} is a file: choose a folder.`);
        msg.textContent = '';
        if (this.fs.exists(folder) && !(await MG.confirmBox('Use this folder again?', `<p><code>${esc(K().tilde(folder))}</code> is there already. Files in it with the names the steps write will be replaced.</p>`, 'Use it'))) return;
        // (one may have started while that was asked)
        if (this.active) return (msg.textContent = busy);
        const all = store.get('wfInputs', {}) || {};
        all[path] = Object.assign({}, vals);
        store.set('wfInputs', all);
        run.disabled = true;
        form.querySelectorAll('input, select, button').forEach((x) => (x.disabled = true));
        this.liveBox = result;
        await this.start(w, path, vals, folder);
      });
    }
    /** run a workflow: inputs {inputStepId: path}, into folder → the run's record (when it has finished) */
    async start(w, path, inputs, folder) {
      if (this.active) {
        toast('A workflow is running already: wait for it to finish, or stop it.', 'warn', 6000);
        return null;
      }
      const run = new E.Run({
        w,
        source: path,
        inputs,
        folder,
        fs: this.fs,
        run: K().runTool,
        onChange: (rec) => this.liveBox && this.liveBox.isConnected && this.renderRecord(rec, this.liveBox, rec.state === 'running'),
        onStatus: (id, text) => {
          const el = this.liveBox && this.liveBox.querySelector(`.wf-step[data-id="${CSS.escape(id)}"] .wf-status`);
          if (el) el.textContent = text || 'Running…';
        }
      });
      this.active = { run, path };
      bus.emit('wf:start', { path, folder });
      if (this.liveBox) this.renderRecord(run.record, this.liveBox, true);
      let rec;
      try {
        rec = await run.start();
      } catch (err) {
        // (the engine records what goes wrong in a step itself: this is anything else, so that the run still ends)
        console.error(err);
        rec = run.record;
        rec.steps.forEach((x) => ['waiting', 'running'].includes(x.state) && Object.assign(x, { state: 'failed', error: x.error || `The run stopped: ${(err && err.message) || err}` }));
        rec.state = 'failed';
        rec.finished = rec.finished || new Date().toISOString();
      } finally {
        this.active = null;
      }
      const ok = rec.steps.filter((e) => e.state === 'ok').length;
      const box = this.liveBox;
      if (box && box.isConnected) this.renderRecord(rec, box, false);
      // (a message, unless the run's page is in sight: it may be gone, or hidden behind another tab of the workbench)
      if (!(box && box.isConnected && box.getClientRects().length && document.visibilityState !== 'hidden')) toast(`The workflow “${esc(rec.name)}” has ${rec.state === 'ok' ? 'finished' : rec.state === 'stopped' ? 'stopped' : 'stopped with an error'}: ${ok} of ${rec.steps.length} steps done.`, rec.state === 'ok' ? 'ok' : 'warn', 8000);
      bus.emit('wf:done', { path, folder, state: rec.state, record: rec });
      return rec;
    }
    /** a run's record: its steps, what each did and wrote, and (when it has finished) what to do next */
    renderRecord(rec, box, live) {
      box.innerHTML = '';
      const done = rec.steps.filter((e) => !['waiting', 'running'].includes(e.state)).length;
      const state = live ? 'running' : rec.state === 'running' ? 'stopped' : rec.state;
      const word = live ? `Running: step ${Math.min(done + 1, rec.steps.length)} of ${rec.steps.length}` : state === 'ok' ? `Done: ${rec.steps.length} step${rec.steps.length === 1 ? '' : 's'}` : state === 'stopped' ? 'Stopped before it had finished' : 'It stopped with an error';
      const secs = rec.finished ? (new Date(rec.finished) - new Date(rec.started)) / 1000 : 0;
      const head = h('div.wf-runhead', h('span.wf-state.' + known(state), { html: icon(STATE[known(state)][0]) + `<span>${esc(word)}</span>` }), h('span.muted', `${stamp(rec.started)}${secs > 0.5 ? ` · ${secs.toFixed(1)} s` : ''}`), h('span.grow'), h('code.wf-folder', K().tilde(rec.folder)));
      if (live) {
        const stop = btn('btn.small', 'stop', 'Stop', () => {
          if (this.active) this.active.run.stop();
          stop.disabled = true;
          stop.lastChild.textContent = 'Stopping after this step…';
        });
        head.appendChild(stop);
      }
      box.appendChild(head);
      const inputs = (Array.isArray(rec.inputs) ? rec.inputs : []).filter((i) => i && typeof i === 'object');
      if (inputs.length) box.appendChild(h('ul.wf-inputs', ...inputs.map((i) => h('li', `${i.n}. ${i.label}: `, h('code', i.path ? K().tilde(String(i.path)) : 'none')))));
      const list = h('ol.wf-steps');
      for (const e of rec.steps) list.appendChild(this._stepRow(e, live));
      box.appendChild(list);
      if (live) return;
      const next = h('div.tl-next');
      next.appendChild(btn('btn', 'folder', 'Open the folder in Files', () => MG.app.revealFile(rec.folder)));
      next.appendChild(btn('btn', 'notebook', 'Open the steps as a notebook', () => this.notebook(rec)));
      const src = rec.source && this.fs.exists(rec.source) ? rec.source : null;
      if (src) next.appendChild(btn('btn', 'rerun', 'Run it again', () => this.go('run', src)));
      if (src && src.startsWith(HOME() + '/')) next.appendChild(btn('btn', 'pencil', 'Edit the workflow', () => this.go('edit', src)));
      box.appendChild(next);
      box.appendChild(h('p.tl-help', { html: `The folder holds the record of this run (<code>${E.RUN_FILE}</code>) and its commands (<code>commands.sh</code>): <code>bash ${esc(K().shArg(rec.folder + '/commands.sh'))}</code> in the terminal runs them again.` }));
    }
    _stepRow(e, live) {
      const li = h('li.wf-step.' + known(e.state), { dataset: { id: String(e.id) } });
      const [ic, word] = STATE[known(e.state)];
      const head = h('div.wf-step-h', h('span.wf-state.' + known(e.state), { html: icon(ic) + `<span>${word}</span>` }), h('b', `${e.n}. ${e.title}`), e.state === 'running' ? h('span.wf-status.muted', 'Running…') : e.summary ? h('span.wf-sum', e.summary) : e.error && e.state !== 'failed' ? h('span.wf-sum.muted', e.error) : null, e.seconds > 0.5 ? h('small.muted', `${e.seconds.toFixed(1)} s`) : null);
      li.appendChild(head);
      const t = E.toolOf(e.tool);
      const has = e.error || e.stdout || e.stderr || (e.files && e.files.length) || e.result || (e.argv && e.argv.length);
      if (!has || e.state === 'running' || e.state === 'waiting') return li;
      const d = h('details.wf-step-b', { open: e.state === 'failed' || (e.state === 'ok' && t && t.stdoutIsResult && !t.render && !live) ? '' : null });
      d.appendChild(h('summary', e.state === 'failed' ? 'What went wrong' : 'What it did'));
      if (e.error && e.state === 'failed') d.appendChild(h('div.tl-fail', e.error));
      if (t && t.render && e.result) {
        try {
          t.render({ result: e.result }, e.values || {}, d);
        } catch (err) {
          /* the printed output will do */
        }
      } else if (e.stdout && e.stdout.trim()) d.appendChild(h(t && t.stdoutIsResult ? 'pre.tl-pre.tl-main-out' : 'pre.tl-pre', e.stdout.replace(/\s+$/, '')));
      if (e.stderr && e.stderr.trim()) d.appendChild(h('pre.tl-pre.err', e.stderr.replace(/\s+$/, '')));
      if (e.traceback && e.state === 'failed') d.appendChild(h('details.tl-tb', h('summary', 'Python’s traceback (for reporting a fault)'), h('pre.tl-pre', e.traceback)));
      const files = (e.files || []).filter((p) => this.fs.exists(p));
      if (files.length) {
        d.appendChild(h('h5', files.length === 1 ? 'The file it wrote' : `The ${files.length} files it wrote`));
        const fl = h('div.tl-files');
        files.forEach((p) => fl.appendChild(K().fileChip(p)));
        d.appendChild(fl);
      }
      if (e.argv && e.argv.length) d.appendChild(h('div.tl-code', h('div.tl-code-t', 'The command'), h('pre.code.wf-cmd', h('code', e.argv.map((a) => a.map(K().shArg).join(' ')).join('\n')))));
      li.appendChild(d);
      return li;
    }
    /** a run's steps as a notebook in ~/notebooks, opened in the Notebook tab */
    async notebook(rec) {
      const nb = E.notebookOf(rec);
      const dir = HOME() + '/notebooks';
      const stem = `${E.slug(rec.name)}-${E.slug(K().base(rec.folder))}`;
      let p = `${dir}/${stem}.ipynb`;
      for (let n = 2; this.fs.exists(p); n++) p = `${dir}/${stem}-${n}.ipynb`;
      this.fs.mkdirp(dir);
      this.fs.writeText(p, JSON.stringify(nb, null, 1) + '\n');
      toast(`Wrote <b>${esc(K().tilde(p))}</b>.`, 'ok');
      await MG.app.openFile(p);
      return p;
    }
    /** a past run, from its record */
    async showRecord(path) {
      const still = this.still();
      let rec;
      try {
        rec = JSON.parse(await this.fs.readText(path));
        if (!rec || !rec[E.RUN_FORMAT] || !Array.isArray(rec.steps)) throw new Error('It isn’t the record of a workflow’s run.');
      } catch (e) {
        toast(`${esc(K().tilde(path))}: ${esc(e.message)}`, 'error', 8000);
        return still() && this.go('list');
      }
      if (!still()) return;
      tidyRecord(rec, path);
      if (this.active && this.active.run.record.folder === rec.folder) return this.go('run', this.active.path);
      // (a run the page was closed or reloaded in the middle of)
      if (rec.state === 'running') rec.steps.forEach((e) => ['running', 'waiting'].includes(e.state) && ((e.state = 'stopped'), (e.error = 'The page was closed or reloaded before it ran.')));
      this.crumb(rec.name, 'Run of ' + stamp(rec.started));
      const M = this.main;
      M.appendChild(h('div.tl-toolhead', h('h2.tl-title', { html: icon('workflow') + `<span>${esc(rec.name)}</span>` }), h('span.tl-pkg', 'a run')));
      const box = h('div.wf-result');
      M.appendChild(box);
      this.renderRecord(rec, box, false);
    }

    /* ---------------- a workflow from the tools you've run ---------------- */
    showExtract() {
      this.crumb('From the tools you’ve run');
      const M = this.main;
      M.appendChild(h('h2.tl-title', { html: icon('rerun') + '<span>A workflow from the tools you’ve run</span>' }));
      M.appendChild(h('p.tl-lead', 'Tick the tools to make into a workflow, in the order they ran. A file one of them wrote that a later one read becomes a connection between their steps, and each file they were given becomes an input of the workflow, so that it can run again on other files.'));
      const log = (store.get(K().LOG_KEY, []) || []).filter((e) => e && E.usable(E.toolOf(e.tool)));
      if (!log.length) {
        M.appendChild(h('p.muted', 'You haven’t run any tools yet. Run some in the Tools tab, one after another on the files the one before wrote, then come back here.'));
        M.appendChild(h('div.tl-next', btn('btn', 'arrowL', 'Workflows', () => this.go('list'))));
        return;
      }
      const t = h('table.table.small.wf-log', h('tr', h('th', ''), h('th', 'Tool'), h('th', 'Its files'), h('th', 'Ran')));
      const boxes = [];
      const hour = Date.now() - 3 * 3600 * 1000;
      log.forEach((e, i) => {
        const tool = E.toolOf(e.tool);
        const cb = h('input', { type: 'checkbox', 'aria-label': 'Use ' + tool.title });
        cb.checked = e.ok && e.time > hour;
        boxes.push([cb, e]);
        const read = E.fileFields(tool).flatMap((f) => [].concat(e.values[f.key] || [])).filter(Boolean);
        t.appendChild(h('tr' + (e.ok ? '' : '.muted'), h('td', cb), h('td', h('b', tool.title), e.ok ? '' : h('span.muted', ' (it failed)')), h('td', read.map((p, k) => h('span', k ? ', ' : '', h('code', K().base(p)))), read.length ? ' → ' : '', `${(e.files || []).length} file${(e.files || []).length === 1 ? '' : 's'}`), h('td.nowrap', stamp(new Date(e.time).toISOString()))));
      });
      M.appendChild(h('div.table-scroll', t));
      const name = h('input.tl-input', { type: 'text', value: 'My workflow', 'aria-label': 'The workflow’s name' });
      const go = btn('btn.primary', 'workflow', 'Make the workflow', () => {
        const chosen = boxes.filter(([cb]) => cb.checked).map(([, e]) => e);
        if (!chosen.length) return toast('Tick the tools to use.', 'warn');
        const w = E.fromRuns(chosen, name.value.trim() || 'My workflow');
        w.annotation = `Made from ${chosen.length} tool${chosen.length === 1 ? '' : 's'} run on ${stamp(new Date(chosen[0].time).toISOString())}.`;
        const p = this.newPath(w.name);
        this.write(p, w);
        bus.emit('wf:extract', { path: p, steps: w.steps.length });
        this.go('edit', p);
      });
      M.appendChild(h('div.tl-form.wf-extract', h('div.tl-field', h('label.tl-label', 'Its name'), name), h('div.tl-actions', go, btn('btn', 'arrowL', 'Workflows', () => this.go('list')))));
    }
  }
  MG.WorkflowsUI = WorkflowsUI;
})();
