import asyncio
import json
from time import perf_counter

import pytest

from app.providers.base import TokenUsage, TranslationFailed, outcome_of
from app.providers.translator import Translator, fallback_targets, translation_messages
from app.usage import Meter

YUE, EN = "洪崖洞夜晚七點半之後會開燈。", "Hongyadong's lights come on after 7:30 pm."


def reply(yue=YUE, en=EN) -> str:
    return json.dumps({"yue": yue, "en": en}, ensure_ascii=False)


class FakeModel:
    """Streams `text` in pieces, waiting `delay` before the first and `en_delay` before the
    `en` field; or raises `error` before streaming."""

    def __init__(self, name, text=None, *, deadline=False, delay=0.0, en_delay=0.0, error=None):
        self.name, self.deadline = name, deadline
        self.text = reply() if text is None else text
        self.delay, self.en_delay, self.error = delay, en_delay, error
        self.closed = False

    async def stream(self, messages):
        try:
            if self.error:
                raise self.error
            await asyncio.sleep(self.delay)
            split = self.text.find('"en"')
            head, tail = (self.text, "") if split < 0 else (self.text[:split], self.text[split:])
            for i in range(0, len(head), 5):
                yield head[i : i + 5]
            await asyncio.sleep(self.en_delay)
            if tail:
                yield tail
            yield TokenUsage(1200, 80)  # the stream's usage comes last
        finally:
            self.closed = True


class FakeCloudTranslate:
    name = "cloud-translate"

    def __init__(self, yue="洪崖洞晚上七點半之後開燈。", en="Lights on after 7:30.", error=None):
        self.yue, self.en, self.error = yue, en, error
        self.calls = 0

    def translate(self, text, targets, source=""):
        self.calls += 1
        self.targets, self.source = targets, source

        async def one(value):
            if self.error:
                raise self.error
            return value

        return asyncio.ensure_future(one(self.yue)), asyncio.ensure_future(one(self.en))


class Refused(Exception):
    status_code = 429


class TooLong(Exception):
    """Like Google's InvalidArgument: "This request contains sentences that are too long"."""

    code = 400


def translator(*models, fallback=None, deadline=0.2, timeout=1.0):
    return Translator(list(models), fallback or FakeCloudTranslate(), deadline, timeout)


async def test_first_model_answers():
    t = translator(FakeModel("gemini", deadline=True), FakeModel("qwen"))
    result = await t.translate("洪崖洞晚上七点半以后开灯", [])
    assert (result.speech, result.provider, result.attempts) == (YUE, "gemini", [])
    assert await result.other == EN


async def test_yue_is_ready_before_en_finishes():
    t = translator(FakeModel("gemini", deadline=True, en_delay=0.3))
    start = perf_counter()
    result = await t.translate("...", [])
    assert perf_counter() - start < 0.2  # TTS can start without waiting for `en`
    assert await result.other == EN


async def test_refusal_429_fails_over_at_once():
    t = translator(FakeModel("gemini", deadline=True, error=Refused()), FakeModel("qwen"))
    result = await t.translate("...", [])
    assert result.provider == "qwen"
    assert [(a.provider, a.outcome) for a in result.attempts] == [("gemini", "429")]


async def test_gemini_past_its_deadline_fails_over():
    gemini = FakeModel("gemini", deadline=True, delay=0.5)
    t = translator(gemini, FakeModel("qwen"), deadline=0.1)
    result = await t.translate("...", [])
    assert result.provider == "qwen"
    assert [(a.provider, a.outcome) for a in result.attempts] == [("gemini", "deadline")]
    assert gemini.closed  # the slow stream is abandoned, not left running


async def test_the_deadline_applies_only_to_models_marked_with_it():
    t = translator(FakeModel("qwen", delay=0.3), deadline=0.1, timeout=1.0)
    assert (await t.translate("...", [])).provider == "qwen"


async def test_latin_letters_in_yue_are_junk():
    junk = FakeModel("gemini", reply(yue="嗰陣時特別多 goods，大家跟緊我。"), deadline=True)
    t = translator(junk, FakeModel("qwen"))
    result = await t.translate("...", [])
    assert result.provider == "qwen"
    assert [(a.provider, a.outcome) for a in result.attempts] == [("gemini", "junk")]


async def test_reply_without_yue_is_bad_json():
    t = translator(FakeModel("gemini", "not json at all", deadline=True), FakeModel("qwen"))
    result = await t.translate("...", [])
    assert [(a.provider, a.outcome) for a in result.attempts] == [("gemini", "bad_json")]


async def test_escaped_quotes_in_yue_are_decoded():
    t = translator(FakeModel("gemini", reply(yue='佢話「"開燈"」'), deadline=True))
    assert (await t.translate("...", [])).speech == '佢話「"開燈"」'


async def test_gpt_oss_answers_when_gemini_and_qwen_fail():
    t = translator(
        FakeModel("gemini", deadline=True, error=Refused()),
        FakeModel("qwen", error=Refused()),  # Groq's free limit for Qwen
        FakeModel("gpt-oss"),  # a separate allowance on Groq
    )
    result = await t.translate("...", [])
    assert result.provider == "gpt-oss"
    outcomes = [(a.provider, a.outcome) for a in result.attempts]
    assert outcomes == [("gemini", "429"), ("qwen", "429")]


