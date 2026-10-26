// Plays one clip at a time on the listener's main audio element, for ListenerPlayer. `load(id)`
// returns the clip's MP3 bytes (memory or the phone's cache), or nothing if it is missing.
// - onEnded(id, ok): the clip finished, or could not play;
// - onInterrupted(id): iOS paused it (earphones taken out, a call): the page stops auto-play,
//   like any audio app, instead of waiting forever for an `ended` that never comes.

import { silenceUrl } from "./silence.js";

export class ClipOutput {
  constructor({ element, load, onEnded, onInterrupted }) {
    this.audio = element || new Audio();
    Object.assign(this, { load, onEnded, onInterrupted });
    this.current = null; // { id, turn }
    this.turn = 0;
    this.url = null;
    this.audio.addEventListener("ended", () => this.#finish(true));
    this.audio.addEventListener("error", () => this.#finish(false));
    this.audio.addEventListener("pause", () => {
      // Our own stop() clears `current` first; a natural end also fires `pause` (ended is
      // true); and a late `pause` from a stopped clip arrives after the next clip started.
      if (!this.current || this.audio.ended || !this.audio.paused) return;
      const { id } = this.current;
      this.current = null;
      this.onInterrupted(id);
    });
  }

  // Must run inside a tap: iOS only lets audio play after a user gesture.
  unlock() {
    this.audio.src = silenceUrl(0.1);
    return this.audio.play().catch(() => {});
  }

  async play(id) {
    const turn = ++this.turn;
    this.current = null;
    const data = await this.load(id);
    if (turn !== this.turn) return; // stopped while loading
    if (!data) {
      this.onEnded(id, false);
      return;
    }
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = URL.createObjectURL(new Blob([data], { type: "audio/mpeg" }));
    this.current = { id, turn };
    this.audio.src = this.url;
    this.audio.play().catch(() => this.#finish(false, turn));
  }

  stop() {
    this.turn++;
    this.current = null;
    this.audio.pause();
  }

  #finish(ok, turn = this.turn) {
    if (!this.current || this.current.turn !== turn) return;
    const { id } = this.current;
    this.current = null;
    this.onEnded(id, ok);
  }
}
