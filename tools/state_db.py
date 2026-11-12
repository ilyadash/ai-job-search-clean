#!/usr/bin/env python3
"""SQLite source of truth for job-search applications, jobs, and outcomes.

This module is a thin compatibility facade and CLI entrypoint. The
implementation lives in tools/state_db_core/, split by domain. Existing
callers can keep using `from tools import state_db` and the CLI path
`python3 tools/state_db.py` unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.state_db_core import *  # noqa: F401,F403
from tools.state_db_core import main


if __name__ == "__main__":
    sys.exit(main())
