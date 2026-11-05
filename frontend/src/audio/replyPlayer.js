// The hub plays family replies to the guide in Mandarin (phase 2). No browser code here, so
// Vitest can test it; the hub store wires it to the microphone and an audio element.
//
// - Replies wait in order of arrival (hard rule 13).
// - One plays only when the guide has been quiet for `quietS` (2 s) by the hub's own VAD, or at
//   once if Guide listening is off. The guide always has priority.
// - To play, the hub fully stops its mic first, with Guide on or off (Guide off only pauses the
//   mic, which stays open): while the Bluetooth clip-on is open, iOS sends all sound to the
//   clip-on (5 Nov spike). Afterwards it reopens the mic if Guide is on, and the next reply
//   again waits for 2 s of quiet, since the guide may have started talking meanwhile.
// - A tap stops the reply at once and reopens the mic.

export class ReplyPlayer {
  constructor({ output, releaseMic, reopenMic, now = () => Date.now() / 1000, quietS = 2, onChange = () => {} }) {
    Object.assign(this, { output, releaseMic, reopenMic, now, quietS, onChange });
    this.queue = []; // [{ id, data }]
    this.playing = null; // the reply on the speaker, or being prepared
    this.listening = false; // Guide latched: the 2 s rule applies
    this.speaking = false; // the hub's VAD hears the guide now
    this.quietSince = -Infinity; // when the guide last stopped (or the mic reopened)
  }

  get waiting() {
    return this.queue.length;
  }

  add(id, data) {
    this.queue.push({ id, data });
    this.onChange();
    this.tick();
  }

  setListening(on) {
    this.listening = on;
    this.quietSince = this.now();
    this.tick();
  }

  speechStarted() {
    this.speaking = true;
  }

  speechEnded() {
    this.speaking = false;
    this.quietSince = this.now();
  }

  canPlay() {
    if (this.playing || !this.queue.length) return false;
    if (!this.listening) return true;
    return !this.speaking && this.now() - this.quietSince >= this.quietS;
  }

  // Called regularly by the hub (about 4 times a second while replies wait).
  async tick() {
    if (!this.canPlay()) return;
    const item = this.queue.shift();
    this.playing = item;
    this.onChange();
    // Always, even with Guide off: a paused mic is still open, and an open Bluetooth clip-on
    // takes the sound (6 Nov: replies were silent with Guide off).
    await this.releaseMic();
    if (this.playing !== item) return; // stopped while the mic was closing
    this.output.play(item.id, item.data);
  }

  // From the output: the reply finished, or could not play.
  async ended(id) {
    if (this.playing?.id !== id) return;
    await this.#finish();
  }

  // The tap on "Playing a reply": stop it now.
  async stop() {
    if (!this.playing) return;
    this.output.stop();
    await this.#finish();
  }

  async #finish() {
    this.playing = null;
    this.onChange();
    await this.reopenMic(); // the hub reopens it only if Guide is on
    if (this.listening) this.quietSince = this.now(); // a fresh 2 s of quiet before the next reply
  }
}
