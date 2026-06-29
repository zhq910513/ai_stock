"""Current ai_stock database baseline.

Revision ID: 0001_current_baseline
Revises:
Create Date: 2026-06-14

This repository's Docker bootstrap path executes ``infra/sql/*.sql`` through
``db_schema.bootstrap``.  The Alembic baseline is kept as the root contract
entry required by ``AGENTS.md`` and delegates to the same SQL files so that the
baseline name, bootstrap SQL and schema-bootstrap container stay aligned.
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001_current_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _project_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "infra" / "sql").exists():
            return parent
    raise RuntimeError("cannot locate project root containing infra/sql")


def _sql_files() -> list[Path]:
    sql_dir = _project_root() / "infra" / "sql"
    return sorted(path for path in sql_dir.glob("*.sql") if path.name != "bootstrap_schema.sql")


def upgrade() -> None:
    bind = op.get_bind()
    for path in _sql_files():
        bind.exec_driver_sql(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError("0001_current_baseline is append-only and has no downgrade path")
