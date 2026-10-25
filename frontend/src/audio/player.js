// Plays Cantonese clips in order on one audio element, unlocked by the start tap (hard rule 12).
// onPlaying(true/false) lets the hub pause capture while a clip plays (hard rule 13).

const silenceUrl = (() => {
  // A tenth of a second of digital silence as a WAV, for the start tap's unlock.
  const rate = 8000;
  const samples = rate / 10;
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
  return () => URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
})();

export class ClipPlayer {
  constructor({ onPlaying = () => {}, onPlayed = () => {}, element } = {}) {
    this.audio = element || new Audio();
    this.queue = [];
    this.current = null;
    this.onPlaying = onPlaying;
    this.onPlayed = onPlayed;
    this.audio.addEventListener("ended", () => this.#finish());
    this.audio.addEventListener("error", () => this.#finish());
  }

  // Must run inside a tap: iOS only lets audio play after a user gesture.
  unlock() {
    this.audio.src = silenceUrl();
    return this.audio.play().catch(() => {});
  }

  enqueue(id, url) {
    this.queue.push({ id, url });
    if (!this.current) this.#next();
  }

  get waiting() {
    return this.queue.length;
  }

  #next() {
    const item = this.queue.shift();
    if (!item) {
      this.current = null;
      this.onPlaying(false);
      return;
    }
    this.current = item;
    this.onPlaying(true);
    this.audio.src = item.url;
    this.audio.play().catch(() => this.#finish());
  }

  #finish() {
    if (!this.current) return;
    this.onPlayed(this.current.id);
    this.current = null;
    this.#next();
  }
}
