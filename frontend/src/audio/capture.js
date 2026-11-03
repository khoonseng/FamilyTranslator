// Microphone capture with Silero VAD in the browser (hard rule 9): only speech is sent.
//
// - The chosen audio input, or the phone's default (hard rule 8), with or without the phone's
//   voice processing (see micSettings.js).
// - The VAD's model and WASM are self-hosted under /vad/ (copied there by `npm run vad-assets`).
// - pause() / start() keep the microphone stream open: re-opening it can make iOS ask for
//   permission again. destroy() releases it, to switch inputs or settings.

import { MicVAD } from "@ricky0123/vad-web";
import { levelOf, micConstraints } from "./micSettings.js";
import { Segmenter } from "./segmenter.js";

export const REDEMPTION_MS = 700; // the pause that ends a segment (about 0.6-0.8 s)
const LEVEL_EVERY_MS = 100;

// `audioContext` must have been created or resumed inside a tap (see the hub store): iOS keeps an
// AudioContext made later, as the VAD's own would be, suspended, and the VAD hears nothing.
// onLevel(0..1) feeds the hub's level bar, about ten times a second.
export async function createCapture({
  send,
  sendAudio,
  audioContext,
  deviceId = "",
  processing = true,
  onLevel = () => {},
}) {
  const segmenter = new Segmenter({ send, sendAudio, redemptionMs: REDEMPTION_MS });
  let stream = null;
  let lastLevel = 0;
  const vad = await MicVAD.new({
    model: "v5",
    audioContext,
    baseAssetPath: "/vad/",
    onnxWASMBasePath: "/vad/",
    startOnLoad: false,
    redemptionMs: REDEMPTION_MS,
    minSpeechMs: 250,
    preSpeechPadMs: 0, // the segmenter keeps its own pre-roll for streaming
    getStream: async () => {
      stream = await navigator.mediaDevices.getUserMedia(micConstraints({ deviceId, processing }));
      return stream;
    },
    pauseStream: async () => {}, // keep the microphone open
    resumeStream: async (s) => s,
    ortConfig: (ort) => {
      ort.env.logLevel = "error";
      ort.env.wasm.numThreads = 1; // no cross-origin isolation, so no threads
    },
    onFrameProcessed: (_probs, frame) => {
      segmenter.onFrame(frame);
      const now = performance.now();
      if (now - lastLevel >= LEVEL_EVERY_MS) {
        lastLevel = now;
        onLevel(levelOf(frame));
      }
    },
    onSpeechStart: () => segmenter.onSpeechStart(),
    onSpeechEnd: () => segmenter.onSpeechEnd(),
    onVADMisfire: () => segmenter.onSpeechEnd(),
  });

  let running = false;
  return {
    get running() {
      return running;
    },
    // The input actually in use, as the phone names it (e.g. "iPhone Microphone"), and whether
    // the phone applied its voice processing. Known once started.
    get input() {
      const track = stream?.getAudioTracks()[0];
      const settings = track?.getSettings?.() ?? {};
      return { label: track?.label ?? "", echoCancellation: settings.echoCancellation };
    },
    async start() {
      if (running) return;
      running = true;
      await vad.start();
    },
    async pause() {
      if (!running) return;
      running = false;
      segmenter.stop(); // ends an open segment
      onLevel(0);
      await vad.pause();
    },
    async destroy() {
      running = false;
      segmenter.stop();
      onLevel(0);
      await vad.destroy();
      vad._vadNode?.disconnect?.(); // the shared AudioContext outlives this capture
      stream?.getTracks().forEach((t) => t.stop());
    },
  };
}
