"""Step 4b: score translations and pick the blind-test finalists.

Per configuration (guide → family): valid JSON, colloquial vs formal markers in `yue`,
Simplified characters in `yue`, glossary terms used, time to first token, total time and
reasoning tokens. Then the best setting per model (and Cloud Translation) becomes a finalist;
a candidate that clearly fails the colloquial check is dropped, not played to the in-laws.

Writes out/translation_scores.md, out/translations_review.md (every output side by side, for
you to read) and out/finalists.json (input to the voice and blind-test steps).

Run: uv run python 05_translate_score.py [--min-colloquial 0.5]
"""

import argparse
import json
from pathlib import Path

from lib import config
from lib.config import OUT
from lib.records import median, percentile, read_jsonl
from lib.scoring import colloquial_score, glitches, glossary_hits, simplified_chars


def group_of(name: str, cfg: dict) -> str:
    """Configs of the same model compete for one finalist slot."""
    if name.startswith("cloud-translate"):
        return "cloud-translate"
    return cfg["llm"]["configs"][name]["model"]


def fmt(value, pattern="{:.2f}s") -> str:
    """Format a number (default: seconds); "-" when missing."""
    return "-" if value is None else pattern.format(value)


def latest(records: list[dict]) -> dict[tuple, dict]:
    out = {}
    for r in records:
        if not r.get("error"):
            out[(r["sentence_id"], r["config"], r["repeat"])] = r
    return out


def score_config(rows: list[dict], cfg: dict) -> dict:
    first = [r for r in rows if r["repeat"] == 0]
    yue = [(r["source"], (r["output"] or {}).get("yue", "")) for r in first]
    en = [(r["source"], (r["output"] or {}).get("en", "")) for r in first]
    per_sentence = [colloquial_score(text, cfg["scoring"]) for _, text in yue]
    colloquial = sum(s["colloquial"] for s in per_sentence)
    formal = sum(s["formal"] for s in per_sentence)
    glossary = config.glossary()
    gy = [glossary_hits(src, out, glossary, "yue") for src, out in yue]
    ge = [glossary_hits(src, out, glossary, "en") for src, out in en]
    # Glitches count over every repeat: a defect in any run could reach a listener.
    glitched = [
        (r["sentence_id"], r["repeat"], g)
        for r in rows
        if (g := glitches((r["output"] or {}).get("yue", "")))
    ]
    return {
        "sentences": len(first),
        "glitches": len(glitched),
        "glitch_examples": glitched,
        "outputs": len(rows),
        "json_ok": sum(r["json_ok"] for r in rows) / len(rows) if rows else None,
        "colloquial": colloquial,
        "formal": formal,
        "ratio": colloquial / (colloquial + formal) if colloquial + formal else None,
        "formal_leaning": sum(s["formal"] > s["colloquial"] for s in per_sentence),
        "simplified": sum(len(simplified_chars(text)) for _, text in yue),
        "glossary_yue": f"{sum(g['found'] for g in gy)}/{sum(g['expected'] for g in gy)}",
        "glossary_en": f"{sum(g['found'] for g in ge)}/{sum(g['expected'] for g in ge)}",
        "ttft": median([r.get("ttft_s") for r in rows]),
        "total": median([r["total_s"] for r in rows]),
        "total_p90": percentile([r["total_s"] for r in rows], 90),
        "reasoning": median([r.get("reasoning_tokens") for r in rows]),
    }


_EFFORT_RANK = {"none": 0, "minimal": 1, "low": 2, "default": 3, "medium": 3, "high": 4, "max": 5}


def effort_rank(name: str, cfg: dict) -> int:
    """Reasoning level declared in config.yaml (Cloud Translation has none)."""
    entry = cfg["llm"]["configs"].get(name)
    effort = ((entry or {}).get("params") or {}).get("reasoning_effort", "none")
    return _EFFORT_RANK.get(str(effort), 3)


def quality_key(name: str, scores: dict) -> tuple:
    """Higher is better: fewer glitches, then colloquial share, then fewer Simplified
    characters, then speed."""
    s = scores[name]
    return (-s["glitches"], round(s["ratio"] or 0, 6), -s["simplified"], -(s["total"] or 99))


