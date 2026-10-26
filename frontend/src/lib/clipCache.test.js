import { describe, expect, it } from "vitest";
import { ClipCache, memoryBackend } from "./clipCache.js";

describe("ClipCache", () => {
  it("loads one day's sentences, oldest first", async () => {
    const cache = new ClipCache(memoryBackend());
    await cache.putSentence("2026-12-19", { id: 10, yue: "十" });
    await cache.putSentence("2026-12-19", { id: 9, yue: "九" });
    await cache.putSentence("2026-12-20", { id: 1, yue: "第二日" });
    const day = await cache.loadDay("2026-12-19");
    expect(day.map((s) => s.id)).toEqual([9, 10]);
    expect(day[0].day).toBe("2026-12-19");
  });

  it("a later write of a sentence replaces it (played flag, English)", async () => {
    const cache = new ClipCache(memoryBackend());
    await cache.putSentence("d", { id: 1, played: false });
    await cache.putSentence("d", { id: 1, played: true });
    expect(await cache.loadDay("d")).toEqual([{ id: 1, played: true, day: "d" }]);
  });

  it("keeps clips per day and sentence", async () => {
    const cache = new ClipCache(memoryBackend());
    const mp3 = new Uint8Array([1, 2, 3]).buffer;
    await cache.putClip("d", 4, mp3);
    expect(await cache.getClip("d", 4)).toBe(mp3);
    expect(await cache.getClip("d", 5)).toBe(undefined);
    expect(await cache.getClip("other", 4)).toBe(undefined);
  });

  it("a broken store never throws", async () => {
    const broken = {
      put: () => Promise.reject(new Error("QuotaExceededError")),
      get: () => Promise.reject(new Error("gone")),
      sentencesOf: () => Promise.reject(new Error("gone")),
    };
    const cache = new ClipCache(broken);
    await cache.putSentence("d", { id: 1 });
    await cache.putClip("d", 1, new ArrayBuffer(1));
    expect(await cache.getClip("d", 1)).toBe(undefined);
    expect(await cache.loadDay("d")).toEqual([]);
  });

  it("falls back to memory where IndexedDB is missing", async () => {
    const cache = await ClipCache.open(); // Node has no IndexedDB
    await cache.putSentence("d", { id: 1 });
    expect((await cache.loadDay("d")).length).toBe(1);
  });
});
