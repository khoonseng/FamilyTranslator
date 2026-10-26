// The listener's player states (hard rule 11; architecture doc, "Player states"). No browser
// code here, so Vitest can test it: an `output` plays one clip at a time and calls ended(id)
// when the clip finishes or fails.
//
// - live (default): new clips play in order as they arrive, each marked played (onPlayed).
// - replaying: a tapped bubble (or sentence) plays, then the player stops in paused. It never
//   runs on into later bubbles, and replays never change the played flag. New clips wait.
// - paused: new clips wait silently, unplayed, until "Play N new" or auto-play back on.
// Jump to latest: in live, with `jumpAt` or more clips waiting, stop the current clip and play
// the newest; the skipped clips stay unplayed and are no longer waiting.
// Sound off (text only): nothing plays and nothing waits.

export class ListenerPlayer {
  constructor({ output, onChange = () => {}, onPlayed = () => {}, jumpAt = 3 }) {
    this.output = output; // { play(id), stop() }
    this.onChange = onChange;
    this.onPlayed = onPlayed;
    this.jumpAt = jumpAt;
    this.state = "live";
    this.sound = true;
    this.queue = []; // clips waiting for live, oldest first
    this.replayRest = []; // the rest of the bubble being replayed
    this.current = null; // { id, live }: live clips get marked played when they finish
  }

  get waiting() {
    return this.queue.length;
  }

  get showJump() {
    return this.state === "live" && this.queue.length >= this.jumpAt;
  }

  get playingId() {
    return this.current?.id ?? null;
  }

  // A new clip is ready (live, or caught up after a reconnect).
  arrive(id) {
    if (!this.sound || this.queue.includes(id) || this.current?.id === id) return;
    this.queue.push(id);
    if (this.state === "live" && !this.current) this.#next();
    this.onChange();
  }

  // Tap on a bubble (its sentences with clips, in order) or on one sentence.
  replay(ids) {
    if (!this.sound || !ids.length) return;
    this.#stop({ requeue: true });
    this.state = "replaying";
    this.replayRest = [...ids];
    this.#next();
    this.onChange();
  }

  // "Play N new", or auto-play switched back on.
  playNew() {
    if (!this.sound || this.state === "live") return;
    this.#stop({ requeue: false });
    this.state = "live";
    this.replayRest = [];
    this.#next();
    this.onChange();
  }

  // Auto-play switched off: the clip playing now stops and waits with the others.
  pause() {
    if (this.state === "paused") return;
    this.#stop({ requeue: true });
    this.state = "paused";
    this.replayRest = [];
    this.onChange();
  }

  jumpToLatest() {
    if (this.state !== "live" || !this.queue.length) return;
    this.#stop({ requeue: false }); // the interrupted clip stays unplayed
    this.queue = this.queue.slice(-1);
    this.#next();
    this.onChange();
  }

  setSound(on) {
    this.#stop({ requeue: false });
    this.sound = on;
    this.state = "live";
    this.queue = [];
    this.replayRest = [];
    this.onChange();
  }

  // A new day: the bubbles are gone, so nothing can wait or replay.
  reset() {
    this.#stop({ requeue: false });
    this.state = "live";
    this.queue = [];
    this.replayRest = [];
    this.onChange();
  }

  // From the output: the clip finished (ok) or could not play.
  ended(id, ok = true) {
    if (this.current?.id !== id) return; // a stopped clip's late event
    const { live } = this.current;
    this.current = null;
    if (live && ok) this.onPlayed(id);
    this.#next();
    this.onChange();
  }

  #next() {
    if (this.state === "replaying") {
      const id = this.replayRest.shift();
      if (id === undefined) {
        this.state = "paused";
        return;
      }
      this.#play(id, false);
    } else if (this.state === "live" && this.queue.length) {
      this.#play(this.queue.shift(), true);
    }
  }

  #play(id, live) {
    this.current = { id, live };
    this.output.play(id);
  }

  // A live clip interrupted by a replay or a pause goes back to the front of the queue.
  #stop({ requeue }) {
    if (!this.current) return;
    if (requeue && this.current.live) this.queue.unshift(this.current.id);
    this.current = null;
    this.output.stop();
  }
}
