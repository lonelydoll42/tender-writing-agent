"""Run the local FastAPI adapter with ``python -m qiaowenshu_agent``."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "qiaowenshu_agent.api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
