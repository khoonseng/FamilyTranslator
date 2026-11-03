// The hub must never go deaf without saying so (weeks 6–7 step 2). Pure decisions, no browser
// APIs, so Vitest can test them; the hub store does the watching and acting.
//
// - The chosen mic (the guide's Bluetooth clip-on) can disappear: out of range, or a flat
//   battery. iOS then silently falls back to the iPhone's own mic. The hub switches to the
//   phone's mic on purpose and says so ("Clip-on mic lost"), and switches back when the
//   clip-on reappears.
// - Back from another app, iOS may have suspended the audio engine or ended the microphone.
//   The hub tries to resume by itself; if that isn't enough, it asks for a tap.

// Which input to use: the chosen one if the phone lists it, else the phone's default.
export function micPlan(chosenId, availableIds) {
  if (!chosenId) return { use: "", lost: false };
  if (availableIds.includes(chosenId)) return { use: chosenId, lost: false };
  return { use: "", lost: true };
}

// After coming back to the page (or a track event): what the hub should do.
// engine: the AudioContext's state; track: { state: "live" | "ended", muted }.
export function healthPlan({ engine, track }) {
  if (!track || track.state === "ended") return "reopen"; // the mic was taken away
  if (engine !== "running") return "resume"; // suspended or interrupted by iOS
  if (track.muted) return "wait"; // another app has the mic for now (a call): it comes back
  return "ok";
}

// What host phones are told about the hub's mic.
export function micStatus({ activeId, lost, needTap }) {
  return { mic: activeId ? "external" : "phone", lost, interrupted: needTap };
}
