import asyncio
import copy
import json

from app import config
from app.pipeline.session import Pipeline
from app.schemas import Mode, SegmentEnd, SegmentStart, TypedText
from tests.fakes import FakeStt, FakeTranscribe, FakeTranslator, FakeTts, fake_providers

ONE_SECOND = bytes(32_000)


class Hub:
    """Collects what the session sends, as the hub would see it."""

    def __init__(self):
        self.messages: list = []

    async def publish(self, message, audio):
        self.messages.append(json.loads(message.model_dump_json()))
        if audio is not None:
            self.messages.append(audio)

    def of(self, kind):
        return [m for m in self.messages if isinstance(m, dict) and m["type"] == kind]


def make(providers=None, echo=0.0, hold_s=0.05):
    """echo=0 switches echo detection off: the fake translator's "粵:<text>" would make every
    test sentence look like an echo of the one before."""
    hub = Hub()
    cfg = copy.deepcopy(config.load())
    cfg["pipeline"]["echo_max_mismatch"] = echo
    cfg["pipeline"]["hold_s"] = hold_s
    session = Pipeline(providers or fake_providers(), cfg, hub.publish, "test")
    return session, hub


async def settle(seconds=0.05):
    await asyncio.sleep(seconds)


async def speak(session, stt, transcript=None, pause_s=0.5, seconds=1, end=True):
    """One hub segment. Chirp 3 returns its final transcript when the stream closes."""
    await session.on_message(SegmentStart(pause_s=pause_s))
    session.on_audio(ONE_SECOND * seconds)
    stream = stt.streams[-1]
    if transcript:
        stream.final(transcript)
    if end:
        await session.on_message(SegmentEnd())
    return stream


async def guide_session(echo=0.0, **kwargs):
    stt = FakeStt()
    session, hub = make(fake_providers(stt=stt, **kwargs), echo=echo)
    await session.start()
    await session.on_message(Mode(mode="guide"))
    return session, hub, stt


async def test_speech_becomes_sentences_in_order_with_text_before_clip():
    # The second sentence translates faster than the first, but must still arrive second.
    translator = FakeTranslator(delays={"第一句话。": 0.1, "第二句话。": 0.0})
    session, hub, stt = await guide_session(translator=translator)
    await speak(session, stt, "第一句话。第二句话。")
    await settle(0.3)
    order = [
        (m["type"], m.get("id") or m.get("sentence_id")) if isinstance(m, dict) else ("mp3", m)
        for m in hub.messages
        if not (isinstance(m, dict) and m["type"] == "english")
    ]
    assert order == [
        ("sentence", 1),
        ("clip", 1),
        ("mp3", "mp3:粵:第一句话。".encode()),
        ("sentence", 2),
        ("clip", 2),
        ("mp3", "mp3:粵:第二句话。".encode()),
    ]
    assert hub.of("sentence")[0]["yue"] == "粵:第一句话。"
    assert {m["en"] for m in hub.of("english")} == {"en:第一句话。", "en:第二句话。"}
    assert translator.warmed


async def test_each_segment_gets_its_own_stream_closed_at_its_end():
    session, _, stt = await guide_session()
    first = await speak(session, stt)
    second = await speak(session, stt, pause_s=0.7)
    assert len(stt.streams) == 2
    await settle()
    assert first.closed and second.closed and session.live is None
    assert len(first.sent) == len(ONE_SECOND)


async def test_a_segment_without_its_end_is_closed_by_the_next_one():
    session, _, stt = await guide_session()
    first = await speak(session, stt, end=False)
    await speak(session, stt, pause_s=0.7)
    await settle()
    assert first.closed


async def test_an_earlier_segment_answering_late_still_comes_first():
    session, hub, stt = await guide_session()
    first = await speak(session, stt, end=False)
    first.auto_end = False  # Chirp 3 is slow to answer for this segment
    await session.on_message(SegmentEnd())
    await speak(session, stt, "后面的一句。", pause_s=0.7)
    await settle()
    assert hub.of("sentence") == []  # waits for the earlier segment
    first.final("前面的一句。")
    first.end()
    await settle()
    assert [m["zh"] for m in hub.of("sentence")] == ["前面的一句。", "后面的一句。"]


async def test_context_is_the_previous_two_sentences():
    translator = FakeTranslator()
    session, _, stt = await guide_session(translator=translator)
    await speak(session, stt, "先去解放碑。然后去洪崖洞。最后回酒店。")
    await settle()
    assert [c for _, c in translator.calls] == [
        [],
        ["先去解放碑。"],
        ["先去解放碑。", "然后去洪崖洞。"],
    ]


