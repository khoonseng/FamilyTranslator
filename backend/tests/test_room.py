import asyncio
import copy
import json

from app import config
from app.rooms.room import Room
from app.schemas import (
    ClipRequest,
    GuideControl,
    HubMic,
    LinkRequest,
    Mode,
    ReplyText,
    SegmentEnd,
    SegmentStart,
    TalkEnd,
    TalkStart,
    TypedText,
)
from app.storage.store import MemoryStore, RoomStore
from tests.fakes import FakeStt, fake_providers


class Phone:
    """What one phone receives: JSON messages as dicts, MP3s as bytes."""

    def __init__(self, stuck=False):
        self.messages: list = []
        self.stuck = stuck  # a phone on hopeless signal: its sends never finish

    async def send_text(self, text):
        if self.stuck:
            await asyncio.Event().wait()
        self.messages.append(json.loads(text))

    async def send_bytes(self, data):
        self.messages.append(data)

    def of(self, kind):
        return [m for m in self.messages if isinstance(m, dict) and m["type"] == kind]

    def last(self, kind):
        return self.of(kind)[-1]


async def make_room(hub_offline_s=0.05, store=None, today=None, clips_in_memory=200, **providers):
    cfg = copy.deepcopy(config.load())
    cfg["rooms"]["hub_offline_s"] = hub_offline_s
    cfg["rooms"]["clips_in_memory"] = clips_in_memory
    cfg["rooms"]["guide_quiet_s"] = 0.05  # Talk opens after this much guide silence
    cfg["pipeline"]["echo_max_mismatch"] = 0.0  # the fake translator would look like echoes
    store = store or RoomStore(MemoryStore())
    room = Room(fake_providers(**providers), cfg, store, today or (lambda: "2026-12-19"))
    room.spend_every_s = 0.02
    await room.start()
    return room


class Closer:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


def join(  # noqa: PLR0913
    room, role="listener", host=False, last_id=0, phone=None, day=None, closer=None, takeover=True,
    talk=False,
):  # fmt: skip
    """A hub here taps Start (takeover) unless the test says it is an automatic reconnect.
    `talk`: a family phone that gave the hub PIN (phase 2)."""
    phone = phone or Phone()
    peer = room.join(
        f"{role}-{id(phone)}", role, host, room.day if day is None else day, last_id,
        phone.send_text, phone.send_bytes, closer.close if closer else None, takeover=takeover,
        talk=talk,
    )  # fmt: skip
    return peer, phone


async def settle(seconds=0.05):
    await asyncio.sleep(seconds)


async def test_every_phone_gets_every_sentence_and_clip_in_order():
    room = await make_room()
    hub, hub_phone = join(room, "hub", host=True)
    _, alice = join(room)
    _, bob = join(room)
    await room.handle(hub, TypedText(text="我们在门口集合。大家跟紧我。"))
    await settle()
    for phone in (hub_phone, alice, bob):
        kinds = [m["type"] if isinstance(m, dict) else "mp3" for m in phone.messages]
        kinds = [k for k in kinds if k not in ("ready", "hub_status", "english")]
        assert kinds == ["sentence", "clip", "mp3", "sentence", "clip", "mp3"]
        assert [m["zh"] for m in phone.of("sentence")] == ["我们在门口集合。", "大家跟紧我。"]


async def test_a_listener_cannot_feed_the_pipeline():
    room = await make_room()
    join(room, "hub", host=True)
    listener, phone = join(room)
    await room.handle(listener, TypedText(text="我们在门口集合。"))
    await room.handle(listener, Mode(mode="guide"))
    await settle()
    assert phone.of("sentence") == [] and room.listening is False


async def test_a_late_phone_catches_up_from_its_last_sentence():
    room = await make_room()
    hub, _ = join(room, "hub", host=True)
    await room.handle(hub, TypedText(text="第一句话。第二句话。第三句话。"))
    await settle()
    _, late = join(room, last_id=1)
    await settle()
    assert late.messages[0] == {
        "type": "ready", "role": "listener", "host": False, "talk": False, "day": "2026-12-19",
        "latest_id": 3,
    }  # fmt: skip
    assert [m["zh"] for m in late.of("sentence")] == ["第二句话。", "第三句话。"]
    assert [m["sentence_id"] for m in late.of("clip")] == [2, 3]
    assert [m["sentence_id"] for m in late.of("english")] == [2, 3]


