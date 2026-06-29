# db-schema README

本文件是 `packages/db-schema` 目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准。

## 定位

`db-schema` 是当前本地 Docker 闭环的数据库 schema bootstrap 包。schema-bootstrap 容器安装本包后执行：

```text
python -m db_schema.bootstrap
```

当前 bootstrap 执行 `infra/sql/*.sql`，并跳过 `infra/sql/bootstrap_schema.sql`。`infra/sql/bootstrap_schema.sql` 仍是当前运行基线渲染文件和审计事实之一。

## 当前文件

- `src/db_schema/bootstrap.py`：定位项目根目录，按文件名顺序执行 `infra/sql/*.sql`。
- `alembic/versions/0001_current_baseline.py`：AGENTS 要求的当前 Alembic 基线入口；它委托执行同一批 `infra/sql/*.sql`，保证基线名称、Docker bootstrap 和 SQL 文件序列一致。
- `infra/sql/0022_t_board_relay_decision_schema_v1.sql`：模型四 `decision_t_relay` / `research_t_relay` 生产表基线。
- `infra/sql/0025_source_data_foundation_indexes_v1.sql`：首次上线 source 底座读路径索引基线，只新增索引和注释，不写业务事实。
- `infra/sql/0026_research_model_payload_assembly_audit_v1.sql`：`research_model_payload_assembler_v1` append-only 组装审计表和索引，不写模型事实。
- `infra/sql/0027_research_model_execution_audit_v1.sql`：`research_model_execution_v1` append-only 执行审计表和索引；同时允许 `decision_memory.memory_entity_v1.memory_age_days` 为 `NULL`，用于缺交易日历年龄时保留 `blocked_data_gap`。
- `pyproject.toml`：包声明和 `psycopg[binary]` 依赖。

## 运行要求

环境变量：

```text
AI_STOCK_DATABASE_URL=postgresql://...
```

Docker compose 中 `schema-bootstrap` 依赖 `postgres` healthy 后运行。本包不保存业务事实，不执行 provider probe，不启动服务。

## 迁移口径

当前有效入口：

```text
packages/db-schema/alembic/versions/0001_current_baseline.py
infra/sql/bootstrap_schema.sql
infra/sql/0002_source_decision_hot_refactor.sql ... infra/sql/0027_research_model_execution_audit_v1.sql
```

`0001_current_baseline.py` 无 downgrade；当前项目不做旧数据迁移和旧字段兼容。新增 schema 或索引时应追加新的 `infra/sql/NNNN_*.sql`，同步更新 `infra/sql/bootstrap_schema.sql` 产物和相关服务 README / `DATA_ASSETS.md`。模型四当前表包括 `decision_t_relay.t_board_day1_candidate_v1`、`t_board_day2_watch_snapshot_v1`、`t_board_day2_entry_trigger_v1`、`t_board_post_entry_monitor_v1`、`t_board_day3_exit_decision_v1`、`t_board_outcome_label_v1`、`t_board_game_hypothesis_snapshot_v1` 和 `research_t_relay.t_board_research_sample_v1`。

## 2026-06-18 运行态应用记录

用户要求“继续闭环”后，当前 Postgres 容器 `af846a793868` 已单独执行：

```text
infra/sql/0027_research_model_execution_audit_v1.sql
sha256=05D782E6A7D63FD23EF797C1AEF69EFC280C357A7A0B25FFEB29E5CB5C86EC17
```

执行结果：

```text
CREATE SCHEMA
ALTER TABLE
CREATE TABLE
CREATE INDEX x4
COMMENT x2
```

验证结果：

```text
to_regclass('governance.research_model_execution_audit_v1') = governance.research_model_execution_audit_v1
decision_memory.memory_entity_v1.memory_age_days is_nullable = YES
indexes:
  idx_research_model_execution_task_day_v1
  idx_research_model_execution_owner_status_v1
  idx_research_model_execution_symbol_day_v1
  idx_research_model_execution_payload_hash_v1
constraints:
  ck_research_model_execution_contract_v1
  ck_research_model_execution_status_v1
  research_model_execution_audit_v1_pkey
```

本次未执行全量 bootstrap、未清库、未重启 Postgres；`schema-bootstrap` 镜像/容器未替换。后续新环境仍应通过 `infra/sql/*.sql` 顺序 bootstrap 获得同一 schema。

## 验证

语法自检：

```bash
python -m py_compile packages/db-schema/src/db_schema/bootstrap.py packages/db-schema/alembic/versions/0001_current_baseline.py
```

Docker/Postgres 验证由：

```bash
docker compose -f infra/docker-compose.yml up schema-bootstrap
```

或完整核心闭环验收覆盖。
