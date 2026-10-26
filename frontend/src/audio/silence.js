// Digital silence as a WAV made on the phone: every sample is zero, so there is nothing to hear
// and nothing to download. Used to unlock audio in the start tap, and by the keep-alive.

export function silenceWav(seconds) {
  const rate = 8000;
  const samples = Math.round(rate * seconds);
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const text = (offset, s) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples * 2, true);
  return buffer;
}

export function silenceUrl(seconds) {
  return URL.createObjectURL(new Blob([silenceWav(seconds)], { type: "audio/wav" }));
}