async def test_a_missing_clip_can_be_asked_for_again():
    room = await make_room()
    hub, _ = join(room, "hub", host=True)
    await room.handle(hub, TypedText(text="第一句话。"))
    await settle()
    listener, phone = join(room, last_id=1)
    await room.handle(listener, ClipRequest(sentence_id=1))
    await settle()
    assert [(m["sentence_id"], m["voice"]) for m in phone.of("clip")] == [
        (1, "yue-HK-Chirp3-HD-Despina")  # the voice is remembered for catch-up and requests
    ]
    assert phone.messages[-1] == "mp3:粵:第一句话。".encode()


async def test_host_controls_are_refused_for_ordinary_listeners():
    room = await make_room()
    hub, hub_phone = join(room, "hub", host=True)
    listener, phone = join(room)
    await room.handle(listener, GuideControl(paused=True))
    await settle()
    assert [m["code"] for m in phone.of("error")] == ["not_host"]
    assert room.hub is hub and room.remote_paused is False
    assert hub_phone.of("guide_remote") == []


async def test_a_host_can_pause_and_resume_guide_remotely():
    room = await make_room()
    hub, hub_phone = join(room, "hub", host=True)
    await room.handle(hub, Mode(mode="guide"))
    host, host_phone = join(room, host=True)
    await room.handle(host, GuideControl(paused=True))
    await settle()
    assert hub_phone.last("guide_remote") == {"type": "guide_remote", "paused": True}
    assert host_phone.last("hub_status")["remote_paused"] is True
    await room.handle(hub, Mode(mode="off"))  # the hub obeys
    await room.handle(host, GuideControl(paused=False))
    await room.handle(hub, Mode(mode="guide"))
    await settle()
    assert hub_phone.last("guide_remote")["paused"] is False
    assert host_phone.last("hub_status") == {
        "type": "hub_status", "online": True, "listening": True, "remote_paused": False,
        "mic": "", "mic_lost": False, "interrupted": False, "guide_talking": False,
        "family_talking": False,
    }  # fmt: skip


async def test_host_phones_learn_when_the_clip_on_is_lost_or_the_hub_needs_a_tap():
    room = await make_room()
    hub, _ = join(room, "hub", host=True)
    _, host_phone = join(room, host=True)
    await room.handle(hub, HubMic(mic="external"))
    await settle()
    assert host_phone.last("hub_status")["mic"] == "external"
    await room.handle(hub, HubMic(mic="phone", lost=True, interrupted=True))
    await settle()
    status = host_phone.last("hub_status")
    assert (status["mic"], status["mic_lost"], status["interrupted"]) == ("phone", True, True)


async def test_only_the_hub_reports_its_mic_and_a_new_hub_starts_unknown():
    room = await make_room()
    hub, _ = join(room, "hub", host=True)
    listener, phone = join(room)
    await room.handle(hub, HubMic(mic="phone", lost=True))
    await room.handle(listener, HubMic(mic="external"))  # ignored
    await settle()
    assert phone.last("hub_status")["mic"] == "phone"
    join(room, "hub", host=True)  # Become hub on another phone
    await settle()
    assert (phone.last("hub_status")["mic"], phone.last("hub_status")["mic_lost"]) == ("", False)


async def test_a_new_hub_takes_over_mid_speech():
    stt = FakeStt()
    room = await make_room(stt=stt)
    hub, old_phone = join(room, "hub", host=True)
    await room.handle(hub, Mode(mode="guide"))
    await room.handle(hub, SegmentStart(pause_s=3))  # the old hub is mid-segment
    new, new_phone = join(room, "hub", host=True)  # Become hub on a host phone
    await settle()
    assert room.hub is new
    assert old_phone.last("role") == {"type": "role", "role": "listener", "reason": "replaced"}
    assert new_phone.of("role") == []
    assert stt.streams[0].closed  # the old hub's segment was ended
    await room.handle(hub, TypedText(text="我还在吗。"))  # the old hub no longer feeds it
    await settle()
    assert new_phone.of("sentence") == []


async def test_an_old_hub_reconnecting_never_takes_the_hub_back():
    room = await make_room()
    old, _ = join(room, "hub", host=True)
    await room.leave(old)  # a dead zone
    new, _ = join(room, "hub", host=True)  # meanwhile, Become hub on another phone
    back, back_phone = join(room, "hub", host=True, takeover=False)  # automatic reconnect
    await settle()
    assert room.hub is new and back.role == "listener"
    assert back_phone.messages[0]["role"] == "listener"


async def test_a_hub_reconnecting_with_no_other_hub_carries_on():
    room = await make_room()
    old, _ = join(room, "hub", host=True)
    await room.leave(old)
    back, back_phone = join(room, "hub", host=True, takeover=False)
    await settle()
    assert room.hub is back and back_phone.messages[0]["role"] == "hub"


