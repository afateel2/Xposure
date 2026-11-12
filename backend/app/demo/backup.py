"""
One-time safety backup before the FIRST destructive demo reset.

`POST /demo/reset` deletes rows (actions, impacts, changes, the ECC-2:2024
version) from the live database. Before the very first one on a machine we
take a plain-SQL `pg_dump` of the whole database, so the state that existed
before the demo tooling ever ran can be restored:

    psql -U xposure -d xposure -f <dump>.sql

Later resets do not repeat it (the demo state is reproducible by design).
The dump goes to `settings.demo_backup_dir` (default
backend/data/cache/demo_backups, gitignored). audit_log is included in the
dump; the reset itself never deletes audit rows.

pg_dump is taken from the local PATH when present, otherwise from inside the
Postgres docker container named by settings.demo_pg_container. A failed
backup blocks the reset: destroying live data without a safety copy is not a
trade the tool makes silently.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..config import settings

FILE_PREFIX = "xposure-pre-demo-"


class BackupError(RuntimeError):
    pass


def backup_dir() -> Path:
    if settings.demo_backup_dir:
        return Path(settings.demo_backup_dir)
    return Path(__file__).resolve().parents[2] / "data" / "cache" / "demo_backups"


def existing_backups() -> list[Path]:
    directory = backup_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{FILE_PREFIX}*.sql"))


def _db_parts() -> dict[str, str]:
    parsed = urlparse(settings.database_url)
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "dbname": (parsed.path or "/").lstrip("/"),
    }


def _pg_dump_command(parts: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    env = dict(os.environ, PGPASSWORD=parts["password"])
    local = shutil.which("pg_dump")
    if local:
        return (
            [local, "-h", parts["host"], "-p", parts["port"], "-U", parts["user"], "-d", parts["dbname"],
             "--clean", "--if-exists"],
            env,
        )
    docker = shutil.which("docker")
    if not docker:
        raise BackupError("Neither pg_dump nor docker is available on PATH, so no backup can be taken.")
    # The password is passed by variable name only, so it never appears on a command line.
    return (
        [docker, "exec", "-e", "PGPASSWORD", settings.demo_pg_container, "pg_dump",
         "-U", parts["user"], "-d", parts["dbname"], "--clean", "--if-exists"],
        env,
    )


def ensure_first_backup() -> dict:
    """Take the backup if none exists yet. Returns
    {"status": "created" | "exists", "path": str, "bytes": int}. Raises
    BackupError on failure."""
    existing = existing_backups()
    if existing:
        latest = existing[-1]
        return {"status": "exists", "path": str(latest), "bytes": latest.stat().st_size}

    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = directory / f"{FILE_PREFIX}{stamp}.sql"
    tmp = final.with_name(final.name + ".part")

    command, env = _pg_dump_command(_db_parts())
    try:
        with tmp.open("wb") as out:
            result = subprocess.run(command, env=env, stdout=out, stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        tmp.unlink(missing_ok=True)
        raise BackupError(f"pg_dump could not be run: {type(exc).__name__}: {exc}") from exc
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        stderr = result.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise BackupError(f"pg_dump failed (exit {result.returncode}): {' | '.join(stderr)}")
    size = tmp.stat().st_size
    if size < 1024:
        tmp.unlink(missing_ok=True)
        raise BackupError(f"pg_dump produced only {size} bytes; refusing to treat that as a backup.")
    tmp.replace(final)
    return {"status": "created", "path": str(final), "bytes": size}
