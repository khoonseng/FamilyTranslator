"""The one fixed room (architecture doc, "One fixed room, one active hub").

- Every phone connects to `/ws/room`: one hub, any number of listeners, some of them hosts.
- The pipeline belongs to the room, so a hub reconnect or takeover carries on with the same
  bubbles, sentence numbers and context.
- Fan-out: everything the pipeline publishes goes to every phone, each through its own send
  queue, so a phone on weak signal never delays the others.
- Storage: each sentence's record and clip are saved in the background (app/storage); on a
  restart the room reloads the day, so bubbles and numbering carry on.
- Days: the room shows one trip-local day. At the first activity after midnight it starts a new
  day: phones clear their bubbles and numbering restarts; earlier days stay in the bucket.
- Catch-up: a joining phone first gets every sentence after its `last_id` (text, then the clips
  in memory; older clips follow from the bucket), then the live stream.
- Host controls (remote pause, the join link) are refused for other phones.
- Family replies (phase 2): a phone that gave the hub PIN may talk or type to the guide. Talk
  starts only when the guide has been quiet for `guide_quiet_s` (the hub's segments say when
  he speaks) and no other phone is talking (one at a time), then runs to its end; typing works
  any time. A reply's Mandarin clip goes to
  the hub only. Become hub on a
  host phone opens the hub page, which takes over like any hub's Start.

Logs carry connection ids, roles and counts only, never text, audio or tokens (hard rule 14)."""

import asyncio
import os
import secrets
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.logs import log
from app.pipeline.session import Pipeline
from app.rooms.history import HistoryArchive
from app.schemas import (
    Clip,
    ClipRequest,
    DayChange,
    English,
    Error,
    GuideControl,
    GuideRemote,
    HistoryClipRequest,
    HistoryDaysRequest,
    HistoryError,
    HistoryPageRequest,
    HubMic,
    HubStatus,
    JoinLink,
    LinkRequest,
    Mode,
    NoClip,
    Ready,
    ReplyText,
    Role,
    SegmentEnd,
    SegmentStart,
    Sentence,
    Spend,
    TalkEnd,
    TalkStart,
    TypedText,
)
from app.usage import Meter

HUB_MESSAGES = (Mode, SegmentStart, SegmentEnd, TypedText)
HOST_MESSAGES = (GuideControl, LinkRequest)
HISTORY_MESSAGES = (HistoryDaysRequest, HistoryPageRequest, HistoryClipRequest)
JOIN_LINK = "settings/join.json"
SPEND_EVERY_S = 10  # how often host phones get a changed estimate, and the counts are saved


@dataclass(eq=False)
class Peer:
    """One connected phone and its own send queue."""

    conn: str
    role: str  # "hub" or "listener"
    host: bool
    send_text: Callable[[str], Awaitable[None]]
    send_bytes: Callable[[bytes], Awaitable[None]]
    close: Callable[[], Awaitable[None]] | None = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    sent: int = 0
    talk: bool = False  # gave the hub PIN: may reply to the guide (phase 2)
    talking: bool = False  # holding Talk now
    device: str = ""  # the phone's random id: its own replies say "You"
    archive_allowed: bool = True
    archive_requests: int = 0

    def put(self, message: BaseModel, audio: bytes | None = None) -> None:
        self.queue.put_nowait((message.model_dump_json(), audio))


