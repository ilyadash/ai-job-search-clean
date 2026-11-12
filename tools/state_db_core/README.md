# state_db_core

Domain modules for the SQLite job-search state store. `tools/state_db.py` is the
public CLI and compatibility facade; this package is the implementation.

## Modules

| Module | Responsibility |
|---|---|
| `common.py` | Paths, constants, `StateError`, statuses, stages, dates, normalizers |
| `db.py` | Connection, migrations, read-only query, backup, schema |
| `jobs.py` | Job rows, upsert, descriptions, candidates, sweep, rank apply |
| `applications.py` | Applications, stages, events, sources, sync state |
| `outcomes.py` | Draft, outcome, notes, event corrections, application list |
| `migration_text.py` | Legacy `outcome.md` / `applications.notes` migration |
| `migration_jobs.py` | Archived-posting and job-description migration |
| `legacy_import.py` | One-time tracker / seen-jobs importer |
| `stats.py` | Funnel metrics, markdown report, upskill data |
| `cli.py` | argparse parser and command handlers |

## Dependency direction

```
common
  ^
db
  ^
jobs
  ^
applications
  ^
outcomes / migration_text / migration_jobs / legacy_import
  ^
stats / cli
  ^
tools/state_db.py facade
```

`applications.py` may import `jobs.py`; `jobs.py` must not import
`applications.py`. `outcomes.py` may import both. Text/job migrations may
orchestrate state modules. `cli.py` is the only module that knows every
command. No module may import the facade.

`db.migrate()` imports `applications.backfill_phase0` lazily to avoid a module
cycle while keeping migrations self-contained.

## Compatibility

External callers and tests may keep using:

```python
from tools import state_db
```

The facade re-exports the legacy public API plus the private helpers still used
by `rank_state.py`, `telegram_common.py`, and the test suite. New code should
import from the owning module instead.
