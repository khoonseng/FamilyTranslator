"""Step 6: the week-1 Cloud Run test service. Deleted after week 1; never part of the app.

/latency   time-to-first-audio. The phone measures its network (round trip, a 5 s upload, the
           MP3 download); Cloud Run times the pipeline on a stored Mandarin sample: Chirp 3
           streaming at real-time pace -> Gemini -> Cantonese TTS.
/locktest  does Cantonese audio keep playing on a locked iPhone? Numbered clips pushed over a
           WebSocket (as the app will), or "radio mode": one continuous MP3 stream.

The two pages, /health and /docs (the endpoint list) are open; the pages ask for the token once
and remember it. Every /api and /ws route needs PROBE_TOKEN (?t= or an X-Probe-Token header;
"Authorize" in /docs). Logs are JSON lines with timings only, never transcripts, translations
or audio (hard rule 14).

Run locally from bakeoff/: uv run uvicorn probe.app:app --port 8080
then open http://localhost:8080/latency. Deploy: probe/deploy.sh
"""

import asyncio
import io
import json
import os
import re
import secrets
import time
import uuid
from functools import cache
from pathlib import Path
from time import perf_counter

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request, Security, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.staticfiles import StaticFiles

from lib import audio, config
from lib.llm import ChatClient, translation_messages
from lib.scoring import parse_json_object
from lib.stt import GoogleStreamingStt
from lib.tts import GoogleTts

STATIC = Path(__file__).parent / "static"
CFG = config.load()  # also loads bakeoff/.env when run locally
PROBE = CFG["probe"]
TOKEN = os.environ.get("PROBE_TOKEN", "")
GUIDE_LANGUAGES = ["cmn-Hans-CN", "yue-Hant-HK"]  # Guide mode (hard rule 8)
TTS_RATE = 24_000  # Chirp 3 HD's own rate; radio mode re-encodes clips at this rate
RADIO_LEAD_S = 2.0  # radio mode stays this far ahead of real time (the phone's buffer)
RADIO_PIECE_S = 0.5
MAX_S = PROBE["locktest_max_minutes"] * 60
# The "yue" value is complete once its closing quote has streamed in; TTS could start then.
_YUE_DONE = re.compile(r'"yue"\s*:\s*"(?:[^"\\]|\\.)*"')

app = FastAPI(title="cq-probe", summary="Week-1 test service: /latency and /locktest")
app.mount("/static", StaticFiles(directory=STATIC), name="static")  # nothing secret in here
_runs: list[dict] = []  # latency results (timings only) while the instance lives
_clips: dict[str, bytes] = {}  # latency run id -> Cantonese MP3, last 20 runs
_locktest_clips: dict[int, tuple[bytes, np.ndarray]] = {}  # n -> (MP3, PCM at TTS_RATE)


def log(event: str, **fields) -> None:
    """One JSON line per event; Cloud Run turns it into a structured log entry."""
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def _authorised(token: str | None) -> bool:
    return bool(TOKEN) and bool(token) and secrets.compare_digest(token, TOKEN)


def check_token(
    query: str | None = Security(APIKeyQuery(name="t", auto_error=False)),
    header: str | None = Security(APIKeyHeader(name="X-Probe-Token", auto_error=False)),
) -> None:
    """Declared as API keys so that /docs shows an Authorize button."""
    if not _authorised(query or header):
        raise HTTPException(status_code=401, detail="Wrong or missing probe token")


Authorised = Depends(check_token)


@cache
def stt() -> GoogleStreamingStt:
    return GoogleStreamingStt(CFG["stt"]["google"], config.project())


@cache
def tts() -> GoogleTts:
    return GoogleTts(CFG["tts"]["google"])


@cache
def translator() -> ChatClient:
    return ChatClient(PROBE["translator"], CFG)


@cache
def phrases() -> list[str]:
    return [term["zh"] for term in config.glossary()]


@cache
def sample_pcm() -> bytes:
    """The Mandarin sample, synthesised once at 16 kHz, with the voice's leading and trailing
    silence cut so that "end of speech" is the last word."""
    google = CFG["tts"]["google"]
    r = tts().synthesize(
        PROBE["sample_text"],
        PROBE["sample_voice"],
        google["cmn_language"],
        encoding="LINEAR16",
        sample_rate_hz=audio.RATE,
    )
    pcm = audio.decode(io.BytesIO(r.audio))
    frame = audio.RATE // 100  # 10 ms
    loud = np.flatnonzero(audio.frame_db(pcm, frame) > -45)
    if len(loud):
        pcm = pcm[loud[0] * frame : (loud[-1] + 1) * frame]
    return pcm.tobytes()


