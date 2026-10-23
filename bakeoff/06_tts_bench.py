"""Step 5a: Cantonese voices.

--shortlist  every yue-HK voice reads the same sentences, on one page for you and your wife:
             out/voices/shortlist.html. Tick 3 Chirp 3 HD voices and paste the line it shows
             into config.yaml (tts.google.yue_voices).
(default)    generate the blind-test clips for the 3 shortlisted voices plus the older
             reference voice, and record how long each voice takes to synthesise:
               round A  voice: the same text in each voice
               round B  translation: every drafted sentence from each finalist, in every voice
               round C  speed: a few sentences at the faster speaking rate
             Writes out/tts/clips/*.mp3 and out/tts/manifest.json for 07_build_blind_test.py.

Clips are cached by voice, rate and text, so re-running only synthesises what's new. Everything
stays inside Google's free 1 million characters a month (a full run is about 7,000).

Run: uv run python 06_tts_bench.py --shortlist
     uv run python 06_tts_bench.py
"""

import argparse
import base64
import hashlib
import html
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lib import config
from lib.config import OUT
from lib.records import median, read_jsonl
from lib.tts import GoogleTts

CLIPS = OUT / "tts" / "clips"
MANIFEST = OUT / "tts" / "manifest.json"


def clip_path(voice: str, rate: float, text: str) -> Path:
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]
    return CLIPS / f"{key}.mp3"


def synthesize_all(tts: GoogleTts, jobs: list[dict], language: str) -> dict[Path, float]:
    """Synthesise every job not already cached. Returns {path: seconds} for new clips."""
    todo = {clip_path(j["voice"], j["rate"], j["text"]): j for j in jobs}
    todo = {p: j for p, j in todo.items() if not p.exists()}
    CLIPS.mkdir(parents=True, exist_ok=True)

    def one(item):
        path, job = item
        for attempt in (1, 2):
            try:
                r = tts.synthesize(job["text"], job["voice"], language, speaking_rate=job["rate"])
                path.write_bytes(r.audio)
                return path, r.latency_s
            except Exception as exc:  # noqa: BLE001 - one retry, then report and carry on
                if attempt == 2:
                    print(f"  FAILED {job['voice']} {job['text'][:20]}: {exc}")
        return path, None

    print(f"Synthesising {len(todo)} new clips ({len(jobs) - len(todo)} cached)")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(pool.map(one, todo.items()))
    return {p: s for p, s in results.items() if s is not None}


def short_name(voice: str) -> str:
    return voice.split("-")[-1] if "Chirp3-HD" in voice else f"{voice} (older voice)"


def shortlist(cfg: dict, tts: GoogleTts) -> None:
    t = cfg["tts"]["google"]
    voices = tts.voices(t["yue_language"])
    texts = t["shortlist_texts"]
    jobs = [{"voice": v.name, "rate": 1.0, "text": text} for v in voices for text in texts]
    synthesize_all(tts, jobs, t["yue_language"])

    rows = []
    for v in voices:
        players = "".join(
            f'<audio controls preload="none" src="data:audio/mpeg;base64,'
            f'{base64.b64encode(clip_path(v.name, 1.0, text).read_bytes()).decode()}"></audio>'
            for text in texts
            if clip_path(v.name, 1.0, text).exists()
        )
        pick = (
            f'<input type="checkbox" value="{v.name}" onchange="update()">'
            if v.is_chirp3_hd
            else '<span class="ref">reference</span>'
        )
        gender = {"FEMALE": "女聲", "MALE": "男聲"}.get(v.gender, v.gender)
        rows.append(
            f"<tr><td>{pick}</td><td><b>{html.escape(short_name(v.name))}</b><br>"
            f"<small>{gender}</small></td><td>{players}</td></tr>"
        )
    page = SHORTLIST_PAGE.replace("{texts}", "".join(f"<li>{html.escape(x)}</li>" for x in texts))
    page = page.replace("{rows}", "\n".join(rows))
    out = OUT / "voices" / "shortlist.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Open {out} in a browser (from Windows: \\\\wsl$ path, or copy it to the desktop).")


def latest_texts(log: str) -> tuple[dict, dict]:
    """{(sentence, config): yue text} preferring repeat 0, and {sentence: Mandarin source}."""
    texts, sources = {}, {}
    rows = [r for r in read_jsonl(OUT / log) if not r.get("error") and r.get("output")]
    for r in sorted(rows, key=lambda r: -r["repeat"]):  # lower repeats overwrite higher ones
        if r["direction"] == "guide_to_family" and r["output"].get("yue"):
            texts[(r["sentence_id"], r["config"])] = r["output"]["yue"]
            sources[r["sentence_id"]] = r["source"]
    return texts, sources