def pick_setting(members: list[str], scores: dict, cfg: dict, margin: float) -> str:
    """One finalist per model.

    1. Within each reasoning level, the best sampling setting (temperature) simply wins.
    2. Across reasoning levels, the lowest level is the default (hard rule 6); a higher level
       wins only if its colloquial share is better by more than `margin`."""
    by_level: dict[int, str] = {}
    for name in members:
        level = effort_rank(name, cfg)
        if level not in by_level or quality_key(name, scores) > quality_key(
            by_level[level], scores
        ):
            by_level[level] = name
    default = by_level[min(by_level)]
    best = max(by_level.values(), key=lambda n: quality_key(n, scores))
    gain = (scores[best]["ratio"] or 0) - (scores[default]["ratio"] or 0)
    return best if gain > margin else default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-colloquial", type=float, default=0.5)
    parser.add_argument(
        "--margin",
        type=float,
        default=0.05,
        help="colloquial-share gain needed to prefer a reasoning-on setting over reasoning off",
    )
    parser.add_argument("--min-json-ok", type=float, default=0.9)
    parser.add_argument("--log", default="translations.jsonl", help="run log under out/")
    args = parser.parse_args()

    cfg = config.load()
    records = latest(read_jsonl(OUT / args.log))
    # Outputs carry the log's suffix: translations_r2.jsonl -> translation_scores_r2.md ...
    suffix = Path(args.log).stem.removeprefix("translations")
    if not records:
        raise SystemExit("No translations yet: run 04_translate_bench.py first.")
    guide = [r for r in records.values() if r["direction"] == "guide_to_family"]
    family = [r for r in records.values() if r["direction"] == "family_to_guide"]
    names = sorted({r["config"] for r in guide})
    scores = {n: score_config([r for r in guide if r["config"] == n], cfg) for n in names}

    lines = [
        "# Translation bake-off scores",
        "",
        "## Guide → family",
        "",
        "Colloquial share = colloquial markers / (colloquial + formal markers) in `yue`.",
        "Formal-leaning = sentences with more formal than colloquial markers.",
        "Glitches = outputs (over all repeats) with English words or runaway repetition.",
        "None of these catch wrong meaning: read out/translations_review.md as well.",
        "",
        "| Config | Sentences | Glitches | Valid JSON | Colloquial share | Formal-leaning "
        "| Simplified chars | Glossary yue | Glossary en | First token "
        "| Total (median) | Total (p90) | Reasoning tokens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for n, s in scores.items():
        lines.append(
            f"| {n} | {s['sentences']} | {s['glitches']}/{s['outputs']} | "
            f"{fmt(s['json_ok'], '{:.0%}')} | "
            f"{fmt(s['ratio'], '{:.0%}')} ({s['colloquial']}/{s['formal']}) | "
            f"{s['formal_leaning']} | {s['simplified']} | {s['glossary_yue']} | "
            f"{s['glossary_en']} | {fmt(s['ttft'])} | {fmt(s['total'])} | "
            f"{fmt(s['total_p90'])} | {fmt(s['reasoning'], '{:.0f}')} |"
        )

    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(group_of(n, cfg), []).append(n)
    finalists, dropped = [], []
    for group, members in groups.items():
        best = pick_setting(members, scores, cfg, args.margin)
        s = scores[best]
        if (s["ratio"] or 0) < args.min_colloquial:
            dropped.append((best, f"colloquial share {fmt(s['ratio'], '{:.0%}')}"))
        elif (s["json_ok"] or 0) < args.min_json_ok:
            dropped.append((best, f"valid JSON {fmt(s['json_ok'], '{:.0%}')}"))
        else:
            finalists.append({"config": best, "group": group})
    examples = [(n, *g) for n, s in scores.items() for g in s["glitch_examples"]]
    if examples:
        lines += ["", "## Glitches found", ""]
        lines += [f"- `{n}` {sid} #{rep}: {', '.join(g)[:80]}" for n, sid, rep, g in examples]
    lines += ["", "## Blind-test finalists", ""]
    lines += [f"- {f['config']} ({f['group']})" for f in finalists]
    lines += [f"- dropped: {n} ({why})" for n, why in dropped]

    if family:
        lines += [
            "",
            "## Family → guide (phase 2 preview)",
            "",
            "| Config | Sentences | Valid JSON | Total (median) |",
            "| --- | --- | --- | --- |",
        ]
        for n in sorted({r["config"] for r in family}):
            rows = [r for r in family if r["config"] == n]
            ok = sum(r["json_ok"] for r in rows) / len(rows)
            lines.append(
                f"| {n} | {len(rows)} | {ok:.0%} | {fmt(median([r['total_s'] for r in rows]))} |"
            )

    report = "\n".join(lines) + "\n"
    (OUT / f"translation_scores{suffix}.md").write_text(report, encoding="utf-8")
    (OUT / f"finalists{suffix}.json").write_text(json.dumps(finalists, indent=2), encoding="utf-8")
    write_review(guide + family, OUT / f"translations_review{suffix}.md")
    print(report)
    print(f"Side-by-side outputs: {OUT / f'translations_review{suffix}.md'}")


def write_review(rows: list[dict], path: Path) -> None:
    """Every repeat-0 output, grouped by sentence, for reading by eye (stays in out/)."""
    lines = ["# Translations side by side", ""]
    seen = []
    for r in rows:
        if r["sentence_id"] not in seen:
            seen.append(r["sentence_id"])
    for sid in seen:
        group = sorted(
            (r for r in rows if r["sentence_id"] == sid and r["repeat"] == 0),
            key=lambda r: r["config"],
        )
        lines += [f"## {sid}", "", f"> {group[0]['source']}", ""]
        for r in group:
            output = r["output"] or {"(invalid JSON)": r.get("raw", "")}
            values = " · ".join(f"**{k}** {v}" for k, v in output.items())
            lines.append(f"- `{r['config']}` {values}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
