"""The room's pipeline (hard rules 8 and 9). It belongs to the room, not to a hub connection,
so a hub reconnect or takeover carries on with the same bubbles, numbering and context.

Audio: the hub's VAD sends `segment_start`, PCM frames (speech plus its own pause detection,
about 0.6-0.8 s), then `segment_end`. Each segment gets its own Chirp 3 stream, opened at its
start and closed at its end, which makes Chirp 3 return the final transcript at once (decided
2026-10-25: a long-lived stream lost a whole segment of real guide speech in testing).

Safety net (hard rule 9): the session keeps each segment's audio. When its stream ends, audio
that Chirp 3's finals don't reach to within `gap_s` of the end goes to `gpt-transcribe`; if
the stream failed, the whole segment does. Each new stream is a fresh try, so the fallback
lasts only as long as Chirp 3 keeps failing.

Transcripts are split into sentences at punctuation. A trailing piece without sentence-ending
punctuation is held: a pause mid-sentence ends a segment, and the next segment's words are
joined to it if the guide carries on within `hold_s`; otherwise it goes on as it is (decided
2026-10-25). The junk filter (text layers, then echo detection) drops chatter, filler,
fragments and our own Cantonese overheard from a listener's speaker. Every kept sentence is
translated and spoken as soon as it is ready, concurrently, but sent to the hub strictly in
order: its text first, then its clip. A later segment's sentences wait for the earlier
segment's. Typed Mandarin skips speech-to-text and the junk filter.

Logs carry ids, labels and timings only, never text or audio (hard rule 14)."""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import perf_counter

from pydantic import BaseModel

from app.logs import log
from app.pipeline.bubbles import Bubbles
from app.pipeline.echo import EchoGuard
from app.pipeline.text import drop_reason, is_complete, split_sentences
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
    pcm: bytearray = field(default_factory=bytearray)  # kept for the safety net
    covered_s: float = 0.0  # how far Chirp 3's finals reach into the segment's audio


@dataclass
class _Pending:
    """The start of a sentence that a pause cut off, waiting for the rest."""

    text: str
    bubble: int
    carried: int = 0  # segments that ended without finishing it


def _done() -> asyncio.Future:
    future = asyncio.get_running_loop().create_future()
    future.set_result(None)
    return future


