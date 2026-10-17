/* =====================================================================
   The workbench's handle on the Pedigree Studio in this frame.

   Pedigree Studio (index.html beside this file) is a copy of the Studio,
   loaded in the Studio tab's frame. This script runs after it, in the
   same page, and gives the workbench a small set of things it may do:

     pedwbStudio.data()            the drawing, as Pedigree Studio saves it
     pedwbStudio.load(data, opts)  show a drawing (opts.tidy: lay it out
                                   afresh with Tidy; it can be undone)
     pedwbStudio.clear()           an empty drawing (it can be undone)
     pedwbStudio.tidy()            Tidy, as the Studio's own button does
     pedwbStudio.fit()             fit the drawing to the window
     pedwbStudio.isEmpty()
     pedwbStudio.status(text)      a message in the Studio's status line
     pedwbStudio.onChange(fn)      fn() after each change to the drawing

   The workbench calls these from the page around the frame (same
   origin), so nothing here listens for messages from elsewhere.
   ===================================================================== */
/* global buildSessionData, restoreSession, runManagedPedigreeLayout, fitToView, scheduleSave, pushUndo, deselectAll, persons, isRestoring:writable */
(function () {
  'use strict';
  const listeners = [];
  let quiet = 0; // changes made by load(): not the person's own
  const tell = () => {
    if (quiet) return;
    listeners.forEach((fn) => {
      try {
        fn();
      } catch (e) {
        /* a listener's trouble is its own */
      }
    });
  };
  // Pedigree Studio calls scheduleSave() after every change to the drawing (it saves the drawing in the browser
  // then); the workbench is told at the same moment.
  const save0 = window.scheduleSave;
  if (typeof save0 === 'function') {
    window.scheduleSave = function () {
      const r = save0.apply(this, arguments);
      tell();
      return r;
    };
  }
  const statusEl = () => document.getElementById('statusBar');

  function tidyNow() {
    if (!persons.size) return;
    runManagedPedigreeLayout({ seedIds: Array.from(persons.keys()), reason: 'manualRedistribute', fromButton: true, fresh: true });
  }

  window.pedwbStudio = {
    version: 1,
    data() {
      return buildSessionData();
    },
    load(data, opts = {}) {
      if (!data || typeof data !== 'object' || !Array.isArray(data.persons)) throw new Error('This is not a Pedigree Studio drawing (it has no list of persons).');
      quiet++;
      try {
        deselectAll();
        pushUndo();
        // (as when the Studio opens a file itself: what restoring does is not a change of its own to undo)
        isRestoring = true;
        try {
          restoreSession(data);
        } finally {
          isRestoring = false;
        }
        if (opts.tidy) tidyNow();
        fitToView();
        scheduleSave();
      } finally {
        quiet--;
      }
      const s = statusEl();
      if (s) s.textContent = opts.message || (opts.tidy ? 'Drawing opened and tidied' : 'Drawing opened');
    },
    clear() {
      this.load({ version: 5, persons: [], labels: [], partnerships: [], childLinks: [], twinLinks: [], legendLabels: {} }, { message: 'New drawing' });
    },
    tidy() {
      pushUndo();
      tidyNow();
      fitToView();
      const s = statusEl();
      if (s) s.textContent = 'Pedigree tidied';
    },
    fit() {
      fitToView();
    },
    isEmpty() {
      return !persons.size;
    },
    status(text) {
      const s = statusEl();
      if (s) s.textContent = String(text || '');
    },
    onChange(fn) {
      if (typeof fn === 'function') listeners.push(fn);
    }
  };
})();
