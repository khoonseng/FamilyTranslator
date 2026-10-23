"""Step 3a: run every non-streaming STT configuration on every chunk from 01_prepare_clips.py.
(Streaming runs are in 02b_stt_streaming.py; both write to the same log.)

Runs per set:
  guide    Chirp 3 Mandarin, with and without glossary hints; Chirp 3 Mandarin + Cantonese
           (Guide mode's language setting, for the junk filter); each OpenAI fallback candidate
           (Mandarin hint + glossary prompt)
  chatter  Chirp 3 Mandarin (what junk Guide mode would produce); Chirp 3 Mandarin + Cantonese;
           each OpenAI candidate in Guide mode (junk-filter check)
  yue      Chirp 3 Cantonese; Chirp 3 Cantonese + English (Family mode); each OpenAI candidate
  en       Chirp 3 Cantonese + English (Family mode); each OpenAI candidate

Appends to out/stt_runs.jsonl (resumable) and drafts out/references.csv for correction.
Chirp 3 calls are sync Recognize (hard rule 14: never batch).

Run: uv run python 02_stt_bench.py [--limit 3] [--sets guide,yue] [--runs chirp3-cmn]
"""

import argparse
from pathlib import Path

from lib import config
from lib.config import OUT
from lib.records import append_jsonl, done_keys, read_csv, read_jsonl, write_csv
from lib.stt import GoogleStt, OpenAiStt

RUNS_FILE = OUT / "stt_runs.jsonl"
REFERENCES = OUT / "references.csv"
REFERENCE_FIELDS = ["chunk_id", "set", "source", "duration_s", "reviewed", "reference", "draft"]

# name -> (language codes, use glossary hints)
GOOGLE_RUNS = {
    "chirp3-cmn": (["cmn-Hans-CN"], False),
    "chirp3-cmn-glossary": (["cmn-Hans-CN"], True),
    "chirp3-cmn+yue": (["cmn-Hans-CN", "yue-Hant-HK"], False),
    "chirp3-yue": (["yue-Hant-HK"], False),
    "chirp3-yue+en": (["yue-Hant-HK", "en-US"], False),
}

# Which run's transcript seeds the reference draft for each set (chatter needs no reference).
DRAFT_FROM = {"guide": "chirp3-cmn-glossary", "yue": "chirp3-yue", "en": "chirp3-yue+en"}


def runs_for(set_name: str, openai_models: list[str]) -> dict[str, tuple]:
    """name -> (kind, model, languages, glossary hints) for one set."""
    google = {
        "guide": ["chirp3-cmn", "chirp3-cmn-glossary", "chirp3-cmn+yue"],
        "chatter": ["chirp3-cmn", "chirp3-cmn+yue"],
        "yue": ["chirp3-yue", "chirp3-yue+en"],
        "en": ["chirp3-yue+en"],
    }[set_name]
    runs = {name: ("google", None, *GOOGLE_RUNS[name]) for name in google}
    if set_name in ("guide", "chatter"):
        # Guide mode: Mandarin hint + glossary. On chatter this shows whether OpenAI keeps
        # Cantonese words (so the junk filter can catch them) or rewrites them as Mandarin.
        for model in openai_models:
            runs[f"openai-{model}"] = ("openai", model, ["cmn-Hans-CN"], True)
    elif set_name in ("yue", "en"):
        # Family mode can't tell the fallback which language is coming, so no hint.
        for model in openai_models:
            runs[f"openai-{model}"] = ("openai", model, [], False)
    return runs


def draft_references(chunks: list[dict], records: list[dict]) -> None:
    """Add rows for new chunks; never overwrite references the owner has already edited."""
    existing = {row["chunk_id"]: row for row in read_csv(REFERENCES)}
    latest = {(r["chunk_id"], r["run"]): r["text"] for r in records if not r.get("error")}
    rows = []
    for chunk in chunks:
        if chunk["set"] not in DRAFT_FROM:
            continue
        if chunk["chunk_id"] in existing:
            rows.append(existing[chunk["chunk_id"]])
            continue
        draft = latest.get((chunk["chunk_id"], DRAFT_FROM[chunk["set"]]), "")
        rows.append(
            {
                "chunk_id": chunk["chunk_id"],
                "set": chunk["set"],
                "source": chunk["source"],
                "duration_s": chunk["duration_s"],
                "reviewed": "",
                "reference": draft,
                "draft": draft,
            }
        )
    write_csv(REFERENCES, rows, REFERENCE_FIELDS)
    pending = sum(not r["reviewed"] for r in rows)
    print(f"\n{REFERENCES}: {len(rows)} rows, {pending} still to review")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=0, help="chunks per set (0 = all)")
    parser.add_argument("--sets", default="guide,chatter,yue,en")
    parser.add_argument("--runs", default="", help="only these run names (comma-separated)")
    args = parser.parse_args()

    cfg = config.load()
    chunks = read_csv(OUT / "chunks" / "manifest.csv")
    if not chunks:
        raise SystemExit("No chunks yet: run 01_prepare_clips.py first.")
    records = read_jsonl(RUNS_FILE)
    done = done_keys(records, ("chunk_id", "run"))
    only_runs = set(filter(None, args.runs.split(",")))
    openai_models = cfg["stt"]["openai"]["models"]
    phrases = [term["zh"] for term in config.glossary()]
    google = GoogleStt(cfg["stt"]["google"], config.project())
    openai_clients = {m: OpenAiStt(m) for m in openai_models}

    for set_name in args.sets.split(","):
        set_chunks = [c for c in chunks if c["set"] == set_name]
        if args.limit:
            set_chunks = set_chunks[: args.limit]
        runs = runs_for(set_name, openai_models)
        print(f"{set_name}: {len(set_chunks)} chunks x {len(runs)} runs")
        for chunk in set_chunks:
            wav = Path(OUT.parent / chunk["path"]).read_bytes()
            for run_name, (kind, model, languages, hints) in runs.items():
                if (chunk["chunk_id"], run_name) in done:
                    continue
                if only_runs and run_name not in only_runs:
                    continue
                client = google if kind == "google" else openai_clients[model]
                record = {"chunk_id": chunk["chunk_id"], "set": set_name, "run": run_name}
                try:
                    result = client.transcribe(wav, languages, phrases if hints else None)
                    record |= {
                        "text": result.text,
                        "segments": result.segments,
                        "labelled_cantonese": result.labelled_cantonese()
                        if kind == "google"
                        else None,
                        "latency_s": round(result.latency_s, 3),
                        "duration_s": float(chunk["duration_s"]),
                    }
                    print(f"  {chunk['chunk_id']} {run_name} {result.latency_s:.2f}s {result.text}")
                except Exception as exc:  # noqa: BLE001 - log the error, keep going, re-run later
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    print(f"  {chunk['chunk_id']} {run_name} ERROR {record['error']}")
                append_jsonl(RUNS_FILE, record)
                records.append(record)

    draft_references(chunks, records)


if __name__ == "__main__":
    main()
