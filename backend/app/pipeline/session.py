"""One hub connection's pipeline (hard rules 8 and 9).

Audio: the hub's VAD sends `segment_start`, PCM frames (speech plus its own pause detection,
about 0.6-0.8 s), then `segment_end`. Each segment gets its own Chirp 3 stream, opened at its
start and closed at its end, which makes Chirp 3 return the final transcript at once (decided
2026-10-25: a long-lived stream lost a whole segment of real guide speech in testing).

Each final transcript is split into sentences at punctuation; the junk filter drops chatter,
filler and fragments; every kept sentence is translated and spoken as soon as it is ready,
concurrently, but sent to the hub strictly in order: its text first, then its clip. A later
segment's sentences wait for the earlier segment's. Typed Mandarin skips speech-to-text and
the junk filter.

Logs carry ids, labels and timings only, never text or audio (hard rule 14)."""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter

from app.logs import log
from app.pipeline.bubbles import Bubbles
from app.pipeline.text import drop_reason, split_sentences
from app.providers.base import SpeechFailed, TranslationFailed
from app.schemas import (
    Clip,
    English,
    Mode,
    NoClip,
    SegmentEnd,
    SegmentStart,
    Sentence,
    TypedText,
)

BYTES_PER_SECOND = 16_000 * 2  # 16 kHz, 16-bit mono


@dataclass
class _Live:
    """One hub segment's Chirp 3 stream."""

    chirp: object  # ChirpStream (or a fake in tests)
    bubble: int
    previous: asyncio.Task | None  # the earlier segment's consumer: its sentences go first
    consumer: asyncio.Task | None = None
    ended_at: float | None = None


def _done() -> asyncio.Future:
    future = asyncio.get_running_loop().create_future()
    future.set_result(None)
    return future


