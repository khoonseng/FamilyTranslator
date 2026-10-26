"""Plays the hub: streams 16 kHz mono WAV files to /ws/room at speaking pace, as the phone will,
and prints what comes back with timings. Each file is one or more segments (cut at 15 s, like
the hub's VAD), followed by 0.7 s of silence (the VAD's pause detection); between files
nothing is sent for `--pause` seconds, as the VAD holds back silence. MP3 clips are saved to
--out.

Credentials (HUB_PIN, API_TOKEN) come from backend/.env. Local only: prints text to this
terminal, never to logs.

Run: cd backend && uv run python tools/fake_hub.py <wav> [<wav> ...]
     [--url wss://chongqing-translator-....run.app/ws/room] [--pause 2.5] [--out tools/out]
     [--text "我们在门口集合。"]
"""

import argparse
import asyncio
import json
import os
import wave
from pathlib import Path
from time import perf_counter

import websockets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RATE = 16_000
FRAME_S = 0.1
SEGMENT_CAP_S = 15
TAIL_S = 0.7  # silence the VAD sends before it decides the segment has ended


def read_pcm(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
            raise SystemExit(f"{path}: need a 16 kHz mono 16-bit WAV")
        return w.readframes(w.getnframes())


async def send_paced(ws, pcm: bytes) -> None:
    frame = int(RATE * 2 * FRAME_S)
    start = perf_counter()
    for i in range(0, len(pcm), frame):
        await ws.send(pcm[i : i + frame])
        await asyncio.sleep(max(0.0, start + (i + frame) / (RATE * 2) - perf_counter()))


async def run(args) -> None:
    load_dotenv(ROOT / ".env")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    speech_end = {"t": None, "speaking": False}
    zh_of: dict[int, str] = {}

    async with websockets.connect(args.url, max_size=None) as ws:
        hello = {
            "type": "hello",
            "role": "hub",
            "pin": os.environ["HUB_PIN"],
            "token": os.environ["API_TOKEN"],
            "takeover": True,  # like tapping Start: replaces any current hub
        }
        await ws.send(json.dumps(hello))
        print("server:", await ws.recv())

        async def receive() -> None:
            pending_clip = None
            async for message in ws:
                now = perf_counter()
                if speech_end["speaking"]:
                    after = "while the guide is still speaking"
                elif speech_end["t"]:
                    after = f"{now - speech_end['t']:.2f}s after speech end"
                else:
                    after = ""
                if isinstance(message, bytes):
                    path = out / f"sentence-{pending_clip:03d}.mp3"
                    path.write_bytes(message)
                    print(f"  clip {pending_clip}: {len(message)} bytes {after} -> {path}")
                    continue
                m = json.loads(message)
                if m["type"] == "sentence":
                    zh_of[m["id"]] = m["zh"]
                    source = m["provider"] or m["status"]
                    print(f"#{m['id']} bubble {m['bubble_id']} [{source}] {after}")
                    print(f"  zh:  {m['zh']}\n  yue: {m['yue']}")
                elif m["type"] == "clip":
                    pending_clip = m["sentence_id"]
                elif m["type"] == "english":
                    print(f"  en {m['sentence_id']}: {m['en']}")
                else:
                    print("server:", m)

        receiver = asyncio.create_task(receive())
        if args.text:
            speech_end["t"] = perf_counter()
            await ws.send(json.dumps({"type": "text", "text": args.text}))
        if args.wavs:
            await ws.send(json.dumps({"type": "mode", "mode": "guide"}))
        for n, path in enumerate(args.wavs):
            pcm = read_pcm(path)
            cap = SEGMENT_CAP_S * RATE * 2
            for k in range(0, len(pcm), cap):
                pause = 3.0 if n == 0 and k == 0 else (args.pause if k == 0 else 0.0)
                if pause and not (n == 0 and k == 0):
                    await asyncio.sleep(pause)
                await ws.send(json.dumps({"type": "segment_start", "pause_s": pause}))
                speech_end["speaking"] = True
                await send_paced(ws, pcm[k : k + cap])
                speech_end["t"], speech_end["speaking"] = perf_counter(), False
                await send_paced(ws, bytes(int(RATE * 2 * TAIL_S)))  # the VAD hears the pause
                await ws.send(json.dumps({"type": "segment_end"}))
            print(f"(sent {Path(path).name}: {len(pcm) / (RATE * 2):.1f}s)")
        await asyncio.sleep(args.wait)
        receiver.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wavs", nargs="*")
    parser.add_argument("--url", default="ws://localhost:8000/ws/room")
    parser.add_argument("--pause", type=float, default=2.5, help="seconds between files")
    parser.add_argument("--text", help="also send this typed Mandarin")
    parser.add_argument("--wait", type=float, default=8.0, help="seconds to wait at the end")
    parser.add_argument("--out", default=str(ROOT / "tools" / "out"))
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
