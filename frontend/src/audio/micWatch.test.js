import { describe, expect, it } from "vitest";
import { healthPlan, micPlan, micStatus } from "./micWatch.js";

describe("micPlan", () => {
  it("no choice: the phone's default", () => {
    expect(micPlan("", ["iphone"])).toEqual({ use: "", lost: false });
  });

  it("the chosen clip-on while the phone lists it", () => {
    expect(micPlan("dji", ["iphone", "dji"])).toEqual({ use: "dji", lost: false });
  });

  it("the clip-on gone: the phone's mic, and say it's lost", () => {
    expect(micPlan("dji", ["iphone"])).toEqual({ use: "", lost: true });
  });
});

describe("healthPlan", () => {
  const live = { state: "live", muted: false };

  it("all well", () => {
    expect(healthPlan({ engine: "running", track: live })).toBe("ok");
  });

  it("iOS suspended or interrupted the audio engine: resume it", () => {
    expect(healthPlan({ engine: "suspended", track: live })).toBe("resume");
    expect(healthPlan({ engine: "interrupted", track: live })).toBe("resume");
  });

  it("the microphone was ended (another app took it): open it again", () => {
    expect(healthPlan({ engine: "running", track: { state: "ended", muted: false } })).toBe("reopen");
    expect(healthPlan({ engine: "running", track: null })).toBe("reopen");
  });

  it("muted for now (a call): wait for it to come back", () => {
    expect(healthPlan({ engine: "running", track: { state: "live", muted: true } })).toBe("wait");
  });
});

describe("micStatus", () => {
  it("tells host phones which mic and whether the hub needs a tap", () => {
    expect(micStatus({ activeId: "dji", lost: false, needTap: false })).toEqual({
      mic: "external", lost: false, interrupted: false,
    });
    expect(micStatus({ activeId: "", lost: true, needTap: true })).toEqual({
      mic: "phone", lost: true, interrupted: true,
    });
  });
});