def blind_clips(cfg: dict, tts: GoogleTts) -> None:
    t, b = cfg["tts"]["google"], cfg["blind_test"]
    if len(t["yue_voices"]) != 3:
        raise SystemExit(
            "Put your 3 shortlisted voices in config.yaml (tts.google.yue_voices) first: "
            "run with --shortlist."
        )
    voices = list(t["yue_voices"]) + [t["reference_voice"]]
    log = b["translations_log"]
    suffix = Path(log).stem.removeprefix("translations")
    finalists_file = OUT / f"finalists{suffix}.json"
    if not finalists_file.exists():
        raise SystemExit(f"No {finalists_file.name}: run 05_translate_score.py --log {log}")
    finalists = [f["config"] for f in json.loads(finalists_file.read_text(encoding="utf-8"))]
    texts, sources = latest_texts(log)

    def text_for(sentence: str, preferred: str) -> str:
        for name in [preferred, *finalists]:
            if (sentence, name) in texts:
                return texts[(sentence, name)]
        raise SystemExit(f"No translation of {sentence} in {log}")

    items = []
    for sid in b["voice_round"]["sentences"]:
        text = text_for(sid, b["voice_round"]["text_from"])
        items += [
            {"round": "A", "sentence": sid, "voice_idx": i, "rate": 1.0, "text": text}
            for i in range(len(voices))
        ]
    sentences = sorted({sid for sid, _ in texts})
    for sid in sentences:
        for name in finalists:
            if (sid, name) not in texts:
                print(f"  note: {name} has no output for {sid}; left out of round B")
                continue
            items += [
                {
                    "round": "B",
                    "sentence": sid,
                    "config": name,
                    "voice_idx": i,
                    "rate": 1.0,
                    "text": texts[(sid, name)],
                }
                for i in range(len(voices))
            ]
    speed = b["speed_round"]
    for sid in speed["sentences"]:
        text = text_for(sid, speed["text_from"])
        items += [
            {
                "round": "C",
                "sentence": sid,
                "voice_idx": i,
                "rate": speed["speaking_rate"],
                "text": text,
            }
            for i in range(len(voices))
        ]

    jobs = [{"voice": voices[i["voice_idx"]], "rate": i["rate"], "text": i["text"]} for i in items]
    latencies = synthesize_all(tts, jobs, t["yue_language"])
    for item in items:
        path = clip_path(voices[item["voice_idx"]], item["rate"], item["text"])
        item["file"] = str(path.relative_to(OUT)) if path.exists() else None
    missing = [i for i in items if not i["file"]]
    if missing:
        raise SystemExit(f"{len(missing)} clips failed to synthesise; re-run to retry them.")

    timing = {}
    for path, seconds in latencies.items():
        job = next(j for j in jobs if clip_path(j["voice"], j["rate"], j["text"]) == path)
        timing.setdefault(job["voice"], []).append(seconds)
    manifest = {
        "voices": voices,
        "finalists": finalists,
        "sources": sources,
        "items": items,
        "tts_seconds_median": {v: median(s) for v, s in timing.items()},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    chars = sum(len(i["text"]) for i in items)
    print(f"{len(items)} clips ({chars} characters) -> {MANIFEST}")
    for voice, seconds in manifest["tts_seconds_median"].items():
        print(f"  {voice}: median {seconds:.2f}s per clip (new clips only)")


SHORTLIST_PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voice shortlist</title>
<style>
  body { font: 17px/1.5 system-ui, sans-serif; margin: 0 auto; max-width: 900px; padding: 16px;
         background: #fff; color: #111; }
  table { border-collapse: collapse; width: 100%; }
  td { border-bottom: 1px solid #ddd; padding: 8px 6px; vertical-align: middle; }
  audio { width: 230px; margin: 2px 6px 2px 0; }
  input[type=checkbox] { transform: scale(1.6); }
  .ref { color: #777; font-size: 13px; }
  #line { position: sticky; bottom: 0; background: #ffd; padding: 12px; border: 1px solid #cc9;
          font-family: ui-monospace, monospace; margin-top: 16px; }
</style></head><body>
<h1>Cantonese voice shortlist</h1>
<p>Every voice reads the same two sentences:</p><ol>{texts}</ol>
<p>Tick the <b>3</b> Chirp 3 HD voices you'd most like the in-laws to compare (a mix of male and
female is good). The older voices at the bottom are only for reference: one of them plays in the
blind test as the fallback voice.</p>
<table>{rows}</table>
<div id="line">Tick 3 voices.</div>
<script>
function update() {
  const picked = [...document.querySelectorAll("input:checked")].map(x => x.value);
  document.getElementById("line").textContent = picked.length === 3
    ? "Paste into config.yaml under tts.google:   yue_voices: [" + picked.join(", ") + "]"
    : "Tick 3 voices (" + picked.length + " ticked).";
}
document.addEventListener("play", e => {
  document.querySelectorAll("audio").forEach(a => { if (a !== e.target) a.pause(); });
}, true);
</script></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shortlist", action="store_true", help="build the shortlist page")
    args = parser.parse_args()
    cfg = config.load()
    tts = GoogleTts(cfg["tts"]["google"])
    if args.shortlist:
        shortlist(cfg, tts)
    else:
        blind_clips(cfg, tts)


if __name__ == "__main__":
    main()
