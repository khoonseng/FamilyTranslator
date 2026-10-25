import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config, main


@pytest.fixture
def client(monkeypatch):
    cfg = config.load()
    monkeypatch.setitem(cfg["hub"], "pin", "2468")
    return TestClient(main.app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "ok"


def test_hub_with_the_right_pin_is_ready(client):
    with client.websocket_connect("/ws/hub") as ws:
        ws.send_json({"type": "hello", "pin": "2468"})
        assert ws.receive_json() == {"type": "ready"}


@pytest.mark.parametrize(
    "first",
    [
        {"type": "hello", "pin": "0000"},
        {"type": "mode", "mode": "guide"},  # anything before hello
        {"type": "hello"},  # malformed
    ],
)
def test_hub_without_the_right_pin_is_closed(client, first):
    with client.websocket_connect("/ws/hub") as ws:
        ws.send_json(first)
        assert ws.receive_json()["code"] == "bad_pin"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_no_pin_configured_lets_nobody_in(client, monkeypatch):
    monkeypatch.setitem(config.load()["hub"], "pin", "")
    assert not main.pin_ok("")
    assert not main.pin_ok("2468")
