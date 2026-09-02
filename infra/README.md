# infra

状态：migrated_copy_except_env

已迁入：`sql/`、`docker/`、`docker-compose.yml`、`model-configs/`、`provider-configs/`、`seeds/`。
未迁入：`env/`（避免复制运行密钥；对照仍在 `ai_stock_source/infra/env`）。

Compose 的 `SERVICE_DIR` 已改到本树落点。Dockerfile 已改为 COPY 能力目录，不再 COPY `services/`。
未执行 compose up、未重启任何容器。
