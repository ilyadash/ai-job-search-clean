"""SQLite connection, migrations, read-only query, and backups."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .common import *

def db_path(repo: Path | str | None = None) -> Path:
    return (Path(repo) if repo else ROOT) / "state" / "job_search.sqlite"


def migrations_dir(repo: Path | str | None = None) -> Path:
    return (Path(repo) if repo else ROOT) / "state" / "migrations"


def applications_dir(repo: Path | str | None = None) -> Path:
    return (Path(repo) if repo else ROOT) / "documents" / "applications"


def connect(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if readonly:
        if not path.is_file():
            raise StateError(f"database not found: {path}")
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only = ON")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def migration_paths(repo: Path | str | None = None) -> list[Path]:
    base = Path(repo) if repo else ROOT
    directory = migrations_dir(base)
    if not directory.is_dir():
        directory = migrations_dir(ROOT)
    return sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))


def _migration_version(path: Path) -> int:
    match = re.match(r"(\d{3})_", path.name)
    if not match:
        raise StateError(f"bad migration filename: {path.name}")
    return int(match.group(1))


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )


def _record_migration(conn: sqlite3.Connection, version: int, name: str) -> None:
    _ensure_migration_table(conn)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (version, name, _now()),
    )


def init_connection(conn: sqlite3.Connection, base: Path | str | None = None) -> None:
    """Apply pending migrations to an already-open connection (no backup)."""
    base_path = Path(base) if base else ROOT
    paths = migration_paths(base_path)
    if not paths:
        raise StateError("no migrations found")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for migration in paths:
        migration_version = _migration_version(migration)
        if migration_version <= version:
            continue
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {migration_version}")
        _record_migration(conn, migration_version, migration.name)
        conn.commit()
        version = migration_version


def migrate(repo: Path | str | None = None, *, backup_before: bool = True) -> dict:
    """Apply pending migrations, backing up an existing database first."""
    base = Path(repo) if repo else ROOT
    path = db_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.is_file() and path.stat().st_size > 0
    conn = connect(path)
    backup_path = None
    try:
        start_version = conn.execute("PRAGMA user_version").fetchone()[0]
        version = start_version
        paths = migration_paths(base)
        if not paths:
            raise StateError("no migrations found")
        target = max(_migration_version(item) for item in paths)
        pending = [item for item in paths if _migration_version(item) > version]
        if existed and pending and backup_before and version > 0:
            backup_path = backup(base)
        if version > 0:
            _ensure_migration_table(conn)
            for migration in paths:
                if _migration_version(migration) <= version:
                    _record_migration(conn, _migration_version(migration), migration.name)
        # A brand-new database starts with the baseline migration.
        if version == 0:
            baseline = paths[0]
            conn.executescript(baseline.read_text(encoding="utf-8"))
            version = _migration_version(baseline)
            conn.execute(f"PRAGMA user_version = {version}")
            _record_migration(conn, version, baseline.name)
            conn.commit()
            pending = [item for item in paths if _migration_version(item) > version]
        applied: list[str] = []
        for migration in pending:
            migration_version = _migration_version(migration)
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {migration_version}")
            _record_migration(conn, migration_version, migration.name)
            conn.commit()
            applied.append(migration.name)
            version = migration_version
        if version != target:
            raise StateError(f"migration chain ended at {version}, expected {target}")
        from .applications import backfill_phase0

        backfill_phase0(conn, base)
        conn.commit()
        return {
            "from": start_version,
            "to": version,
            "applied": applied,
            "backup": backup_path.as_posix() if backup_path else None,
        }
    finally:
        conn.close()


def init_db(repo: Path | str | None = None) -> Path:
    base = Path(repo) if repo else ROOT
    path = db_path(base)
    migrate(base)
    return path


def _readonly_authorizer(action: int, arg1: str | None, arg2: str | None, dbname: str | None, source: str | None) -> int:
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    recursive = getattr(sqlite3, "SQLITE_RECURSIVE", None)
    if recursive is not None:
        allowed.add(recursive)
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def _validate_select(sql: str) -> str:
    text = (sql or "").strip()
    if not text:
        raise StateError("empty SQL")
    body = text[:-1].rstrip() if text.endswith(";") else text
    if ";" in body:
        raise StateError("only one SELECT statement is allowed")
    first = body.lstrip().split(None, 1)[0].casefold()
    if first not in {"select", "with", "explain"}:
        raise StateError("only read-only SELECT statements are allowed")
    return body


def query(sql: str, params: tuple | list = (), limit: int = 500, repo: Path | str | None = None) -> dict:
    body = _validate_select(sql)
    path = db_path(repo)
    conn = connect(path, readonly=True)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.set_authorizer(_readonly_authorizer)
    try:
        cursor = conn.execute(body, tuple(params))
        columns = [item[0] for item in cursor.description or []]
        rows = [dict(row) for row in cursor.fetchmany(max(1, limit) + 1)]
    except sqlite3.Error as exc:
        raise StateError(f"SQL error: {exc}") from None
    finally:
        conn.close()
    truncated = len(rows) > limit
    return {"columns": columns, "rows": rows[:limit], "truncated": truncated}


def backup(repo: Path | str | None = None, destination: Path | str | None = None) -> Path:
    base = Path(repo) if repo else ROOT
    source = db_path(base)
    if not source.is_file():
        raise StateError(f"database not found: {source}")
    target = Path(destination) if destination else (base / "backups" / f"job_search-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.sqlite")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = connect(source, readonly=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
        target_conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        target_conn.close()
        source_conn.close()
    return target

def schema_text(conn: sqlite3.Connection) -> str:
    lines = []
    tables = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    for item in tables:
        lines.append(f"{item['type']}: {item['name']}")
        for column in conn.execute(f"PRAGMA table_info('{item['name']}')").fetchall():
            lines.append(f"  {column['name']} {column['type']}")
    return "\n".join(lines) + "\n"

__all__ = [name for name in globals() if not name.startswith("__")]
