"""JSONL run logs and CSV tables under out/. Runs are resumable: finished keys are skipped,
so a re-run after an error or a rate limit never pays for the same call twice."""

import csv
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def done_keys(records: list[dict], fields: tuple[str, ...]) -> set[tuple]:
    """Keys of successful records (those without an `error`)."""
    return {tuple(r[f] for f in fields) for r in records if not r.get("error")}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # utf-8-sig: tolerate the byte-order mark Excel adds when saving Chinese text.
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written with a BOM so Excel and Numbers open the Chinese text correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def median(values: list[float]) -> float | None:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def percentile(values: list[float], pct: float) -> float | None:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    index = min(len(values) - 1, round(pct / 100 * (len(values) - 1)))
    return values[index]