class Pipeline:
    def __init__(
        self,
        providers,
        cfg: dict,
        publish: Callable[[BaseModel, bytes | None], Awaitable[None]],
        conn: str = "",
    ):
        """publish(message, audio): every message the pipeline produces, with the MP3 for a
        `clip` header. The room stores it and sends it to every phone."""
        self.p = providers
        self.stt_cfg = cfg["stt"]["google"]
        self.net_cfg = cfg["stt"]["safety_net"]
        self.pipe_cfg = cfg["pipeline"]
        self.context_n = cfg["translation"]["context_sentences"]
        self._publish = publish
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
        self._pending: _Pending | None = None
        self._flush: asyncio.Task | None = None
        self.echo = EchoGuard(self.pipe_cfg["echo_window_s"], self.pipe_cfg["echo_max_mismatch"])
        self._next_id = 1
        self._context: deque[str] = deque(maxlen=self.context_n)
        self._text_done = _done()
        self._clip_done = _done()
        self._tasks: set[asyncio.Task] = set()
        self.closed = False

    # --- hub messages -------------------------------------------------------------------------

    def resume(self, next_id: int, next_bubble: int, context: list[str]) -> None:
        """After a restart: carry on the day's numbering and translation context."""
        self._next_id = next_id
        self.bubbles.resume(next_bubble)
        self._context.extend(context[-self.context_n :])

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
        self.live.pcm.extend(pcm)
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
            # Once the last segment is transcribed, its half-sentence goes on as it is.
            last = self._last_consumer
            self._spawn(self._flush_after(last))

    def _on_segment_start(self, pause_s: float) -> None:
        if self.mode != "guide":
            return
        self._end_segment()  # a segment_end that never came
        if self._flush:  # the guide carried on: the held half-sentence waits for this segment
            self._flush.cancel()
            self._flush = None
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
            live.covered_s = max(live.covered_s, final.end_s)
            kept = self._take(final.text, live.bubble)
            log("stt_final", conn=self.conn, end_s=final.end_s, after_end_s=after_end, kept=kept)
        if live.chirp.error is not None:
            log("stt_error", conn=self.conn, error=type(live.chirp.error).__name__)
        log("stt_closed", conn=self.conn, audio_s=round(live.chirp.audio_s, 1))
        await self._safety_net(live)
        self._hold_or_flush()

    async def _safety_net(self, live: _Live) -> None:
        """Hard rule 9: speech Chirp 3 skipped, or a failed stream, goes to gpt-transcribe."""
        audio_s = len(live.pcm) / BYTES_PER_SECOND
        if live.chirp.error is not None:
            reason, start_s = "stream_failed", 0.0
        elif audio_s - live.covered_s > self.net_cfg["gap_s"]:
            reason, start_s = "uncovered", max(0.0, live.covered_s - self.net_cfg["back_s"])
        else:
            return
        start = int(start_s * BYTES_PER_SECOND) // 2 * 2
        if (len(live.pcm) - start) / BYTES_PER_SECOND < self.net_cfg["min_s"]:
            return
        t0 = perf_counter()
        try:
            text = await self.p.transcribe.transcribe(bytes(live.pcm[start:]))
        except Exception as exc:  # noqa: BLE001 - the segment is lost; the guide carries on
            log("safety_net", conn=self.conn, reason=reason, outcome=type(exc).__name__)
            return
        if self.net_cfg["prompt_echo"] in text:  # a known hallucination on silence
            text = ""
        kept = self._take(text, live.bubble) if text else 0
        log(
            "safety_net",
            conn=self.conn,
            reason=reason,
            audio_s=round((len(live.pcm) - start) / BYTES_PER_SECOND, 2),
            seconds=round(perf_counter() - t0, 3),
            kept=kept,
        )

    # --- transcripts into sentences -----------------------------------------------------------

    def _take(self, text: str, bubble: int) -> int:
        """Splits new transcript text into sentences, joined to a held half-sentence, and holds
        a new unfinished tail. Returns how many sentences were kept."""
        if self._pending:
            text, bubble = self._pending.text + text, self._pending.bubble
            self._pending = None
        sentences = split_sentences(text)
        if sentences and not is_complete(sentences[-1]):
            self._pending = _Pending(sentences.pop(), bubble)
        return sum(self._accept(sentence, bubble) for sentence in sentences)

    def _accept(self, sentence: str, bubble: int) -> bool:
        """Junk filter (hard rule 8): the text layers, then echo detection."""
        reason = drop_reason(sentence, self.pipe_cfg)
        if reason is None and self.echo.is_echo(sentence):
            reason = "echo"
        if reason:
            log("sentence_dropped", conn=self.conn, reason=reason)
            return False
        self._dispatch(sentence, bubble, source="speech")
        return True

    def _hold_or_flush(self) -> None:
        """After a segment: keep holding a half-sentence for the next one, or let it go."""
        if not self._pending:
            return
        self._pending.carried += 1
        if self._pending.carried > 1:  # the next segment didn't finish it either
            self._flush_pending()
        elif self.live is None:  # no new segment yet: wait a moment for the guide to go on
            self._flush = self._spawn(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(self.pipe_cfg["hold_s"])
        self._flush = None
        self._flush_pending()

    async def _flush_after(self, consumer: asyncio.Task | None) -> None:
        if consumer:
            await asyncio.gather(consumer, return_exceptions=True)
        if self._flush:
            self._flush.cancel()
            self._flush = None
        self._flush_pending()

    def _flush_pending(self) -> None:
        if self._pending:
            pending, self._pending = self._pending, None
            self._accept(pending.text, pending.bubble)

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
                    )
                )
            finally:
                text_mine.set_result(None)
            if translation is None:
                fields["outcome"] = "no_translation"
                return
            self.echo.remember(translation.yue)
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
                        Clip(sentence_id=sentence_id, bytes=len(speech.audio)), speech.audio
                    )
                else:
                    await self._send(NoClip(sentence_id=sentence_id))
            finally:
                clip_mine.set_result(None)
            fields["total_s"] = round(perf_counter() - started, 3)
            fields.setdefault("outcome", "ok")
            en = await translation.en
            if en:
                await self._send(English(sentence_id=sentence_id, en=en))
        finally:
            # Never leave later sentences waiting on this one.
            for future in (text_mine, clip_mine):
                if not future.done():
                    future.set_result(None)
            log("sentence", **fields)

    async def _send(self, message: BaseModel, audio: bytes | None = None) -> None:
        """One message at a time, so a clip's header and its MP3 are never interleaved."""
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self._publish(message, audio)
            except Exception as exc:  # noqa: BLE001 - keep the pipeline running
                log("publish_error", conn=self.conn, error=type(exc).__name__)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
