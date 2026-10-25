"""Every JSON message on the hub WebSocket. Audio travels as binary frames: 16 kHz 16-bit mono
PCM from the hub, and MP3 clips to the hub, each clip right after its `clip` header."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

# --- hub -> server ----------------------------------------------------------------------------


class Hello(BaseModel):
    """First message: the hub PIN and the API token (hard rule 1)."""

    type: Literal["hello"] = "hello"
    pin: str
    token: str


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


HubMessage = Annotated[
    Hello | Mode | SegmentStart | SegmentEnd | TypedText, Field(discriminator="type")
]
hub_message = TypeAdapter(HubMessage)

# --- server -> hub ----------------------------------------------------------------------------


class Ready(BaseModel):
    type: Literal["ready"] = "ready"


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
