"""FastAPI app: the hub WebSocket, the API docs, a health check, and the built Vue app.

Access (hard rule 1, owner decision 2026-10-25): the hub needs both the hub PIN and the API
token; /openapi.json and every API endpoint need the API token (X-API-Token header, or ?t=).
Open: /health, /docs (an empty shell that asks for the token) and the page's own files.

Run locally: cd backend && uv run uvicorn app.main:app --reload --port 8000
"""

import asyncio
import secrets
import uuid

from fastapi import Depends, FastAPI, HTTPException, Security, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app import config
from app.docs import DOCS_HTML
from app.logs import log
from app.schemas import Error, Hello, Ready, hub_message

HELLO_TIMEOUT_S = 10

app = FastAPI(
    title="Chongqing Family Translator",
    summary="Hub WebSocket and API. Every endpoint except /health needs the API token.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,  # served below, behind the token
)


def _matches(given: str | None, setting: str) -> bool:
    """Constant-time comparison. Nothing configured means nobody gets in."""
    expected = config.load()["access"][setting]
    return (
        bool(expected) and bool(given) and secrets.compare_digest(given.encode(), expected.encode())
    )


def pin_ok(pin: str | None) -> bool:
    return _matches(pin, "hub_pin")


def token_ok(token: str | None) -> bool:
    return _matches(token, "api_token")


def require_token(
    header: str | None = Security(APIKeyHeader(name="X-API-Token", auto_error=False)),
    query: str | None = Security(APIKeyQuery(name="t", auto_error=False)),
) -> None:
    """Declared as API keys so /docs shows which endpoints need the token."""
    if not token_ok(header or query):
        raise HTTPException(status_code=401, detail="Wrong or missing API token")


Token = Depends(require_token)


@app.get("/health")  # not /healthz: Cloud Run reserves it
def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/docs", include_in_schema=False)
def docs() -> HTMLResponse:
    return HTMLResponse(DOCS_HTML)


@app.get("/openapi.json", include_in_schema=False, dependencies=[Token])
def openapi() -> JSONResponse:
    return JSONResponse(app.openapi())


@app.websocket("/ws/hub")
async def hub_socket(ws: WebSocket) -> None:
    """The hub's channel. The first message must be `hello` with the hub PIN and API token;
    see app/schemas.py for every message."""
    await ws.accept()
    conn = uuid.uuid4().hex[:8]
    try:
        first = await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S)
        hello = hub_message.validate_json(first)
    except (TimeoutError, ValidationError, WebSocketDisconnect):
        hello = None
    if not isinstance(hello, Hello) or not (pin_ok(hello.pin) and token_ok(hello.token)):
        log("hub_rejected", conn=conn)
        if ws.client_state.name == "CONNECTED":
            await ws.send_text(Error(code="bad_credentials").model_dump_json())
            await ws.close(code=1008)
        return
    log("hub_open", conn=conn)
    await ws.send_text(Ready().model_dump_json())
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            # The pipeline arrives in step 3; until then the hub just stays connected.
    finally:
        log("hub_close", conn=conn)


# Last, so the routes above take precedence. Only present once the frontend is built.
if config.static_dir().is_dir():
    app.mount("/", StaticFiles(directory=config.static_dir(), html=True), name="static")
