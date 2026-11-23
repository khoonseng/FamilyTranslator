"""Load config.yaml and the profile's glossary, with ${VAR} replaced from the environment / .env.

Language profiles (owner decision 2026-11-23): the `PROFILE` environment variable picks the
language pair a service runs, one per Cloud Run service. `config.yaml` is the Chongqing profile
(Mandarin guide, Cantonese/English family) and the default; another profile is an overlay,
`profiles/<name>.yaml`, deep-merged over it (dicts merge, lists and values replace)."""

import os
import re
from functools import cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent  # backend/

_ENV_VAR = re.compile(r"\$\{(\w+)\}")

DEFAULT_PROFILE = "chongqing"


def _expand(value):
    if isinstance(value, str):
        return _ENV_VAR.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _merge(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def profile_name() -> str:
    return os.environ.get("PROFILE") or DEFAULT_PROFILE


@cache
def load() -> dict:
    load_dotenv(ROOT / ".env")  # local development only; Cloud Run sets the environment
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    name = profile_name()
    if name != DEFAULT_PROFILE:
        overlay = ROOT / "profiles" / f"{name}.yaml"
        if not overlay.is_file():
            raise RuntimeError(f"Unknown PROFILE {name!r}: no {overlay}")
        with open(overlay, encoding="utf-8") as f:
            cfg = _merge(cfg, yaml.safe_load(f) or {})
    if cfg["profile"]["name"] != name:
        raise RuntimeError(f"PROFILE {name!r} loaded a profile named {cfg['profile']['name']!r}")
    return _expand(cfg)


def clear_caches() -> None:
    """Forget the loaded config, glossary and prompts (tests that switch PROFILE)."""
    load.cache_clear()
    glossary.cache_clear()
    prompt.cache_clear()


@cache
def glossary() -> list[dict]:
    with open(ROOT / load()["profile"]["glossary"], encoding="utf-8") as f:
        return yaml.safe_load(f)["terms"] or []


def glossary_text() -> str:
    """Glossary as prompt lines: Mandarin = Cantonese = English."""
    return "\n".join(f"- {t['zh']} = {t['yue']} = {t['en']}" for t in glossary())


@cache
def prompt(name: str) -> str:
    """A prompt by its path under prompts/, without .md (e.g. `cantonese-guide/guide_to_family`)."""
    return (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def project() -> str:
    value = load()["gcp"]["project"]
    if not value:
        raise RuntimeError("GCP_PROJECT is not set")
    return value


def static_dir() -> Path:
    """The built Vue app: /app/static in the container, frontend/dist when run locally."""
    return Path(os.environ.get("STATIC_DIR", ROOT.parent / "frontend" / "dist"))
