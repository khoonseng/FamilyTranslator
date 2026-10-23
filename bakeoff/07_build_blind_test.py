"""Step 5b: build the in-laws' blind test as ONE self-contained HTML file (all audio inside).

Open out/blind/blind_test.html on the laptop (double-click, no server or network needed) and
hand over the earphones. Three rounds, in Cantonese, one sentence per screen:
  A  voice        the same sentence in 4 voices: pick the nicest
  B  translation  each finalist's version, in the voice that won round A, with the text shown
                  large: rate each (唔自然 / 都可以 / 好自然) and pick the best
  C  speed        a few faster clips: can they follow?

Clips get random ids and options are shuffled per sentence, so nothing on the page reveals which
voice or translator is which. The answer key is written separately to out/blind/key.json.
Progress is saved in the browser, so closing the page doesn't lose answers. At the end the page
offers the results as a file to download; 08_blind_score.py reveals and tallies them.

Run: uv run python 07_build_blind_test.py
"""

import base64
import json
import random
import secrets

from lib.config import OUT

MANIFEST = OUT / "tts" / "manifest.json"
BLIND = OUT / "blind"


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("No clips yet: run 06_tts_bench.py first.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = manifest["items"]
    rng = random.Random(secrets.randbits(64))
    audio, key = {}, {"voices": manifest["voices"], "clips": {}, "options": {}}

    def add_clip(item: dict) -> str:
        clip_id = secrets.token_hex(4)
        audio[clip_id] = base64.b64encode((OUT / item["file"]).read_bytes()).decode()
        key["clips"][clip_id] = {k: item.get(k) for k in ("round", "sentence", "voice_idx")}
        return clip_id

    def sentences(round_name: str) -> list[str]:
        return list(dict.fromkeys(i["sentence"] for i in items if i["round"] == round_name))

    round_a = []
    for sid in sentences("A"):
        clips = [
            {"id": add_clip(i), "v": i["voice_idx"]}
            for i in items
            if i["round"] == "A" and i["sentence"] == sid
        ]
        rng.shuffle(clips)
        round_a.append({"clips": clips})

    round_b = []
    b_sentences = sentences("B")
    rng.shuffle(b_sentences)
    for sid in b_sentences:
        options = []
        for name in manifest["finalists"]:
            versions = [
                i
                for i in items
                if i["round"] == "B" and i["sentence"] == sid and i.get("config") == name
            ]
            if not versions:
                continue
            option_id = secrets.token_hex(4)
            key["options"][option_id] = {"sentence": sid, "config": name}
            options.append(
                {
                    "id": option_id,
                    "text": versions[0]["text"],
                    "clips": {str(i["voice_idx"]): add_clip(i) for i in versions},
                }
            )
        rng.shuffle(options)
        round_b.append({"options": options})

    round_c = []
    for sid in sentences("C"):
        clips = {
            str(i["voice_idx"]): add_clip(i)
            for i in items
            if i["round"] == "C" and i["sentence"] == sid
        }
        round_c.append({"clips": clips})

    data = {
        "voiceCount": len(manifest["voices"]),
        "a": round_a,
        "b": round_b,
        "c": round_c,
        "audio": audio,
        "build": secrets.token_hex(3),  # ties a results file to this page and key
    }
    key["build"] = data["build"]
    BLIND.mkdir(parents=True, exist_ok=True)
    page = PAGE.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    (BLIND / "blind_test.html").write_text(page, encoding="utf-8")
    (BLIND / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), "utf-8")
    size_mb = (BLIND / "blind_test.html").stat().st_size / 1e6
    print(
        f"Round A {len(round_a)} sentences, B {len(round_b)}, C {len(round_c)}; "
        f"{len(audio)} clips, {size_mb:.1f} MB"
    )
    print(f"Page: {BLIND / 'blind_test.html'}   Key (don't open during the test): key.json")


