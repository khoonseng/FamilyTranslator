<script setup>
// /mictest: which microphone does Safari really capture? (owner request 2026-11-03)
// iOS Safari can report an external mic's name while still capturing the built-in one (WebKit
// bugs 211192 and 282939). This page opens the mic with the hub's settings, optionally with a
// user-reported audio-session trick, shows live levels, and records 10 s to play back on the
// phone, so you can hear which mic was used. Nothing is sent anywhere: no server, no pipeline.
import { onBeforeUnmount, ref } from "vue";
import { levelOf, micConstraints, microphones } from "../audio/micSettings.js";

const TRICKS = {
  none: "None",
  workaround: "auto → open mic → play-and-record",
  reopen: "auto → open mic → play-and-record → open mic again",
  before: "play-and-record → open mic",
};

const mics = ref([]);
const micId = ref("");
const processing = ref(false);
const trick = ref("workaround");
const running = ref(false);
const levels = ref([0, 0]);
const label = ref("");
const settings = ref("");
const log = ref([]);
const recording = ref(false);
const recordingUrl = ref("");
const hasSession = typeof navigator !== "undefined" && "audioSession" in navigator;

let ctx = null;
let stream = null;
let frame = 0;

function note(text) {
  log.value.unshift(`${new Date().toLocaleTimeString()}  ${text}`);
}

function setSession(type) {
  if (!hasSession) return note("navigator.audioSession is not available");
  try {
    navigator.audioSession.type = type;
    note(`audioSession.type = ${type} (now: ${navigator.audioSession.type})`);
  } catch (error) {
    note(`audioSession.type = ${type} failed: ${error.name}`);
  }
}

async function openMic() {
  const s = await navigator.mediaDevices.getUserMedia(
    micConstraints({ deviceId: micId.value, processing: processing.value }),
  );
  note(`mic opened: ${s.getAudioTracks()[0]?.label || "(no name)"}`);
  return s;
}

function attachMeter() {
  const source = ctx.createMediaStreamSource(stream);
  const splitter = ctx.createChannelSplitter(2);
  const silent = ctx.createGain();
  silent.gain.value = 0; // Safari only runs nodes that lead to the output
  source.connect(splitter);
  const analysers = [0, 1].map((channel) => {
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    splitter.connect(analyser, channel);
    analyser.connect(silent);
    return analyser;
  });
  silent.connect(ctx.destination);
  const buffer = new Float32Array(2048);
  const tick = () => {
    levels.value = analysers.map((a) => {
      a.getFloatTimeDomainData(buffer);
      return levelOf(buffer);
    });
    frame = requestAnimationFrame(tick);
  };
  tick();
}

// Inside the Start tap: the AudioContext is made before anything is awaited (iOS).
async function start() {
  ctx = new AudioContext();
  ctx.resume();
  log.value = [];
  note(`Start: mic "${mics.value.find((m) => m.id === micId.value)?.label ?? "Phone default"}", ` +
    `voice processing ${processing.value ? "on" : "off"}, trick: ${TRICKS[trick.value]}`);
  try {
    if (trick.value === "before") setSession("play-and-record");
    if (trick.value === "workaround" || trick.value === "reopen") setSession("auto");
    stream = await openMic();
    if (trick.value === "workaround" || trick.value === "reopen") setSession("play-and-record");
    if (trick.value === "reopen") {
      stream.getTracks().forEach((t) => t.stop());
      stream = await openMic();
    }
    const track = stream.getAudioTracks()[0];
    label.value = track.label;
    settings.value = JSON.stringify(track.getSettings(), null, 1);
    attachMeter();
    running.value = true;
    mics.value = microphones(await navigator.mediaDevices.enumerateDevices());
  } catch (error) {
    note(`error: ${error.name} ${error.message}`);
    stop();
  }
}

