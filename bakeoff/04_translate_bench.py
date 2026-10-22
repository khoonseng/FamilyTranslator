"""Step 4a: translate the bench sentences with every LLM configuration and Cloud Translation.

Sentences:
  guide → family   sentences.yaml (drafted narration) plus up to --guide-sentences sentences
                   from the reviewed guide transcripts in out/references.csv
  family → guide   the reviewed Cantonese and English family questions (phase 2 preview)

Configurations: every entry under llm.configs in config.yaml, plus `cloud-translate` and,
once the glossary is uploaded, `cloud-translate-glossary`. Guide sentences run --repeats times
for latency; quality is judged on repeat 0.

Groq's Free plan allows about 30 requests a minute and 1,000 a day, so Groq calls are paced
and the run is resumable: if it hits the daily cap, re-run tomorrow and it carries on.
Appends to out/translations.jsonl, or to the log named by --log.

Run: uv run python 04_translate_bench.py [--configs qwen-off,cloud-translate] [--repeats 3]
"""

import argparse
import time

import yaml

from lib import config
from lib.config import OUT, ROOT
from lib.llm import ChatClient, reasoning_tokens, translation_messages
from lib.mt import CloudTranslate
from lib.records import append_jsonl, done_keys, read_csv, read_jsonl
from lib.scoring import parse_json_object
from lib.text import split_sentences

REVIEWED = {"y", "yes", "x", "1", "true"}
MIN_INTERVAL_S = {"groq": 2.2}  # stay under 30 requests/minute on the Free plan
MT_CODES = {"guide": "zh-CN", "yue": "yue", "en": "en"}


def build_sentences(max_guide: int, context_n: int) -> list[dict]:
    """[{id, direction, set, text, context}] in narration order."""
    sentences = []
    drafted = yaml.safe_load((ROOT / "sentences.yaml").read_text(encoding="utf-8"))["sentences"]
    for i, text in enumerate(drafted):
        sentences.append(
            {
                "id": f"draft-{i:02d}",
                "direction": "guide_to_family",
                "set": "guide",
                "text": text,
                "context": drafted[max(0, i - context_n) : i],
            }
        )

    references = [
        r
        for r in read_csv(OUT / "references.csv")
        if r["reviewed"].strip().lower() in REVIEWED and r["reference"].strip()
    ]
    # Real guide narration: split reviewed chunks into sentences, keep each source's order.
    taken, previous = 0, {}
    for r in (r for r in references if r["set"] == "guide"):
        for j, text in enumerate(split_sentences(r["reference"])):
            history = previous.setdefault(r["source"], [])
            if taken < max_guide and len(text) >= 6:
                sentences.append(
                    {
                        "id": f"{r['chunk_id']}-{j}",
                        "direction": "guide_to_family",
                        "set": "guide",
                        "text": text,
                        "context": history[-context_n:] if context_n else [],
                    }
                )
                taken += 1
            history.append(text)

    for r in (r for r in references if r["set"] in ("yue", "en")):
        sentences.append(
            {
                "id": r["chunk_id"],
                "direction": "family_to_guide",
                "set": r["set"],
                "text": r["reference"].strip(),
                "context": [],
            }
        )
    return sentences


def run_mt(mt: CloudTranslate, sentence: dict, use_glossary: bool) -> dict:
    """Two calls (in the app they run in parallel, so total = the slower one)."""
    source = MT_CODES[sentence["set"]]
    if sentence["direction"] == "guide_to_family":
        targets = {"yue": "yue", "en": "en"}
    else:
        targets = {"zh_hans": "zh-CN", "other": "en" if source == "yue" else "yue"}
    output, latencies = {}, []
    for key, target in targets.items():
        r = mt.translate(sentence["text"], source, target, use_glossary)
        output[key] = r.text
        latencies.append(r.latency_s)
    return {"output": output, "ttft_s": None, "total_s": round(max(latencies), 3)}


def run_llm(client: ChatClient, sentence: dict) -> dict:
    messages = translation_messages(sentence["direction"], sentence["text"], sentence["context"])
    r = client.chat(messages, stream=True)
    return {
        "output": parse_json_object(r.text),
        "raw": r.text,
        "ttft_s": round(r.ttft_s, 3) if r.ttft_s is not None else None,
        "total_s": round(r.total_s, 3),
        "reasoning_tokens": reasoning_tokens(r.usage),
        "usage": r.usage,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--configs", default="", help="only these configs (comma-separated)")
    parser.add_argument("--repeats", type=int, default=3, help="runs per guide sentence")
    parser.add_argument("--guide-sentences", type=int, default=5)
    parser.add_argument("--directions", default="guide_to_family,family_to_guide")
    parser.add_argument("--limit", type=int, default=0, help="sentences per direction (trial)")
    parser.add_argument(
        "--log",
        default="translations.jsonl",
        help="run log under out/; a new name starts a fresh run (e.g. translations_r2.jsonl)",
    )
    args = parser.parse_args()

    cfg = config.load()
    sentences = build_sentences(args.guide_sentences, cfg["llm"].get("context_sentences", 2))
    directions = set(args.directions.split(","))
    names = list(cfg["llm"]["configs"]) + ["cloud-translate"]
    if cfg["mt"]["google"].get("glossary_id"):
        names.append("cloud-translate-glossary")
    if args.configs:
        names = [n for n in names if n in args.configs.split(",")]

    clients = {n: ChatClient(n, cfg) for n in names if n in cfg["llm"]["configs"]}
    mt = None
    if any(n.startswith("cloud-translate") for n in names):
        mt = CloudTranslate(cfg["mt"]["google"], config.project())
    provider_of = {n: cfg["llm"]["configs"][n]["provider"] for n in clients}
    last_call: dict[str, float] = {}

    runs_file = OUT / args.log
    records = read_jsonl(runs_file)
    done = done_keys(records, ("sentence_id", "config", "repeat"))
    for direction in ("guide_to_family", "family_to_guide"):
        if direction not in directions:
            continue
        todo = [s for s in sentences if s["direction"] == direction]
        if args.limit:
            todo = todo[: args.limit]
        repeats = args.repeats if direction == "guide_to_family" else 1
        print(f"{direction}: {len(todo)} sentences x {len(names)} configs x {repeats} repeats")
        for sentence in todo:
            for name in names:
                for repeat in range(repeats):
                    if (sentence["id"], name, repeat) in done:
                        continue
                    provider = provider_of.get(name, "google")
                    wait = MIN_INTERVAL_S.get(provider, 0) - (
                        time.monotonic() - last_call.get(provider, 0)
                    )
                    if wait > 0:
                        time.sleep(wait)
                    last_call[provider] = time.monotonic()
                    record = {
                        "sentence_id": sentence["id"],
                        "direction": direction,
                        "set": sentence["set"],
                        "source": sentence["text"],
                        "config": name,
                        "repeat": repeat,
                    }
                    try:
                        if name in clients:
                            record |= run_llm(clients[name], sentence)
                        else:
                            record |= run_mt(mt, sentence, name.endswith("glossary"))
                        record["json_ok"] = bool(record["output"])
                        print(
                            f"  {sentence['id']} {name} #{repeat} {record['total_s']:.2f}s "
                            f"{record['output']}"
                        )
                    except Exception as exc:  # noqa: BLE001 - log, keep going, re-run later
                        record["error"] = f"{type(exc).__name__}: {exc}"
                        print(f"  {sentence['id']} {name} #{repeat} ERROR {record['error']}")
                    append_jsonl(runs_file, record)


if __name__ == "__main__":
    main()
