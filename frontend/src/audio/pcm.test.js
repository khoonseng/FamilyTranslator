import { describe, expect, it } from "vitest";
import { floatTo16BitPcm } from "./pcm.js";

describe("floatTo16BitPcm", () => {
  it("scales and clips samples to 16-bit", () => {
    expect(Array.from(floatTo16BitPcm(new Float32Array([0, 1, -1, 0.5, 2, -2])))).toEqual([
      0, 32767, -32768, 16383, 32767, -32768,
    ]);
  });
});