function stop() {
  cancelAnimationFrame(frame);
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  ctx?.close();
  ctx = null;
  running.value = false;
  levels.value = [0, 0];
  if (hasSession && trick.value !== "none") {
    setSession("playback"); // the reporter's way back to normal output quality
    setSession("auto");
  }
}

function record() {
  if (!stream) return;
  const chunks = [];
  const recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = () => {
    if (recordingUrl.value) URL.revokeObjectURL(recordingUrl.value);
    recordingUrl.value = URL.createObjectURL(new Blob(chunks, { type: recorder.mimeType }));
    recording.value = false;
    note("recorded 10 s: play it back below");
  };
  recording.value = true;
  recorder.start();
  setTimeout(() => recorder.state !== "inactive" && recorder.stop(), 10_000);
}

async function listMics() {
  try {
    mics.value = microphones(await navigator.mediaDevices.enumerateDevices());
  } catch {
    mics.value = [];
  }
}

onBeforeUnmount(stop);
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-xl flex-col gap-4 bg-white p-4 text-base">
    <h1 class="text-2xl font-bold">Mic test</h1>
    <p class="text-slate-600">
      Which mic does Safari really capture? Start, then record 10 s while speaking from the next
      room with the clip-on on your collar, and play it back. Nothing is sent anywhere.
    </p>

    <label class="flex flex-col gap-1">
      Microphone
      <select v-model="micId" class="rounded border border-slate-300 p-2" :disabled="running"
        @focus="listMics">
        <option value="">Phone default</option>
        <option v-for="mic in mics" :key="mic.id" :value="mic.id">{{ mic.label }}</option>
      </select>
      <span class="text-sm text-slate-500">Names appear after the first Start.</span>
    </label>
    <label class="flex items-center gap-3">
      <input v-model="processing" type="checkbox" class="h-5 w-5" :disabled="running" />
      Phone voice processing
    </label>
    <label class="flex flex-col gap-1">
      Audio-session trick
      <select v-model="trick" class="rounded border border-slate-300 p-2" :disabled="running">
        <option v-for="(text, key) in TRICKS" :key="key" :value="key">{{ text }}</option>
      </select>
      <span class="text-sm text-slate-500">
        navigator.audioSession: {{ hasSession ? "available" : "not available on this browser" }}
      </span>
    </label>

    <div class="flex gap-2">
      <button v-if="!running" class="flex-1 rounded-xl bg-emerald-600 p-4 text-xl font-semibold text-white"
        @click="start">Start</button>
      <button v-else class="flex-1 rounded-xl bg-red-600 p-4 text-xl font-semibold text-white"
        @click="stop">Stop</button>
      <button class="flex-1 rounded-xl bg-blue-600 p-4 text-xl font-semibold text-white disabled:bg-slate-400"
        :disabled="!running || recording" @click="record">
        {{ recording ? "Recording…" : "Record 10 s" }}
      </button>
    </div>

    <div v-if="running" class="flex flex-col gap-2">
      <p>Capturing: <b>{{ label || "(no name)" }}</b></p>
      <div v-for="(level, channel) in levels" :key="channel" class="flex items-center gap-2">
        <span class="w-20 text-sm text-slate-500">Channel {{ channel + 1 }}</span>
        <span class="h-3 flex-1 overflow-hidden rounded-full bg-slate-200">
          <span class="block h-full rounded-full bg-emerald-600" :style="{ width: `${Math.round(level * 100)}%` }"></span>
        </span>
      </div>
    </div>

    <audio v-if="recordingUrl" :src="recordingUrl" controls class="w-full"></audio>

    <details v-if="settings">
      <summary class="cursor-pointer">Track settings</summary>
      <pre class="overflow-x-auto rounded bg-slate-100 p-2 text-xs">{{ settings }}</pre>
    </details>
    <ol class="flex flex-col gap-1 rounded bg-slate-100 p-2 font-mono text-xs">
      <li v-for="(line, i) in log" :key="i">{{ line }}</li>
    </ol>
  </main>
</template>