async def test_a_new_hub_signing_in_replaces_the_old_one():
    room = await make_room()
    _, old_phone = join(room, "hub", host=True)
    new, _ = join(room, "hub", host=True)
    await settle()
    assert room.hub is new
    assert old_phone.last("role")["reason"] == "replaced"


async def test_listeners_learn_the_hub_is_offline_after_a_grace_time():
    room = await make_room(hub_offline_s=0.05)
    hub, _ = join(room, "hub", host=True)
    _, phone = join(room)
    await room.leave(hub)
    await settle(0.02)
    assert phone.last("hub_status")["online"] is True  # still within the grace time
    await settle(0.1)
    assert phone.last("hub_status")["online"] is False
    join(room, "hub", host=True)  # the hub comes back
    await settle()
    assert phone.last("hub_status")["online"] is True


async def test_a_stuck_phone_does_not_delay_the_others():
    room = await make_room()
    hub, _ = join(room, "hub", host=True)
    join(room, phone=Phone(stuck=True))
    _, fine = join(room)
    await room.handle(hub, TypedText(text="大家跟紧我。"))
    await settle()
    assert [m["zh"] for m in fine.of("sentence")] == ["大家跟紧我。"]


# --- storage, days and the join link ------------------------------------------------------------


async def test_a_restart_brings_back_the_day_and_carries_on_numbering():
    store = RoomStore(MemoryStore())
    room = await make_room(store=store)
    hub, _ = join(room, "hub", host=True)
    await room.handle(hub, TypedText(text="第一句话。第二句话。"))
    await settle()
    restarted = await make_room(store=store)  # e.g. Cloud Run scaled to zero and back
    assert list(restarted.history) == [1, 2]
    assert restarted.join_token == room.join_token
    hub, _ = join(restarted, "hub", host=True)
    _, phone = join(restarted)
    await restarted.handle(hub, TypedText(text="第三句话。"))
    await settle()
    assert [m["id"] for m in phone.of("sentence")] == [1, 2, 3]  # catch-up, then live
    assert phone.of("sentence")[-1]["bubble_id"] == 2  # a new bubble after the restart


async def test_records_saved_before_a_new_field_still_catch_up():
    store = RoomStore(MemoryStore())
    old = {"id": 1, "bubble_id": 1, "zh": "第一句话。", "yue": "粵", "status": "ok",
           "provider": "gemini", "en": "", "clip": "none"}  # fmt: skip
    await store.put_sentence("2026-12-19", old)  # saved before `stt` existed
    room = await make_room(store=store)
    _, phone = join(room)
    await settle()
    assert phone.last("sentence")["stt"] == ""


async def test_catch_up_fetches_older_clips_from_the_bucket():
    room = await make_room(clips_in_memory=1)
    hub, _ = join(room, "hub", host=True)
    await room.handle(hub, TypedText(text="第一句话。第二句话。"))
    await settle()
    assert list(room.clips) == [2]  # only the newest stays in memory
    _, late = join(room)
    await settle()
    assert sorted(m["sentence_id"] for m in late.of("clip")) == [1, 2]


async def test_a_phone_from_yesterday_gets_today_from_the_start():
    room = await make_room()
    hub, _ = join(room, "hub", host=True)
    await room.handle(hub, TypedText(text="第一句话。第二句话。"))
    await settle()
    _, phone = join(room, day="2026-12-18", last_id=5)  # its numbers are yesterday's
    await settle()
    assert [m["id"] for m in phone.of("sentence")] == [1, 2]


async def test_a_new_day_clears_the_bubbles_and_restarts_numbering():
    days = iter(["2026-12-19"] * 3 + ["2026-12-20"] * 99)  # start, join, first sentence
    room = await make_room(today=lambda: next(days))
    hub, hub_phone = join(room, "hub", host=True)
    await room.handle(hub, TypedText(text="今天最后一句。"))
    await settle()
    await room.handle(hub, TypedText(text="明天第一句话。"))  # after midnight
    await settle()
    assert hub_phone.last("day") == {"type": "day", "day": "2026-12-20"}
    assert hub_phone.last("sentence")["id"] == 1 and list(room.history) == [1]


async def test_a_host_can_get_and_renew_the_join_link():
    room = await make_room()
    host, host_phone = join(room, host=True)
    closer = Closer()
    _, family = join(room, closer=closer)
    await room.handle(host, LinkRequest())
    await settle()
    old = host_phone.last("join_link")["token"]
    assert old == room.join_token
    await room.handle(host, LinkRequest(new=True))
    await settle(0.3)
    assert host_phone.last("join_link")["token"] == room.join_token != old
    assert family.last("error")["code"] == "link_changed" and closer.closed
    assert await room.store.get_json("settings/join.json") == {"token": room.join_token}


