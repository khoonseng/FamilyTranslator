"""Step 3b: score STT runs against the corrected references.

Before running: open out/references.csv, correct the `reference` column, and put `y` in
`reviewed` for each row you have checked. Only reviewed rows count towards error rates.

Reports per set and run: character error rate (pooled over chunks), median and p90 latency;
the junk filter's drop rates; and how colloquial each run's Cantonese transcripts are (does the
fallback turn Cantonese speech into Mandarin-style text?). Writes out/stt_scores.md.

Run: uv run python 03_stt_score.py
"""

from lib import config
from lib.config import OUT
from lib.records import median, percentile, read_csv, read_jsonl
from lib.scoring import cantonese_char_count, char_edits, colloquial_score

SCRIPT = {"guide": "simplified", "yue": "traditional", "en": "simplified"}
FILTER_RUN = "chirp3-cmn+yue"


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
        "",
        "| Set | Run | Reviewed chunks | Error rate | Median latency | p90 latency |",
        "| --- | --- | --- | --- | --- | --- |",
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
            latencies = [r["latency_s"] for r in rows]
            lines.append(
                f"| {set_name} | {run} | {scored} | "
                f"{fmt(edits / length if length else None, '{:.1%}')} | "
                f"{fmt(median(latencies))} | {fmt(percentile(latencies, 90))} |"
            )

    # Two candidate tests for junk-filter layer 2, both on the Mandarin + Cantonese run:
    # Chirp 3's language label, and Cantonese-only characters in the transcript.
    cantonese_chars = cfg["scoring"]["cantonese_only_chars"]
    tests = {"labelled Cantonese (>50% of characters)": lambda r: bool(r["labelled_cantonese"])}
    for n in (1, 2, 3):
        tests[f"≥{n} Cantonese-only character(s)"] = lambda r, n=n: (
            cantonese_char_count(r["text"], cantonese_chars) >= n
        )
    lines += [
        "",
        "## Junk filter layer 2: candidate tests",
        "",
        "Want: guide speech wrongly dropped ≈ 0%, family chatter correctly dropped ≈ 100%.",
        "",
        "| Test | Guide speech dropped | Chatter dropped |",
        "| --- | --- | --- |",
    ]
    by_set = {
        s: [r for (_, run), r in records.items() if run == FILTER_RUN and r["set"] == s]
        for s in ("guide", "chatter")
    }
    for label, test in tests.items():
        cells = []
        for s in ("guide", "chatter"):
            rows = by_set[s]
            dropped = sum(test(r) for r in rows)
            rate = fmt(dropped / len(rows) if rows else None, "{:.0%}")
            cells.append(f"{dropped}/{len(rows)} ({rate})")
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")

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
