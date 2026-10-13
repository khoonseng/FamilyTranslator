"""Load config.yaml and glossary.yaml, with ${VAR} replaced from the environment / .env."""

import os
import re
from functools import cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "recordings"
OUT = ROOT / "out"

_ENV_VAR = re.compile(r"\$\{(\w+)\}")


def _expand(value):
    if isinstance(value, str):
        return _ENV_VAR.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@cache
def load() -> dict:
    load_dotenv(ROOT / ".env")
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return _expand(yaml.safe_load(f))


@cache
def glossary() -> list[dict]:
    with open(ROOT / "glossary.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["terms"]


def glossary_text() -> str:
    """Glossary as prompt lines: Mandarin = Cantonese = English."""
    return "\n".join(f"- {t['zh']} = {t['yue']} = {t['en']}" for t in glossary())


def prompt(name: str) -> str:
    return (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def project() -> str:
    value = load()["gcp"]["project"]
    if not value:
        raise RuntimeError("GCP_PROJECT is not set (bakeoff/.env)")
    return value
