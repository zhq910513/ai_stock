from __future__ import annotations

import uvicorn

from source_data_service.api import app


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8041)
