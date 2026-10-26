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
- Host controls (remote pause, Become hub, the join link) are refused for other phones.

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
from app.schemas import (
    BecomeHub,
    Clip,
    ClipRequest,
    DayChange,
    English,
    Error,
    GuideControl,
    GuideRemote,
    HubStatus,
    JoinLink,
    LinkRequest,
    Mode,
    NoClip,
    Ready,
    Role,
    SegmentEnd,
    SegmentStart,
    Sentence,
    TypedText,
)

HUB_MESSAGES = (Mode, SegmentStart, SegmentEnd, TypedText)
HOST_MESSAGES = (GuideControl, BecomeHub, LinkRequest)
JOIN_LINK = "settings/join.json"


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
        self.pipeline = self._new_pipeline()
        self.peers: set[Peer] = set()
        self.hub: Peer | None = None
        self.history: OrderedDict[int, dict] = OrderedDict()  # sentence id -> record
        self.clips: OrderedDict[int, bytes] = OrderedDict()  # the most recent clips
        self.join_token = ""
        self.listening = False  # the hub's Guide latch
        self.remote_paused = False
        self.hub_online = False
        self._offline: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

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
        log("room_start", sentences=len(records))
        await self.pipeline.start()

    # --- phones -------------------------------------------------------------------------------

    def join(self, conn, role, host, day, last_id, send_text, send_bytes, close=None) -> Peer:  # noqa: PLR0913
        self._check_day()
        peer = Peer(conn, "listener", host, send_text, send_bytes, close)
        if day != self.day:
            last_id = 0  # the phone's bubbles are from another day: it clears them
        latest = next(reversed(self.history), 0)
        peer.put(Ready(role=role, host=host, day=self.day, latest_id=latest))
        stored_clips = []
        for message, audio in self._catch_up(last_id):
            if message is None:
                stored_clips.append(audio)  # a clip id to fetch from the bucket
            else:
                peer.put(message, audio)
        self.peers.add(peer)
        peer.task = asyncio.create_task(self._sender(peer))
        if stored_clips:
            self._spawn(self._send_stored_clips(peer, stored_clips))
        if role == "hub":
            self._set_hub(peer)
        else:
            peer.put(self._status())
        log("room_join", conn=conn, role=role, host=host, phones=len(self.peers))
        return peer

    async def leave(self, peer: Peer) -> None:
        self.peers.discard(peer)
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
                self._broadcast(self._status())
            await self.pipeline.on_message(message)
        elif isinstance(message, ClipRequest):
            self._spawn(self._send_clip(peer, message.sentence_id))
        elif isinstance(message, HOST_MESSAGES):
            if not peer.host:
                peer.put(Error(code="not_host"))
                log("host_refused", conn=peer.conn)
                return
            if isinstance(message, BecomeHub):
                self._set_hub(peer)
                peer.put(Role(role="hub", reason="became_hub"))
            elif isinstance(message, GuideControl):
                self.remote_paused = message.paused
                if self.hub:
                    self.hub.put(GuideRemote(paused=message.paused))
                self._broadcast(self._status())
                log("guide_remote", conn=peer.conn, paused=message.paused)
            else:
                if message.new:
                    await self._new_join_link()
                peer.put(JoinLink(token=self.join_token))

    def on_audio(self, peer: Peer, pcm: bytes) -> None:
        if peer is self.hub:
            self.pipeline.on_audio(pcm)

    # --- the join link --------------------------------------------------------------------------

    async def _new_join_link(self) -> None:
        """A new token: the old link stops working, and phones still on it are disconnected
        (they show "This link no longer works")."""
        self.join_token = secrets.token_urlsafe(12)
        await self.store.put_json(JOIN_LINK, {"token": self.join_token})
        removed = 0
        for peer in list(self.peers):
            if peer.role == "listener" and not peer.host:
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
            old.put(Role(role="listener", reason="replaced"))
            self._spawn(self._hub_gone(offline_timer=False))
            log("hub_replaced", old=old.conn, new=peer.conn)
        self.hub = peer
        peer.role = "hub"
        if self._offline:
            self._offline.cancel()
            self._offline = None
        self.hub_online = True
        self._broadcast(self._status())

    async def _hub_gone(self, offline_timer: bool = True) -> None:
        """The hub left or was replaced: end its segment; listeners learn after a grace time."""
        await self.pipeline.on_message(Mode(mode="off"))
        self.listening = False
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
        return HubStatus(
            online=self.hub_online, listening=self.listening, remote_paused=self.remote_paused
        )

    # --- days ---------------------------------------------------------------------------------

    def _new_pipeline(self) -> Pipeline:
        return Pipeline(self.providers, self.full_cfg, self._publish, conn="room")

    def _check_day(self) -> None:
        """At the first activity after midnight (trip-local), start a new day."""
        today = self.today()
        if today == self.day:
            return
        old = self.pipeline
        self._spawn(old.on_message(Mode(mode="off")))
        self.day = today
        self.history.clear()
        self.clips.clear()
        self.pipeline = self._new_pipeline()
        self._spawn(self.pipeline.start())
        self._broadcast(DayChange(day=today))
        log("day_change")

    # --- sentences ----------------------------------------------------------------------------

    async def _publish(self, message: BaseModel, audio: bytes | None) -> None:
        """Everything the pipeline produces: remember it, save it, send it to every phone."""
        day = self.day
        if isinstance(message, Sentence):
            self.history[message.id] = message.model_dump() | {"en": "", "clip": "pending"}
        elif isinstance(message, Clip) and audio is not None:
            self.clips[message.sentence_id] = audio
            while len(self.clips) > self.cfg["clips_in_memory"]:
                self.clips.popitem(last=False)
            self._set(message.sentence_id, clip="ready")
            self._spawn(self._save(day, message.sentence_id, audio))
        elif isinstance(message, NoClip):
            self._set(message.sentence_id, clip="none")
            self._spawn(self._save(day, message.sentence_id))
        elif isinstance(message, English):
            self._set(message.sentence_id, en=message.en)
            self._spawn(self._save(day, message.sentence_id))
        self._broadcast(message, audio)

    def _set(self, sentence_id: int, **fields) -> None:
        if sentence_id in self.history:
            self.history[sentence_id].update(fields)

    async def _save(self, day: str, sentence_id: int, mp3: bytes | None = None) -> None:
        """Writes the clip (if any), then the record. Never delays the live stream."""
        try:
            if mp3 is not None:
                await self.store.put_clip(day, sentence_id, mp3)
            if sentence_id in self.history:
                await self.store.put_sentence(day, dict(self.history[sentence_id]))
        except Exception as exc:  # noqa: BLE001 - the live stream matters more than the copy
            log("store_error", id=sentence_id, error=type(exc).__name__)

    def _catch_up(self, last_id: int):
        """Everything after `last_id`: all the text first, so the screen fills quickly, then
        the clips. A clip no longer in memory comes back as (None, sentence_id), to be fetched
        from the bucket."""
        newer = [r for sid, r in self.history.items() if sid > last_id]
        for record in newer:
            yield Sentence(**{k: record[k] for k in Sentence.model_fields if k != "type"}), None
            if record["en"]:
                yield English(sentence_id=record["id"], en=record["en"]), None
        for record in newer:
            if record["clip"] == "none":
                yield NoClip(sentence_id=record["id"]), None
            elif record["id"] in self.clips:
                audio = self.clips[record["id"]]
                yield Clip(sentence_id=record["id"], bytes=len(audio)), audio
            elif record["clip"] == "ready":
                yield None, record["id"]

    async def _send_stored_clips(self, peer: Peer, sentence_ids: list[int]) -> None:
        for sentence_id in sentence_ids:
            await self._send_clip(peer, sentence_id)

    async def _send_clip(self, peer: Peer, sentence_id: int) -> None:
        """A clip on request: from memory, else from the bucket, else 'no clip'."""
        record = self.history.get(sentence_id)
        if record is None or record["clip"] == "pending":
            return  # unknown, or still being spoken: it arrives live
        audio = self.clips.get(sentence_id)
        if audio is None and record["clip"] == "ready":
            audio = await self.store.get_clip(self.day, sentence_id)
        if audio is None:
            peer.put(NoClip(sentence_id=sentence_id))
        else:
            peer.put(Clip(sentence_id=sentence_id, bytes=len(audio)), audio)

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
