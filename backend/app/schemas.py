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
    `last_id` is the last sentence the phone already has, for catch-up."""

    type: Literal["hello"] = "hello"
    role: Literal["hub", "listener"]
    room: str = ""
    pin: str = ""
    token: str = ""
    last_id: int = Field(default=0, ge=0)


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


class BecomeHub(BaseModel):
    """Host listeners only: make this phone the hub."""

    type: Literal["become_hub"] = "become_hub"


PhoneMessage = Annotated[
    Hello | Mode | SegmentStart | SegmentEnd | TypedText | ClipRequest | GuideControl | BecomeHub,
    Field(discriminator="type"),
]
phone_message = TypeAdapter(PhoneMessage)

# --- server -> phone --------------------------------------------------------------------------


class Ready(BaseModel):
    """The phone is in. `role` and `host` tell its page what to show."""

    type: Literal["ready"] = "ready"
    role: Literal["hub", "listener"]
    host: bool = False


class Role(BaseModel):
    """The phone's role changed: another phone took over as hub, or this one became the hub."""

    type: Literal["role"] = "role"
    role: Literal["hub", "listener"]
    reason: Literal["replaced", "became_hub"]


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
