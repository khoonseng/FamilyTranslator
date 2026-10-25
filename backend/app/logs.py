"""Structured logs: one JSON line per event, which Cloud Run turns into a log entry.

Request ids, timings and errors only. Never transcripts, translations or audio (hard rule 14):
callers pass numbers and short codes, never text from the conversation."""

import json


def log(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)