async def test_only_hosts_can_see_the_join_link():
    room = await make_room()
    listener, phone = join(room)
    await room.handle(listener, LinkRequest(new=True))
    await settle()
    assert phone.last("error")["code"] == "not_host" and phone.of("join_link") == []


# --- spending ---------------------------------------------------------------------------------


async def test_only_host_listeners_see_the_spend_never_the_hub():
    room = await make_room()
    hub, hub_phone = join(room, "hub", host=True)  # the hub signs in with the PIN too
    _, host_phone = join(room, host=True)
    _, family = join(room)
    await room.handle(hub, TypedText(text="我们在门口集合。"))
    await settle(0.1)
    spend = host_phone.last("spend")
    assert spend["usd"] >= 0 and spend["warn"] is False and spend["warn_usd"] == 12
    assert hub_phone.of("spend") == [] and family.of("spend") == []


async def test_spend_warns_above_the_threshold():
    room = await make_room()
    _, host_phone = join(room, host=True)
    room.meter.tts("yue-HK-Chirp3-HD-Despina", 500_000)  # US$15
    await settle(0.1)
    assert host_phone.last("spend") == {"type": "spend", "usd": 15.0, "warn": True, "warn_usd": 12}


async def test_the_days_usage_survives_a_restart():
    store = RoomStore(MemoryStore())
    room = await make_room(store=store)
    room.meter.tts("yue-HK-Chirp3-HD-Despina", 100_000)
    await settle(0.1)
    restarted = await make_room(store=store)
    assert restarted.meter.to_dict() == {"tts": {"yue-HK-Chirp3-HD-Despina": 100_000}}


# --- family replies (phase 2) -------------------------------------------------------------------


async def test_only_phones_with_the_hub_pin_may_reply():
    room = await make_room()
    join(room, "hub", host=True)
    family, phone = join(room)  # the join link only
    await room.handle(family, ReplyText(text="幾點集合？"))
    await room.handle(family, TalkStart())
    await settle()
    assert [m["code"] for m in phone.of("error")] == ["not_allowed", "not_allowed"]
    assert phone.of("sentence") == []


async def test_a_typed_reply_reaches_everyone_and_its_mandarin_only_the_hub():
    room = await make_room()
    hub, hub_phone = join(room, "hub", host=True)
    asker, asker_phone = join(room, talk=True)
    _, other = join(room)
    await room.handle(asker, ReplyText(text="幾點集合？"))
    await settle()
    for phone in (hub_phone, asker_phone, other):
        sentence = phone.last("sentence")
        assert (sentence["kind"], sentence["zh"], sentence["mandarin"]) == (
            "reply", "幾點集合？", "普:幾點集合？",
        )  # fmt: skip
        assert phone.last("english")["en"] == "other:幾點集合？"
    assert hub_phone.last("clip")["for_hub"] is True
    assert "mp3:普:幾點集合？".encode() in hub_phone.messages
    for phone in (asker_phone, other):  # listeners hear Cantonese only, never the Mandarin
        assert phone.of("clip") == [] and not any(isinstance(m, bytes) for m in phone.messages)


async def test_with_guide_off_speech_on_the_hub_is_not_the_guide_talking():
    room = await make_room()
    hub, _ = join(room, "hub", host=True)
    asker, phone = join(room, talk=True)
    await room.handle(hub, SegmentStart(pause_s=3))  # Guide off: a stray segment
    await settle(0.01)
    assert room.guide_talking is False
    await room.handle(asker, TalkStart())
    assert asker.talking


