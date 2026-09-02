# packages/db-schema

状态：`migrated_package_only`

迁入来源：`ai_stock_source/packages/db-schema`  
依赖 SQL：已复制到 `infra/sql/`（28 个文件）  
未执行：`python -m db_schema.bootstrap`、清库、替换 schema-bootstrap 容器。

## 定位

Docker schema-bootstrap 安装本包后执行 `python -m db_schema.bootstrap`。
bootstrap 按文件名顺序执行 `infra/sql/*.sql`，跳过 `bootstrap_schema.sql`。

## 当前文件

- `src/db_schema/bootstrap.py`
- `alembic/versions/0001_current_baseline.py`（无 downgrade，委托同一批 SQL）
- `pyproject.toml`：依赖 `psycopg[binary]>=3.2,<4.0`

## 禁止

未解锁 `schema-bootstrap` / Postgres 前，不得对运行库执行 bootstrap。
