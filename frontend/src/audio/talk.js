// Hold to talk on a family phone (phase 2): the phone's own mic, recorded only while the button
// is held (never an open mic), sent to the server as 16 kHz 16-bit PCM like the hub's audio.
// On release the mic is fully stopped, so iOS puts the sound back to normal (5 Nov spike).

import { micConstraints } from "./micSettings.js";
import { floatTo16BitPcm } from "./pcm.js";

export const TALK_RATE = 16000;
export const MAX_TALK_S = 30;

// Why Talk can't start now, or "" if it can. The guide has priority (hard rule 8), and one
// family phone talks at a time (owner decision 2026-11-05). Typing is never blocked.
export function talkBlock({ canTalk, guideTalking, familyTalking, talking }) {
  if (!canTalk) return "locked";
  if (talking) return "";
  if (guideTalking) return "guide";
  if (familyTalking) return "someone";
  return "";
}

// Averages each run of input samples into one output sample (a simple low-pass as it goes).
export function downsample(samples, fromRate, toRate = TALK_RATE) {
  if (fromRate === toRate) return Float32Array.from(samples);
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

// Starts recording. Call the first part inside the press itself: iOS only lets an AudioContext
// run if it is created in a tap. onPcm(ArrayBuffer) receives about 4 chunks a second.
export async function startRecorder({ onPcm }) {
  const ctx = new AudioContext();
  ctx.resume().catch(() => {});
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(micConstraints({ processing: true }));
  } catch (error) {
    ctx.close();
    throw error;
  }
  const source = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  node.onaudioprocess = (e) => {
    const pcm = floatTo16BitPcm(downsample(e.inputBuffer.getChannelData(0), ctx.sampleRate));
    onPcm(pcm.buffer);
  };
  source.connect(node);
  node.connect(ctx.destination); // Safari only runs nodes that lead to the output (silent)
  return {
    stop() {
      node.onaudioprocess = null;
      source.disconnect();
      node.disconnect();
      stream.getTracks().forEach((t) => t.stop()); // release the mic: sound back to normal
      ctx.close();
    },
  };
}