def test_config_tries_three_llms_and_prices_each():
    from app import config

    cfg = config.load()
    order = cfg["translation"]["order"]
    assert order == ["gemini", "qwen", "gpt-oss"]
    gpt_oss = cfg["translation"]["models"]["gpt-oss"]
    assert (gpt_oss["provider"], gpt_oss["model"]) == ("groq", "openai/gpt-oss-120b")
    assert gpt_oss["params"]["reasoning_effort"] == "low"  # its lowest (hard rule 6)
    for name in order:  # the spend figure counts every translator
        assert name in cfg["spending"]["llm_per_million_in"]
        assert name in cfg["spending"]["llm_per_million_out"]


async def test_both_llms_fail_then_cloud_translation():
    fallback = FakeCloudTranslate()
    t = translator(
        FakeModel("gemini", deadline=True, error=Refused()),
        FakeModel("qwen", error=RuntimeError("down")),
        fallback=fallback,
    )
    result = await t.translate("...", [])
    assert (result.provider, result.speech) == ("cloud-translate", fallback.yue)
    assert await result.other == fallback.en
    assert [a.outcome for a in result.attempts] == ["429", "error"]
    assert (fallback.targets, fallback.source) == (("yue", "en"), "zh-CN")


async def test_everything_fails():
    t = translator(
        FakeModel("gemini", deadline=True, error=Refused()),
        FakeModel("qwen", error=TimeoutError()),
        fallback=FakeCloudTranslate(error=RuntimeError("down")),
    )
    with pytest.raises(TranslationFailed) as failed:
        await t.translate("...", [])
    assert [(a.provider, a.outcome) for a in failed.value.attempts] == [
        ("gemini", "429"),
        ("qwen", "timeout"),
        ("cloud-translate", "error"),
    ]


def test_messages_carry_glossary_and_context():
    system, user = translation_messages("到了", ["先去解放碑", "然后去洪崖洞"])
    assert user == {"role": "user", "content": "到了"}
    assert "洪崖洞 = " in system["content"]  # glossary line
    assert "- 先去解放碑\n- 然后去洪崖洞" in system["content"]
    assert "{glossary}" not in system["content"] and "{context}" not in system["content"]


def test_no_context_says_none():
    system, _ = translation_messages("到了", [])
    assert "(none)" in system["content"]


@pytest.mark.parametrize(
    "exc, outcome",
    [
        (Refused(), "429"),
        (TimeoutError(), "timeout"),
        (TooLong(), "rejected"),
        (RuntimeError(), "error"),
    ],
)
def test_outcome_labels(exc, outcome):
    assert outcome_of(exc) == outcome


async def test_the_meter_counts_tokens_from_the_reply():
    t = translator(FakeModel("gemini", deadline=True))
    t.meter = Meter()
    result = await t.translate("...", [])
    await result.other
    assert t.meter.to_dict() == {"llm_in": {"gemini": 1200}, "llm_out": {"gemini": 80}}


async def test_an_abandoned_reply_is_billed_for_its_prompt_and_cloud_translation_by_characters():
    t = translator(
        FakeModel("gemini", deadline=True, delay=0.5),
        FakeModel("qwen", error=RuntimeError("down")),
        deadline=0.05,
    )
    t.meter = Meter()
    await t.translate("我们到了。", [])
    counts = t.meter.to_dict()
    assert 800 < counts["llm_in"]["gemini"] < 1200  # estimated from the prompt's length
    assert counts["mt"] == {"cloud-translate": 2 * len("我们到了。")}


# --- family replies (phase 2) -------------------------------------------------------------------


def family_reply(zh_hans="我们几点集合？", other="What time do we meet?") -> str:
    return json.dumps({"zh_hans": zh_hans, "other": other}, ensure_ascii=False)


async def test_a_reply_reads_the_mandarin_then_the_other_language():
    t = translator(FakeModel("gemini", family_reply(), deadline=True))
    result = await t.translate("我哋幾點集合？", [], direction="family")
    assert (result.speech, result.provider) == ("我们几点集合？", "gemini")
    assert await result.other == "What time do we meet?"


async def test_english_names_in_a_reply_are_not_junk():
    t = translator(FakeModel("gemini", family_reply(zh_hans="附近有KFC吗？"), deadline=True))
    result = await t.translate("Is there a KFC nearby?", [], direction="family")
    assert (result.speech, result.attempts) == ("附近有KFC吗？", [])


async def test_a_reply_falls_back_to_cloud_translation_into_mandarin():
    fallback = FakeCloudTranslate(yue="附近有洗手间吗？", en="附近有洗手間嗎？")
    t = translator(FakeModel("gemini", deadline=True, error=Refused()), fallback=fallback)
    result = await t.translate("Is there a toilet nearby?", [], direction="family")
    assert (result.provider, result.speech) == ("cloud-translate", "附近有洗手间吗？")
    assert (fallback.targets, fallback.source) == (("zh-CN", "yue"), "")  # Google detects it


def test_fallback_targets_follow_the_direction():
    assert fallback_targets("洪崖洞几点开灯？", "guide") == ("yue", "en")
    assert fallback_targets("我哋幾點走？", "family") == ("zh-CN", "en")  # Cantonese: English
    assert fallback_targets("When do we leave?", "family") == ("zh-CN", "yue")  # English


def test_the_family_prompt_fills_in_glossary_and_context():
    system, user = translation_messages("幾點集合？", ["先去解放碑"], direction="family")
    assert user["content"] == "幾點集合？"
    assert '"zh_hans"' in system["content"] and "- 先去解放碑" in system["content"]
    assert "{glossary}" not in system["content"] and "{context}" not in system["content"]
