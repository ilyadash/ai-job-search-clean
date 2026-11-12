"""Compatibility facade for the job-search SQLite state store.

The implementation is split into domain modules; this package re-exports the
names that external consumers (and the legacy tools/state_db.py entrypoint)
still use.
"""

from .common import *
from .db import *
from .jobs import *
from .applications import *
from .outcomes import *
from .migration_text import *
from .migration_jobs import *
from .legacy_import import *
from .stats import *
from .cli import main

__all__ = [name for name in globals() if not name.startswith("__")]
