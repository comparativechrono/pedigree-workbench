"""Allow running as `python -m mpedtools`."""
import sys
from .cli import main
sys.exit(main())
