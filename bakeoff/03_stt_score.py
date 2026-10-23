"""Step 3b: score STT runs against the corrected references.

Before running: open out/references.csv, correct the `reference` column, and put `y` in
`reviewed` for each row you have checked. Only reviewed rows count towards error rates.

Reports per set and run (sync and streaming): character error rate (pooled over chunks),
median and p90 latency; the junk filter's drop rates per sentence at each candidate
Cantonese-character share; and how colloquial each run's Cantonese transcripts are (does the
fallback turn Cantonese speech into Mandarin-style text?). Writes out/stt_scores.md.

Run: uv run python 03_stt_score.py
"""

from lib import config
from lib.config import OUT
from lib.records import median, percentile, read_csv, read_jsonl
from lib.scoring import cantonese_share, char_edits, colloquial_score
from lib.text import split_sentences

SCRIPT = {"guide": "simplified", "yue": "traditional", "en": "simplified"}
# Guide mode's language setting (Mandarin + Cantonese), sync and streaming, plus the OpenAI
# candidate that could replace Chirp 3 (it gets a Mandarin hint in Guide mode).
FILTER_RUNS = ["chirp3-cmn+yue", "chirp3-stream", "openai-gpt-transcribe"]


def latest_records() -> dict[tuple[str, str], dict]:
    """Last successful record per (chunk, run)."""
    latest = {}
    for r in read_jsonl(OUT / "stt_runs.jsonl"):
        if not r.get("error"):
            latest[(r["chunk_id"], r["run"])] = r
    return latest


def fmt(value, pattern="{:.2f}s") -> str:
    """Format a number (default: seconds); "-" when missing."""
    return "-" if value is None else pattern.format(value)


def speech_dropped(record: dict, margin_s: float = 1.0) -> bool:
    """Streaming only: the final transcripts stop more than margin_s before the chunk's speech
    ends, so the rest was never transcribed (seen on chunk 6-0008, 2026-10-23)."""
    finals = record.get("finals")
    if finals is None:
        return False
    covered = max((f["audio_end_s"] for f in finals), default=0.0)
    return covered < record["duration_s"] - margin_s


def junk_filter_section(records: dict, scoring_cfg: dict) -> list[str]:
    """Junk-filter layer 2 (decided 2026-10-23): split each Guide-mode transcript into
    sentences and drop a sentence when Cantonese-only characters exceed a share of it. Compares
    candidate shares on guide speech (should survive) and family chatter (should be dropped).
    Chirp 3's own language label is shown for reference only."""
    chars = scoring_cfg["cantonese_only_chars"]
    lines = [
        "",
        "## Junk filter layer 2: Cantonese-character share per sentence",
        "",
        "Want: guide sentences wrongly dropped ≈ 0%, chatter sentences dropped ≈ 100%.",
        "",
        "| Run | Rule | Guide sentences dropped | Chatter sentences dropped |",
        "| --- | --- | --- | --- |",
    ]
    for run in FILTER_RUNS:
        sentences = {
            s: [
                sentence
                for (_, rn), r in records.items()
                if rn == run and r["set"] == s
                for sentence in split_sentences(r["text"])
            ]
            for s in ("guide", "chatter")
        }
        if not any(sentences.values()):
            continue
        for share in scoring_cfg["junk_filter_shares"]:
            cells = []
            for s in ("guide", "chatter"):
                items = sentences[s]
                dropped = sum(cantonese_share(x, chars) > share for x in items)
                rate = fmt(dropped / len(items) if items else None, "{:.0%}")
                cells.append(f"{dropped}/{len(items)} ({rate})")
            lines.append(f"| {run} | share > {share:.0%} | {cells[0]} | {cells[1]} |")
        chunks = {
            s: [r for (_, rn), r in records.items() if rn == run and r["set"] == s]
            for s in ("guide", "chatter")
        }
        cells = []
        for s in ("guide", "chatter"):
            rows = chunks[s]
            dropped = sum(bool(r.get("labelled_cantonese")) for r in rows)
            rate = fmt(dropped / len(rows) if rows else None, "{:.0%}")
            cells.append(f"{dropped}/{len(rows)} chunks ({rate})")
        lines.append(f"| {run} | Chirp 3 label (reference) | {cells[0]} | {cells[1]} |")
    return lines


def main() -> None:
    cfg = config.load()
    records = latest_records()
    if not records:
        raise SystemExit("No STT runs yet: run 02_stt_bench.py first.")
    reviewed = {
        r["chunk_id"]: r["reference"]
        for r in read_csv(OUT / "references.csv")
        if r["reviewed"].strip().lower() in {"y", "yes", "x", "1", "true"}
    }
    lines = ["# STT bake-off scores", ""]

    lines += [
        "## Accuracy and speed",
        "",
        "Character error rate counts only reviewed chunks; latency counts every chunk.",
        "Latency means different things: for sync runs it is the request time, to which the app",
        "adds ~0.7 s of pause detection and the upload; for `chirp3-stream*` runs it is the time",
        "from the end of speech to the final transcript, which is all the app waits.",
        "",
        "| Set | Run | Reviewed chunks | Error rate | Median latency | p90 latency "
        "| Speech dropped |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for set_name in ("guide", "yue", "en"):
        runs = sorted({run for (_, run), r in records.items() if r["set"] == set_name})
        for run in runs:
            rows = [r for (_, rn), r in records.items() if rn == run and r["set"] == set_name]
            edits = length = scored = 0
            for r in rows:
                if r["chunk_id"] in reviewed:
                    e, n = char_edits(reviewed[r["chunk_id"]], r["text"], SCRIPT[set_name])
                    edits, length, scored = edits + e, length + n, scored + 1
            # A negative streaming latency means the last final came before speech ended: the
            # end of the chunk was never transcribed, so it can't count as a latency.
            latencies = [r["latency_s"] for r in rows if (r["latency_s"] or 0) >= 0]
            dropped = [r for r in rows if speech_dropped(r)]
            lines.append(
                f"| {set_name} | {run} | {scored} | "
                f"{fmt(edits / length if length else None, '{:.1%}')} | "
                f"{fmt(median(latencies))} | {fmt(percentile(latencies, 90))} | "
                f"{f'{len(dropped)} of {len(rows)}' if 'finals' in rows[0] else '-'} |"
            )

    lines += junk_filter_section(records, cfg["scoring"])

    lines += [
        "",
        "## Cantonese transcripts: colloquial or Mandarin-style?",
        "",
        "| Run | Colloquial markers | Formal markers | Colloquial share |",
        "| --- | --- | --- | --- |",
    ]
    yue_runs = sorted({run for (_, run), r in records.items() if r["set"] == "yue"})
    for run in yue_runs:
        text = "".join(
            r["text"] for (_, rn), r in records.items() if rn == run and r["set"] == "yue"
        )
        s = colloquial_score(text, cfg["scoring"])
        lines.append(f"| {run} | {s['colloquial']} | {s['formal']} | {fmt(s['ratio'], '{:.0%}')} |")

    report = "\n".join(lines) + "\n"
    (OUT / "stt_scores.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
