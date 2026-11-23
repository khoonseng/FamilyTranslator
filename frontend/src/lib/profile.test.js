import { describe, expect, it } from "vitest";
import { DEFAULT_PROFILE, PROFILES, profileName, text } from "./profile.js";

const page = (content) => ({
  querySelector: (sel) => (sel === 'meta[name="profile"]' && content !== null ? { content } : null),
});

describe("language profiles", () => {
  it("reads the profile the server named, or falls back to Chongqing", () => {
    expect(profileName(page("chongqing"))).toBe("chongqing");
    expect(profileName(page(null))).toBe(DEFAULT_PROFILE);
    expect(profileName(page("atlantis"))).toBe(DEFAULT_PROFILE);
    expect(profileName(undefined)).toBe(DEFAULT_PROFILE);
  });

  it("uses Chongqing without a page (tests)", () => {
    expect(text).toBe(PROFILES.chongqing);
  });

  it("gives every profile the same strings, so none shows as undefined", () => {
    const keys = Object.keys(PROFILES.chongqing).sort();
    for (const [name, table] of Object.entries(PROFILES)) {
      expect(Object.keys(table).sort(), name).toEqual(keys);
      for (const [key, value] of Object.entries(table)) {
        const shown = typeof value === "function" ? value(3) : value;
        expect(typeof shown, `${name}.${key}`).toBe("string");
        expect(shown.length, `${name}.${key}`).toBeGreaterThan(0);
      }
    }
  });

  it("keeps the Chongqing wording", () => {
    const t = PROFILES.chongqing;
    expect(t.hubRepliesWaiting(2)).toBe("2 个回覆等导游停一停 · 2 waiting for the guide to pause");
    expect(t.playNew(3)).toBe("播放 3 句新嘅 · Play 3 new");
    expect(t.talkRelease(12)).toBe("講完放手 · Release to send · 12s");
    expect(t.shareText).toBe("撳呢條連結，聽導遊講嘅廣東話：");
  });
});
