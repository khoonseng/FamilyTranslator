// Which speech-to-text and which translator produced a sentence, for host phones only (owner
// request 2026-10-27). `fallback` is true when anything other than the main path was used:
// gpt-transcribe (the safety net, or the Chirp 3 stream down), or Qwen / Cloud Translation.

const STT = { chirp_3: "Chirp 3", "gpt-transcribe": "gpt-transcribe", typed: "Typed" };
const TRANSLATORS = { gemini: "Gemini", qwen: "Qwen", "cloud-translate": "Cloud Translation" };
const MAIN = new Set(["chirp_3", "typed", "gemini"]);

export function sourceLabel({ stt = "", provider = "" }) {
  const parts = stt ? stt.split("+") : [];
  const names = [parts.map((p) => STT[p] ?? p).join(" + "), TRANSLATORS[provider] ?? provider];
  return {
    text: names.filter(Boolean).join(" · "),
    fallback: [...parts, provider].some((name) => name && !MAIN.has(name)),
  };
}
