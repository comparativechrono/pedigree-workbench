/* The workflow engine (assets/js/workflows.js) in Node: the example workflows have no problems; files connect only to
   inputs of their kinds, and never in a loop; where a run's files go; a run, step by step, with a stand-in for Python;
   its commands and notebook; a workflow made from the tools that were run; and then each example workflow run for
   real, its steps' commands run by the workbench's Python packages (python/), as the Tools tab runs them.

     node tests/workflows/engine.js            (--quick: without the real runs)
*/
const fs = require('fs');
const path = require('path');
const { load, MemFS, DiskFS, ROOT, HOME } = require('./env.js');

const out = [];
const check = (ok, what) => out.push((ok ? 'ok    ' : 'FAIL  ') + what);
const EXDIR = path.join(ROOT, 'data', 'examples', 'workflows');
const examples = fs.readdirSync(EXDIR).filter((f) => f.endsWith('.workflow.json')).sort();

async function units() {
  const files = new MemFS();
  const MG = load(files);
  const E = MG.workflowEngine;
  const K = MG.toolsKit;

  // every tool but Match conditions to terms can be a step, and says what it writes with its defaults
  const usable = K.TOOLS.filter(E.usable).map((t) => t.id);
  check(usable.length === K.TOOLS.length - 1 && !usable.includes('terms'), `every tool but Match conditions to terms can be a step (${usable.length})`);
  let quiet = true;
  for (const t of K.TOOLS.filter(E.usable)) {
    const w = E.newWorkflow('t');
    const s = E.addTool(w, t.id);
    try {
      E.stepOutputs(w, s);
      E.stepInputs(w, s);
    } catch (e) {
      quiet = false;
      check(false, `${t.id}: ${e.message}`);
    }
  }
  check(quiet, 'every tool says what it reads and writes, as a step with its defaults');

  // the examples: no problems, and they read back as they were written
  for (const f of examples) {
    const w = E.parse(fs.readFileSync(path.join(EXDIR, f), 'utf8'));
    const probs = E.problems(w);
    check(!probs.length && E.serialise(w) === fs.readFileSync(path.join(EXDIR, f), 'utf8'), `${f}: no problems (${probs.map((p) => p.text).join('; ')})`);
  }

  // connections: kinds, sets of files, loops
  const w = E.newWorkflow('Test of connections');
  const drawing = E.addInput(w, ['studio'], 'The drawing');
  const pic = E.addInput(w, ['image'], 'A picture');
  const conv = E.addTool(w, 'studio2ga4gh');
  check(E.connect(w, drawing.id, 'file', conv.id, 'input') === '', 'a drawing connects to Drawing → GA4GH');
  check(/reads a Pedigree Studio drawing/.test(E.connect(w, pic.id, 'file', conv.id, 'input')), 'a picture doesn’t, and it says why');
  const split = E.addTool(w, 'split');
  check(E.connect(w, conv.id, 'family', split.id, 'input') === '', 'the Family connects to One file for each person');
  const view = E.addTool(w, 'view');
  check(/set of files/.test(E.connect(w, split.id, 'people', view.id, 'input')), 'a set of Phenopackets doesn’t connect to an input of one file');
  const merge = E.addTool(w, 'merge');
  check(E.connect(w, split.id, 'people', merge.id, 'inputs') === '', '… but does to Put files together, which reads several');
  check(E.problems(w).every((p) => !/needs two files/.test(p.text)), 'a set of files is enough for Put files together');
  const fill = E.addTool(w, 'normalise');
  E.connect(w, merge.id, 'out', fill.id, 'input');
  check(JSON.stringify(E.stepOutputs(w, fill).find((o) => o.name === 'out').kinds) === '["cohort"]', 'Fill in missing terms writes the kind of file it reads (a Cohort, from Put files together)');
  check(/loop/.test(E.connect(w, fill.id, 'out', merge.id, 'inputs')), 'a loop is refused');
  const order = E.orderSteps(w).map((s) => s.id);
  check(order.indexOf(conv.id) < order.indexOf(split.id) && order.indexOf(split.id) < order.indexOf(merge.id) && order.indexOf(merge.id) < order.indexOf(fill.id), 'the steps run in order, each after the steps it reads from');
  check(E.problems(w).some((p) => p.step === pic.id && /no step reads it/.test(p.text)), 'an input that no step reads is a problem');
  check(E.problems(w).some((p) => p.step === view.id && /isn’t connected/.test(p.text)), 'an input of a step that isn’t connected is a problem');
  E.removeStep(w, split.id);
  check(!E.allConns(merge).length, 'removing a step takes away its connections');

  // settings: a choice changes the files a step writes; a default from an input's name is left to the run
  const w2 = E.newWorkflow('Settings');
  const p2 = E.addInput(w2, ['image'], 'The picture');
  const read = E.addTool(w2, 'pedinterp');
  E.connect(w2, p2.id, 'file', read.id, 'input');
  const names = () => E.stepOutputs(w2, read).map((o) => o.name).join(',');
  check(names() === 'ped,drawing', 'Picture → PED file and drawing writes the PED file and the drawing');
  read.params.ga4gh = true;
  read.params.studio = false;
  check(names() === 'ped,pedigree', '… and with its settings changed, the PED file and the GA4GH Pedigree');
  // with the marks read (who has died, the proband, carriers), no PED file, which can't hold them: a step that read it
  // has a problem, and so does the step itself if it writes neither the drawing nor the GA4GH Pedigree
  const mode = E.addTool(w2, 'pednet-mode');
  E.connect(w2, read.id, 'ped', mode.id, 'input');
  read.params.marks = true;
  check(names() === 'pedigree' && E.problems(w2).some((q) => q.step === mode.id && /doesn’t write with its settings as they are/.test(q.text)),
    '… and with the marks read, the GA4GH Pedigree alone: a step that read the PED file says it isn’t written');
  read.params.ga4gh = false;
  check(E.problems(w2).some((q) => q.step === read.id && /can’t hold who has died/.test(q.text)), '… and the form says the marks need the drawing or the GA4GH Pedigree');
  E.removeStep(w2, mode.id);
  delete read.params.marks;
  read.params.ga4gh = true;
  const tool = K.TOOL.pedinterp;
  check(E.fromInputName(tool, tool.fields.find((f) => f.key === 'family')) && !E.fromInputName(tool, tool.fields.find((f) => f.key === 'upscale')), 'its family id comes from the picture’s name, when it runs');
  const g = K.TOOL.pedgen;
  check(String(E.valuesOf(g, { mode: 'AR' }, {}, null).generations) === '4' && String(E.valuesOf(g, {}, {}, null).generations) === '3', 'a default that follows another setting follows it (PedGen’s generations, from its mode)');
  check(JSON.stringify(E.paramsFrom(g, E.valuesOf(g, { mode: 'AR', seed: '7' }, {}, null))) === '{"mode":"AR","seed":"7"}', 'the settings of a tool run are those that aren’t defaults');

  // a run, with a stand-in for Python that writes what each tool says it writes
  files.writeText('/data/examples/okafor.studio.json', fs.readFileSync(path.join(ROOT, 'data/examples/okafor.studio.json'), 'utf8'));
  files.writeText('/data/examples/example-terms.json', fs.readFileSync(path.join(ROOT, 'data/examples/example-terms.json'), 'utf8'));
  const share = E.parse(fs.readFileSync(path.join(EXDIR, 'share-a-drawing.workflow.json'), 'utf8'));
  const ins = Object.fromEntries(share.steps.filter((s) => s.type === 'input').map((s) => [s.id, s.default]));
  const folder = E.runFolder(files, share, ins);
  check(folder === HOME + '/results/share-a-drawing-in-the-ga4gh-standard/okafor', `a run’s folder is named after the workflow and its input (${folder})`);
  const ran = [];
  const fake = async (t, v) => {
    ran.push(t.id);
    const outs = E.outputsOf(t, v);
    const written = [];
    for (const o of outs) {
      const p = o.path || (o.guess && o.guess[0]) || (v.outdir || folder) + '/made-by-' + t.id + '.json';
      const kind = o.kinds ? o.kinds[0] : MG.app.pedKind(v.input);
      files.writeText(p, kind === 'pedigree' ? '{"individuals": [], "relationships": []}' : kind === 'family' ? '{"proband": {}, "pedigree": {"persons": []}}' : '{}');
      written.push(p);
    }
    return { ok: true, code: 0, stdout: t.id === 'validate' ? '' : 'done\n', stderr: '', files: written, result: t.id === 'validate' ? { valid: true, name: 'GA4GH Pedigree', errors: 0 } : undefined };
  };
  const run = new E.Run({ w: share, source: '/data/examples/workflows/share-a-drawing.workflow.json', inputs: ins, folder, fs: files, run: fake });
  const rec = await run.start();
  check(rec.state === 'ok' && rec.steps.every((e) => e.state === 'ok'), `the run finishes, every step done (${rec.steps.map((e) => e.state).join(', ')})`);
  check(ran.join(',') === 'studio2ga4gh,validate,validate,deidentify,validate', `its steps run in order (${ran.join(', ')})`);
  const conv1 = rec.steps[0];
  check(conv1.values.outdir === folder && conv1.values.prefix === 'okafor' && conv1.values.terms === '/data/examples/example-terms.json', 'Drawing → GA4GH writes into the run’s folder, named after the drawing, with the terms file');
  check(rec.steps[1].values.input === folder + '/okafor_ga4gh-pedigree.json' && rec.steps[2].values.input === folder + '/okafor_phenopackets-family.json', 'each check reads the file it is connected to');
  check(rec.steps[3].values.out === folder + '/okafor.deidentified.json' && rec.steps[3].values.keyfile === folder + '/okafor.key.json', `De-identify writes beside them, with its key (${rec.steps[3].values.out})`);
  check(rec.steps[1].summary === 'Valid: a correct GA4GH Pedigree.', 'a check says what it found');
  const saved = JSON.parse(await files.readText(folder + '/workflow-run.json'));
  check(saved.state === 'ok' && saved.steps.length === 5 && saved.workflow.name === share.name, 'the record of the run is in its folder');
  const script = await files.readText(folder + '/commands.sh');
  check(/^#!\/bin\/bash/.test(script) && /\nstudio2ga4gh \/data\/examples\/okafor\.studio\.json -d ~\/results\/share-a-drawing-in-the-ga4gh-standard\/okafor -o okafor -t \/data\/examples\/example-terms\.json\n/.test(script) && (script.match(/^pedigree-ga4gh validate/gm) || []).length === 3, 'its commands are in commands.sh, for the terminal');
  const nb = E.notebookOf(saved);
  check(nb.cells.filter((c) => c.cell_type === 'code').length === 6 && /from studio2ga4gh import convert_file/.test(nb.cells[2].source.join('') + nb.cells[3].source.join('')), 'and its steps make a notebook of Python');

  // a run of the same again: a folder of its own; and a step whose file has the name of one before it: a folder of its own
  check(E.runFolder(files, share, ins) === folder + '-2', 'the next run of it has a folder of its own');
  const twice = E.newWorkflow('Twice');
  const d = E.addInput(twice, ['studio'], 'The drawing');
  const a = E.addTool(twice, 'studio2ga4gh');
  const b = E.addTool(twice, 'studio2ga4gh');
  E.connect(twice, d.id, 'file', a.id, 'input');
  E.connect(twice, d.id, 'file', b.id, 'input');
  const rec2 = await new E.Run({ w: twice, inputs: { [d.id]: '/data/examples/okafor.studio.json' }, folder: HOME + '/results/twice', fs: files, run: fake }).start();
  check(rec2.steps[0].values.outdir === HOME + '/results/twice' && rec2.steps[1].values.outdir === HOME + '/results/twice/3-drawing-ga4gh-pedigree-and-phenopackets', `a step that would write a file of the same name as one before it writes into a folder of its own (${rec2.steps[1].values.outdir})`);

  // a step that fails, and the steps after it
  const failing = async (t, v) => (t.id === 'studio2ga4gh' ? { ok: false, code: 1, stdout: '', stderr: 'it broke', files: [] } : fake(t, v));
  const rec3 = await new E.Run({ w: share, inputs: ins, folder: HOME + '/results/broken', fs: files, run: failing }).start();
  check(rec3.state === 'failed' && rec3.steps[0].state === 'failed' && rec3.steps.slice(1).every((e) => e.state === 'skipped'), 'when a step fails, the steps that read its files don’t run');
  // an input missing
  const rec4 = await new E.Run({ w: share, inputs: { s1: '/data/examples/nothing.studio.json' }, folder: HOME + '/results/missing', fs: files, run: fake }).start();
  check(rec4.steps[0].state === 'failed' && /isn’t there/.test(rec4.steps[0].error), `an input file that isn’t there is said (${rec4.steps[0].error})`);
  // stopping
  let r5;
  const slow = async (t, v) => {
    r5.stop();
    return fake(t, v);
  };
  r5 = new E.Run({ w: share, inputs: ins, folder: HOME + '/results/stopped', fs: files, run: slow });
  const rec5 = await r5.start();
  check(rec5.state === 'stopped' && rec5.steps[0].state === 'ok' && rec5.steps.slice(1).every((e) => e.state === 'stopped'), 'a run that is stopped stops after the step it is on');

  // a workflow made from tools that were run, one reading what the one before it wrote
  const log = [
    { tool: 'pedinterp', values: E.valuesOf(K.TOOL.pedinterp, { handDrawn: true }, { input: '/data/examples/okafor-sketch.png' }, null), files: [HOME + '/results/okafor-sketch.ped', HOME + '/results/okafor-sketch.studio.json'], ok: true, time: 1 },
    { tool: 'pednet-mode', values: E.valuesOf(K.TOOL['pednet-mode'], { method: 'patterns' }, { input: HOME + '/results/okafor-sketch.ped' }, null), files: [], ok: true, time: 2 },
    { tool: 'studio2ped', values: E.valuesOf(K.TOOL.studio2ped, {}, { input: HOME + '/results/okafor-sketch.studio.json' }, null), files: [HOME + '/results/okafor-sketch.ped'], ok: true, time: 3 }
  ];
  const made = E.fromRuns(log, 'From what I ran');
  const [inp, s1, s2, s3] = E.orderSteps(made);
  check(made.steps.length === 4 && inp.type === 'input' && inp.default === '/data/examples/okafor-sketch.png', 'a workflow made from three tools run has their input as its input');
  check(JSON.stringify(s1.params) === '{"handDrawn":true}' && s2.params.method === 'patterns', 'the steps keep the settings that weren’t defaults');
  check(E.connsOf(s2, 'input')[0].step === s1.id && E.connsOf(s2, 'input')[0].output === 'ped' && E.connsOf(s3, 'input')[0].output === 'drawing', 'a file one wrote and the next read is a connection');
  check(!E.problems(made).length, 'and it has no problems');
  {
    // (the walkthrough's: Drawing → GA4GH with a terms file, then a check of the GA4GH Pedigree it wrote)
    const ga = E.valuesOf(K.TOOL.studio2ga4gh, {}, { input: '/data/examples/price.studio.json', terms: '/data/examples/example-terms.json' }, null);
    const log2 = [
      { tool: 'studio2ga4gh', values: ga, files: [HOME + '/results/price_ga4gh-pedigree.json', HOME + '/results/price_phenopackets-family.json'], ok: true, time: 1 },
      { tool: 'validate', values: E.valuesOf(K.TOOL.validate, {}, { input: HOME + '/results/price_ga4gh-pedigree.json' }, null), files: [], ok: true, time: 2 }
    ];
    const made2 = E.fromRuns(log2, 'Checked GA4GH');
    const [drawingIn, termsIn, toGa4gh, checkIt] = E.orderSteps(made2);
    check(drawingIn.type === 'input' && !drawingIn.optional && termsIn.type === 'input' && termsIn.optional && termsIn.default === '/data/examples/example-terms.json', 'a file the tool can do without (the terms file) is an optional input; the drawing isn’t');
    check(toGa4gh.tool === 'studio2ga4gh' && checkIt.tool === 'validate' && E.connsOf(checkIt, 'input')[0].step === toGa4gh.id && E.connsOf(checkIt, 'input')[0].output === 'pedigree' && !E.problems(made2).length, 'the check reads the GA4GH Pedigree the step before it writes');
  }

  // the form's checks see the files as they will be: two of a kind are two files, and a set is several
  {
    const w = E.newWorkflow('Compare');
    const a = E.addInput(w, ['pedigree'], 'A');
    const b = E.addInput(w, ['pedigree'], 'B');
    const d = E.addTool(w, 'diff');
    E.connect(w, a.id, 'file', d.id, 'input');
    E.connect(w, b.id, 'file', d.id, 'input2');
    check(!E.problems(w).length, `two files of the same kind can be compared (${E.problems(w).map((p) => p.text).join('; ')})`);
    const w2 = E.newWorkflow('Compare with itself');
    const a2 = E.addInput(w2, ['pedigree'], 'A');
    const d2 = E.addTool(w2, 'diff');
    E.connect(w2, a2.id, 'file', d2.id, 'input');
    E.connect(w2, a2.id, 'file', d2.id, 'input2');
    check(E.problems(w2).some((p) => /different/.test(p.text)), 'a file compared with itself is a problem');
    const w3 = E.newWorkflow('Split and put together');
    const f3 = E.addInput(w3, ['family'], 'Family');
    const sp = E.addTool(w3, 'split');
    const mg = E.addTool(w3, 'merge');
    E.connect(w3, f3.id, 'file', sp.id, 'input');
    check(!E.connect(w3, sp.id, 'people', mg.id, 'inputs') && !E.problems(w3).length, `a set of files goes into Put files together, with no problem (${E.problems(w3).map((p) => p.text).join('; ')})`);
    const w4 = E.newWorkflow('One file put together');
    const f4 = E.addInput(w4, ['family'], 'Family');
    const mg4 = E.addTool(w4, 'merge');
    E.connect(w4, f4.id, 'file', mg4.id, 'inputs');
    const twos = E.problems(w4).filter((p) => /two/.test(p.text));
    check(twos.length === 1 && /needs two files or more/.test(twos[0].text), `one file put together is a problem, said once (${twos.map((p) => p.text).join('; ')})`);
    const w5 = E.newWorkflow('Optional');
    const i5 = E.addInput(w5, ['studio'], 'Drawing');
    i5.optional = true;
    const c5 = E.addTool(w5, 'studio2ped');
    E.connect(w5, i5.id, 'file', c5.id, 'input');
    check(E.problems(w5).some((p) => /can be left as none/.test(p.text)), 'an input that can be left as none, which a step needs, is a problem');
  }

  // an input that a tool's settings hide can't be connected; the + by an ontology offers the tool set to read it
  {
    const w = E.newWorkflow('Ontology');
    const o = E.addInput(w, ['obo'], 'HPO');
    const nm = E.addTool(w, 'normalise');
    check(/doesn’t read/.test(E.connect(w, o.id, 'file', nm.id, 'hpo')), 'an input its settings hide can’t be connected (Fill in missing terms reads an ontology only when it looks terms up here)');
    const r = E.readersOf(['obo'], false).find((x) => x.t.id === 'normalise');
    check(r && r.f.key === 'hpo' && r.params.lookup === 'local', 'the + by an ontology offers Fill in missing terms, set to look terms up here');
    Object.assign(nm.params, r.params);
    check(!E.connect(w, o.id, 'file', nm.id, 'hpo'), '… and then it reads it');
  }

  // a choice that follows the kind of file a step is given is made as the editor shows it
  {
    const w = E.newWorkflow('Convert');
    const i = E.addInput(w, ['pedigree', 'family'], 'GA4GH');
    const c = E.addTool(w, 'ga4gh-convert');
    E.connect(w, i.id, 'file', c.id, 'input');
    const said = E.stepOutputs(w, c)[0].kinds[0];
    const plan = E.planStep(w, c, { [i.id]: { file: '/data/examples/okafor_phenopackets-family.json' } }, HOME + '/results/conv', new Set(), null);
    check(plan.outs[0].kinds[0] === said && plan.v.to === said, `a conversion makes the kind of file the editor says it does, whatever it is given (${said})`);
    check(E.valuesOf(K.TOOL.filter, { ids: 5, prune: 'false' }, {}, null).ids === '5' && E.valuesOf(K.TOOL.filter, { prune: 'false' }, {}, null).prune === false, 'a setting from a file is the type its field holds');
  }

  // a workflow made from tools run with a set of files: the set where they read all of it, else inputs
  {
    const fam = '/data/examples/okafor_phenopackets-family.json';
    const people = ['II-1', 'II-2', 'III-1'].map((x) => `${HOME}/results/okafor-people/${x}.json`);
    const split = { tool: 'split', values: E.valuesOf(K.TOOL.split, {}, { input: fam }, null), files: people, ok: true, time: 1 };
    const merged = (paths) => ({ tool: 'merge', values: E.valuesOf(K.TOOL.merge, {}, { inputs: paths }, null), files: [HOME + '/results/cohort.json'], ok: true, time: 2 });
    const some = E.fromRuns([split, merged(people.slice(0, 2))], 'Some');
    const cs = E.connsOf(some.steps.find((s) => s.tool === 'merge'), 'inputs');
    check(cs.length === 2 && cs.every((c) => E.stepOf(some, c.step).type === 'input'), 'two files of a set of three, put together, are inputs of the workflow, not the set');
    const all = E.fromRuns([split, merged(people)], 'All');
    const ca = E.connsOf(all.steps.find((s) => s.tool === 'merge'), 'inputs');
    check(ca.length === 1 && ca[0].output === 'people' && !E.problems(all).length, 'all the files of a set, put together, are the set, once');
    const view = { tool: 'view', values: E.valuesOf(K.TOOL.view, {}, { input: people[0] }, null), files: [], ok: true, time: 2 };
    const one = E.fromRuns([split, view], 'One');
    const cv = E.connsOf(one.steps.find((s) => s.tool === 'view'), 'input');
    check(cv.length === 1 && E.stepOf(one, cv[0].step).type === 'input' && !E.problems(one).length, 'one file of a set, looked inside, is an input of the workflow');
  }

  // only the files a step wrote this time are its files; a drawing of two families gives a GA4GH Pedigree for each
  {
    files.writeText(HOME + '/results/stale.json', '{}');
    const outs = [{ name: 'out', label: 'file', path: HOME + '/results/stale.json' }];
    check(E.collect(outs, [], files).lost.length === 1 && E.collect(outs, [HOME + '/results/stale.json'], files).got.out, 'a file there from an earlier run is no file of the step’s');
    const two = async (t, v) => {
      if (t.id !== 'studio2ga4gh') return { ok: true, code: 0, stdout: '', stderr: '', files: [], result: { valid: true, name: 'GA4GH Pedigree', errors: 0, findings: [] } };
      const ps = ['_1_ga4gh-pedigree.json', '_2_ga4gh-pedigree.json', '_1_phenopackets-family.json', '_2_phenopackets-family.json'].map((x) => v.outdir + '/' + v.prefix + x);
      ps.forEach((p) => files.writeText(p, '{}'));
      return { ok: true, code: 0, stdout: '', stderr: '', files: ps };
    };
    const rec = await new E.Run({ w: share, inputs: ins, folder: HOME + '/results/two-families', fs: files, run: two }).start();
    check(rec.steps[0].state === 'ok' && rec.steps[0].outputs.pedigree.length === 2, 'a drawing of two families: Drawing → GA4GH writes a GA4GH Pedigree for each, and they are its files');
    check(rec.steps[1].state === 'failed' && /given 2 files/.test(rec.steps[1].error), `… which a check of one file says it can’t take (${rec.steps[1].error})`);
  }

  // a run ends, whatever goes wrong: its folder is a file, or a step can't be got ready
  {
    files.writeText(HOME + '/results/a-file', 'x');
    const r = await new E.Run({ w: share, inputs: ins, folder: HOME + '/results/a-file', fs: files, run: fake }).start();
    check(r.state === 'failed' && r.steps[0].state === 'failed' && /couldn’t be made/.test(r.steps[0].error) && r.steps.slice(1).every((e) => e.state === 'skipped'), 'a run whose folder is a file ends, failed, and says why');
    const w = E.newWorkflow('Two checks');
    const fi = E.addInput(w, ['family'], 'Family');
    const sp = E.addTool(w, 'split');
    const va = E.addTool(w, 'validate');
    E.connect(w, fi.id, 'file', sp.id, 'input');
    E.connect(w, fi.id, 'file', va.id, 'input');
    const fs2 = Object.create(files);
    fs2.mkdirp = (p) => {
      if (/people/.test(p)) throw new Error('Not a directory');
      return files.mkdirp(p);
    };
    files.writeText(HOME + '/data/fam_phenopackets-family.json', '{"proband": {}}');
    const said = console.error;
    console.error = () => {}; // (the run says what went wrong in the console too)
    const r2 = await new E.Run({ w, inputs: { [fi.id]: HOME + '/data/fam_phenopackets-family.json' }, folder: HOME + '/results/two-checks', fs: fs2, run: fake }).start();
    console.error = said;
    const [eSplit, eCheck] = [r2.steps.find((e) => e.tool === 'split'), r2.steps.find((e) => e.tool === 'validate')];
    check(eSplit.state === 'failed' && /couldn’t run: Not a directory/.test(eSplit.error) && eCheck.state === 'ok' && r2.state === 'failed', `a step that can’t be got ready fails, and the run goes on (${eSplit.error})`);
  }

  // commands.sh: a name stays in its comment, and a file written first ends where it should
  {
    const { spawnSync } = require('child_process');
    const os = require('os');
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wf-sh-'));
    const rec = {
      name: 'Mine\ntouch MADE-BY-THE-NAME',
      started: new Date().toISOString(),
      folder: HOME + '/results/x',
      steps: [{ n: 1, tool: 'filter', title: 'Keep some people', state: 'ok', values: {}, argv: [['true']], prepared: [{ path: HOME + '/results/x/ids.txt', text: 'II-1\nEOF\ntouch MADE-BY-THE-IDS\n' }] }]
    };
    fs.writeFileSync(path.join(tmp, 'commands.sh'), E.scriptOf(rec));
    const r = spawnSync('bash', ['commands.sh'], { cwd: tmp, env: { HOME: tmp, PATH: '/usr/bin:/bin' }, encoding: 'utf8' });
    const ids = fs.existsSync(path.join(tmp, 'results/x/ids.txt')) ? fs.readFileSync(path.join(tmp, 'results/x/ids.txt'), 'utf8') : null;
    check(r.status === 0 && !fs.existsSync(path.join(tmp, 'MADE-BY-THE-NAME')) && !fs.existsSync(path.join(tmp, 'MADE-BY-THE-IDS')) && ids === 'II-1\nEOF\ntouch MADE-BY-THE-IDS\n', 'commands.sh runs only the steps’ commands, whatever the workflow’s name and the ids say');
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

async function examplesRun() {
  for (const f of examples) {
    const files = new DiskFS();
    const MG = load(files);
    const E = MG.workflowEngine;
    const w = E.parse(fs.readFileSync(path.join(EXDIR, f), 'utf8'));
    const ins = Object.fromEntries(w.steps.filter((s) => s.type === 'input').map((s) => [s.id, s.default]));
    const folder = E.runFolder(files, w, ins);
    const t0 = Date.now();
    const rec = await new E.Run({ w, source: '/data/examples/workflows/' + f, inputs: ins, folder, fs: files, run: files.runner(MG) }).start();
    const bad = rec.steps.filter((e) => e.state !== 'ok');
    check(rec.state === 'ok', `${f}: every step runs, in Python (${((Date.now() - t0) / 1000).toFixed(1)} s)${bad.length ? ': ' + bad.map((e) => `${e.n}. ${e.title}: ${e.error || e.state} ${(e.stderr || '').trim().split('\n').pop()}`).join('; ') : ''}`);
    const wrote = rec.steps.flatMap((e) => Object.values(e.outputs || {}).flat());
    check(wrote.length && wrote.every((p) => files.exists(p) && p.startsWith(folder + '/')), `${f}: the files the steps say they write are in the run’s folder (${wrote.length})`);
    for (const e of rec.steps) if (e.tool === 'validate' && e.state === 'ok') check(/^Valid/.test(e.summary), `${f}: ${e.n}. ${e.title}: ${e.summary}`);
    fs.rmSync(files.tmp, { recursive: true, force: true });
  }
}

(async () => {
  try {
    await units();
    if (!process.argv.includes('--quick')) await examplesRun();
  } catch (e) {
    out.push('FAIL  ' + (e && e.stack ? e.stack : e));
  }
  console.log(out.join('\n'));
  const bad = out.filter((l) => l.startsWith('FAIL')).length;
  console.log(`\n${out.length - bad} passed, ${bad} failed`);
  process.exit(bad ? 1 : 0);
})();