@cache
def silence_mp3() -> bytes:
    return audio.mp3_bytes(np.zeros(TTS_RATE // 2, np.int16), TTS_RATE)


def locktest_clip(n: int) -> tuple[bytes, np.ndarray]:
    if n not in _locktest_clips:
        google = CFG["tts"]["google"]
        r = tts().synthesize(
            PROBE["locktest_text"].format(n=n), PROBE["voice"], google["yue_language"]
        )
        _locktest_clips[n] = (r.audio, audio.decode(io.BytesIO(r.audio), TTS_RATE))
    return _locktest_clips[n]


def _error(stage: str, exc: Exception) -> str:
    return f"{stage}: {type(exc).__name__}: {str(exc)[:200]}"


def latency_run() -> dict:
    """One pass of the guide -> family pipeline on the stored sample, timed per stage.

    server_s = Chirp 3's final transcript after the end of speech + translation until the
    "yue" text is complete (TTS can start then) + TTS. The text is returned to the page but
    never logged."""
    run: dict = {"run_id": uuid.uuid4().hex[:8], "at": time.time()}
    text: dict = {}
    streaming = CFG["stt"]["google"]["streaming"]
    stage = "stt"
    try:
        s = stt().stream(
            sample_pcm(),
            GUIDE_LANGUAGES,
            phrases(),
            frame_ms=streaming["frame_ms"],
            tail_silence_s=streaming["tail_silence_s"],
            endpointing="standard",
        )
        run["speech_s"] = s.speech_end_s
        run["stt_s"] = round(s.finalize_latency_s, 3) if s.finals else None
        text["transcript"] = s.text
        if not s.finals:
            raise RuntimeError("no final transcript")

        yue_at: list[float] = []

        def on_text(so_far: str) -> None:
            if not yue_at and _YUE_DONE.search(so_far):
                yue_at.append(perf_counter())

        stage = "translate"
        r = translator().chat(translation_messages("guide_to_family", s.text, []), on_text=on_text)
        returned = perf_counter()
        output = parse_json_object(r.text) or {}
        run["llm_ttft_s"] = round(r.ttft_s, 3) if r.ttft_s is not None else None
        # Counted back from the end, so it shares total_s's start (after any token refresh).
        run["llm_yue_s"] = round(r.total_s - (returned - yue_at[0]) if yue_at else r.total_s, 3)
        run["llm_total_s"] = round(r.total_s, 3)
        text["yue"] = output.get("yue", "")
        if not text["yue"]:
            raise RuntimeError("no yue in the reply")

        stage = "tts"
        google = CFG["tts"]["google"]
        clip = tts().synthesize(text["yue"], PROBE["voice"], google["yue_language"])
        run["tts_s"] = round(clip.latency_s, 3)
        run["mp3_kb"] = round(len(clip.audio) / 1000, 1)
        run["server_s"] = round(run["stt_s"] + run["llm_yue_s"] + run["tts_s"], 3)
        _clips[run["run_id"]] = clip.audio
        while len(_clips) > 20:
            _clips.pop(next(iter(_clips)))
    except Exception as exc:  # noqa: BLE001 - report the failed stage, keep the service up
        run["error"] = _error(stage, exc)
    _runs.append(run)
    log("latency_run", **run)
    return run | text


# --- pages ---------------------------------------------------------------------------------


@app.get("/health")  # not /healthz: Cloud Run reserves it
def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/latency", summary="Latency test page (asks for the token)")
def latency_page() -> FileResponse:
    return FileResponse(STATIC / "latency.html", headers={"Cache-Control": "no-store"})


@app.get("/locktest", summary="Locked-screen test page (asks for the token)")
def locktest_page() -> FileResponse:
    return FileResponse(STATIC / "locktest.html", headers={"Cache-Control": "no-store"})


# --- /latency API --------------------------------------------------------------------------


@app.get("/api/ping", dependencies=[Authorised])
def ping(request: Request) -> dict:
    """Tiny round trip. Also shows the phone's public IP, to check where its traffic exits
    (an SG roaming eSIM should exit in Singapore)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "")
    return {"ip": ip, "server_time": time.time()}


@app.post("/api/upload", dependencies=[Authorised])
async def upload(request: Request) -> dict:
    """Receives the phone's 5 s of 16 kHz PCM (160 KB) and discards it."""
    return {"bytes": len(await request.body())}


@app.post("/api/latency/run", dependencies=[Authorised])
def run_latency() -> dict:
    return latency_run()


@app.get("/api/clip/{run_id}", dependencies=[Authorised])
def clip(run_id: str) -> Response:
    if run_id not in _clips:
        raise HTTPException(status_code=404)
    return Response(_clips[run_id], media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/latency/client", dependencies=[Authorised])
async def latency_client(request: Request) -> dict:
    """The phone's own measurements for a run (network timings only)."""
    body = await request.json()
    fields = ("run_id", "rtt_s", "upload_s", "upload_kb_s", "download_s", "total_s", "network")
    entry = {k: body.get(k) for k in fields}
    for run in _runs:
        if run["run_id"] == entry["run_id"]:
            run["client"] = entry
    log("latency_client", **entry)
    return {"ok": True}


@app.get("/api/results", dependencies=[Authorised])
def results() -> dict:
    return {"latency": _runs}


# --- /locktest API -------------------------------------------------------------------------


@app.get("/api/silence.mp3", dependencies=[Authorised])
def silence() -> Response:
    """Half a second of silence, played on the start tap to unlock audio on iOS."""
    return Response(silence_mp3(), media_type="audio/mpeg")


@app.post("/api/locktest/event", dependencies=[Authorised])
async def locktest_event(request: Request) -> dict:
    """What the phone saw: clip received / played, screen hidden / visible, timer ticks."""
    body = await request.json()
    fields = ("session", "mode", "context", "type", "n", "at", "detail")
    log("locktest_client", **{k: body.get(k) for k in fields})
    return {"ok": True}


def _interval(value: str | float | None) -> float:
    """Seconds from one clip's start to the next: the page's choice, else config. Long ones
    mimic a guide who goes quiet, to see whether iOS suspends a locked page in the silence."""
    try:
        return min(600.0, max(5.0, float(value)))
    except (TypeError, ValueError):
        return float(PROBE["locktest_interval_s"])


@app.websocket("/ws/locktest")
async def ws_locktest(ws: WebSocket) -> None:
    """Pushes clip n every interval: a JSON {n} message, then the MP3 as a binary frame."""
    if not _authorised(ws.query_params.get("t")):
        await ws.close(code=1008)
        return
    await ws.accept()
    session = ws.query_params.get("session", "?")
    interval = _interval(ws.query_params.get("interval"))
    start = time.monotonic()
    log("locktest_ws_open", session=session, interval_s=interval)

    async def push() -> None:
        n = 0
        while time.monotonic() - start < MAX_S:
            n += 1
            mp3, _ = await run_in_threadpool(locktest_clip, n)
            await ws.send_json({"n": n, "sent_at": time.time()})
            await ws.send_bytes(mp3)
            log("locktest_sent", session=session, n=n, t=round(time.monotonic() - start, 1))
            await run_in_threadpool(locktest_clip, n + 1)  # ready before it is due
            await asyncio.sleep(max(0.0, start + n * interval - time.monotonic()))
        await ws.close()

    pusher = asyncio.create_task(push())
    try:
        while (await ws.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        pusher.cancel()
        log("locktest_ws_close", session=session, t=round(time.monotonic() - start, 1))


@app.get("/api/radio", dependencies=[Authorised])
async def radio(session: str = "?", interval: float | None = None) -> StreamingResponse:
    """Radio mode: one endless MP3 stream, clip n at n x interval with silence between.

    Sent a little ahead of real time. If the phone stops reading, sends back up, so a clip's
    `wall_s` running ahead of its `audio_s` in the log shows the phone stopped pulling."""
    stream_id = uuid.uuid4().hex[:6]
    interval = _interval(interval)

    async def body():
        encoder = audio.Mp3Encoder(TTS_RATE)
        piece = int(RADIO_PIECE_S * TTS_RATE)
        start, sent_s, n = time.monotonic(), 0.0, 0
        log("radio_open", session=session, stream=stream_id, interval_s=interval)
        try:
            while sent_s < MAX_S:
                n += 1
                _, pcm = await run_in_threadpool(locktest_clip, n)
                segment = np.zeros(max(int(interval * TTS_RATE), len(pcm)), np.int16)
                segment[: len(pcm)] = pcm
                log(
                    "radio_clip",
                    session=session,
                    stream=stream_id,
                    n=n,
                    audio_s=round(sent_s, 1),
                    wall_s=round(time.monotonic() - start, 1),
                )
                for i in range(0, len(segment), piece):
                    part = segment[i : i + piece]
                    data = encoder.encode(part)
                    if data:
                        yield data
                    sent_s += len(part) / TTS_RATE
                    await asyncio.sleep(max(0.0, start + sent_s - RADIO_LEAD_S - time.monotonic()))
        finally:
            log(
                "radio_close",
                session=session,
                stream=stream_id,
                n=n,
                wall_s=round(time.monotonic() - start, 1),
            )

    return StreamingResponse(body(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
