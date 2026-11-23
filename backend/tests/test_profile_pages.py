"""The built page per language profile (2026-11-23): Chongqing serves it untouched; another
profile names itself in it and sets its language, title and install name."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, main
from tests.test_app import client  # noqa: F401 - the fixture

INDEX = """<!doctype html>
<html lang="zh-HK">
  <head>
    <meta name="profile" content="chongqing" />
    <title>Chongqing Translator</title>
  </head>
  <body><div id="app"></div></body>
</html>
"""
MANIFEST = {"name": "Chongqing Family Translator", "short_name": "Translator", "lang": "zh-HK"}
SWAPPED = {
    "name": "cantonese-guide",
    "page": {"lang": "zh-CN", "title": "Guide Translator", "install_name": "Guide Translator"},
}


@pytest.fixture
def built(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "manifest.webmanifest").write_text(json.dumps(MANIFEST), encoding="utf-8")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    return tmp_path


def test_chongqing_has_no_profile_routes():
    assert config.load()["profile"]["page"] is None
    paths = {getattr(r, "path", None) for r in main.app.routes}
    assert "/manifest.webmanifest" not in paths and "/index.html" not in paths


def test_chongqing_serves_the_built_page_byte_for_byte(client, built):  # noqa: F811
    for path in ("/join", "/listen", "/host", "/mictest"):
        assert client.get(path).content == INDEX.encode()


def test_rewrite_index_names_the_profile_and_sets_lang_and_title():
    page = main.rewrite_index(INDEX, SWAPPED)
    assert '<meta name="profile" content="cantonese-guide"' in page
    assert '<html lang="zh-CN">' in page
    assert "<title>Guide Translator</title>" in page
    assert page.count("chongqing") == 0


def test_another_profile_rewrites_every_address(client, built, monkeypatch):  # noqa: F811
    profile = config.load()["profile"]
    monkeypatch.setitem(profile, "name", SWAPPED["name"])
    monkeypatch.setitem(profile, "page", SWAPPED["page"])
    expected = main.rewrite_index(INDEX, SWAPPED)
    for path in ("/join", "/listen", "/host", "/mictest"):
        response = client.get(path)
        assert response.text == expected
        assert response.headers["cache-control"] == "no-cache"
    app = FastAPI()
    app.include_router(main.profile_pages)
    pages = TestClient(app)
    for path in ("/", "/index.html"):
        assert pages.get(path).text == expected
    manifest = pages.get("/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.json() == MANIFEST | {"name": "Guide Translator", "lang": "zh-CN"}
