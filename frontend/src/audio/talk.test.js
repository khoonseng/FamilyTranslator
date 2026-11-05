import { describe, expect, it } from "vitest";
import { downsample, talkBlock } from "./talk.js";

describe("talkBlock", () => {
  const open = { canTalk: true, guideTalking: false, familyTalking: false, talking: false };

  it("Talk is open when the guide is quiet and nobody else is talking", () => {
    expect(talkBlock(open)).toBe("");
  });

  it("without the hub PIN, Talk is locked", () => {
    expect(talkBlock({ ...open, canTalk: false })).toBe("locked");
  });

  it("the guide has priority, then one family phone at a time", () => {
    expect(talkBlock({ ...open, guideTalking: true })).toBe("guide");
    expect(talkBlock({ ...open, familyTalking: true })).toBe("someone");
  });

  it("once talking, nothing blocks finishing", () => {
    expect(talkBlock({ ...open, talking: true, guideTalking: true, familyTalking: true })).toBe("");
  });
});

describe("downsample", () => {
  it("48 kHz to 16 kHz keeps a third of the samples, averaged", () => {
    const out = downsample(Float32Array.from([0, 0.3, 0.6, 1, 1, 1]), 48000);
    expect(out.length).toBe(2);
    expect(out[0]).toBeCloseTo(0.3);
    expect(out[1]).toBeCloseTo(1);
  });

  it("44.1 kHz gives about 16000 samples a second", () => {
    expect(downsample(new Float32Array(44100), 44100).length).toBe(16000);
  });

  it("already 16 kHz: unchanged", () => {
    expect(Array.from(downsample(Float32Array.from([0.1, 0.2]), 16000))).toEqual([
      expect.closeTo(0.1),
      expect.closeTo(0.2),
    ]);
  });
});
