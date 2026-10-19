/* The workbench's example drawings, PED and MPED files, as the Risk tab reads them in the page (assets/js/risk-read.js),
   printed as JSON for readers.py to set against what studio2ped and mpedtools make of them.
   usage: node tests/risk/read_examples.js [FILE...] */
'use strict';
const fs = require('fs');
const path = require('path');
const R = require('../../assets/js/risk-read.js');

const ROOT = path.join(__dirname, '..', '..');
const EX = path.join(ROOT, 'data', 'examples');
const files = process.argv.length > 2 ? process.argv.slice(2) : [
  ...fs.readdirSync(EX).filter((f) => /\.(studio\.json|ped|mped)$/.test(f)).map((f) => path.join(EX, f)),
  ...fs.readdirSync(path.join(EX, 'pednet')).filter((f) => /\.ped$/.test(f)).map((f) => path.join(EX, 'pednet', f))
];
const out = files.sort().map((file) => {
  const text = fs.readFileSync(file, 'utf8');
  const families = /\.studio\.json$/.test(file) ? [R.fromStudio(JSON.parse(text), path.basename(file))] : R.fromPed(text);
  return { file: path.relative(ROOT, file), families };
});
process.stdout.write(JSON.stringify(out));