PAGE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>廣東話試聽</title>
<style>
  :root { --bg: #fffdf7; --fg: #1a1a1a; --accent: #b3471d; --soft: #f1e7d8; --line: #d8c9b2; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font: 22px/1.5 "PingFang HK", "Microsoft JhengHei", system-ui, sans-serif; }
  main { max-width: 760px; margin: 0 auto; padding: 20px 16px 60px; }
  h1 { font-size: 34px; margin: 8px 0 4px; }
  .step { color: #6b5a44; font-size: 18px; }
  .q { font-size: 28px; font-weight: 700; margin: 18px 0 10px; }
  button { font: inherit; border: 2px solid var(--line); background: #fff; color: var(--fg);
           border-radius: 14px; padding: 14px 18px; margin: 6px 6px 6px 0; cursor: pointer; }
  button.play { background: var(--soft); min-width: 150px; }
  button.chosen { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.big { font-size: 28px; padding: 18px 28px; }
  button.next { background: var(--accent); color: #fff; border-color: var(--accent); }
  button:disabled { opacity: .4; cursor: default; }
  .card { border: 2px solid var(--line); border-radius: 16px; padding: 14px; margin: 14px 0;
          background: #fff; }
  .label { font-weight: 700; font-size: 26px; margin-right: 8px; }
  .text { font-size: 30px; line-height: 1.45; margin: 10px 0; }
  .nav { margin-top: 24px; display: flex; justify-content: space-between; }
  textarea { width: 100%; height: 120px; font: 13px ui-monospace, monospace; }
</style></head><body><main id="app"></main>
<script>
const DATA = /*DATA*/null;
const LABELS = ["甲", "乙", "丙", "丁", "戊"];
const STORE = "blind-" + DATA.build;
let state = (() => { try { return JSON.parse(localStorage.getItem(STORE)) || null; }
                     catch (e) { return null; } })()
            || { screen: "start", i: 0, a: {}, b: {}, c: {} };
function save() { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }

let player = null;
function play(id) {
  if (player) { player.pause(); }
  player = new Audio("data:audio/mpeg;base64," + DATA.audio[id]);
  player.play();
}

function winner() {  // round A: the voice picked most often (ties: the earlier-listed voice)
  const votes = Array(DATA.voiceCount).fill(0);
  Object.values(state.a).forEach(v => votes[v] += 1);
  return votes.indexOf(Math.max(...votes));
}

const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => k.startsWith("on") ? e[k] = v : e.setAttribute(k, v));
  kids.flat().forEach(k => e.append(k));
  return e;
};
const btn = (text, onclick, cls = "") => el("button", { class: cls, onclick }, text);

function nav(canNext, onNext, onBack) {
  return el("div", { class: "nav" },
    onBack ? btn("← 上一句", onBack) : el("span"),
    Object.assign(btn("下一句 →", onNext, "next big"), { disabled: !canNext }));
}

function go(screen, i = 0) {
  if (player) player.pause();
  state.screen = screen; state.i = i; save(); render();
}

function render() {
  const app = document.getElementById("app");
  app.innerHTML = "";
  const s = state.screen, i = state.i;
  if (s === "start") {
    app.append(el("h1", {}, "廣東話試聽"),
      el("p", {}, "請戴好耳筒。每一句會有幾個版本，聽完之後揀你最鍾意嗰個。冇對錯㗎，憑感覺就得。"),
      btn("開始", () => go("a", 0), "next big"));
  } else if (s === "a") {
    const item = DATA.a[i];
    app.append(el("div", { class: "step" }, `第一部分：聲音　第 ${i + 1} / ${DATA.a.length} 句`),
      el("div", { class: "q" }, "邊一把聲最好聽、最易聽？"),
      ...item.clips.map((c, k) => el("div", { class: "card" },
        el("span", { class: "label" }, LABELS[k]),
        btn("▶ 播放", () => play(c.id), "play"),
        btn("揀呢個", () => { state.a[i] = c.v; save(); render(); },
            state.a[i] === c.v ? "chosen" : ""))),
      nav(state.a[i] !== undefined,
          () => i + 1 < DATA.a.length ? go("a", i + 1) : go("b", 0),
          i > 0 ? () => go("a", i - 1) : null));
  } else if (s === "b") {
    const item = DATA.b[i], v = String(winner());
    const answer = state.b[i] || (state.b[i] = { ratings: {}, best: null });
    const rated = item.options.every(o => answer.ratings[o.id]);
    app.append(el("div", { class: "step" }, `第二部分：講法　第 ${i + 1} / ${DATA.b.length} 句`),
      el("div", { class: "q" }, "每個版本聽完，話我知自唔自然；最後揀最好嗰個。"),
      ...item.options.map((o, k) => el("div", { class: "card" },
        el("span", { class: "label" }, LABELS[k]),
        btn("▶ 播放", () => play(o.clips[v]), "play"),
        el("div", { class: "text" }, o.text),
        ...[["唔自然", 1], ["都可以", 2], ["好自然", 3]].map(([t, n]) =>
          btn(t, () => { answer.ratings[o.id] = n; save(); render(); },
              answer.ratings[o.id] === n ? "chosen" : "")))),
      el("div", { class: "q" }, "邊個版本最好？"),
      el("div", {}, ...item.options.map((o, k) =>
        btn(LABELS[k], () => { answer.best = o.id; save(); render(); },
            answer.best === o.id ? "chosen big" : "big"))),
      nav(rated && answer.best,
          () => i + 1 < DATA.b.length ? go("b", i + 1) : go("c", 0),
          () => i > 0 ? go("b", i - 1) : go("a", DATA.a.length - 1)));
  } else if (s === "c") {
    const item = DATA.c[i], v = String(winner());
    app.append(el("div", { class: "step" }, `第三部分：快啲講　第 ${i + 1} / ${DATA.c.length} 句`),
      el("div", { class: "q" }, "呢句講得快少少，聽唔聽得明？"),
      el("div", { class: "card" }, btn("▶ 播放", () => play(item.clips[v]), "play")),
      el("div", {}, ...[["聽得明", 3], ["有少少吃力", 2], ["聽唔明", 1]].map(([t, n]) =>
        btn(t, () => { state.c[i] = n; save(); render(); },
            state.c[i] === n ? "chosen big" : "big"))),
      nav(state.c[i] !== undefined,
          () => i + 1 < DATA.c.length ? go("c", i + 1) : go("end"),
          () => i > 0 ? go("c", i - 1) : go("b", DATA.b.length - 1)));
  } else {
    const result = { build: DATA.build, voiceWinner: winner(),
      a: DATA.a.map((_, k) => state.a[k]),
      b: DATA.b.map((_, k) => state.b[k]),
      c: DATA.c.map((_, k) => state.c[k]) };
    const json = JSON.stringify(result);
    const download = () => {
      const a = el("a", { href: URL.createObjectURL(new Blob([json], { type: "application/json" })),
                          download: "blind_results.json" });
      a.click();
    };
    app.append(el("h1", {}, "多謝！"), el("p", {}, "做完喇，辛苦晒。"),
      btn("下載結果 (blind_results.json)", download, "next big"),
      el("p", { class: "step" }, "Or copy this text into out/blind/blind_results.json:"),
      el("textarea", { readonly: "" }, json),
      btn("← 返回修改", () => go("c", DATA.c.length - 1)));
  }
  window.scrollTo(0, 0);
}
render();
</script></body></html>
"""

if __name__ == "__main__":
    main()
