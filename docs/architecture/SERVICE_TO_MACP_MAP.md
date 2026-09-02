# 迁入映射

| 落点 | 迁入来源 | 状态 |
|---|---|---|
| `data_foundation/source-data-service` | `ai_stock_source/services/source-data-service` | migrated_copy |
| `runtime/scheduler-service` | `ai_stock_source/services/scheduler-service` | migrated_copy |
| `runtime/data-inspector-service` | `ai_stock_source/services/data-inspector-service` | migrated_copy |
| `research/research-service` | `ai_stock_source/services/research-service` | migrated_copy |
| `research/research-center-service` | `ai_stock_source/services/research-center-service` | migrated_copy |
| `frontend/shence-frontend-service` | `ai_stock_source/services/shence-frontend-service` | migrated_copy |
| `intelligence/hot-candidates-service` | `ai_stock_source/services/models_services/hot-candidates-service` | migrated_copy |
| `intelligence/candidate-memory-service` | `ai_stock_source/services/models_services/candidate-memory-service` | migrated_copy |
| `intelligence/ambush-watchlist-service` | `ai_stock_source/services/models_services/ambush-watchlist-service` | migrated_copy |
| `intelligence/t-board-relay-service` | `ai_stock_source/services/models_services/t-board-relay-service` | migrated_copy |
| `packages/common` | `ai_stock_source/packages/common` | migrated |
| `packages/db-schema` | `ai_stock_source/packages/db-schema` | migrated_package_only |
| `infra` | `ai_stock_source/infra` | migrated_copy_except_env |
| `scripts` | `ai_stock_source/scripts` | migrated_copy |
| `macp/` | 无 | new_overlay |
| `intelligence/evaluation` | 无 | new_overlay |
| `packages/macp-contracts` | 无 | new_overlay |

对照源完整保留。本树 Compose 路径已改，**未**对运行容器执行切换。
`infra/env` 未复制。
