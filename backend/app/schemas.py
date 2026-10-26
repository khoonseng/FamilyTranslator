"""Every JSON message on the room WebSocket (`/ws/room`), for the hub and every listener.
Audio travels as binary frames: 16 kHz 16-bit mono PCM from the hub, and MP3 clips to every
phone, each clip right after its `clip` header."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

# --- phone -> server --------------------------------------------------------------------------


class Hello(BaseModel):
    """First message (hard rule 1).
    - hub: the hub PIN and the API token;
    - listener: the room token from the join link; a host listener (owner, wife) also sends
      the PIN and API token, which unlock the host controls.
    `day` and `last_id`: the trip-local day the phone's bubbles are from and the last sentence
    it already has, for catch-up. Sentence numbers restart each day.
    `takeover` (hub only): true when someone tapped Start or Become hub, which replaces the
    current hub; false on an automatic reconnect, which never displaces another phone that took
    over meanwhile (e.g. while the old hub was in a dead zone): it joins as a listener."""

    type: Literal["hello"] = "hello"
    role: Literal["hub", "listener"]
    room: str = ""
    pin: str = ""
    token: str = ""
    day: str = ""
    last_id: int = Field(default=0, ge=0)
    takeover: bool = False


class Mode(BaseModel):
    """Guide is a latch (hard rule 8); `off` stops listening."""

    type: Literal["mode"] = "mode"
    mode: Literal["guide", "off"]


class SegmentStart(BaseModel):
    """The hub's VAD heard speech start. `pause_s` is the silence before it (bubble rule)."""

    type: Literal["segment_start"] = "segment_start"
    pause_s: float = Field(ge=0)


class SegmentEnd(BaseModel):
    """The hub's VAD cut a segment: a pause, or the 15 s cap."""

    type: Literal["segment_end"] = "segment_end"


class TypedText(BaseModel):
    """Mandarin typed on the hub; skips speech-to-text."""

    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=500)


class ClipRequest(BaseModel):
    """Any phone: send me this sentence's clip again (missing from my cache)."""

    type: Literal["clip_request"] = "clip_request"
    sentence_id: int


class GuideControl(BaseModel):
    """Host listeners only: pause or resume the hub's Guide listening (remote pause)."""

    type: Literal["guide_control"] = "guide_control"
    paused: bool


class LinkRequest(BaseModel):
    """Host listeners only: send me the join link's token; with `new`, make a new one first
    (the old link stops working and phones still on it are disconnected)."""

    type: Literal["link"] = "link"
    new: bool = False


PhoneMessage = Annotated[
    Hello | Mode | SegmentStart | SegmentEnd | TypedText | ClipRequest | GuideControl | LinkRequest,
    Field(discriminator="type"),
]
phone_message = TypeAdapter(PhoneMessage)

# --- server -> phone --------------------------------------------------------------------------


class Ready(BaseModel):
    """The phone is in. `role` and `host` tell its page what to show (a hub reconnecting after
    another phone took over gets `listener`). `day` is the room's
    trip-local day; if the phone's bubbles are from another day, it clears them. Sentences up to
    `latest_id` that follow are catch-up, not live."""

    type: Literal["ready"] = "ready"
    role: Literal["hub", "listener"]
    host: bool = False
    day: str = ""
    latest_id: int = 0


class DayChange(BaseModel):
    """A new trip-local day started: every phone clears its bubbles; numbering restarts."""

    type: Literal["day"] = "day"
    day: str


class Spend(BaseModel):
    """To host listeners only: today's estimated cost; `warn` above the daily threshold. The
    hub (the guide's screen) never gets it, and it never stops translation."""

    type: Literal["spend"] = "spend"
    usd: float
    warn: bool
    warn_usd: float


class JoinLink(BaseModel):
    """To host phones: the token for the family's join link, /join#<token>."""

    type: Literal["join_link"] = "join_link"
    token: str


class Role(BaseModel):
    """To the old hub: another phone took over as hub (Start on the hub page, or Become hub on a
    host phone, which opens the hub page), so this one is now a listener."""

    type: Literal["role"] = "role"
    role: Literal["listener"] = "listener"
    reason: Literal["replaced"] = "replaced"


class HubStatus(BaseModel):
    """Sent to every phone when it changes. `online` turns false after about 20 s without a hub.
    `remote_paused`: a host phone paused Guide listening."""

    type: Literal["hub_status"] = "hub_status"
    online: bool
    listening: bool
    remote_paused: bool


class GuideRemote(BaseModel):
    """To the hub: a host phone paused or resumed Guide listening."""

    type: Literal["guide_remote"] = "guide_remote"
    paused: bool


class Error(BaseModel):
    type: Literal["error"] = "error"
    code: str  # e.g. "bad_credentials", "bad_message"
    message: str = ""


class Sentence(BaseModel):
    """One sentence, sent as soon as its Cantonese is ready, in order. `zh` is the transcript
    (or typed text), never regenerated. If every translator failed, `yue` is empty and the hub
    operator interprets (architecture doc, "Failover")."""

    type: Literal["sentence"] = "sentence"
    id: int
    bubble_id: int
    zh: str
    yue: str
    status: Literal["ok", "no_translation"] = "ok"
    provider: str = ""  # which translator produced it (gemini, qwen, cloud-translate)


class Clip(BaseModel):
    """Header for the sentence's MP3, which follows as the next binary frame. Clips arrive in
    sentence order, each after its sentence."""

    type: Literal["clip"] = "clip"
    sentence_id: int
    bytes: int


class NoClip(BaseModel):
    """Every voice failed for this sentence: text only."""

    type: Literal["no_clip"] = "no_clip"
    sentence_id: int


class English(BaseModel):
    """The sentence's English, which finishes after the Cantonese (shown from weeks 4–5)."""

    type: Literal["english"] = "english"
    sentence_id: int
    en: str
