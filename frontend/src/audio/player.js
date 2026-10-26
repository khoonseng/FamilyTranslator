// Plays Cantonese clips in order on one audio element, unlocked by the start tap (hard rule 12).
// onPlaying(true/false) lets the hub pause capture while a clip plays (hard rule 13).

import { silenceUrl } from "./silence.js";

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
    this.audio.src = silenceUrl(0.1);
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
