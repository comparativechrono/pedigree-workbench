/* The example workflows (data/examples/workflows/*.workflow.json), made with the workflow engine itself, so that each
   connection is one it allows, and the boxes are laid out as Tidy lays them out.

     node build/make_example_workflows.js
*/
const fs = require('fs');
const path = require('path');
const { load, MemFS, ROOT } = require('../tests/workflows/env.js');
const MG = load(new MemFS());
const E = MG.workflowEngine;
const EX = '/data/examples/';
const OUT = path.join(ROOT, 'data', 'examples', 'workflows');

function make(file, name, annotation, build) {
  const w = E.newWorkflow(name);
  w.annotation = annotation;
  build(w);
  E.autoLayout(w);
  w.created = w.updated = '2026-10-20T12:00:00.000Z';
  const probs = E.problems(w);
  if (probs.length) throw new Error(`${file}: ${probs.map((p) => p.text).join('; ')}`);
  fs.writeFileSync(path.join(OUT, file), E.serialise(w));
  console.log(`data/examples/workflows/${file}: ${w.steps.length} steps`);
}
const join = (w, a, out, b, key) => {
  const why = E.connect(w, a.id, out, b.id, key);
  if (why) throw new Error(why);
};

make('share-a-drawing.workflow.json', 'Share a drawing in the GA4GH standard',
  'A drawing and the terms of its conditions become a GA4GH Pedigree and a Phenopackets Family, each checked against the standard, and a de-identified copy of the Family to share, checked too.',
  (w) => {
    const drawing = E.addInput(w, ['studio'], 'The drawing');
    drawing.default = EX + 'okafor.studio.json';
    const terms = E.addInput(w, ['terms'], 'Terms for its conditions');
    terms.default = EX + 'example-terms.json';
    terms.optional = true;
    const conv = E.addTool(w, 'studio2ga4gh');
    join(w, drawing, 'file', conv, 'input');
    join(w, terms, 'file', conv, 'terms');
    const check1 = E.addTool(w, 'validate');
    join(w, conv, 'pedigree', check1, 'input');
    const check2 = E.addTool(w, 'validate');
    join(w, conv, 'family', check2, 'input');
    const deid = E.addTool(w, 'deidentify');
    join(w, conv, 'family', deid, 'input');
    const check3 = E.addTool(w, 'validate');
    join(w, deid, 'out', check3, 'input');
  });

make('sketch-to-drawing.workflow.json', 'From a sketch to a drawing, and its mode of inheritance',
  'A pedigree sketched by hand becomes a PED file, a Pedigree Studio drawing and a GA4GH Pedigree (PedInterp). The GA4GH Pedigree is checked against the standard, and PedNet weighs up the family’s mode of inheritance.',
  (w) => {
    const pic = E.addInput(w, ['image'], 'The sketch');
    pic.default = EX + 'okafor-sketch.png';
    const read = E.addTool(w, 'pedinterp');
    read.params = { handDrawn: true, ga4gh: true };
    join(w, pic, 'file', read, 'input');
    const check = E.addTool(w, 'validate');
    join(w, read, 'pedigree', check, 'input');
    const mode = E.addTool(w, 'pednet-mode');
    join(w, read, 'ped', mode, 'input');
  });

make('simulate-and-test.workflow.json', 'Simulate a family, and test PedNet on it',
  'PedGen makes up a family with a recessive condition (the same family each time, with its seed). PedNet weighs up its mode of inheritance and ranks the simulated variant, and the family is drawn for the Studio.',
  (w) => {
    const sim = E.addTool(w, 'pedgen');
    sim.params = { mode: 'AR', seed: '7', family: 'SIMAR' };
    const mode = E.addTool(w, 'pednet-mode');
    join(w, sim, 'ped', mode, 'input');
    const rank = E.addTool(w, 'pednet-rank');
    join(w, sim, 'ped', rank, 'input');
    join(w, sim, 'genotypes', rank, 'variants');
    const draw = E.addTool(w, 'ped2studio');
    join(w, sim, 'ped', draw, 'input');
  });

make('update-an-old-file.workflow.json', 'Bring a file from an older tool up to date',
  'A GA4GH file made by an older version of our tools is upgraded to the standard form, its findings that have a name but no term are given terms from a terms file, and the result is checked against the standard.',
  (w) => {
    const old = E.addInput(w, ['pedigree', 'family', 'cohort', 'phenopacket', 'json'], 'The file from an older tool');
    old.default = EX + 'older/studio2ga4gh-0.3_phenopackets-family.json';
    const terms = E.addInput(w, ['terms'], 'Terms file');
    terms.default = EX + 'example-terms.json';
    const up = E.addTool(w, 'upgrade');
    join(w, old, 'file', up, 'input');
    const fill = E.addTool(w, 'normalise');
    join(w, up, 'out', fill, 'input');
    join(w, terms, 'file', fill, 'mapping');
    const check = E.addTool(w, 'validate');
    join(w, fill, 'out', check, 'input');
  });
