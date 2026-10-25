"""Every JSON message on the hub WebSocket. Audio travels as binary frames: 16 kHz 16-bit mono
PCM from the hub, and MP3 clips to the hub, each clip right after its `clip` header."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

# --- hub -> server ----------------------------------------------------------------------------


class Hello(BaseModel):
    type: Literal["hello"] = "hello"
    pin: str


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
    code: str  # e.g. "bad_pin", "bad_message"
    message: str = ""


class Sentence(BaseModel):
    """One translated sentence. `zh` is the transcript (or typed text), never regenerated."""

    type: Literal["sentence"] = "sentence"
    id: int
    bubble_id: int
    zh: str
    yue: str
    en: str = ""
    provider: str = ""  # which translator produced it (gemini, qwen, cloud-translate)


class Clip(BaseModel):
    """Header for the MP3 that follows as the next binary frame."""

    type: Literal["clip"] = "clip"
    sentence_id: int
    bytes: int
