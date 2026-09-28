"""Serve Octopoda's graphical dashboard against a local Octopoda API.

Octopoda's bundled React dashboard is cloud-oriented: when opened via an IP
address it points at the hosted API and asks the user to register.  This app
serves the same UI on ``localhost``, injects the local development key, and
proxies its ``/v1`` requests to the project's local Octopoda server.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from starlette.background import BackgroundTask


DEFAULT_API_URL = "http://127.0.0.1:8741"
DEFAULT_LOCAL_KEY = "local-dev"
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _dashboard_static_dir() -> Path:
    """Locate the React bundle installed by the ``octopoda`` package."""
    try:
        import synrix_runtime.dashboard as dashboard_package
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Octopoda's dashboard assets are unavailable. Install "
            "`octopoda[server]` in the active Python environment."
        ) from exc

    static_dir = Path(dashboard_package.__file__).parent / "static"
    if not static_dir.is_dir():
        raise RuntimeError(f"Octopoda dashboard assets were not found at {static_dir}.")
    return static_dir


STATIC_DIR = _dashboard_static_dir()
app = FastAPI(title="UCust.AI Local Octopoda Dashboard", docs_url=None, redoc_url=None)


def _api_url() -> str:
    return os.getenv("OCTOPODA_DASHBOARD_API_URL", DEFAULT_API_URL).rstrip("/")


def _local_key() -> str:
    return os.getenv("OCTOPODA_API_KEY") or DEFAULT_LOCAL_KEY


def _dashboard_html() -> str:
    """Return the bundled SPA with local-only authentication preconfigured."""
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    bootstrap = (
        "<script>"
        f"localStorage.setItem('octopoda_api_key', {json.dumps(_local_key())});"
        "localStorage.setItem('octopoda_tenant_id', 'dev');"
        "localStorage.setItem('octopoda_email', 'dev@ucust.local');"
        "</script>"
    )
    return index_html.replace("</head>", f"{bootstrap}</head>", 1)


def _safe_static_file(path: str) -> Path | None:
    """Resolve an existing static file without allowing path traversal."""
    candidate = (STATIC_DIR / path).resolve()
    if not candidate.is_relative_to(STATIC_DIR.resolve()) or not candidate.is_file():
        return None
    return candidate


def _proxy_request_headers(request: Request) -> dict[str, str]:
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS and name.lower() != "host"
    }
    if "authorization" not in [k.lower() for k in headers]:
        headers["authorization"] = f"Bearer {_local_key()}"
    return headers


def _proxy_response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
    }


@app.api_route(
    "/v1/{path:path}",
    methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
)
async def proxy_octopoda_api(path: str, request: Request) -> StreamingResponse:
    """Forward dashboard calls to the local Octopoda REST API."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=None))
    upstream_request = client.build_request(
        request.method,
        f"{_api_url()}/v1/{path}",
        params=request.query_params,
        content=await request.body(),
        headers=_proxy_request_headers(request),
    )
    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=503,
            detail=(
                f"Local Octopoda API is unavailable at {_api_url()}. "
                "Start it on port 8741 before opening the dashboard."
            ),
        ) from exc

    async def response_body() -> AsyncIterator[bytes]:
        async for chunk in upstream_response.aiter_raw():
            yield chunk

    return StreamingResponse(
        response_body(),
        status_code=upstream_response.status_code,
        headers=_proxy_response_headers(upstream_response),
        background=BackgroundTask(client.aclose),
    )


@app.get("/{path:path}", response_class=HTMLResponse, response_model=None)
async def dashboard(path: str) -> HTMLResponse | FileResponse:
    """Serve the React SPA and its static assets."""
    if path:
        static_file = _safe_static_file(path)
        if static_file is not None:
            return FileResponse(static_file)
    return HTMLResponse(_dashboard_html())

