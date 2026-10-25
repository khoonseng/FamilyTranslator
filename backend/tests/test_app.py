import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config, main
from tests.fakes import fake_providers

PIN, TOKEN = "24681357", "97531864"


@pytest.fixture
def client(monkeypatch):
    access = config.load()["access"]
    monkeypatch.setitem(access, "hub_pin", PIN)
    monkeypatch.setitem(access, "api_token", TOKEN)
    monkeypatch.setattr(main, "providers", fake_providers)  # no network in tests
    return TestClient(main.app)


def test_health_is_open(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"


def test_docs_page_is_a_shell_and_the_spec_needs_the_token(client):
    page = client.get("/docs")
    assert page.status_code == 200
    assert "X-API-Token" in page.text and "/ws/hub" not in page.text
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/openapi.json", headers={"X-API-Token": "wrong"}).status_code == 401
    spec = client.get("/openapi.json", headers={"X-API-Token": TOKEN})
    assert spec.status_code == 200
    assert "/health" in spec.json()["paths"]


def test_hub_with_pin_and_token_is_ready(client):
    with client.websocket_connect("/ws/hub") as ws:
        ws.send_json({"type": "hello", "pin": PIN, "token": TOKEN})
        assert ws.receive_json() == {"type": "ready"}


@pytest.mark.parametrize(
    "first",
    [
        {"type": "hello", "pin": PIN, "token": "wrong"},
        {"type": "hello", "pin": "wrong", "token": TOKEN},
        {"type": "hello", "pin": PIN},  # no token
        {"type": "mode", "mode": "guide"},  # anything before hello
    ],
)
def test_hub_without_both_credentials_is_closed(client, first):
    with client.websocket_connect("/ws/hub") as ws:
        ws.send_json(first)
        assert ws.receive_json()["code"] == "bad_credentials"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_nothing_configured_lets_nobody_in(client, monkeypatch):
    access = config.load()["access"]
    monkeypatch.setitem(access, "hub_pin", "")
    monkeypatch.setitem(access, "api_token", "")
    assert not main.pin_ok("") and not main.pin_ok(PIN)
    assert not main.token_ok("") and not main.token_ok(TOKEN)


def test_typed_text_comes_back_translated_with_its_clip(client):
    with client.websocket_connect("/ws/hub") as ws:
        ws.send_json({"type": "hello", "pin": PIN, "token": TOKEN})
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "text", "text": "我们在门口集合。"})
        sentence = ws.receive_json()
        assert (sentence["type"], sentence["yue"]) == ("sentence", "粵:我们在门口集合。")
        clip = ws.receive_json()
        assert clip["type"] == "clip"
        assert len(ws.receive_bytes()) == clip["bytes"]


def test_bad_message_is_reported_not_fatal(client):
    with client.websocket_connect("/ws/hub") as ws:
        ws.send_json({"type": "hello", "pin": PIN, "token": TOKEN})
        ws.receive_json()
        ws.send_json({"type": "mode", "mode": "family"})  # phase 2, not in the MVP
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "text", "text": "好。"})
        assert ws.receive_json()["type"] == "sentence"
