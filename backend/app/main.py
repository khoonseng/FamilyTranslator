"""FastAPI app: the hub WebSocket, a health check, and the built Vue app as static files.

Run locally: cd backend && uv run uvicorn app.main:app --reload --port 8000
"""

import asyncio
import secrets
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app import config
from app.logs import log
from app.schemas import Error, Hello, Ready, hub_message

HELLO_TIMEOUT_S = 10

app = FastAPI(title="Chongqing Family Translator", docs_url=None, redoc_url=None)


def pin_ok(pin: str) -> bool:
    """Hard rule 1: only a phone with the hub PIN may trigger provider calls. No PIN configured
    means nobody gets in."""
    expected = config.load()["hub"]["pin"]
    return bool(expected) and secrets.compare_digest(pin.encode(), expected.encode())


@app.get("/health")  # not /healthz: Cloud Run reserves it
def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.websocket("/ws/hub")
async def hub_socket(ws: WebSocket) -> None:
    await ws.accept()
    conn = uuid.uuid4().hex[:8]
    try:
        first = await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S)
        hello = hub_message.validate_json(first)
    except (TimeoutError, ValidationError, WebSocketDisconnect):
        hello = None
    if not isinstance(hello, Hello) or not pin_ok(hello.pin):
        log("hub_rejected", conn=conn)
        if ws.client_state.name == "CONNECTED":
            await ws.send_text(Error(code="bad_pin").model_dump_json())
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
