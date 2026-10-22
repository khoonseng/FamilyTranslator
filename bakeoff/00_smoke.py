"""Step 1: call every provider once, before any bench runs.

Checks model IDs, reasoning switches, Chirp 3 language labels, real yue-HK voices and the
Cloud Translation language pairs. Each check reports PASS/FAIL and the run carries on, so one
broken provider doesn't hide the others. Costs a few cents.

Run: uv run python 00_smoke.py [--only stt,llm,mt,tts]
"""

import argparse
import io
import traceback
import wave

from lib import config
from lib.llm import ChatClient, reasoning_tokens, translation_messages
from lib.mt import CloudTranslate
from lib.scoring import colloquial_score, parse_json_object
from lib.stt import GoogleStreamingStt, GoogleStt, OpenAiStt
from lib.tts import GoogleTts

MANDARIN = "大家好，我们现在到了洪崖洞，晚上七点以后灯会全部亮起来。"
CANTONESE = "我哋而家去食重慶火鍋，你哋想唔想食辣啲？"

results: list[tuple[str, bool]] = []


def check(label: str, fn) -> None:
    print(f"\n--- {label}")
    try:
        fn()
        results.append((label, True))
        print("PASS")
    except Exception as exc:  # noqa: BLE001 - report every failure and keep going
        results.append((label, False))
        print(f"FAIL: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=1)


def tts_checks(cfg: dict, tts_client: GoogleTts) -> None:
    def list_voices(language: str):
        voices = tts_client.voices(language)
        assert voices, f"no voices for {language}"
        for v in voices:
            mark = "  <- Chirp 3 HD" if v.is_chirp3_hd else ""
            print(f"  {v.name}  {v.languages}  {v.gender}  {v.sample_rate_hz} Hz{mark}")
        chirp = [v for v in voices if v.is_chirp3_hd]
        print(f"  {len(chirp)} Chirp 3 HD voice(s) of {len(voices)}")
        wrong = [v.name for v in voices if language not in v.languages]
        assert not wrong, f"voices not tagged {language}: {wrong}"

    t = cfg["tts"]["google"]
    check(f"TTS voices {t['yue_language']}", lambda: list_voices(t["yue_language"]))
    check(f"TTS voices {t['cmn_language']}", lambda: list_voices(t["cmn_language"]))


def synth_wav(cfg: dict, tts_client: GoogleTts, text: str, language: str) -> bytes:
    voices = [v for v in tts_client.voices(language) if v.is_chirp3_hd] or tts_client.voices(
        language
    )
    result = tts_client.synthesize(
        text, voices[0].name, language, encoding="LINEAR16", sample_rate_hz=16000
    )
    print(f"  synthesised test audio with {voices[0].name} in {result.latency_s:.2f}s")
    return result.audio


def stt_checks(cfg: dict, tts_client: GoogleTts) -> None:
    t = cfg["tts"]["google"]
    audio = {}

    def make_audio():
        audio["cmn"] = synth_wav(cfg, tts_client, MANDARIN, t["cmn_language"])
        audio["yue"] = synth_wav(cfg, tts_client, CANTONESE, t["yue_language"])

    check("STT test audio (via TTS)", make_audio)
    if not audio:
        return

    google = GoogleStt(cfg["stt"]["google"], config.project())
    phrases = [term["zh"] for term in config.glossary()]
    cases = [
        ("cmn", ["cmn-Hans-CN"], None),
        ("cmn", ["cmn-Hans-CN"], phrases),
        ("cmn", ["cmn-Hans-CN", "yue-Hant-HK"], None),  # junk-filter label check
        ("yue", ["cmn-Hans-CN", "yue-Hant-HK"], None),
        ("yue", ["yue-Hant-HK", "en-US"], None),  # Family mode
    ]
    for source, languages, hints in cases:

        def run(source=source, languages=languages, hints=hints):
            r = google.transcribe(audio[source], languages, hints)
            print(f"  {r.latency_s:.2f}s  labels={r.languages}  {r.text}")
            assert r.text, "empty transcript"

        hint = " + glossary hints" if hints else ""
        check(f"Chirp 3 on {source} audio, {languages}{hint}", run)

    streaming = GoogleStreamingStt(cfg["stt"]["google"], config.project())
    for source in ("cmn", "yue"):

        def run_stream(source=source):
            with wave.open(io.BytesIO(audio[source])) as w:
                pcm = w.readframes(w.getnframes())
            r = streaming.stream(pcm, ["cmn-Hans-CN", "yue-Hant-HK"], phrases)
            print(f"  end of speech -> final: {r.finalize_latency_s:.2f}s  {r.text}")
            assert r.finals, "no final transcript"

        check(f"Chirp 3 streaming on {source} audio, Guide mode", run_stream)

    for model in cfg["stt"]["openai"]["models"]:
        for source, languages in (("cmn", ["cmn-Hans-CN"]), ("yue", ["yue-Hant-HK"])):

            def run(model=model, source=source, languages=languages):
                r = OpenAiStt(model).transcribe(audio[source], languages, phrases)
                print(f"  {r.latency_s:.2f}s  {r.text}")
                assert r.text, "empty transcript"

            check(f"OpenAI {model} on {source} audio", run)


def llm_checks(cfg: dict) -> None:
    messages = translation_messages("guide_to_family", MANDARIN, [])
    for name in cfg["llm"]["configs"]:

        def run(name=name):
            client = ChatClient(name, cfg)
            r = client.chat(messages, stream=False)
            print(f"  model={client.model} params={client.params}")
            print(f"  {r.total_s:.2f}s  reasoning_tokens={reasoning_tokens(r.usage)}")
            print(f"  usage={r.usage}")
            print(f"  reply={r.text}")
            parsed = parse_json_object(r.text)
            assert parsed and parsed.get("yue"), "reply is not JSON with a `yue` field"
            print(f"  colloquial={colloquial_score(parsed['yue'], cfg['scoring'])}")
            s = client.chat(messages, stream=True)
            ttft = f"{s.ttft_s:.2f}s" if s.ttft_s is not None else "n/a"
            print(f"  streamed: first token {ttft}, total {s.total_s:.2f}s")

        check(f"LLM {name}", run)


def mt_checks(cfg: dict) -> None:
    mt = CloudTranslate(cfg["mt"]["google"], config.project())
    pairs = [
        (MANDARIN, "zh-CN", "yue"),
        (MANDARIN, "zh-CN", "en"),
        (CANTONESE, "yue", "zh-CN"),
        ("Can we stop for a toilet break soon?", "en", "zh-CN"),
    ]
    for text, source, target in pairs:

        def run(text=text, source=source, target=target):
            r = mt.translate(text, source, target)
            print(f"  {r.latency_s:.2f}s  {r.text}")
            if target == "yue":
                print(f"  colloquial={colloquial_score(r.text, cfg['scoring'])}")

        check(f"Cloud Translation {source} -> {target}", run)
    if cfg["mt"]["google"].get("glossary_id"):
        check(
            "Cloud Translation zh-CN -> yue with glossary",
            lambda: print("  " + mt.translate(MANDARIN, "zh-CN", "yue", use_glossary=True).text),
        )
    else:
        print("\n(glossary not uploaded yet; glossary check skipped)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="tts,stt,llm,mt", help="comma-separated subset")
    only = set(parser.parse_args().only.split(","))

    cfg = config.load()
    print(f"Project: {cfg['gcp']['project'] or '(GCP_PROJECT not set)'}")
    print("Reminder: Groq Data Controls must have Zero Data Retention switched on (rule 14).")

    tts_client = GoogleTts(cfg["tts"]["google"]) if only & {"tts", "stt"} else None
    if "tts" in only:
        tts_checks(cfg, tts_client)
    if "stt" in only:
        stt_checks(cfg, tts_client)
    if "llm" in only:
        llm_checks(cfg)
    if "mt" in only:
        mt_checks(cfg)

    passed = sum(ok for _, ok in results)
    print(f"\n=== {passed}/{len(results)} checks passed")
    for label, ok in results:
        if not ok:
            print(f"  FAIL  {label}")


if __name__ == "__main__":
    main()