async def test_junk_filter_drops_chatter_filler_and_fragments():
    session, hub, stt = await guide_session()
    await speak(session, stt, "我哋喺度等緊佢哋。嗯。大家跟紧我，不要走散了。")
    await settle()
    assert [m["zh"] for m in hub.of("sentence")] == ["大家跟紧我，不要走散了。"]


async def test_audio_outside_guide_mode_or_segments_is_ignored():
    stt = FakeStt()
    session, _ = make(fake_providers(stt=stt))
    await session.on_message(SegmentStart(pause_s=3))  # not in Guide mode yet
    session.on_audio(ONE_SECOND)
    assert stt.streams == []
    await session.on_message(Mode(mode="guide"))
    stream = await speak(session, stt)
    session.on_audio(ONE_SECOND)  # after segment_end: not sent
    assert len(stream.sent) == len(ONE_SECOND)


async def test_bubbles_follow_pauses():
    session, hub, stt = await guide_session()
    await speak(session, stt, "第一段话。", pause_s=3)
    await speak(session, stt, "第二段话。", pause_s=0.7)  # short pause: same bubble
    await speak(session, stt, "第三段话。", pause_s=2.5)  # over 2 s: new bubble
    await settle()
    assert [(m["zh"], m["bubble_id"]) for m in hub.of("sentence")] == [
        ("第一段话。", 1),
        ("第二段话。", 1),
        ("第三段话。", 2),
    ]


async def test_a_seventh_sentence_starts_a_new_bubble():
    session, hub, stt = await guide_session()
    await speak(session, stt, "".join(f"第{n}句话。" for n in "一二三四五六七"), pause_s=3)
    await settle()
    assert [m["bubble_id"] for m in hub.of("sentence")] == [1] * 6 + [2]


async def test_typed_mandarin_skips_stt_and_the_filter_and_gets_its_own_bubble():
    stt = FakeStt()
    session, hub = make(fake_providers(stt=stt))
    await session.on_message(TypedText(text="我们在门口集合。嗯。"))
    await settle()
    assert stt.streams == []
    assert [(m["zh"], m["bubble_id"]) for m in hub.of("sentence")] == [
        ("我们在门口集合。", 1),
        ("嗯。", 1),
    ]


async def test_translation_failure_sends_the_transcript_for_the_operator():
    session, hub = make(fake_providers(translator=FakeTranslator(fail={"第一句。"})))
    await session.on_message(TypedText(text="第一句。第二句。"))
    await settle()
    first, second = hub.of("sentence")
    assert (first["status"], first["yue"], first["zh"]) == ("no_translation", "", "第一句。")
    assert second["status"] == "ok"
    assert [m["sentence_id"] for m in hub.of("clip")] == [2]  # the failure didn't block it


async def test_voice_failure_sends_no_clip_and_keeps_order():
    session, hub = make(fake_providers(tts=FakeTts(fail={"粵:第一句。"})))
    await session.on_message(TypedText(text="第一句。第二句。"))
    await settle()
    kinds = [m["type"] for m in hub.messages if isinstance(m, dict) and m["type"] != "english"]
    assert kinds == ["sentence", "no_clip", "sentence", "clip"]


async def test_switching_guide_off_closes_the_open_segment():
    session, _, stt = await guide_session()
    stream = await speak(session, stt, end=False)
    await session.on_message(Mode(mode="off"))
    await settle()
    assert stream.closed and session.live is None
    session.on_audio(ONE_SECOND)
    assert len(stream.sent) == len(ONE_SECOND)


# --- safety net (hard rule 9) -----------------------------------------------------------------


async def test_audio_chirp_skipped_goes_to_gpt_transcribe():
    transcribe = FakeTranscribe("一边吃烧烤一边看夜景。")
    session, hub, stt = await guide_session(transcribe=transcribe)
    await session.on_message(SegmentStart(pause_s=3))
    session.on_audio(ONE_SECOND * 6)
    stt.streams[-1].final("可以去悬崖餐厅看夜景。", end_s=2.0)  # Chirp 3 stopped at 2 s of 6
    await session.on_message(SegmentEnd())
    await settle()
    assert transcribe.calls == [int((6 - 2.0 + 0.2) * 32_000)]  # from 1.8 s, a little overlap
    assert [m["zh"] for m in hub.of("sentence")] == [
        "可以去悬崖餐厅看夜景。",
        "一边吃烧烤一边看夜景。",
    ]