class HubSession:
    def __init__(
        self,
        providers,
        cfg: dict,
        send_json: Callable[[str], Awaitable[None]],
        send_bytes: Callable[[bytes], Awaitable[None]],
        conn: str = "",
    ):
        self.p = providers
        self.stt_cfg = cfg["stt"]["google"]
        self.pipe_cfg = cfg["pipeline"]
        self.context_n = cfg["translation"]["context_sentences"]
        self._send_json, self._send_bytes = send_json, send_bytes
        self._send_lock = asyncio.Lock()
        self.conn = conn
        self.mode = "off"
        self.bubbles = Bubbles(
            self.pipe_cfg["bubble_pause_s"],
            self.pipe_cfg["bubble_max_audio_s"],
            self.pipe_cfg["bubble_max_sentences"],
        )
        self.live: _Live | None = None  # the open segment's stream
        self._last_consumer: asyncio.Task | None = None
        self._next_id = 1
        self._context: deque[str] = deque(maxlen=self.context_n)
        self._text_done = _done()
        self._clip_done = _done()
        self._tasks: set[asyncio.Task] = set()
        self.closed = False

    # --- hub messages -------------------------------------------------------------------------

    async def start(self) -> None:
        self._spawn(self.p.translator.warm_up())

    async def on_message(self, message) -> None:
        if isinstance(message, Mode):
            await self._on_mode(message.mode)
        elif isinstance(message, SegmentStart):
            self._on_segment_start(message.pause_s)
        elif isinstance(message, SegmentEnd):
            self._on_segment_end()
        elif isinstance(message, TypedText):
            bubble = self.bubbles.new()
            for sentence in split_sentences(message.text) or [message.text.strip()]:
                self._dispatch(sentence, bubble, source="typed")

    def on_audio(self, pcm: bytes) -> None:
        """Speech frames count only in Guide mode, inside a segment."""
        if self.mode != "guide" or self.live is None:
            return
        self.live.chirp.send(pcm)
        self.bubbles.add_audio(self.live.bubble, len(pcm) / BYTES_PER_SECOND)

    async def close(self) -> None:
        self.closed = True
        for task in list(self._tasks):
            task.cancel()

    # --- the stream ---------------------------------------------------------------------------

    async def _on_mode(self, mode: str) -> None:
        self.mode = mode
        log("hub_mode", conn=self.conn, mode=mode)
        if mode == "off":
            self._end_segment()

    def _on_segment_start(self, pause_s: float) -> None:
        if self.mode != "guide":
            return
        self._end_segment()  # a segment_end that never came
        bubble = self.bubbles.on_segment(pause_s)
        live = _Live(self.p.stt.open(self.stt_cfg["guide_languages"]), bubble, self._last_consumer)
        live.consumer = self._last_consumer = self._spawn(self._consume(live))
        self.live = live

    def _on_segment_end(self) -> None:
        self._end_segment()

    def _end_segment(self) -> None:
        """Closing the stream makes Chirp 3 return the segment's final transcript at once."""
        if self.live is None:
            return
        live, self.live = self.live, None
        live.ended_at = perf_counter()
        self._spawn(live.chirp.close())

    async def _consume(self, live: _Live) -> None:
        if live.previous:  # sentences stay in speaking order across segments
            await asyncio.gather(live.previous, return_exceptions=True)
        while (final := await live.chirp.finals.get()) is not None:
            after_end = round(perf_counter() - live.ended_at, 3) if live.ended_at else None
            bubble = live.bubble
            kept = 0
            for sentence in split_sentences(final.text):
                reason = drop_reason(sentence, self.pipe_cfg)
                if reason:
                    log("sentence_dropped", conn=self.conn, reason=reason)
                    continue
                self._dispatch(sentence, bubble, source="speech")
                kept += 1
            log("stt_final", conn=self.conn, end_s=final.end_s, after_end_s=after_end, kept=kept)
        if live.chirp.error is not None:
            log("stt_error", conn=self.conn, error=type(live.chirp.error).__name__)
        log("stt_closed", conn=self.conn, audio_s=round(live.chirp.audio_s, 1))

    # --- one sentence -------------------------------------------------------------------------

    def _dispatch(self, zh: str, bubble_hint: int, source: str) -> None:
        sentence_id = self._next_id
        self._next_id += 1
        bubble = self.bubbles.on_sentence(bubble_hint)
        context = list(self._context)
        self._context.append(zh)
        loop = asyncio.get_running_loop()
        text_prev, clip_prev = self._text_done, self._clip_done
        self._text_done, self._clip_done = loop.create_future(), loop.create_future()
        self._spawn(
            self._process(
                sentence_id, bubble, zh, context, source,
                text_prev, self._text_done, clip_prev, self._clip_done,
            )
        )  # fmt: skip

    async def _process(
        self, sentence_id, bubble, zh, context, source, text_prev, text_mine, clip_prev, clip_mine
    ) -> None:
        started = perf_counter()
        fields = {"conn": self.conn, "id": sentence_id, "bubble": bubble, "source": source}
        try:
            try:
                translation = await self.p.translator.translate(zh, context)
            except TranslationFailed as failed:
                translation = None
                fields["attempts"] = [f"{a.provider}:{a.outcome}" for a in failed.attempts]
            await text_prev
            try:
                await self._send(
                    Sentence(
                        id=sentence_id,
                        bubble_id=bubble,
                        zh=zh,
                        yue=translation.yue if translation else "",
                        status="ok" if translation else "no_translation",
                        provider=translation.provider if translation else "",
                    ).model_dump_json()
                )
            finally:
                text_mine.set_result(None)
            if translation is None:
                fields["outcome"] = "no_translation"
                return
            fields |= {
                "provider": translation.provider,
                "attempts": [f"{a.provider}:{a.outcome}" for a in translation.attempts],
                "translate_s": translation.yue_s,
            }
            try:
                speech = await self.p.tts.speak(translation.yue)
                fields |= {"voice": speech.voice, "tts_s": speech.seconds}
            except SpeechFailed:
                speech = None
                fields["outcome"] = "no_clip"
            await clip_prev
            try:
                if speech:
                    await self._send(
                        Clip(sentence_id=sentence_id, bytes=len(speech.audio)).model_dump_json(),
                        speech.audio,
                    )
                else:
                    await self._send(NoClip(sentence_id=sentence_id).model_dump_json())
            finally:
                clip_mine.set_result(None)
            fields["total_s"] = round(perf_counter() - started, 3)
            fields.setdefault("outcome", "ok")
            en = await translation.en
            if en:
                await self._send(English(sentence_id=sentence_id, en=en).model_dump_json())
        finally:
            # Never leave later sentences waiting on this one.
            for future in (text_mine, clip_mine):
                if not future.done():
                    future.set_result(None)
            log("sentence", **fields)

    async def _send(self, text: str, audio: bytes | None = None) -> None:
        """A JSON message, and for clips the MP3 right after it, never interleaved."""
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self._send_json(text)
                if audio is not None:
                    await self._send_bytes(audio)
            except Exception:  # noqa: BLE001 - the hub went away; the session is closing
                self.closed = True

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
