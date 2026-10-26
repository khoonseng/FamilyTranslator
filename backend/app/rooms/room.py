"""The one fixed room (architecture doc, "One fixed room, one active hub").

- Every phone connects to `/ws/room`: one hub, any number of listeners, some of them hosts.
- The pipeline belongs to the room, so a hub reconnect or takeover carries on with the same
  bubbles, sentence numbers and context.
- Fan-out: everything the pipeline publishes goes to every phone, each through its own send
  queue, so a phone on weak signal never delays the others.
- Catch-up: a joining phone first gets every sentence after its `last_id` (text, then the clips
  still in memory), then the live stream. Nothing is awaited in between, so nothing slips past.
- Host controls (remote pause, Become hub) are refused for phones that didn't sign in as host.

Logs carry connection ids, roles and counts only, never text or audio (hard rule 14)."""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.logs import log
from app.pipeline.session import Pipeline
from app.schemas import (
    BecomeHub,
    Clip,
    ClipRequest,
    English,
    Error,
    GuideControl,
    GuideRemote,
    HubStatus,
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


@dataclass(eq=False)
class Peer:
    """One connected phone and its own send queue."""

    conn: str
    role: str  # "hub" or "listener"
    host: bool
    send_text: Callable[[str], Awaitable[None]]
    send_bytes: Callable[[bytes], Awaitable[None]]
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    sent: int = 0

    def put(self, message: BaseModel, audio: bytes | None = None) -> None:
        self.queue.put_nowait((message.model_dump_json(), audio))


class Room:
    def __init__(self, providers, cfg: dict):
        self.cfg = cfg["rooms"]
        self.pipeline = Pipeline(providers, cfg, self._publish, conn="room")
        self.peers: set[Peer] = set()
        self.hub: Peer | None = None
        self.history: OrderedDict[int, dict] = OrderedDict()  # sentence id -> record
        self.clips: OrderedDict[int, bytes] = OrderedDict()  # the most recent clips
        self.listening = False  # the hub's Guide latch
        self.remote_paused = False
        self.hub_online = False
        self._offline: asyncio.Task | None = None

    async def start(self) -> None:
        await self.pipeline.start()

    # --- phones -------------------------------------------------------------------------------

    def join(self, conn: str, role: str, host: bool, last_id: int, send_text, send_bytes) -> Peer:
        peer = Peer(conn, "listener", host, send_text, send_bytes)
        peer.put(Ready(role=role, host=host))
        for message, audio in self._catch_up(last_id):
            peer.put(message, audio)
        self.peers.add(peer)
        peer.task = asyncio.create_task(self._sender(peer))
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
            if isinstance(message, Mode):
                self.listening = message.mode == "guide"
                if self.listening:
                    self.remote_paused = False
                self._broadcast(self._status())
            await self.pipeline.on_message(message)
        elif isinstance(message, ClipRequest):
            self._resend_clip(peer, message.sentence_id)
        elif isinstance(message, GuideControl | BecomeHub):
            if not peer.host:
                peer.put(Error(code="not_host"))
                log("host_refused", conn=peer.conn)
                return
            if isinstance(message, BecomeHub):
                self._set_hub(peer)
                peer.put(Role(role="hub", reason="became_hub"))
            else:
                self.remote_paused = message.paused
                if self.hub:
                    self.hub.put(GuideRemote(paused=message.paused))
                self._broadcast(self._status())
                log("guide_remote", conn=peer.conn, paused=message.paused)

    def on_audio(self, peer: Peer, pcm: bytes) -> None:
        if peer is self.hub:
            self.pipeline.on_audio(pcm)

    # --- the hub ------------------------------------------------------------------------------

    def _set_hub(self, peer: Peer) -> None:
        old = self.hub
        if old is not None and old is not peer:
            old.role = "listener"
            old.put(Role(role="listener", reason="replaced"))
            asyncio.create_task(self._hub_gone(offline_timer=False))
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

    # --- sentences ----------------------------------------------------------------------------

    async def _publish(self, message: BaseModel, audio: bytes | None) -> None:
        """Everything the pipeline produces: remember it, then send it to every phone."""
        if isinstance(message, Sentence):
            self.history[message.id] = message.model_dump() | {"en": "", "clip": "pending"}
        elif isinstance(message, Clip) and audio is not None:
            self.clips[message.sentence_id] = audio
            while len(self.clips) > self.cfg["clips_in_memory"]:
                self.clips.popitem(last=False)
            self._set(message.sentence_id, clip="ready")
        elif isinstance(message, NoClip):
            self._set(message.sentence_id, clip="none")
        elif isinstance(message, English):
            self._set(message.sentence_id, en=message.en)
        self._broadcast(message, audio)

    def _set(self, sentence_id: int, **fields) -> None:
        if sentence_id in self.history:
            self.history[sentence_id].update(fields)

    def _catch_up(self, last_id: int):
        """Everything after `last_id`: all the text first, so the screen fills quickly, then
        the clips still in memory. Missing clips can be asked for with `clip_request`."""
        newer = [r for sid, r in self.history.items() if sid > last_id]
        for record in newer:
            yield Sentence(**{k: record[k] for k in Sentence.model_fields if k != "type"}), None
            if record["en"]:
                yield English(sentence_id=record["id"], en=record["en"]), None
        for record in newer:
            yield from self._clip_items(record["id"])

    def _clip_items(self, sentence_id: int):
        record = self.history.get(sentence_id)
        if record is None:
            return
        if record["clip"] == "none":
            yield NoClip(sentence_id=sentence_id), None
        elif sentence_id in self.clips:
            audio = self.clips[sentence_id]
            yield Clip(sentence_id=sentence_id, bytes=len(audio)), audio

    def _resend_clip(self, peer: Peer, sentence_id: int) -> None:
        for message, audio in self._clip_items(sentence_id):
            peer.put(message, audio)

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
