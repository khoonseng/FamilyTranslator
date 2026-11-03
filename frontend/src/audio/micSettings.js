// The hub's microphone settings (owner decision 2026-11-03), kept free of browser APIs so Vitest
// can test them.
//
// - Which input: Safari didn't take audio from a DJI Mic Mini 2 receiver the way Voice Memos
//   did (nothing beyond about 1 m from the phone, with the transmitter on the speaker's
//   collar), so the hub can pick an input by its id.
// - "Phone voice processing": iOS's echo cancellation, noise suppression and automatic gain.
//   With them on, iOS uses its call-style voice processing, which may ignore a plug-in mic.
//   Off is allowed on the hub (hard rule 13 amended): in phase 1 the hub plays nothing, and in
//   phase 2 it stops listening while it plays, so nothing can loop.

export function micConstraints({ deviceId = "", processing = true } = {}) {
  return {
    audio: {
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      channelCount: 1,
      echoCancellation: processing,
      noiseSuppression: processing,
      autoGainControl: processing,
    },
  };
}

// 0..1 for a level bar: the frame's loudness on a 60 dB scale (-60 dBFS and below show empty).
export function levelOf(frame) {
  if (!frame?.length) return 0;
  let sum = 0;
  for (const sample of frame) sum += sample * sample;
  const rms = Math.sqrt(sum / frame.length);
  if (rms <= 0) return 0;
  return Math.min(1, Math.max(0, (20 * Math.log10(rms) + 60) / 60));
}

// The microphones Safari lists, by name. Names appear only once the mic has been allowed.
export function microphones(devices) {
  return devices
    .filter((d) => d.kind === "audioinput")
    .map((d, i) => ({ id: d.deviceId, label: d.label || `Microphone ${i + 1}` })); // numbered among inputs
}
