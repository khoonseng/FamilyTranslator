"""What every provider adapter returns (hard rule 6). The pipeline uses only these types, never a
provider SDK, so tests can swap in fakes."""

from collections.abc import Awaitable
from dataclasses import dataclass, field


@dataclass
class Attempt:
    """One provider tried for a sentence and why it was passed over: "429", "deadline",
    "timeout", "rejected" (400: e.g. a sentence too long for a Chirp 3 HD voice), "junk",
    "bad_json" or "error". Logged as is: no text."""

    provider: str
    outcome: str
    seconds: float


@dataclass
class TokenUsage:
    """The last item a chat stream yields: what the reply cost (spending meter)."""

    input: int
    output: int


@dataclass
class Translation:
    """`yue` is ready as soon as it is complete, so TTS can start; `en` follows (hard rule 3)."""

    yue: str
    en: Awaitable[str]
    provider: str
    yue_s: float  # request start -> `yue` complete
    attempts: list[Attempt] = field(default_factory=list)


class TranslationFailed(Exception):
    """Every translator failed on a sentence; the hub operator interprets (architecture doc)."""

    def __init__(self, attempts: list[Attempt]):
        super().__init__(", ".join(f"{a.provider}:{a.outcome}" for a in attempts))
        self.attempts = attempts


@dataclass
class Speech:
    audio: bytes  # MP3
    voice: str
    seconds: float
    attempts: list[Attempt] = field(default_factory=list)


class SpeechFailed(Exception):
    def __init__(self, attempts: list[Attempt]):
        super().__init__(", ".join(f"{a.provider}:{a.outcome}" for a in attempts))
        self.attempts = attempts


@dataclass
class SttFinal:
    """A final transcript from the stream. `end_s` is where it ends in the stream's audio
    (Chirp 3's result_end_offset), which the safety net compares with segment ends."""

    text: str
    end_s: float
    language: str = ""


def outcome_of(exc: BaseException) -> str:
    """Short, text-free failure label for logs and failover decisions."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429 or "429" in type(exc).__name__ or "RateLimit" in type(exc).__name__:
        return "429"
    if isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__:
        return "timeout"
    if status == 400:
        return "rejected"
    return "error"
