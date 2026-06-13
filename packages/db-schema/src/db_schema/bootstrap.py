from __future__ import annotations

import os
from pathlib import Path

import psycopg


def _project_root() -> Path:
    # Docker image workdir is /app; local tests may run from repository root.
    cwd = Path.cwd()
    if (cwd / "infra" / "sql").exists():
        return cwd
    if Path("/app/infra/sql").exists():
        return Path("/app")
    for parent in [cwd, *cwd.parents]:
        if (parent / "infra" / "sql").exists():
            return parent
    raise RuntimeError("cannot locate infra/sql directory")


def iter_sql_files() -> list[Path]:
    sql_dir = _project_root() / "infra" / "sql"
    return sorted(path for path in sql_dir.glob("*.sql") if path.name != "bootstrap_schema.sql")


def main() -> None:
    database_url = os.environ.get("AI_STOCK_DATABASE_URL")
    if not database_url:
        raise RuntimeError("AI_STOCK_DATABASE_URL is required")
    files = iter_sql_files()
    if not files:
        raise RuntimeError("no SQL migration files found under infra/sql")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for path in files:
                cur.execute(path.read_text(encoding="utf-8"))
        conn.commit()
    print(f"applied {len(files)} SQL migration files")


if __name__ == "__main__":
    main()
