"""Language profiles (2026-11-23): PROFILE picks an overlay merged over config.yaml."""

import pytest

from app import config


@pytest.fixture
def profile(monkeypatch):
    """Set PROFILE for one test; caches are cleared before and after."""

    def use(name):
        if name is None:
            monkeypatch.delenv("PROFILE", raising=False)
        else:
            monkeypatch.setenv("PROFILE", name)
        config.clear_caches()
        return config.load()

    yield use
    monkeypatch.delenv("PROFILE", raising=False)
    config.clear_caches()


def test_no_profile_is_chongqing(profile):
    assert profile(None)["profile"]["name"] == "chongqing"
    assert profile("chongqing")["profile"]["name"] == "chongqing"


def test_chongqing_is_config_yaml_untouched(profile):
    assert profile(None) == profile("chongqing")


def test_an_unknown_profile_fails_at_startup(profile):
    with pytest.raises(RuntimeError, match="Unknown PROFILE"):
        profile("atlantis")


def test_merge_merges_dicts_and_replaces_lists_and_values():
    base = {"a": {"b": 1, "c": [1, 2]}, "d": 1}
    overlay = {"a": {"c": [3]}, "d": None, "e": 2}
    assert config._merge(base, overlay) == {"a": {"b": 1, "c": [3]}, "d": None, "e": 2}
    assert base == {"a": {"b": 1, "c": [1, 2]}, "d": 1}  # the base is not changed
