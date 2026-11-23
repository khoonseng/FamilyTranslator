"""Characterization test for the Chongqing profile (language profiles, 2026-11-23).

`snapshot()` collects what the Chongqing service actually does with its languages: the exact
translation prompts, the Cloud Translation fallback, STT phrase hints and languages, the voices
for guide sentences and replies, the junk filter's verdicts and the page titles. The golden file
was generated from revision 00016's code before the profile refactor. The refactor may change
HOW these values are reached (the accessors below), never the values: tests/golden/chongqing.json
must not be edited to make this test pass.

Regenerate only for a deliberate Chongqing change:
    uv run python -m tests.test_profile_chongqing
"""

import asyncio
import json
from pathlib import Path

from app import config
from app.pipeline.text import drop_reason
from app.providers import build
from app.providers import mt as mt_module
from app.providers.translator import DIRECTIONS, fallback_targets, translation_messages

GOLDEN = Path(__file__).parent / "golden" / "chongqing.json"

CONTEXT = ["先去解放碑", "然后去洪崖洞"]

JUNK_CASES = [
    "我哋喺度等緊佢哋。",
    "嗯。",
    "嗯嗯啊。",
    "好",
    "大家跟紧我，不要走散了。",
    "这个地方唔，人很多，大家要注意安全，不要走散了。",
    "那个。",
    "對。",
    "佢哋",
    "我们现在到了洪崖洞，大家可以拍照。",
    "唔該",
    "呃，这个",
]

FALLBACK_TEXTS = {
    "guide": ["洪崖洞几点开灯？"],
    "family": ["我哋幾點走？", "When do we leave?"],
}


def _fallback_sources() -> dict:
    """The source language CloudTranslate sends for each direction's fallback targets."""
    seen = {}

    async def fake_translate(self, text, target, source):
        seen.setdefault(text, []).append([target, source])
        return ""

    async def run():
        original = mt_module.CloudTranslate._translate
        mt_module.CloudTranslate._translate = fake_translate
        try:
            client = mt_module.CloudTranslate({"location": "us-central1"}, "p", 1)
            for direction, texts in FALLBACK_TEXTS.items():
                for text in texts:
                    tasks = client.translate(text, *_targets_args(text, direction))
                    await asyncio.gather(*tasks)
        finally:
            mt_module.CloudTranslate._translate = original

    asyncio.run(run())
    return seen


def _targets_args(text: str, direction: str) -> tuple:
    """How the translator calls CloudTranslate.translate for a direction."""
    return (fallback_targets(text, direction),)


def _tts(t) -> dict:
    return {
        "endpoint": t.endpoint,
        "language": t.language,
        "voices": t.voices,
        "speaking_rate": t.speaking_rate,
        "timeout_s": t.timeout_s,
    }


def _providers(p) -> dict:
    """Accessors for the provider wiring; renamed attributes are updated here, values aren't."""
    return {
        "guide_sentence_voice": _tts(p.tts),
        "reply_voice": _tts(p.mandarin_tts),
        "stt_phrases": p.stt.phrases,
        "transcribe_prompt": p.transcribe.prompt,
        "translator": {
            "models": [
                [m.name, m.model, m.temperature, m.params, m.deadline] for m in p.translator.models
            ],
            "deadline_s": p.translator.yue_deadline_s,
            "timeout_s": p.translator.timeout_s,
        },
    }


def _directions() -> dict:
    return {
        name: {
            "prompt": d.prompt,
            "speech": d.speech,
            "other": d.other,
            "latin_is_junk": d.latin_is_junk,
        }
        for name, d in DIRECTIONS.items()
    }


def _stt_languages(cfg: dict) -> dict:
    stt = cfg["stt"]["google"]
    return {"guide": stt["guide_languages"], "family": stt["family_languages"]}


def snapshot() -> dict:
    from app.docs import DOCS_HTML
    from app.main import app

    cfg = config.load()
    return {
        "messages": {
            "guide": translation_messages("到了", CONTEXT),
            "guide_no_context": translation_messages("到了", []),
            "family": translation_messages("幾點集合？", CONTEXT, direction="family"),
        },
        "directions": _directions(),
        "fallback_targets": {
            d: {t: list(fallback_targets(t, d)) for t in texts}
            for d, texts in FALLBACK_TEXTS.items()
        },
        "fallback_sources": _fallback_sources(),
        "providers": _providers(build(cfg)),
        "stt_languages": _stt_languages(cfg),
        "junk": {s: drop_reason(s, cfg["pipeline"]) for s in JUNK_CASES},
        "titles": {
            "app": app.title,
            "docs_has_title": "Chongqing Family Translator" in DOCS_HTML,
        },
    }


def test_chongqing_behaviour_is_unchanged(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    monkeypatch.delenv("PROFILE", raising=False)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(snapshot(), ensure_ascii=False)) == golden


if __name__ == "__main__":
    import os

    os.environ.setdefault("GCP_PROJECT", "test-project")
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(
        json.dumps(snapshot(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {GOLDEN}")
