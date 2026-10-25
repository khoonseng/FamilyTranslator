// Silero VAD hands over Float32 samples in [-1, 1]; the server wants 16-bit PCM (hard rule 9:
// raw 16 kHz PCM, no encoder).
export function floatTo16BitPcm(samples) {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}
