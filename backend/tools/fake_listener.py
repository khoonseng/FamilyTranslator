"""Plays a listener phone: joins /ws/room with the room token (and, with --host, the PIN and API
token) and prints what arrives, with arrival times. For checking fan-out and catch-up.

Credentials (ROOM_TOKEN, and HUB_PIN / API_TOKEN for --host) come from backend/.env. Local
only: prints text to this terminal, never to logs.

Run: cd backend && uv run python tools/fake_listener.py [--last-id 3] [--host] [--seconds 30]
     [--url wss://chongqing-translator-....run.app/ws/room] [--name ear-1]
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import perf_counter

import websockets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


async def run(args) -> None:
    load_dotenv(ROOT / ".env")
    hello = {"type": "hello", "role": "listener", "room": os.environ["ROOM_TOKEN"]}
    if args.host:
        hello |= {"pin": os.environ["HUB_PIN"], "token": os.environ["API_TOKEN"]}
    hello["last_id"] = args.last_id
    start = perf_counter()
    clips = 0
    async with websockets.connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps(hello))
        try:
            async with asyncio.timeout(args.seconds):
                async for message in ws:
                    t = f"[{args.name} {perf_counter() - start:6.2f}s]"
                    if isinstance(message, bytes):
                        clips += 1
                        print(f"{t} mp3 {len(message)} bytes")
                        continue
                    m = json.loads(message)
                    if m["type"] == "sentence":
                        print(f"{t} #{m['id']} bubble {m['bubble_id']}: {m['yue'] or m['zh']}")
                    elif m["type"] in ("clip", "english"):
                        continue
                    else:
                        print(f"{t} {m}")
        except TimeoutError:
            pass
    print(f"[{args.name}] done: {clips} clips")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="ws://localhost:8000/ws/room")
    parser.add_argument("--last-id", type=int, default=0)
    parser.add_argument("--host", action="store_true", help="also sign in as a host")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--name", default="ear")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
