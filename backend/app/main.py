"""FastAPI app: the hub WebSocket, the API docs, a health check, and the built Vue app.

Access (hard rule 1, owner decisions 2026-10-25/26): the hub needs both the hub PIN and the
API token; a listener needs the room token from its join link, and a host listener also the PIN
and API token; /openapi.json and every API endpoint need the API token (X-API-Token header, or
?t=).
Open: /health, /docs (an empty shell that asks for the token) and the page's own files, also
served at /join (the join link, /join#<room token>: the phone never sends what follows the #)
/listen and /host.

Run locally: cd backend && uv run uvicorn app.main:app --reload --port 8000
"""

import asyncio
import secrets
import uuid
from functools import cache

from fastapi import Depends, FastAPI, HTTPException, Security, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app import config
from app.docs import DOCS_HTML
from app.logs import log
from app.providers import Providers
from app.providers import build as build_providers
from app.rooms.room import Room
from app.schemas import Error, Hello, phone_message
from app.storage.store import GcsStore, MemoryStore, RoomStore

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


@cache
def providers() -> Providers:
    """Built once per server, on the first hub connection (tests replace this)."""
    return build_providers()


_room: Room | None = None


async def room() -> Room:
    """The one fixed room, created on the first connection (tests reset `_room`)."""
    global _room
    if _room is None:
        _room = Room(providers(), config.load(), store())
        await _room.start()
    return _room


@cache
def store() -> RoomStore:
    """The private bucket on Cloud Run; in memory when no bucket is set (tests, local runs)."""
    bucket = config.load()["storage"]["bucket"]
    return RoomStore(GcsStore(bucket, config.project()) if bucket else MemoryStore())


async def room_ok(token: str | None) -> bool:
    """The join link's token, which host phones can renew (owner decision 2026-10-26)."""
    expected = (await room()).join_token
    return (
        bool(expected) and bool(token) and secrets.compare_digest(token.encode(), expected.encode())
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


def _app_page() -> FileResponse:
    """The Vue app reads these addresses itself. The join link's token never reaches the
    server here: it follows the #, and the page sends it in its WebSocket hello."""
    index = config.static_dir() / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


@app.get("/join", include_in_schema=False)
def join_page() -> FileResponse:
    return _app_page()


@app.get("/listen", include_in_schema=False)
def listen_page() -> FileResponse:
    return _app_page()


@app.get("/host", include_in_schema=False)
def host_page() -> FileResponse:
    """The owner's and wife's listener page; it signs in with the PIN and API token."""
    return _app_page()


@app.websocket("/ws/room")
async def room_socket(ws: WebSocket) -> None:
    """Every phone's channel: the hub and every listener. The first message must be `hello`
    (see app/schemas.py): the hub sends the hub PIN and API token; a listener sends the room
    token from its join link, and a host listener also the PIN and API token."""
    await ws.accept()
    conn = uuid.uuid4().hex[:8]
    try:
        first = await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S)
        hello = phone_message.validate_json(first)
    except (TimeoutError, ValidationError, WebSocketDisconnect):
        hello = None
    host = isinstance(hello, Hello) and pin_ok(hello.pin) and token_ok(hello.token)
    if not isinstance(hello, Hello):
        allowed = False
    elif hello.role == "hub":
        allowed = host
    elif hello.pin or hello.token:  # a host listener (signed in through /host): both must be right
        allowed = host
    else:  # a family listener: the join link's token
        allowed = await room_ok(hello.room)
    if not allowed:
        log("room_rejected", conn=conn)
        if ws.client_state.name == "CONNECTED":
            await ws.send_text(Error(code="bad_credentials").model_dump_json())
            await ws.close(code=1008)
        return
    the_room = await room()
    peer = the_room.join(
        conn, hello.role, host, hello.day, hello.last_id, ws.send_text, ws.send_bytes, ws.close,
        takeover=hello.takeover,
    )  # fmt: skip
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                the_room.on_audio(peer, message["bytes"])
            elif message.get("text") is not None:
                try:
                    parsed = phone_message.validate_json(message["text"])
                except ValidationError:
                    peer.put(Error(code="bad_message"))
                    continue
                await the_room.handle(peer, parsed)
    finally:
        await the_room.leave(peer)


# Last, so the routes above take precedence. Only present once the frontend is built.
if config.static_dir().is_dir():
    app.mount("/", StaticFiles(directory=config.static_dir(), html=True), name="static")
