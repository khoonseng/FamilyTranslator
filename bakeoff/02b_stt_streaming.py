"""Step 3a (streaming): stream chunks to Chirp 3 at real-time pace, as the hub would.

Measures what streaming is for: the time from the end of speech to the final transcript, and
whether accuracy holds compared with the sync runs in 02_stt_bench.py. Results go to the same
log (out/stt_runs.jsonl), so 03_stt_score.py scores them side by side.

Runs (Guide mode = Mandarin + Cantonese codes + glossary hints, as the app would use them):
  guide, chatter   chirp3-stream        standard endpointing
  guide            chirp3-stream-short  short endpointing (earlier results, may split mid-word)
  yue, en          chirp3-stream-family Cantonese + English (Family mode)

--continuous streams the first --seconds of each guide recording as one long stream, the way
the guide actually talks, and reports how Chirp 3 splits it (out/stt_stream_sessions.jsonl).

Streams run at real speed, so the run takes about as long as the audio divided by --parallel.

Run: uv run python 02b_stt_streaming.py [--limit 3] [--parallel 4]
     uv run python 02b_stt_streaming.py --continuous [--seconds 120]
"""

import argparse
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from lib import audio, config
from lib.config import OUT, RECORDINGS
from lib.records import append_jsonl, done_keys, read_csv, read_jsonl
from lib.stt import GoogleStreamingStt, SttResult

RUNS_FILE = OUT / "stt_runs.jsonl"
SESSIONS_FILE = OUT / "stt_stream_sessions.jsonl"
GUIDE = ["cmn-Hans-CN", "yue-Hant-HK"]
FAMILY = ["yue-Hant-HK", "en-US"]

# name -> (sets, language codes, glossary hints, endpointing)
RUNS = {
    "chirp3-stream": (("guide", "chatter"), GUIDE, True, "standard"),
    "chirp3-stream-short": (("guide",), GUIDE, True, "short"),
    "chirp3-stream-family": (("yue", "en"), FAMILY, False, "standard"),
}


def read_pcm(path: Path, target_dbfs: float | None) -> bytes:
    """Chunk audio, levelled to target_dbfs (as the app must do before streaming)."""
    with wave.open(str(path)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    return (audio.normalize(pcm, target_dbfs) if target_dbfs is not None else pcm).tobytes()


def stream_chunk(stt: GoogleStreamingStt, chunk: dict, run: str, phrases, stream_cfg) -> dict:
    _, languages, hints, endpointing = RUNS[run]
    record = {"chunk_id": chunk["chunk_id"], "set": chunk["set"], "run": run}
    try:
        r = stt.stream(
            read_pcm(OUT.parent / chunk["path"], stream_cfg.get("target_rms_dbfs")),
            languages,
            phrases if hints else None,
            frame_ms=stream_cfg["frame_ms"],
            tail_silence_s=stream_cfg["tail_silence_s"],
            endpointing=endpointing,
        )
        record |= {
            "text": r.text,
            "segments": r.segments,
            "labelled_cantonese": SttResult(r.text, 0, r.segments).labelled_cantonese(),
            # For streaming, latency = end of speech -> last final transcript.
            "latency_s": r.finalize_latency_s,
            "first_interim_s": r.first_interim_s,
            "finals": [vars(f) for f in r.finals],
            "duration_s": float(chunk["duration_s"]),
        }
    except Exception as exc:  # noqa: BLE001 - log the error, keep going, re-run later
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def run_chunks(args, cfg, stt, phrases) -> None:
    chunks = read_csv(OUT / "chunks" / "manifest.csv")
    if not chunks:
        raise SystemExit("No chunks yet: run 01_prepare_clips.py first.")
    done = set() if args.force else done_keys(read_jsonl(RUNS_FILE), ("chunk_id", "run"))
    only = set(filter(None, args.runs.split(",")))
    jobs = []
    for run, (sets, *_rest) in RUNS.items():
        if only and run not in only:
            continue
        for set_name in sets:
            set_chunks = [c for c in chunks if c["set"] == set_name]
            if args.limit:
                set_chunks = set_chunks[: args.limit]
            jobs += [(c, run) for c in set_chunks if (c["chunk_id"], run) not in done]
    audio_min = sum(float(c["duration_s"]) for c, _ in jobs) / 60
    print(f"{len(jobs)} streams, {audio_min:.1f} min of audio, {args.parallel} at a time")

    stream_cfg = cfg["stt"]["google"]["streaming"]
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(stream_chunk, stt, c, run, phrases, stream_cfg) for c, run in jobs]
        for future in as_completed(futures):
            record = future.result()
            append_jsonl(RUNS_FILE, record)
            if record.get("error"):
                print(f"  {record['chunk_id']} {record['run']} ERROR {record['error']}")
            else:
                print(
                    f"  {record['chunk_id']} {record['run']} "
                    f"+{record['latency_s'] or 0:.2f}s {record['text']}"
                )


def run_continuous(args, cfg, stt, phrases) -> None:
    """One long stream per guide recording: how does Chirp 3 split continuous narration?"""
    files = sorted(p for p in (RECORDINGS / "guide").glob("*") if p.is_file())
    if not files:
        raise SystemExit(f"No guide recordings in {RECORDINGS / 'guide'}")
    stream_cfg = cfg["stt"]["google"]["streaming"]
    for path in files:
        pcm = audio.decode(path)[: int(args.seconds * audio.RATE)]
        if stream_cfg.get("target_rms_dbfs") is not None:
            pcm = audio.normalize(pcm, stream_cfg["target_rms_dbfs"])
        r = stt.stream(
            pcm.tobytes(),
            GUIDE,
            phrases,
            frame_ms=stream_cfg["frame_ms"],
            tail_silence_s=stream_cfg["tail_silence_s"],
        )
        # Delay of each final after the audio it covers was sent (real-time pacing).
        delays = [round(f.received_s - f.audio_end_s, 3) for f in r.finals]
        unfinished = sum(
            not f.text.rstrip().endswith(("。", "？", "！", "?", "!")) for f in r.finals
        )
        record = {
            "source": path.name,
            "audio_s": round(len(pcm) / audio.RATE, 1),
            "finals": [vars(f) for f in r.finals],
            "delays_s": delays,
            "unfinished_finals": unfinished,
        }
        append_jsonl(SESSIONS_FILE, record)
        delays.sort()
        median = delays[len(delays) // 2] if delays else None
        print(
            f"{path.name}: {len(r.finals)} finals over {record['audio_s']}s, "
            f"median delay {median}s, {unfinished} ending mid-sentence"
        )
        for f in r.finals:
            print(f"  {f.audio_end_s:6.1f}s  {f.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=0, help="chunks per set (0 = all)")
    parser.add_argument("--runs", default="", help="only these run names (comma-separated)")
    parser.add_argument("--parallel", type=int, default=4, help="streams at a time")
    parser.add_argument("--continuous", action="store_true", help="whole guide recordings")
    parser.add_argument("--seconds", type=float, default=120, help="--continuous: per file")
    parser.add_argument(
        "--force", action="store_true", help="re-run chunks already done (the newest run counts)"
    )
    args = parser.parse_args()

    cfg = config.load()
    stt = GoogleStreamingStt(cfg["stt"]["google"], config.project())
    phrases = [term["zh"] for term in config.glossary()]
    if args.continuous:
        if args.seconds > 290:
            raise SystemExit("Google closes a stream after 5 minutes: use --seconds 290 or less.")
        run_continuous(args, cfg, stt, phrases)
    else:
        run_chunks(args, cfg, stt, phrases)


if __name__ == "__main__":
    main()
