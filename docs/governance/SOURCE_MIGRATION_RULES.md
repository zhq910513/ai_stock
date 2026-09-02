# 源码迁入规则

`ai_stock_source/` 是只读对照，不是长期开发树。

## 允许

- 按 `docs/architecture/SERVICE_TO_MACP_MAP.md` 整包迁入对应落点。
- 迁入时只改路径、Compose `SERVICE_DIR`、文档引用。
- 迁入后用原测试与 healthz 验收。

## 禁止

- 在落点手写平行 source / scheduler / owner / inspector。
- 借迁入重写模型公式、采集链路或调度语义。
- 绕过 fetch orchestration 或直接读 `raw_*`。
- 删除 append-only 事实或 task store。

## 流程

```text
按服务解锁
-> 整包复制到落点
-> 修正路径
-> 运行原测试 / healthz
-> 落点 README 标 migrated
-> 对照源目录保留到该包拍板
```
