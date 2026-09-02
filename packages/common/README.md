# packages/common

状态：`migrated`

迁入来源：`ai_stock_source/packages/common`  
迁入方式：整包复制，未改逻辑。对照源目录仍保留。

## 定位

轻量共享工具。当前只有版本号和 `health_payload`。

## 当前文件

- `pyproject.toml`：`ai-stock-common` 0.1.0，Python >=3.12，依赖 `pydantic>=2.8,<3.0`
- `src/ai_stock_common/__init__.py`：`__version__ = "0.1.0"`
- `src/ai_stock_common/health.py`：`health_payload(service, version, status="ok", extra=None)`

## 已知缺口

源码三模型 `config.py` 写了 `from ai_stock_common.settings import BaseServiceSettings`，对照包内没有 `settings.py`。迁入不补造该模块。

## 验证

```bash
python -m py_compile packages/common/src/ai_stock_common/__init__.py packages/common/src/ai_stock_common/health.py
```
