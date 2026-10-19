// The Tools tab's tools (assets/js/tools.js), each with sample values: print the command each runs and its Python, as
// JSON lines, for run_equiv.py. tools.js is loaded with a small stand-in for the page.
//
//   node tests/equivalence/gen.js assets/js/tools.js > cases.jsonl
const path = require('path');
const HOME = '/home/user';
const MG = {
  h: () => ({}), esc: (s) => s, toast() {}, store: { get: (k, d) => d, set() {} }, bus: { on() {}, emit() {} },
  path: { dirname: (p) => p.replace(/\/[^/]*$/, '') || '/' },
  icon: () => '', kernels: {}, config: {},
  app: { HOME, kindNames: {}, pedKind: (p) => (/\.studio\.json$/.test(p) ? 'studio' : /_ga4gh-pedigree\.json$/.test(p) ? 'pedigree' : /_phenopackets-family\.json$/.test(p) ? 'family' : /\.mped$/.test(p) ? 'mped' : /\.ped$/.test(p) ? 'ped' : /\.png$/.test(p) ? 'image' : /\.vcf$/.test(p) ? 'vcf' : /genotypes\.tsv$/.test(p) ? 'variants' : 'json') }
};
global.window = { MG, matchMedia: () => ({ matches: false }) };
require(path.resolve(process.argv[2] || path.join(__dirname, '..', '..', 'assets', 'js', 'tools.js')));
const TOOLS = Object.fromEntries(MG.pedTools.map((t) => [t.id, t]));
const EX = '/data/examples/';
const R = HOME + '/results/';
// two small families in one PED file, written for the cases that need one (see FILES)
const TWO = R + 'two-families.ped';
const FILES = { [TWO]: ['FAMA\t1\t0\t0\t1\t2', 'FAMA\t2\t0\t0\t2\t1', 'FAMA\t3\t1\t2\t1\t2', 'FAMA\t4\t1\t2\t2\t1', 'FAMB\t1\t0\t0\t1\t1', 'FAMB\t2\t0\t0\t2\t2', 'FAMB\t3\t1\t2\t2\t2', 'FAMB\t4\t1\t2\t1\t1', ''].join('\n') };
// [tool, values, {fails: the command and the Python must both stop with an error}]
const CASES = [
  ['studio2ga4gh', { input: EX + 'okafor.studio.json', terms: EX + 'example-terms.json' }],
  ['studio2ga4gh', { input: EX + 'lynch.studio.json', terms: EX + 'example-terms.json', ids: 'drawing', only: 'family', family: 'LYN', prefix: 'lynch-drawing' }],
  ['ga4gh2studio', { input: EX + 'okafor_ga4gh-pedigree.json' }],
  ['ga4gh2studio', { input: EX + 'okafor_phenopackets-family.json', out: '~/pedigrees/okafor-from-family.studio.json' }],
  ['studio2ped', { input: EX + 'okafor.studio.json' }],
  ['studio2ped', { input: EX + 'cf-cousins.studio.json', prefix: 'cf' }],
  ['studio2ped', { input: EX + 'lynch.studio.json', prefix: 'lynch-text', ids: 'text' }],
  ['ped2studio', { input: EX + 'lynch.ped' }],
  ['ped2studio', { input: EX + 'okafor.mped', colour: '#c0392b', shading: true, pattern: 'dots', fill: 'half', out: '~/pedigrees/okafor-shaded.studio.json' }],
  ['ga4gh-convert', { input: EX + 'okafor_ga4gh-pedigree.json', to: 'family', proband: 'IV-3' }],
  ['ga4gh-convert', { input: EX + 'okafor_phenopackets-family.json', to: 'pedigree' }],
  ['export', { input: EX + 'okafor_phenopackets-family.json', fmt: 'ped' }],
  ['export', { input: EX + 'okafor_ga4gh-pedigree.json', fmt: 'tsv' }],
  ['export', { input: EX + 'okafor_phenopackets-family.json', fmt: 'yaml' }],
  ['export', { input: EX + 'okafor_phenopackets-family.json', fmt: 'jsonl' }],
  ['upgrade', { input: EX + 'older/studio2ga4gh-0.3_phenopackets-family.json' }],
  ['upgrade', { input: EX + 'older/abusua2ga4gh-0.2_ga4gh-pedigree.json' }],
  ['normalise', { input: R + "studio2ga4gh-0.3.upgraded.json", mapping: EX + 'example-terms.json', lookup: 'no' }],
  ['validate', { input: EX + 'okafor_ga4gh-pedigree.json' }],
  ['view', { input: EX + 'okafor_phenopackets-family.json', what: 'view' }],
  ['view', { input: EX + 'okafor_ga4gh-pedigree.json', what: 'stats' }],
  ['diff', { input: EX + 'okafor_ga4gh-pedigree.json', input2: R + 'okafor_ga4gh-pedigree.json' }],
  ['deidentify', { input: EX + 'okafor_phenopackets-family.json' }],
  ['deidentify', { input: EX + 'okafor_ga4gh-pedigree.json', remap: 'hash', salt: 'pepper', binAge: '10y', dropProv: true, out: '~/results/okafor-hashed.json', keyfile: '~/results/okafor-hashed.key.json' }],
  ['filter', { input: EX + 'okafor_phenopackets-family.json', who: 'affected' }],
  ['filter', { input: EX + 'okafor_ga4gh-pedigree.json', ids: 'IV-3\nIII-2\nIII-3', terms: 'HP:0000365', out: '~/results/okafor-three.json' }],
  ['split', { input: EX + 'okafor_phenopackets-family.json' }],
  ['merge', { inputs: [R + 'okafor-people/IV-3.json', R + 'okafor-people/II-3.json'], cid: 'okafor-cases' }],
  ['add', { input: EX + 'okafor_phenopackets-family.json', phenotypes: 'HP:0000365=Hearing impairment\nHP:0001263', excluded: true, diseases: 'MONDO:0007254=breast cancer', onset: 'P45Y', vital: 'ALIVE', out: '~/results/okafor-added.json' }],
  ['add', { input: EX + 'okafor_ga4gh-pedigree.json', target: 'II-3', diseases: 'MONDO:0007254', out: '~/results/okafor-added2.json' }],
  ['mped-info', { input: EX + 'okafor.mped' }],
  ['mped-extract', { input: EX + 'okafor.mped', which: 'Breast_cancer' }],
  ['mped-extract', { input: EX + 'okafor.mped', which: '', prefix: 'okall' }],
  ['mped-merge', { inputs: [R + 'okall_Hearing_loss_from_birth.ped', R + 'okall_Breast_cancer.ped'], names: 'Hearing Breast' }],
  ['mped-split', { input: EX + 'okafor.mped' }],
  ['mped-convert', { input: EX + 'okafor.mped', action: 'to-ped', column: 'Breast_cancer' }],
  ['mped-convert', { input: EX + 'lynch.ped', action: 'to-mped' }],
  ['mped-convert', { input: EX + 'lynch.ped', action: 'add', column: 'Pancreatic', value: '1', out: '~/results/lynch-plus.mped' }],
  ['mped-convert', { input: EX + 'okafor.mped', action: 'remove', column: 'Hearing_loss_from_birth', out: '~/results/okafor-less.mped' }],
  ['pedinterp', { input: EX + 'lynch.png' }],
  ['pedinterp', { input: EX + 'lynch.png', family: 'LYN', upscale: 4, outdir: '~/results/pictures' }],
  ['pednet-graph', { input: EX + 'lynch.ped' }],
  ['pednet-graph', { input: EX + 'pednet/consanguineous.ped', kinship: true, graphml: true }],
  ['pednet-graph', { input: EX + 'cf-cousins.mped', family: 'FAM1', kinship: true, xlinked: true, graphml: true, mating: true }],
  ['pednet-mode', { input: EX + 'lynch.ped' }],
  ['pednet-mode', { input: EX + 'lynch.ped', penetrance: '0.9', phenocopy: 0.01, proband: 'III-3', threshold: 0.9 }],
  ['pednet-mode', { input: EX + 'cf-cousins.mped', method: 'patterns' }],
  ['pednet-mode', { input: EX + 'okafor.mped', method: 'metrics' }],
  ['pednet-rank', { input: EX + 'pednet/dominant.ped', variants: EX + 'pednet/dominant.vcf' }],
  ['pednet-rank', { input: EX + 'pednet/recessive.ped', variants: EX + 'pednet/recessive.vcf', modes: 'AR', top: 3, maxfreq: '0.005', passed: true, out: '~/results/recessive-ar.tsv' }],
  ['pedgen', { mode: 'AR', generations: 4, seed: '7' }],
  ['pedgen', { mode: 'AD', seed: '3', partners: 0.5, ancestors: 0.1, freq: 0.05, clean: true, genotypes: false, family: 'SIM2' }],
  ['pednet-rank', { input: R + 'FAM1.ped', variants: R + 'FAM1-genotypes.tsv', out: '' }],
  ['pednet-rank', { input: R + 'FAM1.ped', variants: R + 'FAM1-genotypes.tsv', modes: 'AR' }],
  // penetrances separated by spaces; families taken together; a seed too large for a JavaScript number
  ['pednet-mode', { input: EX + 'lynch.ped', penetrance: '0.6 0.8  0.95' }],
  ['pednet-mode', { input: TWO, together: true }],
  ['pednet-mode', { input: TWO, together: true, family: 'FAMB', proband: '3' }],
  ['pedgen', { mode: 'AD', seed: '123456789012345678901', family: 'BIG' }],
  // a dominant condition with cousins who marry, and at least three people affected
  ['pedgen', { mode: 'AD', generations: 4, seed: '5', cousins: 0.5, minAffected: 3, family: 'SIM3' }],
  // the kinship table is for one family: with two, and none given, both stop
  ['pednet-graph', { input: TWO, kinship: true }, { fails: true }]
];
const expand = (p) => String(p).replace(/^~(?=\/|$)/, HOME);
for (const [id, given, how = {}] of CASES) {
  const t = TOOLS[id];
  const v = {};
  for (const f of t.fields) v[f.key] = given[f.key] != null ? given[f.key] : f.type === 'files' ? [] : f.type === 'file' ? '' : typeof f.def === 'function' ? undefined : f.def;
  for (const f of t.fields) if (v[f.key] === undefined) v[f.key] = f.def(v);
  for (const f of t.fields) {
    if (f.show && !f.show(v)) v[f.key] = f.type === 'check' ? false : f.type === 'files' ? [] : '';
    if ((f.type === 'file' || f.type === 'folder' || f.type === 'path') && v[f.key]) v[f.key] = expand(v[f.key]);
    if (f.type === 'files') v[f.key] = v[f.key].map(expand);
  }
  let argv = t.argv(v);
  if (!Array.isArray(argv[0])) argv = [argv];
  // (the form's check must pass, as it does before the tool can run)
  const problem = t.check ? t.check(v) : '';
  if (problem) throw new Error(`${id}: the form would refuse ${JSON.stringify(given)}: ${problem}`);
  const files = Object.entries(FILES).filter(([p]) => JSON.stringify(given).includes(p)).map(([path, text]) => ({ path, text }));
  console.log(JSON.stringify({ id, argv, python: t.python ? t.python(v) : '', outputs: t.outputs ? t.outputs(v) : [], files, fails: !!how.fails, idfile: id === 'filter' && v.ids ? { path: argv[0][argv[0].indexOf('--id-list') + 1], text: v.ids.split('\n').join('\n') + '\n' } : null }));
}
