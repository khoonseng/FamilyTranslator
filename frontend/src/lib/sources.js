// Which speech-to-text, translator and voice produced a sentence, for host phones only (owner
// requests 2026-10-27). `fallback` is true when anything other than the main path was used:
// gpt-transcribe (the safety net, or the Chirp 3 stream down), Qwen / Cloud Translation, or a
// voice other than a Chirp 3 HD one (Despina refused the sentence, e.g. too long).

const STT = { chirp_3: "Chirp 3", "gpt-transcribe": "gpt-transcribe", typed: "Typed" };
const TRANSLATORS = { gemini: "Gemini", qwen: "Qwen", "cloud-translate": "Cloud Translation" };
const MAIN = new Set(["chirp_3", "typed", "gemini"]);

// yue-HK-Chirp3-HD-Despina -> Despina, yue-HK-Standard-A -> Standard-A
const voiceName = (voice) => voice.replace(/^[a-z]+-[A-Z]+-/, "").replace(/^Chirp3-HD-/, "");

export function sourceLabel({ stt = "", provider = "", voice = "" }) {
  const parts = stt ? stt.split("+") : [];
  const names = [
    parts.map((p) => STT[p] ?? p).join(" + "),
    TRANSLATORS[provider] ?? provider,
    voice && voiceName(voice),
  ];
  return {
    text: names.filter(Boolean).join(" · "),
    fallback:
      [...parts, provider].some((name) => name && !MAIN.has(name)) ||
      (!!voice && !voice.includes("Chirp3-HD")),
  };
}
