import { describe, expect, it } from "vitest";
import { sourceLabel } from "./sources.js";

describe("sourceLabel", () => {
  it("the main path", () => {
    expect(sourceLabel({ stt: "chirp_3", provider: "gemini" })).toEqual({
      text: "Chirp 3 · Gemini",
      fallback: false,
    });
    expect(sourceLabel({ stt: "typed", provider: "gemini" }).text).toBe("Typed · Gemini");
  });

  it("any fallback is flagged", () => {
    expect(sourceLabel({ stt: "gpt-transcribe", provider: "gemini" }).fallback).toBe(true);
    expect(sourceLabel({ stt: "chirp_3", provider: "qwen" })).toEqual({
      text: "Chirp 3 · Qwen",
      fallback: true,
    });
    expect(sourceLabel({ stt: "chirp_3", provider: "cloud-translate" }).text).toBe(
      "Chirp 3 · Cloud Translation",
    );
  });

  it("a sentence joined from both speech-to-texts names both", () => {
    expect(sourceLabel({ stt: "chirp_3+gpt-transcribe", provider: "gemini" })).toEqual({
      text: "Chirp 3 + gpt-transcribe · Gemini",
      fallback: true,
    });
  });

  it("names the voice, and flags the fallback voice", () => {
    const main = { stt: "chirp_3", provider: "gemini", voice: "yue-HK-Chirp3-HD-Despina" };
    expect(sourceLabel(main)).toEqual({ text: "Chirp 3 · Gemini · Despina", fallback: false });
    expect(sourceLabel({ ...main, voice: "yue-HK-Standard-A" })).toEqual({
      text: "Chirp 3 · Gemini · Standard-A",
      fallback: true,
    });
  });

  it("no translation, or an older record without the speech-to-text", () => {
    expect(sourceLabel({ stt: "chirp_3", provider: "" }).text).toBe("Chirp 3");
    expect(sourceLabel({ provider: "gemini" }).text).toBe("Gemini");
    expect(sourceLabel({})).toEqual({ text: "", fallback: false });
  });
});