class Room:
    def __init__(self, providers, cfg: dict, store, today: Callable[[], str] | None = None):
        self.providers = providers
        self.full_cfg = cfg
        self.cfg = cfg["rooms"]
        self.store = store
        zone = ZoneInfo(self.cfg["timezone"])
        self.today = today or (lambda: datetime.now(zone).date().isoformat())
        self.day = self.today()
        self.prices = cfg["spending"]
        self.meter = Meter()
        self.spend_every_s = SPEND_EVERY_S
        self.peers: set[Peer] = set()
        self.hub: Peer | None = None
        self.history: OrderedDict[int, dict] = OrderedDict()  # sentence id -> record
        self.clips: OrderedDict[int, bytes] = OrderedDict()  # the most recent clips
        self.join_token = ""
        self.listening = False  # the hub's Guide latch
        self.remote_paused = False
        self.hub_mic: HubMic | None = None  # what the hub last said about its mic
        self.guide_talking = False  # the guide speaks, or stopped less than guide_quiet_s ago
        self._quiet: asyncio.Task | None = None
        self.talker: Peer | None = None  # the family phone holding Talk (one at a time)
        self.hub_online = False
        self._offline: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self.archive = HistoryArchive(store, self.today)
        self._saves: dict[tuple[str, int], asyncio.Task] = {}
        self.pipeline = self._new_pipeline()

    async def start(self) -> None:
        """Loads the join link and today's sentences, so a restart carries on."""
        link = await self.store.get_json(JOIN_LINK)
        if link and link.get("token"):
            self.join_token = link["token"]
        else:  # first start: a local override (development), else a fresh random token
            self.join_token = os.environ.get("ROOM_TOKEN") or secrets.token_urlsafe(12)
            await self.store.put_json(JOIN_LINK, {"token": self.join_token})
        records = await self.store.load_day(self.day)
        for record in records:
            self.history[record["id"]] = record
        if records:
            self.pipeline.resume(
                next_id=records[-1]["id"] + 1,
                next_bubble=max(r["bubble_id"] for r in records) + 1,
                context=[r["zh"] for r in records],
            )
        self._use_meter(Meter(await self.store.get_json(self._usage_name())))
        log("room_start", sentences=len(records))
        self._spawn(self._spend_loop())
        await self.pipeline.start()

    # --- phones -------------------------------------------------------------------------------

    def join(  # noqa: PLR0913
        self,
        conn,
        role,
        host,
        day,
        last_id,
        send_text,
        send_bytes,
        close=None,
        takeover=False,
        talk=False,
        device="",
    ) -> Peer:
        """`takeover`: a hub's Start or Become hub. Without it (an automatic reconnect), a hub
        joins as a listener if another phone is the hub now."""
        self._check_day()
        if role == "hub" and not takeover and self.hub is not None:
            role = "listener"
            log("hub_reconnect_declined", conn=conn)
        peer = Peer(conn, "listener", host, send_text, send_bytes, close)
        peer.talk = talk or host
        peer.device = device
        if day != self.day:
            last_id = 0  # the phone's bubbles are from another day: it clears them
        latest = next(reversed(self.history), 0)
        talk = peer.talk and role != "hub"
        peer.put(Ready(role=role, host=host, talk=talk, day=self.day, latest_id=latest))
        stored_clips = []
        for message, audio in self._catch_up(last_id):
            if message is None:
                stored_clips.append(audio)  # a clip id to fetch from the bucket
            else:
                peer.put(message, audio)
        self.peers.add(peer)
        peer.task = asyncio.create_task(self._sender(peer))
        if stored_clips:
            self._spawn(self._send_stored_clips(peer, self.day, stored_clips))
        if role == "hub":
            self._set_hub(peer)
        else:
            peer.put(self._status())
            if host:
                peer.put(self._spend())
        log("room_join", conn=conn, role=role, host=host, talk=talk, phones=len(self.peers))
        return peer

    async def leave(self, peer: Peer) -> None:
        peer.archive_allowed = False
        self.peers.discard(peer)
        if peer.talking:  # what they said so far still goes to the guide
            self._talk_over(peer)
        if peer.task:
            peer.task.cancel()
        if peer is self.hub:
            self.hub = None
            await self._hub_gone()
        log("room_leave", conn=peer.conn, sent=peer.sent, phones=len(self.peers))

    async def handle(self, peer: Peer, message: BaseModel) -> None:
        if isinstance(message, HUB_MESSAGES):
            if peer is not self.hub:
                return  # only the active hub feeds the pipeline
            self._check_day()
            if isinstance(message, Mode):
                self.listening = message.mode == "guide"
                if self.listening:
                    self.remote_paused = False
                else:
                    self._guide_quiet_now()
                self._broadcast(self._status())
            elif isinstance(message, SegmentStart):
                if self.listening:  # with Guide off, nothing the hub hears is the guide
                    self._guide_speaking()
            elif isinstance(message, SegmentEnd):
                self._guide_paused()
            await self.pipeline.on_message(message)
        elif isinstance(message, ClipRequest):
            self._spawn(self._send_clip(peer, self.day, message.sentence_id))
        elif isinstance(message, HISTORY_MESSAGES):
            self._request_history(peer, message)
        elif isinstance(message, (TalkStart, TalkEnd, ReplyText)):
            self._reply(peer, message)
        elif isinstance(message, HubMic):
            if peer is not self.hub:
                return
            self.hub_mic = message
            self._broadcast(self._status())
            log("hub_mic", conn=peer.conn, mic=message.mic, lost=message.lost,
                interrupted=message.interrupted)  # fmt: skip
        elif isinstance(message, HOST_MESSAGES):
            if not peer.host:
                peer.put(Error(code="not_host"))
                log("host_refused", conn=peer.conn)
                return
            if isinstance(message, GuideControl):
                self.remote_paused = message.paused
                if self.hub:
                    self.hub.put(GuideRemote(paused=message.paused))
                self._broadcast(self._status())
                log("guide_remote", conn=peer.conn, paused=message.paused)
            else:
                if message.new:
                    await self._new_join_link()
                peer.put(JoinLink(token=self.join_token))

    def _request_history(self, peer: Peer, message) -> None:
        if peer.role != "listener" or not peer.archive_allowed or peer.archive_requests >= 4:
            peer.put(HistoryError(request_id=message.request_id))
            return
        peer.archive_requests += 1
        self._spawn(self._send_history(peer, message))

    async def _send_history(self, peer: Peer, message) -> None:
        try:
            response, audio = await self.archive.response(message)
            if peer.archive_allowed:
                peer.put(response, audio)
        except Exception as exc:  # noqa: BLE001 - a failed archive read must not drop the room
            log("history_read_error", error=type(exc).__name__)
            if peer.archive_allowed:
                peer.put(HistoryError(request_id=message.request_id))
        finally:
            peer.archive_requests -= 1

    def on_audio(self, peer: Peer, pcm: bytes) -> None:
        if peer is self.hub:
            self.pipeline.on_audio(pcm)
        elif peer.talking and not self.pipeline.reply_audio(peer.conn, pcm):
            self._talk_over(peer)  # the 30 s cap: the recording has been sent on

    # --- family replies (phase 2) ---------------------------------------------------------------

    def _reply(self, peer: Peer, message: BaseModel) -> None:
        if not peer.talk:
            peer.put(Error(code="not_allowed"))
            log("reply_refused", conn=peer.conn)
            return
        self._check_day()
        if isinstance(message, TalkStart):
            refusal = (
                "guide_talking" if self.guide_talking  # the guide has priority (hard rule 8)
                else "someone_talking" if self.talker not in (None, peer)  # one at a time
                else ""
            )  # fmt: skip
            if refusal:
                peer.put(Error(code=refusal))
                log("talk_refused", conn=peer.conn, reason=refusal)
                return
            peer.talking = True
            self.talker = peer
            self.pipeline.reply_start(peer.conn, peer.device)
            self._broadcast(self._status())
            log("talk_start", conn=peer.conn)
        elif isinstance(message, TalkEnd):
            if peer.talking:
                self._talk_over(peer)
                log("talk_end", conn=peer.conn)
        else:
            self.pipeline.reply_text(message.text, peer.device)
            log("reply_typed", conn=peer.conn)

    def _talk_over(self, peer: Peer) -> None:
        """The recording goes to the guide, and the floor opens for the next phone."""
        peer.talking = False
        self.pipeline.reply_end(peer.conn)
        if self.talker is peer:
            self.talker = None
            self._broadcast(self._status())

    def _guide_speaking(self) -> None:
        if self._quiet:
            self._quiet.cancel()
            self._quiet = None
        self._set_guide_talking(True)

    def _guide_paused(self) -> None:
        """Talk opens once the guide has been quiet for `guide_quiet_s` (hard rule 8)."""
        if self._quiet:
            self._quiet.cancel()
        self._quiet = self._spawn(self._quiet_after())

    async def _quiet_after(self) -> None:
        await asyncio.sleep(self.cfg["guide_quiet_s"])
        self._quiet = None
        self._set_guide_talking(False)

    def _guide_quiet_now(self) -> None:
        """Guide listening stopped, or the hub left: nothing to wait for."""
        if self._quiet:
            self._quiet.cancel()
            self._quiet = None
        self._set_guide_talking(False)

    def _set_guide_talking(self, talking: bool) -> None:
        if talking != self.guide_talking:
            self.guide_talking = talking
            self._broadcast(self._status())

    # --- the join link --------------------------------------------------------------------------

    async def _new_join_link(self) -> None:
        """A new token: the old link stops working, and phones still on it are disconnected
        (they show "This link no longer works")."""
        self.join_token = secrets.token_urlsafe(12)
        await self.store.put_json(JOIN_LINK, {"token": self.join_token})
        removed = 0
        for peer in list(self.peers):
            if peer.role == "listener" and not peer.host:
                peer.archive_allowed = False
                peer.put(Error(code="link_changed"))
                if peer.close:
                    self._spawn(self._close_after_send(peer))
                removed += 1
        log("join_link_changed", disconnected=removed)

    async def _close_after_send(self, peer: Peer) -> None:
        await asyncio.sleep(0.2)  # let the error message go out first
        await peer.close()

    # --- the hub ------------------------------------------------------------------------------

    def _set_hub(self, peer: Peer) -> None:
        old = self.hub
        if old is not None and old is not peer:
            old.role = "listener"
            old.put(Role())
            self._spawn(self._hub_gone(offline_timer=False))
            log("hub_replaced", old=old.conn, new=peer.conn)
        self.hub = peer
        peer.role = "hub"
        self.hub_mic = None  # until the new hub says
        if self._offline:
            self._offline.cancel()
            self._offline = None
        self.hub_online = True
        self._broadcast(self._status())

    async def _hub_gone(self, offline_timer: bool = True) -> None:
        """The hub left or was replaced: end its segment; listeners learn after a grace time."""
        await self.pipeline.on_message(Mode(mode="off"))
        self.listening = False
        self._guide_quiet_now()
        if self.hub is None:
            self.hub_mic = None
        if offline_timer and self.hub is None:
            self._offline = asyncio.create_task(self._go_offline())
        self._broadcast(self._status())

    async def _go_offline(self) -> None:
        await asyncio.sleep(self.cfg["hub_offline_s"])
        self._offline = None
        if self.hub is None:
            self.hub_online = False
            self._broadcast(self._status())
            log("hub_offline")

    def _status(self) -> HubStatus:
        mic = self.hub_mic
        return HubStatus(
            online=self.hub_online,
            listening=self.listening,
            remote_paused=self.remote_paused,
            mic=mic.mic if mic else "",
            mic_lost=bool(mic and mic.lost),
            interrupted=bool(mic and mic.interrupted),
            guide_talking=self.guide_talking,
            family_talking=self.talker is not None,
        )

    # --- days ---------------------------------------------------------------------------------

    def _new_pipeline(self) -> Pipeline:
        day, history = self.day, self.history

        async def publish(message, audio):
            await self._publish(day, history, message, audio)

        return Pipeline(self.providers, self.full_cfg, publish, conn="room")

    def _check_day(self) -> None:
        """At the first activity after midnight (trip-local), start a new day."""
        today = self.today()
        if today == self.day:
            return
        old = self.pipeline
        self._spawn(old.on_message(Mode(mode="off")))
        self._spawn(self._save_usage(self._usage_name(), self.meter))
        self.day = today
        self.history = OrderedDict()
        self.clips.clear()
        self.pipeline = self._new_pipeline()
        # A family member still holding Talk across midnight: their recording carries on in the
        # new day and is saved there, instead of being lost with yesterday's pipeline.
        self.pipeline.replies, old.replies = old.replies, {}
        self._use_meter(Meter())
        self._spawn(self.pipeline.start())
        self._broadcast(DayChange(day=today))
        log("day_change")

    # --- spending -----------------------------------------------------------------------------

    def _use_meter(self, meter: Meter) -> None:
        self.meter = meter
        self.pipeline.meter = meter
        self.providers.translator.meter = meter

    def _usage_name(self) -> str:
        return f"days/{self.day}/usage.json"

    def _spend(self) -> Spend:
        usd = round(self.meter.cost(self.prices), 2)
        warn_usd = self.prices["warn_usd"]
        return Spend(usd=usd, warn=usd > warn_usd, warn_usd=warn_usd)

    async def _spend_loop(self) -> None:
        """While usage changes: tell host listeners (never the hub) and save the counts."""
        while True:
            await asyncio.sleep(self.spend_every_s)
            if not self.meter.changed:
                continue
            self.meter.changed = False
            spend = self._spend()
            for peer in self.peers:
                if peer.host and peer.role == "listener":
                    peer.put(spend)
            await self._save_usage(self._usage_name(), self.meter)

    async def _save_usage(self, name: str, meter: Meter) -> None:
        try:
            await self.store.put_json(name, meter.to_dict())
        except Exception as exc:  # noqa: BLE001
            log("store_error", what="usage", error=type(exc).__name__)

    # --- sentences ----------------------------------------------------------------------------

    async def _publish(self, day, history, message: BaseModel, audio: bytes | None) -> None:
        """Everything the pipeline produces: remember it, save it, send it to every phone."""
        current = day == self.day
        if isinstance(message, Sentence):
            record = message.model_dump() | {
                "en": "",
                "clip": "pending" if message.status == "ok" else "none",
            }
            history[message.id] = record
        else:
            record = history.get(message.sentence_id)
            if record is None:
                return
            if isinstance(message, Clip):
                record.update(clip="ready", voice=message.voice)
            elif isinstance(message, NoClip):
                record.update(clip="none")
            elif isinstance(message, English):
                record.update(en=message.en)
        self._queue_save(day, record, audio)

        if not current:
            return  # work finishing after midnight still belongs to the previous archive
        if isinstance(message, Clip) and audio is not None:
            self.clips[message.sentence_id] = audio
            while len(self.clips) > self.cfg["clips_in_memory"]:
                self.clips.popitem(last=False)
        if self._for_hub_only(message):
            if self.hub:
                self.hub.put(message, audio)
            return
        self._broadcast(message, audio)

    def _for_hub_only(self, message: BaseModel) -> bool:
        """A reply's Mandarin clip (or its absence) is for the guide, played by the hub."""
        if isinstance(message, Clip):
            return message.for_hub
        if isinstance(message, NoClip):
            return self.history.get(message.sentence_id, {}).get("kind") == "reply"
        return False

    def _queue_save(self, day: str, record: dict, mp3: bytes | None) -> None:
        key = (day, record["id"])
        previous = self._saves.get(key)

        async def save():
            try:
                if previous is not None:
                    await previous
                await self._save(day, snapshot, mp3)
            finally:
                if self._saves.get(key) is asyncio.current_task():
                    self._saves.pop(key)

        snapshot = dict(record)
        if snapshot["clip"] == "pending":
            snapshot["clip"] = "none"  # this text survives even if synthesis never finishes
        self._saves[key] = self._spawn(save())

    async def _save(self, day: str, record: dict, mp3: bytes | None) -> None:
        """Writes the clip (if any), then the record. Never delays the live stream."""
        try:
            if mp3 is not None:
                await self.store.put_clip(day, record["id"], mp3)
            await self.store.put_sentence(day, record)
            self.archive.invalidate(day)
        except Exception as exc:  # noqa: BLE001 - the live stream matters more than the copy
            log("store_error", id=record["id"], error=type(exc).__name__)

    def _catch_up(self, last_id: int):
        """Everything after `last_id`: all the text first, so the screen fills quickly, then
        the clips. A clip no longer in memory comes back as (None, sentence_id), to be fetched
        from the bucket. A reply's Mandarin clip is never caught up: it was for the guide, then."""
        newer = [r for sid, r in self.history.items() if sid > last_id]
        for record in newer:
            # Records saved before a field existed (e.g. `stt`) take its default.
            fields = {k: record[k] for k in Sentence.model_fields if k != "type" and k in record}
            yield Sentence(**fields), None
            if record["en"]:
                yield English(sentence_id=record["id"], en=record["en"]), None
        for record in newer:
            if record.get("kind") == "reply":
                continue
            if record["clip"] == "none":
                yield NoClip(sentence_id=record["id"]), None
            elif record["id"] in self.clips:
                audio = self.clips[record["id"]]
                voice = record.get("voice", "")
                yield Clip(sentence_id=record["id"], bytes=len(audio), voice=voice), audio
            elif record["clip"] == "ready":
                yield None, record["id"]

    async def _send_stored_clips(self, peer: Peer, day: str, sentence_ids: list[int]) -> None:
        for sentence_id in sentence_ids:
            await self._send_clip(peer, day, sentence_id)

    async def _send_clip(self, peer: Peer, day: str, sentence_id: int) -> None:
        """A clip on request: from memory, else from the bucket, else 'no clip'."""
        if day != self.day:
            return
        record = self.history.get(sentence_id)
        if record is None or record["clip"] == "pending":
            return  # unknown, or still being spoken: it arrives live
        if record.get("kind") == "reply":
            peer.put(NoClip(sentence_id=sentence_id))  # a reply's Mandarin was for the guide
            return
        audio = self.clips.get(sentence_id)
        if audio is None and record["clip"] == "ready":
            audio = await self.store.get_clip(day, sentence_id)
        if day != self.day:
            return
        if audio is None:
            peer.put(NoClip(sentence_id=sentence_id))
        else:
            voice = record.get("voice", "")
            peer.put(Clip(sentence_id=sentence_id, bytes=len(audio), voice=voice), audio)

    # --- sending ------------------------------------------------------------------------------

    def _broadcast(self, message: BaseModel, audio: bytes | None = None) -> None:
        text = message.model_dump_json()
        for peer in self.peers:
            peer.queue.put_nowait((text, audio))

    async def _sender(self, peer: Peer) -> None:
        """Sends one phone's queue in order: a clip's header and its MP3 always together."""
        try:
            while True:
                text, audio = await peer.queue.get()
                await peer.send_text(text)
                if audio is not None:
                    await peer.send_bytes(audio)
                peer.sent += 1
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the phone went away; its socket loop will notice
            log("send_failed", conn=peer.conn)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
