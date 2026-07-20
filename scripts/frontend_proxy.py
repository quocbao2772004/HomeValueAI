from __future__ import annotations

import os
from pathlib import Path
import sys
import asyncio

import requests
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.env import load_app_env  # noqa: E402
from src.security import internal_proxy_key  # noqa: E402

FRONTEND_DIR = ROOT / "frontend"
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

app = FastAPI(title="HomeValue Frontend Proxy")


def _backend_base() -> str:
    return os.getenv("FRONTEND_PROXY_API_BASE", "http://127.0.0.1:1108").rstrip("/")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def api_proxy(path: str, request: Request):
    target = f"{_backend_base()}/{path}"
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
    }
    headers["X-Internal-Proxy-Key"] = internal_proxy_key()
    if request.client:
        headers.setdefault("X-Forwarded-For", request.client.host)

    upstream = await asyncio.to_thread(
        requests.request,
        request.method,
        target,
        params=list(request.query_params.multi_items()),
        data=body,
        headers=headers,
        timeout=_int_env("FRONTEND_PROXY_TIMEOUT_SECONDS", 60),
    )
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    load_app_env()
    uvicorn.run(
        "scripts.frontend_proxy:app",
        host=os.getenv("FRONTEND_HOST", "0.0.0.0"),
        port=_int_env("FRONTEND_PORT", 2707),
        app_dir=str(ROOT),
    )
