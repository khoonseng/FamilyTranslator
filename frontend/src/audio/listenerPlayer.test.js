import { describe, expect, it } from "vitest";
import { ListenerPlayer } from "./listenerPlayer.js";

class FakeOutput {
  constructor() {
    this.played = [];
    this.stops = 0;
    this.now = null;
  }
  play(id) {
    this.played.push(id);
    this.now = id;
  }
  stop() {
    this.stops++;
    this.now = null;
  }
}

function setup(options = {}) {
  const output = new FakeOutput();
  const marked = [];
  const player = new ListenerPlayer({ output, onPlayed: (id) => marked.push(id), ...options });
  const finish = (ok = true) => player.ended(output.now, ok);
  return { output, marked, player, finish };
}

describe("ListenerPlayer: live", () => {
  it("plays new clips in order, one at a time, and marks them played", () => {
    const { output, marked, player, finish } = setup();
    player.arrive(1);
    player.arrive(2);
    expect(output.played).toEqual([1]);
    expect(player.waiting).toBe(1);
    finish();
    finish();
    expect(output.played).toEqual([1, 2]);
    expect(marked).toEqual([1, 2]);
    expect(player.playingId).toBe(null);
  });

  it("a clip that fails to play is not marked, and the next one plays", () => {
    const { output, marked, player, finish } = setup();
    player.arrive(1);
    player.arrive(2);
    finish(false);
    expect(output.played).toEqual([1, 2]);
    expect(marked).toEqual([]);
  });

  it("ignores a stopped clip's late ended event and duplicate arrivals", () => {
    const { output, player } = setup();
    player.arrive(1);
    player.arrive(1);
    player.arrive(2);
    player.ended(2);
    expect(output.played).toEqual([1]);
    expect(player.waiting).toBe(1);
  });
});

describe("ListenerPlayer: replaying and paused", () => {
  it("a replay plays only the tapped bubble, then stops in paused", () => {
    const { output, marked, player, finish } = setup();
    player.replay([4, 5]);
    expect(player.state).toBe("replaying");
    finish();
    finish();
    expect(output.played).toEqual([4, 5]);
    expect(player.state).toBe("paused");
    expect(marked).toEqual([]); // replays never change the played flag
  });

  it("new clips wait silently during a replay and while paused", () => {
    const { output, player, finish } = setup();
    player.replay([4]);
    player.arrive(9);
    finish();
    player.arrive(10);
    expect(output.played).toEqual([4]);
    expect(player.waiting).toBe(2);
  });

  it("Play N new goes back to live and plays the waiting clips in order", () => {
    const { output, marked, player, finish } = setup();
    player.pause();
    player.arrive(9);
    player.arrive(10);
    player.playNew();
    expect(player.state).toBe("live");
    finish();
    finish();
    expect(output.played).toEqual([9, 10]);
    expect(marked).toEqual([9, 10]);
  });

  it("tapping a bubble mid-live stops the clip, which waits to play again later", () => {
    const { output, marked, player, finish } = setup();
    player.arrive(1);
    player.replay([7]);
    expect(output.stops).toBe(1);
    expect(output.played).toEqual([1, 7]);
    finish();
    expect(player.state).toBe("paused");
    expect(player.waiting).toBe(1);
    player.playNew();
    finish();
    expect(output.played).toEqual([1, 7, 1]);
    expect(marked).toEqual([1]);
  });

  it("tapping another bubble mid-replay stops the current one: clips never overlap", () => {
    const { output, player } = setup();
    player.replay([4, 5]);
    player.replay([8]);
    expect(output.stops).toBe(1);
    expect(output.played).toEqual([4, 8]);
    player.ended(4); // the first replay's late event changes nothing
    expect(output.now).toBe(8);
  });

  it("auto-play off stops the clip and keeps it waiting", () => {
    const { output, player } = setup();
    player.arrive(1);
    player.pause();
    expect(player.state).toBe("paused");
    expect(output.now).toBe(null);
    expect(player.waiting).toBe(1);
  });
});

describe("ListenerPlayer: jump to latest", () => {
  it("shows at 3 waiting, plays the newest and leaves the skipped clips unplayed", () => {
    const { output, marked, player, finish } = setup();
    [1, 2, 3].forEach((id) => player.arrive(id));
    expect(player.showJump).toBe(false); // 1 playing, 2 waiting
    player.arrive(4);
    expect(player.showJump).toBe(true);
    player.jumpToLatest();
    expect(output.played).toEqual([1, 4]);
    expect(player.waiting).toBe(0);
    finish();
    expect(marked).toEqual([4]);
  });

  it("never shows while paused", () => {
    const { player } = setup();
    player.pause();
    [1, 2, 3, 4].forEach((id) => player.arrive(id));
    expect(player.showJump).toBe(false);
  });
});

describe("ListenerPlayer: sound off and new day", () => {
  it("with sound off nothing plays or waits; switching it on starts live and empty", () => {
    const { output, player } = setup();
    player.arrive(1);
    player.setSound(false);
    player.arrive(2);
    player.replay([1]);
    expect(output.played).toEqual([1]);
    expect(player.waiting).toBe(0);
    player.setSound(true);
    player.arrive(3);
    expect(output.played).toEqual([1, 3]);
  });

  it("reset clears everything and returns to live", () => {
    const { output, player } = setup();
    player.pause();
    player.arrive(1);
    player.reset();
    expect([player.state, player.waiting, output.now]).toEqual(["live", 0, null]);
  });
});
