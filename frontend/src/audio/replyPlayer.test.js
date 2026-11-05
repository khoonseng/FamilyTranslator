import { beforeEach, describe, expect, it } from "vitest";
import { ReplyPlayer } from "./replyPlayer.js";

let clock, log, player;

beforeEach(() => {
  clock = 100;
  log = [];
  player = new ReplyPlayer({
    output: { play: (id) => log.push(`play ${id}`), stop: () => log.push("stop") },
    releaseMic: async () => log.push("mic off"),
    reopenMic: async () => log.push("mic on"),
    now: () => clock,
  });
});

describe("ReplyPlayer", () => {
  it("with Guide off, a reply plays at once, with no mic to release", async () => {
    player.add(1, "mp3");
    await Promise.resolve();
    expect(log).toEqual(["play 1"]);
  });

  it("waits for 2 s of guide quiet, releases the mic, plays, then reopens the mic", async () => {
    player.setListening(true);
    player.speechStarted();
    player.add(1, "mp3");
    await player.tick();
    expect(log).toEqual([]); // the guide is talking
    player.speechEnded();
    clock += 1;
    await player.tick();
    expect(log).toEqual([]); // only 1 s of quiet
    clock += 1;
    await player.tick();
    expect(log).toEqual(["mic off", "play 1"]);
    await player.ended(1);
    expect(log).toEqual(["mic off", "play 1", "mic on"]);
  });

  it("replies play in order, each after a fresh 2 s of quiet", async () => {
    player.setListening(true);
    player.add(1, "a");
    player.add(2, "b");
    clock += 2;
    await player.tick();
    await player.ended(1);
    await player.tick();
    expect(log).toEqual(["mic off", "play 1", "mic on"]); // 2 waits: the guide may speak now
    clock += 2;
    await player.tick();
    expect(log.slice(-2)).toEqual(["mic off", "play 2"]);
  });

  it("a tap stops the reply and reopens the mic", async () => {
    player.setListening(true);
    player.add(1, "a");
    clock += 2;
    await player.tick();
    await player.stop();
    expect(log).toEqual(["mic off", "play 1", "stop", "mic on"]);
    expect(player.playing).toBe(null);
  });

  it("a late ended event from an older reply changes nothing", async () => {
    player.add(1, "a");
    await Promise.resolve();
    await player.ended(9);
    expect(player.playing.id).toBe(1);
  });
});
