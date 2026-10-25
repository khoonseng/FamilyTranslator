"""Translation with per-sentence failover (hard rules 4 and 6): the LLMs in config order
(Gemini, then Qwen), then Google Cloud Translation as the last resort.

A sentence moves to the next provider at once, never retried, when the current one:
- errors or refuses (a Vertex 429 can last for long stretches);
- is a model with a deadline (Gemini) and its `yue` isn't complete within `yue_deadline_s`;
- returns `yue` containing Latin letters: a junk word such as "goods" (run 6, 24 Oct).

`yue` is returned as soon as its closing quote streams in, so TTS can start; `en` keeps
streaming in the background (the field TTS needs comes first, architecture doc)."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from time import perf_counter

from app import config
from app.providers.base import Attempt, Translation, TranslationFailed, outcome_of

_YUE = re.compile(r'"yue"\s*:\s*"((?:[^"\\]|\\.)*)"')
_LATIN = re.compile(r"[A-Za-z]")


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


def translation_messages(text: str, context: list[str]) -> list[dict]:
    """The guide → family prompt with the glossary and the previous sentences (hard rule 7)."""
    system = (
        config.prompt("guide_to_family")
        .replace("{glossary}", config.glossary_text())
        .replace("{context}", "\n".join(f"- {c}" for c in context) or "(none)")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


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

    async def translate(self, text: str, context: list[str]) -> Translation:
        started = perf_counter()
        messages = translation_messages(text, context)
        attempts: list[Attempt] = []
        for model in self.models:
            t0 = perf_counter()
            try:
                yue, en = await self._from_llm(model, messages)
            except _Skip as skip:
                outcome = skip.outcome
            except Exception as exc:  # noqa: BLE001 - any failure moves to the next provider
                outcome = outcome_of(exc)
            else:
                return Translation(
                    yue, en, model.name, round(perf_counter() - started, 3), attempts
                )
            attempts.append(Attempt(model.name, outcome, round(perf_counter() - t0, 3)))
        return await self._from_fallback(text, started, attempts)

    async def _from_llm(self, model, messages: list[dict]) -> tuple[str, asyncio.Task]:
        reply = ""
        pieces: AsyncIterator[str] = model.stream(messages)

        async def until_yue() -> re.Match | None:
            nonlocal reply
            async for piece in pieces:
                reply += piece
                if match := _YUE.search(reply):
                    return match
            return None

        limit = self.yue_deadline_s if model.deadline else self.timeout_s
        try:
            async with asyncio.timeout(limit):
                match = await until_yue()
        except TimeoutError:
            await pieces.aclose()
            raise _Skip("deadline" if model.deadline else "timeout") from None
        except BaseException:
            await pieces.aclose()
            raise
        if match:
            yue = json.loads(f'"{match.group(1)}"').strip()
        else:  # the stream ended without a recognisable "yue": one last look at the whole reply
            yue = str((parse_json_object(reply) or {}).get("yue", "")).strip()
        if not yue:
            await pieces.aclose()
            raise _Skip("bad_json")
        if _LATIN.search(yue):
            await pieces.aclose()
            raise _Skip("junk")
        return yue, asyncio.ensure_future(self._rest_en(pieces, reply))

    async def _rest_en(self, pieces: AsyncIterator[str], reply: str) -> str:
        """Reads the rest of the reply for `en`. Never raises: English is a nice-to-have."""
        try:
            async with asyncio.timeout(self.timeout_s):
                async for piece in pieces:
                    reply += piece
        except Exception:  # noqa: BLE001
            await pieces.aclose()
        return str((parse_json_object(reply) or {}).get("en", "")).strip()

    async def _from_fallback(
        self, text: str, started: float, attempts: list[Attempt]
    ) -> Translation:
        t0 = perf_counter()
        yue_task, en_task = self.fallback.translate(text)
        try:
            yue = (await asyncio.wait_for(yue_task, self.timeout_s)).strip()
            if not yue:
                raise ValueError("empty")
        except Exception as exc:  # noqa: BLE001
            en_task.cancel()
            attempts.append(
                Attempt(self.fallback.name, outcome_of(exc), round(perf_counter() - t0, 3))
            )
            raise TranslationFailed(attempts) from None

        async def en() -> str:
            try:
                return (await asyncio.wait_for(en_task, self.timeout_s)).strip()
            except Exception:  # noqa: BLE001
                return ""

        return Translation(
            yue,
            asyncio.ensure_future(en()),
            self.fallback.name,
            round(perf_counter() - started, 3),
            attempts,
        )
