"""Allow running as `python -m ped2studio`."""

import sys

from .cli import main

sys.exit(main())
