// Microphone capture with Silero VAD in the browser (hard rule 9): only speech is sent.
//
// - The default audio input via getUserMedia, echo cancellation on (hard rules 8 and 13).
// - The VAD's model and WASM are self-hosted under /vad/ (copied there by `npm run vad-assets`).
// - pause() / resume() are for half-duplex playback (hard rule 13). The microphone stream stays
//   open throughout: re-opening it can make iOS ask for permission again.

import { MicVAD } from "@ricky0123/vad-web";
import { Segmenter } from "./segmenter.js";

export const REDEMPTION_MS = 700; // the pause that ends a segment (about 0.6-0.8 s)

export async function createCapture({ send, sendAudio }) {
  const segmenter = new Segmenter({ send, sendAudio, redemptionMs: REDEMPTION_MS });
  const vad = await MicVAD.new({
    model: "v5",
    baseAssetPath: "/vad/",
    onnxWASMBasePath: "/vad/",
    startOnLoad: false,
    redemptionMs: REDEMPTION_MS,
    minSpeechMs: 250,
    preSpeechPadMs: 0, // the segmenter keeps its own pre-roll for streaming
    getStream: () =>
      navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, autoGainControl: true, noiseSuppression: true },
      }),
    pauseStream: async () => {}, // keep the microphone open
    resumeStream: async (stream) => stream,
    ortConfig: (ort) => {
      ort.env.logLevel = "error";
      ort.env.wasm.numThreads = 1; // no cross-origin isolation, so no threads
    },
    onFrameProcessed: (_probs, frame) => segmenter.onFrame(frame),
    onSpeechStart: () => segmenter.onSpeechStart(),
    onSpeechEnd: () => segmenter.onSpeechEnd(),
    onVADMisfire: () => segmenter.onSpeechEnd(),
  });

  let running = false;
  return {
    get running() {
      return running;
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
      await vad.pause();
    },
    async destroy() {
      running = false;
      segmenter.stop();
      await vad.destroy();
    },
  };
}
