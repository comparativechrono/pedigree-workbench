"""The Pedigree workbench's own Python: what joins the web page to the packages.

``pedwb.cli`` runs the packages' command-line programs by name (the terminal's
``studio2ped``, ``phenotk`` and the rest, and ``!`` lines in notebooks), and
``pedwb.gui`` has the small functions the point-and-click Tools tab calls:
reading a drawing's colour key, suggesting ontology terms, checking a file.

None of this is needed to use the packages on your own computer: there you
install them with pip and call them directly.
"""

__version__ = "1.0.0"
