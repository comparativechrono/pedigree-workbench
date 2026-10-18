"""``python -m mondonorm FILE.json ...``: the same as the ``mondonorm`` command."""
from .cli import main

raise SystemExit(main())
