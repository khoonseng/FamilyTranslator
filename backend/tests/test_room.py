import asyncio
import copy
import json

from app import config
from app.rooms.room import Room
from app.schemas import BecomeHub, ClipRequest, GuideControl, Mode, SegmentStart, TypedText
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


async def make_room(hub_offline_s=0.05, **providers):
    cfg = copy.deepcopy(config.load())
    cfg["rooms"]["hub_offline_s"] = hub_offline_s
    cfg["pipeline"]["echo_max_mismatch"] = 0.0  # the fake translator would look like echoes
    room = Room(fake_providers(**providers), cfg)
    await room.start()
    return room


def join(room, role="listener", host=False, last_id=0, phone=None):
    phone = phone or Phone()
    peer = room.join(f"{role}-{id(phone)}", role, host, last_id, phone.send_text, phone.send_bytes)
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
    assert late.messages[0] == {"type": "ready", "role": "listener", "host": False}
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
    assert [m["sentence_id"] for m in phone.of("clip")] == [1]
    assert phone.messages[-1] == "mp3:粵:第一句话。".encode()


async def test_host_controls_are_refused_for_ordinary_listeners():
    room = await make_room()
    hub, hub_phone = join(room, "hub", host=True)
    listener, phone = join(room)
    await room.handle(listener, GuideControl(paused=True))
    await room.handle(listener, BecomeHub())
    await settle()
    assert [m["code"] for m in phone.of("error")] == ["not_host", "not_host"]
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
    }  # fmt: skip


async def test_a_host_takes_over_as_hub_mid_speech():
    stt = FakeStt()
    room = await make_room(stt=stt)
    hub, old_phone = join(room, "hub", host=True)
    await room.handle(hub, Mode(mode="guide"))
    await room.handle(hub, SegmentStart(pause_s=3))  # the old hub is mid-segment
    host, host_phone = join(room, host=True)
    await room.handle(host, BecomeHub())
    await settle()
    assert room.hub is host
    assert old_phone.last("role") == {"type": "role", "role": "listener", "reason": "replaced"}
    assert host_phone.last("role") == {"type": "role", "role": "hub", "reason": "became_hub"}
    assert stt.streams[0].closed  # the old hub's segment was ended
    await room.handle(hub, TypedText(text="我还在吗。"))  # the old hub no longer feeds it
    await settle()
    assert host_phone.of("sentence") == []


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
