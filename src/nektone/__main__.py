"""Support `python -m nektone`.

Relative imports work here because `-m` establishes the package context.
The *frozen* entry point is packaging/entry.py, which cannot use them —
see the comment at the top of that file.
"""
import sys

from .app import main

sys.exit(main())
