/* =====================================================================
   Settings for the Pedigree workbench.
   Edit and re-upload this file; nothing else needs to change.
   ===================================================================== */
window.MG_CONFIG = {
  courseTitle: 'Pedigree workbench',
  courseSubtitle: 'Pedigree Studio · conversions · GA4GH and Phenopackets · ontology terms – in your browser',

  /* The prefix of what the page keeps in the browser (files, notebooks, settings). Every site
     of ours on the same address (comparativechrono.github.io/…) shares one browser storage, so
     each needs its own prefix: change it only if two copies of this workbench on one web site
     must not share their saved work. */
  storePrefix: 'pedwb',
  hostname: 'pedigrees',

  /* Python in the browser (Pyodide). To host it with the site instead of the CDN, download the
     Pyodide release and put its folder here, e.g. 'assets/vendor/pyodide/'. */
  pyodideBase: 'https://cdn.jsdelivr.net/pyodide/v0.29.5/full/',
  /* Pyodide packages loaded when Python starts (PyYAML, for phenotk's YAML output). Any other
     Pyodide package (pandas, matplotlib …) loads when a notebook cell imports it. */
  pythonPreload: ['pyyaml'],
  pythonBackground: [],

  /* Where the Tools tab downloads the Human Phenotype Ontology from when you ask it to keep a
     copy on this computer (about 11 MB). raw.githubusercontent.com lets web pages download. */
  hpoDownload: 'https://raw.githubusercontent.com/obophenotype/human-phenotype-ontology/master/hp.obo',

  /* How much the workbench may keep in this browser before it warns (megabytes). */
  storageWarnMB: 500
};