async def test_finals_reaching_the_end_need_no_safety_net():
    transcribe = FakeTranscribe("不该出现。")
    session, _, stt = await guide_session(transcribe=transcribe)
    await session.on_message(SegmentStart(pause_s=3))
    session.on_audio(ONE_SECOND * 3)
    stt.streams[-1].final("我们到了。", end_s=2.3)  # within 1 s of the 3 s end (the VAD tail)
    await session.on_message(SegmentEnd())
    await settle()
    assert transcribe.calls == []


async def test_a_failed_stream_sends_the_whole_segment():
    transcribe = FakeTranscribe("大家跟紧我。")
    session, hub, stt = await guide_session(transcribe=transcribe)
    await session.on_message(SegmentStart(pause_s=3))
    session.on_audio(ONE_SECOND * 2)
    stt.streams[-1].error = RuntimeError("stream down")
    await session.on_message(SegmentEnd())
    await settle()
    assert transcribe.calls == [2 * 32_000]
    assert [m["zh"] for m in hub.of("sentence")] == ["大家跟紧我。"]


async def test_gpt_transcribe_repeating_its_prompt_is_ignored():
    transcribe = FakeTranscribe("Places and dishes: 解放碑, 洪崖洞")
    session, hub, stt = await guide_session(transcribe=transcribe)
    await speak(session, stt, seconds=3)  # no finals at all
    await settle()
    assert transcribe.calls and hub.of("sentence") == []


# --- half-sentence hold ---------------------------------------------------------------------


async def test_a_sentence_cut_by_a_pause_is_joined_with_the_rest():
    translator = FakeTranslator()
    session, hub, stt = await guide_session(translator=translator)
    await speak(session, stt, "我们等一下", pause_s=3)
    await speak(session, stt, "去洪崖洞。", pause_s=0.8)  # carries on within the hold
    await settle()
    assert [m["zh"] for m in hub.of("sentence")] == ["我们等一下去洪崖洞。"]


async def test_a_half_sentence_goes_on_alone_if_the_guide_stops():
    session, hub, stt = await guide_session()
    await speak(session, stt, "我们等一下", pause_s=3)
    await settle(0.02)
    assert hub.of("sentence") == []  # held ...
    await settle(0.1)  # ... until hold_s passes
    assert [m["zh"] for m in hub.of("sentence")] == ["我们等一下"]


async def test_a_half_sentence_goes_on_when_guide_is_switched_off():
    session, hub, stt = await guide_session()
    await speak(session, stt, "我们等一下", pause_s=3, end=False)
    await session.on_message(Mode(mode="off"))
    await settle(0.02)
    assert [m["zh"] for m in hub.of("sentence")] == ["我们等一下"]


async def test_complete_sentences_are_not_held():
    session, hub, stt = await guide_session()
    await speak(session, stt, "我们到了。", pause_s=3)
    await settle(0.02)
    assert [m["zh"] for m in hub.of("sentence")] == ["我们到了。"]


async def test_a_half_sentence_is_not_held_across_two_segments():
    session, hub, stt = await guide_session()
    await speak(session, stt, "我们等一下", pause_s=3)
    await speak(session, stt, pause_s=0.8)  # the next segment brings no words
    await settle(0.02)
    assert [m["zh"] for m in hub.of("sentence")] == ["我们等一下"]


# --- echo detection (junk-filter layer 4) -----------------------------------------------------


async def test_our_own_cantonese_overheard_is_dropped():
    translator = FakeTranslator()
    session, hub, stt = await guide_session(echo=0.6, translator=translator)
    await session.on_message(TypedText(text="洪崖洞晚上七点半以后开灯。"))
    await settle()
    # A listener phone on speaker plays "粵:洪崖洞晚上七点半以后开灯。"; the hub hears it.
    await speak(session, stt, "洪崖洞晚上7点半以后开灯。", pause_s=3)
    await settle()
    assert len(hub.of("sentence")) == 1
    assert len(translator.calls) == 1


async def test_a_new_guide_sentence_is_not_an_echo():
    session, hub, stt = await guide_session(echo=0.6)
    await session.on_message(TypedText(text="洪崖洞晚上七点半以后开灯。"))
    await settle()
    await speak(session, stt, "明天早上七点在酒店大堂集合。", pause_s=3)
    await settle()
    assert len(hub.of("sentence")) == 2
