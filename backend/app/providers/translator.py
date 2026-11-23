"""Translation with per-sentence failover (hard rules 4 and 6): the LLMs in config order
(Gemini, Qwen, gpt-oss), then Google Cloud Translation as the last resort.

Two directions, each with its own prompt and reply fields, set per language profile in config
(`translation.directions`; owner decision 2026-11-23). In the Chongqing profile:
- `guide`: the guide's Mandarin → `yue` (spoken to the family), then `en`;
- `family` (phase 2): a family member's Cantonese or English → `zh_hans` (spoken to the guide),
  then `other` (English for Cantonese, Cantonese for English).

A sentence moves to the next provider at once, never retried, when the current one:
- errors or refuses (a Vertex 429 can last for long stretches);
- is a model with a deadline (Gemini) and its first field isn't complete within
  `yue_deadline_s`;
- (a direction with `latin_is_junk`, the guide's) returns a spoken field containing Latin
  letters: a junk word such as "goods" (run 6, 24 Oct). Replies skip this check: English
  speakers use names, which stay in Latin letters.

The first field is returned as soon as its closing quote streams in, so TTS can start; the
second keeps streaming in the background (the field TTS needs comes first, architecture doc)."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import perf_counter

from app import config
from app.providers.base import Attempt, TokenUsage, Translation, TranslationFailed, outcome_of

_LATIN = re.compile(r"[A-Za-z]")
_CJK = re.compile(r"[一-鿿]")


@dataclass(frozen=True)
class Direction:
    prompt: str
    speech: str  # the JSON field the voice speaks, first in the reply
    other: str  # the second field
    latin_is_junk: bool

    def field(self, name: str) -> re.Pattern:
        return re.compile(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"')


DIRECTION_NAMES = ("guide", "family")


def direction_of(name: str) -> Direction:
    """A direction's prompt and reply fields, from the language profile's config."""
    d = config.load()["translation"]["directions"][name]
    return Direction(d["prompt"], d["speech_key"], d["other_key"], bool(d["latin_is_junk"]))


def parse_json_object(text: str) -> dict | None:
    """The first JSON object in a reply (tolerates code fences or chatter)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def translation_messages(text: str, context: list[str], direction: str = "guide") -> list[dict]:
    """The direction's prompt with the glossary and the previous sentences (hard rule 7)."""
    system = (
        config.prompt(direction_of(direction).prompt)
        .replace("{glossary}", config.glossary_text())
        .replace("{context}", "\n".join(f"- {c}" for c in context) or "(none)")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def fallback_targets(text: str, direction: str) -> tuple[str, str]:
    """Cloud Translation's two target languages (`translation.fallback` in config). For a reply
    the second one is the family's other language: in the Chongqing profile, English if the
    reply is written in Chinese characters (Cantonese), else Cantonese. This only picks a
    display language for typed or transcribed text."""
    f = config.load()["translation"]["fallback"][direction]
    if "other" in f:
        return f["speech"], f["other"]
    return f["speech"], (f["other_if_cjk"] if _CJK.search(text) else f["other_else"])


def fallback_source(direction: str) -> str:
    """The source language Cloud Translation is told, or "" to let Google detect it."""
    return config.load()["translation"]["fallback"][direction]["source"] or ""


def _estimate_tokens(messages: list[dict]) -> int:
    """About three characters per token for this prompt (Vertex counted 995 tokens for a prompt
    this estimate puts at 983)."""
    return sum(len(m["content"]) for m in messages) // 3


class _Stream:
    """A chat reply as it streams in: its text so far, and its TokenUsage once it arrives."""

    def __init__(self, pieces: AsyncIterator):
        self.pieces = pieces
        self.text = ""
        self.usage: TokenUsage | None = None

    async def read_until(self, pattern: re.Pattern | None) -> re.Match | None:
        """Reads until `pattern` matches the text (or, with None, to the end)."""
        async for piece in self.pieces:
            if isinstance(piece, TokenUsage):
                self.usage = piece
                continue
            self.text += piece
            if pattern and (match := pattern.search(self.text)):
                return match
        return None

    async def close(self) -> None:
        await self.pieces.aclose()


class _Skip(Exception):
    def __init__(self, outcome: str):
        self.outcome = outcome


class Translator:
    def __init__(self, models: list, fallback, yue_deadline_s: float, timeout_s: float):
        """models: ChatModel-like objects (name, deadline, stream()); fallback: CloudTranslate."""
        self.models = models
        self.fallback = fallback
        self.yue_deadline_s = yue_deadline_s
        self.timeout_s = timeout_s
        self.meter = None  # the room's spending meter, if any

    def _bill(self, name: str, usage: TokenUsage) -> bool:
        if self.meter:
            self.meter.llm(name, usage.input, usage.output)
        return True

    async def warm_up(self) -> None:
        for model in self.models:
            if hasattr(model, "warm_up"):
                try:
                    await model.warm_up()
                except Exception:  # noqa: BLE001 - the first sentence will simply fail over
                    pass

    async def translate(
        self, text: str, context: list[str], direction: str = "guide"
    ) -> Translation:
        started = perf_counter()
        way = direction_of(direction)
        messages = translation_messages(text, context, direction)
        attempts: list[Attempt] = []
        for model in self.models:
            t0 = perf_counter()
            try:
                speech, other = await self._from_llm(model, messages, way)
            except _Skip as skip:
                outcome = skip.outcome
            except Exception as exc:  # noqa: BLE001 - any failure moves to the next provider
                outcome = outcome_of(exc)
            else:
                return Translation(
                    speech, other, model.name, round(perf_counter() - started, 3), attempts
                )
            attempts.append(Attempt(model.name, outcome, round(perf_counter() - t0, 3)))
        return await self._from_fallback(text, started, attempts, direction)

    async def _from_llm(self, model, messages: list[dict], way: Direction):
        stream = _Stream(model.stream(messages))
        try:
            return await self._speech_or_skip(model, stream, way)
        except BaseException:
            if stream.usage is None:  # an abandoned reply still cost its prompt: estimate it
                self._bill(model.name, TokenUsage(_estimate_tokens(messages), 0))
            raise

    async def _speech_or_skip(self, model, stream: "_Stream", way: Direction):
        limit = self.yue_deadline_s if model.deadline else self.timeout_s
        try:
            async with asyncio.timeout(limit):
                match = await stream.read_until(way.field(way.speech))
        except TimeoutError:
            await stream.close()
            raise _Skip("deadline" if model.deadline else "timeout") from None
        except BaseException:
            await stream.close()
            raise
        if stream.usage:
            self._bill(model.name, stream.usage)
        if match:
            speech = json.loads(f'"{match.group(1)}"').strip()
        else:  # the stream ended without a recognisable field: one last look at the whole reply
            speech = str((parse_json_object(stream.text) or {}).get(way.speech, "")).strip()
        if not speech:
            await stream.close()
            raise _Skip("bad_json")
        if way.latin_is_junk and _LATIN.search(speech):
            await stream.close()
            raise _Skip("junk")
        return speech, asyncio.ensure_future(self._rest(model.name, stream, way.other))

    async def _rest(self, name: str, stream: "_Stream", field: str) -> str:
        """Reads the rest of the reply for the second field. Never raises: it is a nice-to-have."""
        billed = stream.usage is not None
        try:
            async with asyncio.timeout(self.timeout_s):
                await stream.read_until(None)
        except Exception:  # noqa: BLE001
            await stream.close()
        if stream.usage and not billed:
            self._bill(name, stream.usage)
        return str((parse_json_object(stream.text) or {}).get(field, "")).strip()

    async def _from_fallback(
        self, text: str, started: float, attempts: list[Attempt], direction: str
    ) -> Translation:
        t0 = perf_counter()
        if self.meter:
            self.meter.mt(len(text) * 2)  # two calls
        first_task, second_task = self.fallback.translate(
            text, fallback_targets(text, direction), fallback_source(direction)
        )
        try:
            speech = (await asyncio.wait_for(first_task, self.timeout_s)).strip()
            if not speech:
                raise ValueError("empty")
        except Exception as exc:  # noqa: BLE001
            second_task.cancel()
            attempts.append(
                Attempt(self.fallback.name, outcome_of(exc), round(perf_counter() - t0, 3))
            )
            raise TranslationFailed(attempts) from None

        async def other() -> str:
            try:
                return (await asyncio.wait_for(second_task, self.timeout_s)).strip()
            except Exception:  # noqa: BLE001
                return ""

        return Translation(
            speech,
            asyncio.ensure_future(other()),
            self.fallback.name,
            round(perf_counter() - started, 3),
            attempts,
        )
