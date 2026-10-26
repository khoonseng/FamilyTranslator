import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config, main
from app.storage.store import MemoryStore, RoomStore
from tests.fakes import fake_providers

PIN, TOKEN, ROOM = "24681357", "97531864", "room-k7Q2"


@pytest.fixture
def client(monkeypatch):
    access = config.load()["access"]
    monkeypatch.setitem(access, "hub_pin", PIN)
    monkeypatch.setitem(access, "api_token", TOKEN)
    monkeypatch.setenv("ROOM_TOKEN", ROOM)  # the join link's token on first start
    monkeypatch.setattr(main, "store", lambda: RoomStore(MemoryStore()))
    monkeypatch.setattr(main, "providers", fake_providers)  # no network in tests
    monkeypatch.setattr(main, "_room", None)  # a fresh room per test
    return TestClient(main.app)


def test_health_is_open(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"


def test_listener_addresses_serve_the_app(client, monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<div id=app></div>")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    for path in ("/join", "/listen"):
        page = client.get(path)
        assert page.status_code == 200
        assert page.text == "<div id=app></div>"
        assert page.headers["cache-control"] == "no-cache"


def test_listener_addresses_without_a_built_app_are_not_found(client, monkeypatch, tmp_path):
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    assert client.get("/listen").status_code == 404


def test_docs_page_is_a_shell_and_the_spec_needs_the_token(client):
    page = client.get("/docs")
    assert page.status_code == 200
    assert "X-API-Token" in page.text and "/ws/room" not in page.text
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/openapi.json", headers={"X-API-Token": "wrong"}).status_code == 401
    spec = client.get("/openapi.json", headers={"X-API-Token": TOKEN})
    assert spec.status_code == 200
    assert "/health" in spec.json()["paths"]


HUB = {"type": "hello", "role": "hub", "pin": PIN, "token": TOKEN}
LISTENER = {"type": "hello", "role": "listener", "room": ROOM}
HOST = {"type": "hello", "role": "listener", "pin": PIN, "token": TOKEN}  # no join link


def first_non_status(ws):
    while (message := ws.receive_json())["type"] == "hub_status":
        pass
    return message


@pytest.mark.parametrize(
    "hello, ready",
    [
        (HUB, {"role": "hub", "host": True}),
        (LISTENER, {"role": "listener", "host": False}),
        (HOST, {"role": "listener", "host": True}),
    ],
)
def test_each_role_with_the_right_credentials_is_ready(client, hello, ready):
    with client.websocket_connect("/ws/room") as ws:
        ws.send_json(hello)
        message = ws.receive_json()
        assert message["type"] == "ready"
        assert {k: message[k] for k in ready} == ready


@pytest.mark.parametrize(
    "first",
    [
        HUB | {"token": "wrong"},
        HUB | {"pin": "wrong"},
        {"type": "hello", "role": "hub", "room": ROOM},  # a room token doesn't make a hub
        LISTENER | {"room": "wrong"},
        HOST | {"pin": "wrong"},  # host credentials offered must be right
        HOST | {"pin": "wrong", "room": ROOM},  # even alongside a good join link
        {"type": "mode", "mode": "guide"},  # anything before hello
    ],
)
def test_wrong_credentials_are_refused(client, first):
    with client.websocket_connect("/ws/room") as ws:
        ws.send_json(first)
        assert ws.receive_json()["code"] == "bad_credentials"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_nothing_configured_lets_nobody_in(client, monkeypatch):
    access = config.load()["access"]
    for key in ("hub_pin", "api_token"):
        monkeypatch.setitem(access, key, "")
    assert not main.pin_ok("") and not main.pin_ok(PIN)
    assert not main.token_ok("") and not main.token_ok(TOKEN)


def test_typed_text_reaches_a_listener_with_its_clip(client):
    with client.websocket_connect("/ws/room") as hub, client.websocket_connect("/ws/room") as ear:
        hub.send_json(HUB)
        assert hub.receive_json()["role"] == "hub"
        ear.send_json(LISTENER)
        assert ear.receive_json()["role"] == "listener"
        hub.send_json({"type": "text", "text": "我们在门口集合。"})
        sentence = first_non_status(ear)
        assert (sentence["type"], sentence["yue"]) == ("sentence", "粵:我们在门口集合。")
        clip = ear.receive_json()
        assert clip["type"] == "clip"
        assert len(ear.receive_bytes()) == clip["bytes"]


def test_bad_message_is_reported_not_fatal(client):
    with client.websocket_connect("/ws/room") as ws:
        ws.send_json(HUB)
        ws.receive_json()
        ws.send_json({"type": "mode", "mode": "family"})  # phase 2, not built yet
        assert first_non_status(ws)["code"] == "bad_message"
        ws.send_json({"type": "text", "text": "好的我们走吧。"})
        assert first_non_status(ws)["type"] == "sentence"
