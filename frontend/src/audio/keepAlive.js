// The silent keep-alive on listener phones (hard rule 12). A second audio element loops a second
// of digital silence while the phone is in the room, because iOS freezes a locked page (and its
// WebSocket) about 10 s after its audio stops. Clips play on the main player, unchanged.
// If iOS pauses the loop, it is restarted; if that is refused, onBlocked(true) asks the page to
// show "Tap to resume audio", whose tap calls resume(). Never used on the hub (hard rule 13).

import { silenceUrl } from "./silence.js";

export class KeepAlive {
  constructor({ element, url = () => silenceUrl(1), onBlocked = () => {} } = {}) {
    this.audio = element || new Audio();
    this.url = url;
    this.onBlocked = onBlocked;
    this.running = false;
    this.blocked = false;
    this.audio.addEventListener("pause", () => {
      if (this.running) this.#play(); // paused by iOS (lock-screen controls, waking up)
    });
  }

  // The first call must run inside a tap.
  start() {
    this.running = true;
    this.audio.loop = true;
    this.audio.src = this.url();
    return this.#play();
  }

  // Inside the "Tap to resume audio" tap.
  resume() {
    return this.running ? this.#play() : Promise.resolve();
  }

  // When the page becomes visible again: restart it if it stopped while hidden.
  check() {
    return this.running && this.audio.paused ? this.#play() : Promise.resolve();
  }

  stop() {
    this.running = false;
    this.audio.pause();
  }

  #play() {
    return this.audio.play().then(
      () => this.#setBlocked(false),
      () => this.#setBlocked(true),
    );
  }

  #setBlocked(blocked) {
    if (blocked === this.blocked) return;
    this.blocked = blocked;
    this.onBlocked(blocked);
  }
}