async def test_talk_waits_until_the_guide_has_been_quiet_then_runs_to_its_end():
    stt = FakeStt()
    room = await make_room(stt=stt)
    hub, _ = join(room, "hub", host=True)
    await room.handle(hub, Mode(mode="guide"))
    asker, phone = join(room, talk=True)
    await room.handle(hub, SegmentStart(pause_s=3))  # the guide speaks
    await settle(0.01)
    assert phone.last("hub_status")["guide_talking"] is True
    await room.handle(asker, TalkStart())
    await settle(0.01)
    assert phone.last("error")["code"] == "guide_talking"
    await room.handle(hub, SegmentEnd())
    await settle(0.01)
    await room.handle(asker, TalkStart())  # under 2 s (here 0.05 s) since the guide stopped
    await settle(0.01)
    assert [m["code"] for m in phone.of("error")] == ["guide_talking", "guide_talking"]
    await settle(0.1)
    assert phone.last("hub_status")["guide_talking"] is False
    await room.handle(asker, TalkStart())
    assert asker.talking
    await room.handle(hub, SegmentStart(pause_s=3))  # the guide starts again: Talk carries on
    room.on_audio(asker, bytes(32_000))
    # The guide's new segment has its own stream; the reply keeps the Family languages.
    reply = next(st for st in stt.streams if st.languages == ["yue-Hant-HK", "en-US"])
    assert len(reply.sent) == 32_000
    reply.final("我哋幾點食飯？")
    await room.handle(asker, TalkEnd())
    await settle()
    replies = [m for m in phone.of("sentence") if m["kind"] == "reply"]
    assert [(m["zh"], m["stt"]) for m in replies] == [("我哋幾點食飯？", "chirp_3")]


async def test_a_reply_clip_is_never_caught_up_or_sent_to_a_listener_on_request():
    room = await make_room()
    join(room, "hub", host=True)
    asker, _ = join(room, talk=True)
    await room.handle(asker, ReplyText(text="多謝晒。"))
    await settle()
    late, phone = join(room)
    await room.handle(late, ClipRequest(sentence_id=1))
    await settle()
    assert phone.last("sentence")["kind"] == "reply"
    assert phone.of("clip") == [] and phone.last("no_clip")["sentence_id"] == 1


async def test_a_phone_leaving_mid_talk_still_sends_what_it_said():
    stt = FakeStt()
    room = await make_room(stt=stt)
    hub, hub_phone = join(room, "hub", host=True)
    asker, _ = join(room, talk=True)
    await room.handle(asker, TalkStart())
    room.on_audio(asker, bytes(32_000))
    stt.streams[-1].final("唔該。")
    await room.leave(asker)
    await settle()
    assert hub_phone.last("sentence")["zh"] == "唔該。"


async def test_one_phone_talks_at_a_time_and_typing_stays_open():
    stt = FakeStt()
    room = await make_room(stt=stt)
    join(room, "hub", host=True)
    first, _ = join(room, talk=True)
    second, second_phone = join(room, talk=True)
    await room.handle(first, TalkStart())
    await settle(0.01)
    assert second_phone.last("hub_status")["family_talking"] is True
    await room.handle(second, TalkStart())
    await room.handle(second, ReplyText(text="我打字問。"))  # typing works meanwhile
    await settle()
    assert second_phone.last("error")["code"] == "someone_talking"
    assert any(m["zh"] == "我打字問。" for m in second_phone.of("sentence"))
    await room.handle(first, TalkEnd())
    await settle(0.01)
    assert second_phone.last("hub_status")["family_talking"] is False
    await room.handle(second, TalkStart())  # the floor is free again
    assert second.talking


async def test_the_floor_opens_when_the_talker_leaves():
    room = await make_room()
    join(room, "hub", host=True)
    first, _ = join(room, talk=True)
    second, _ = join(room, talk=True)
    await room.handle(first, TalkStart())
    await room.leave(first)
    await room.handle(second, TalkStart())
    assert second.talking


async def test_a_reply_carries_the_askers_device_id_for_you():
    room = await make_room()
    join(room, "hub", host=True)
    asker = room.join(
        "asker", "listener", False, room.day, 0, Phone().send_text, Phone().send_bytes,
        talk=True, device="phone-abc",
    )  # fmt: skip
    _, other = join(room)
    await room.handle(asker, ReplyText(text="唔該。"))
    await settle()
    assert other.last("sentence")["asker"] == "phone-abc"


async def test_talk_across_midnight_is_kept_and_saved_in_the_new_day():
    clock = {"day": "2026-12-19"}
    stt = FakeStt()
    room = await make_room(stt=stt, today=lambda: clock["day"])
    join(room, "hub", host=True)
    asker, phone = join(room, talk=True)
    await room.handle(asker, TalkStart())  # 23:59:55
    room.on_audio(asker, bytes(5 * 32_000))
    clock["day"] = "2026-12-20"  # midnight
    room.on_audio(asker, bytes(15 * 32_000))  # 00:00:15: still recording
    reply = stt.streams[-1]
    assert len(reply.sent) == 20 * 32_000  # nothing lost across midnight
    reply.final("我哋聽日幾點出發？")
    await room.handle(asker, TalkEnd())
    await settle()
    assert room.day == "2026-12-20"
    assert phone.last("sentence")["id"] == 1  # the new day's first entry
    assert await room.store.load_day("2026-12-20")
