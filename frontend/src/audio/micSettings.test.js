import { describe, expect, it } from "vitest";
import { levelOf, micConstraints, microphones } from "./micSettings.js";

describe("micConstraints", () => {
  it("defaults to the phone's chosen input with voice processing on", () => {
    expect(micConstraints()).toEqual({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  });

  it("a chosen input, with voice processing off", () => {
    expect(micConstraints({ deviceId: "dji", processing: false })).toEqual({
      audio: {
        deviceId: { exact: "dji" },
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
  });
});

describe("levelOf", () => {
  it("silence is empty, full scale is full", () => {
    expect(levelOf(new Float32Array(512))).toBe(0);
    expect(levelOf(new Float32Array(512).fill(1))).toBe(1);
  });

  it("speech-like levels land in between", () => {
    const level = levelOf(new Float32Array(512).fill(0.03)); // about -30 dBFS
    expect(level).toBeGreaterThan(0.4);
    expect(level).toBeLessThan(0.6);
  });

  it("no frame shows nothing", () => {
    expect(levelOf(undefined)).toBe(0);
  });
});

describe("microphones", () => {
  it("lists inputs only, with a name for unnamed ones", () => {
    const devices = [
      { kind: "audioinput", deviceId: "a", label: "iPhone Microphone" },
      { kind: "audiooutput", deviceId: "b", label: "Speaker" },
      { kind: "audioinput", deviceId: "c", label: "" },
    ];
    expect(microphones(devices)).toEqual([
      { id: "a", label: "iPhone Microphone" },
      { id: "c", label: "Microphone 2" },
    ]);
  });
});
