"""The cantonese-guide language profile (2026-11-23): the Chongqing roles swapped. A Cantonese
guide; a family that hears Mandarin and replies in Mandarin or English."""

import asyncio
import copy
import json

import pytest

from app import config
from app.pipeline.session import Pipeline
from app.pipeline.text import drop_reason
from app.providers import build
from app.providers.translator import (
    DIRECTION_NAMES,
    direction_of,
    fallback_source,
    fallback_targets,
    translation_messages,
)
from app.schemas import Mode, SegmentEnd, SegmentStart
from tests.fakes import FakeStt, FakeTts, fake_providers

ONE_SECOND = bytes(32_000)


@pytest.fixture
def swapped(monkeypatch):
    monkeypatch.setenv("PROFILE", "cantonese-guide")
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    config.clear_caches()
    yield config.load()
    monkeypatch.delenv("PROFILE")
    config.clear_caches()


def test_the_profile_loads_over_chongqing(swapped):
    assert swapped["profile"]["name"] == "cantonese-guide"
    assert swapped["stt"]["google"]["guide_languages"] == ["yue-Hant-HK", "cmn-Hans-CN"]
    assert swapped["stt"]["google"]["family_languages"] == ["cmn-Hans-CN", "en-US"]
    # Untouched settings still come from config.yaml.
    assert swapped["translation"]["order"] == ["gemini", "qwen", "gpt-oss"]
    assert swapped["tts"]["family_voice"]["endpoint"] == "texttospeech.googleapis.com"
    assert swapped["profile"]["page"]["lang"] == "zh-CN"


def test_each_prompt_exists_and_asks_for_its_direction_keys(swapped):
    for name in DIRECTION_NAMES:
        way = direction_of(name)
        prompt = config.prompt(way.prompt)
        assert f'"{way.speech}"' in prompt and f'"{way.other}"' in prompt
    assert (direction_of("guide").speech, direction_of("family").speech) == ("zh_hans", "yue")


def test_the_prompts_fill_in_an_empty_glossary_and_context(swapped):
    system, user = translation_messages("我哋而家去食飯。", ["先去碼頭"])
    assert user["content"] == "我哋而家去食飯。"
    assert "Cantonese-speaking tour guide" in system["content"]
    assert "(none)" in system["content"] and "- 先去碼頭" in system["content"]
    assert "{glossary}" not in system["content"] and "{context}" not in system["content"]
    assert "Chongqing" not in system["content"]


def test_cloud_translation_codes_are_swapped(swapped):
    assert (fallback_targets("我哋幾點走？", "guide"), fallback_source("guide")) == (
        ("zh-CN", "en"),
        "",
    )
    assert fallback_targets("我们几点走？", "family") == ("yue", "en")  # Mandarin: English
    assert fallback_targets("When do we leave?", "family") == ("yue", "zh-CN")  # English


def test_voices_and_hints_are_swapped(swapped):
    p = build(swapped)
    assert (p.family_tts.language, p.family_tts.voices[0]) == ("cmn-CN", "cmn-CN-Chirp3-HD-Kore")
    assert (p.guide_tts.language, p.guide_tts.voices[0]) == ("yue-HK", "yue-HK-Chirp3-HD-Despina")
    assert p.stt.phrases == [] and p.transcribe.prompt is None  # empty glossary for now


def test_the_junk_filter_keeps_the_cantonese_guide(swapped):
    pipe = swapped["pipeline"]
    assert drop_reason("我哋而家喺度等緊大家。", pipe) is None  # layer 2 is off
    assert drop_reason("嗯。", pipe) == "filler"
    assert drop_reason("好", pipe) == "short"


async def test_guide_speech_and_replies_use_the_swapped_languages_and_voices(swapped):
    stt = FakeStt()
    providers = fake_providers(
        stt=stt,
        family_tts=FakeTts(voice="cmn-CN-Chirp3-HD-Kore"),
        guide_tts=FakeTts(voice="yue-HK-Chirp3-HD-Despina"),
    )
    messages = []

    async def publish(message, audio):
        messages.append(json.loads(message.model_dump_json()))

    cfg = copy.deepcopy(swapped)
    cfg["pipeline"]["echo_max_mismatch"] = 0.0
    session = Pipeline(providers, cfg, publish, "test")
    await session.start()
    await session.on_message(Mode(mode="guide"))
    await session.on_message(SegmentStart(pause_s=0.5))
    session.on_audio(ONE_SECOND)
    assert stt.streams[-1].languages == ["yue-Hant-HK", "cmn-Hans-CN"]
    stt.streams[-1].final("我哋而家去食飯。")
    await session.on_message(SegmentEnd())
    session.reply_start("phone-1")
    session.reply_audio("phone-1", ONE_SECOND * 2)
    assert stt.streams[-1].languages == ["cmn-Hans-CN", "en-US"]
    stt.streams[-1].final("我们几点集合？")
    session.reply_end("phone-1")
    await asyncio.sleep(0.2)
    clips = {m["for_hub"]: m["voice"] for m in messages if m["type"] == "clip"}
    assert clips == {False: "cmn-CN-Chirp3-HD-Kore", True: "yue-HK-Chirp3-HD-Despina"}
    await session.close()
