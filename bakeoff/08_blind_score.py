"""Step 5c: reveal and tally the in-laws' blind test.

Save the results the page offers as out/blind/blind_results.json (or pass another path), then
run this. It matches answers to out/blind/key.json and reports:
  round A  votes per voice, and the winning voice
  round B  per translator: times picked as best, average naturalness (1 = 唔自然, 3 = 好自然),
           and how often it was rated 唔自然
  round C  whether the faster speech was easy to follow
Writes out/blind_results.md.

Run: uv run python 08_blind_score.py [path/to/blind_results.json]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from lib.config import OUT

BLIND = OUT / "blind"
FOLLOW = {3: "聽得明 (easy)", 2: "有少少吃力 (a little hard)", 1: "聽唔明 (couldn't follow)"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", nargs="?", default=str(BLIND / "blind_results.json"))
    args = parser.parse_args()
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    key = json.loads((BLIND / "key.json").read_text(encoding="utf-8"))
    if results.get("build") != key.get("build"):
        raise SystemExit("These results come from a different build of the page than key.json.")
    voices = key["voices"]

    lines = ["# Blind test results", ""]
    votes = Counter(v for v in results["a"] if v is not None)
    lines += ["## Round A: voice", "", "| Voice | Votes |", "| --- | --- |"]
    for idx, voice in enumerate(voices):
        lines.append(f"| {voice} | {votes.get(idx, 0)} |")
    lines += ["", f"Winner (used for rounds B and C): **{voices[results['voiceWinner']]}**", ""]

    best, ratings = Counter(), {}
    for answer in results["b"]:
        if not answer:
            continue
        if answer.get("best"):
            best[key["options"][answer["best"]]["config"]] += 1
        for option_id, rating in answer["ratings"].items():
            ratings.setdefault(key["options"][option_id]["config"], []).append(rating)
    lines += [
        "## Round B: translation",
        "",
        "| Translator | Picked as best | Average naturalness (1-3) | Rated 唔自然 |",
        "| --- | --- | --- | --- |",
    ]
    for config in sorted(ratings, key=lambda c: (-best[c], -sum(ratings[c]) / len(ratings[c]))):
        r = ratings[config]
        lines.append(
            f"| {config} | {best[config]} of {len(results['b'])} | {sum(r) / len(r):.2f} "
            f"| {r.count(1)} of {len(r)} |"
        )

    follow = Counter(a for a in results["c"] if a is not None)
    lines += ["", "## Round C: faster speech", ""]
    lines += [f"- {label}: {follow.get(score, 0)}" for score, label in FOLLOW.items()]

    report = "\n".join(lines) + "\n"
    (OUT / "blind_results.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
