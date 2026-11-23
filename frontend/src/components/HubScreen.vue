<script setup>
// The hub: the Guide latch tints the whole screen (hard rule 8); bubbles show the Cantonese
// large and the guide's Mandarin small, as text only (the listener phones play the audio).
import { nextTick, ref, watch } from "vue";
import { text } from "../lib/profile.js";
import { useHubStore } from "../stores/hub.js";

const hub = useHubStore();
const typed = ref("");
const list = ref(null);

function send() {
  if (hub.sendText(typed.value)) typed.value = "";
}

// Keep the newest bubble in view.
watch(
  () => Object.keys(hub.sentences).length,
  async () => {
    await nextTick();
    list.value?.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
  },
);

const connectionLabel = {
  connecting: "Connecting…",
  connected: "Connected",
  offline: "Offline: reconnecting…",
};
</script>

<template>
  <main
    class="flex min-h-dvh flex-col transition-colors"
    :class="hub.listening ? 'bg-emerald-100' : 'bg-slate-100'"
  >
    <header class="sticky top-0 z-10 flex flex-col gap-3 p-4 pb-2" :class="hub.listening ? 'bg-emerald-100' : 'bg-slate-100'">
      <div class="flex items-center justify-between text-base">
        <span class="flex items-center gap-2">
          <span class="inline-block h-3 w-3 rounded-full"
            :class="hub.connection === 'connected' ? 'bg-emerald-600' : 'bg-amber-500'"></span>
          {{ connectionLabel[hub.connection] }}
        </span>
      </div>
      <p v-if="hub.remotePaused && !hub.listening" class="rounded-lg bg-amber-100 p-3 text-lg text-amber-900">
        已由另一部手機暫停 · Paused from another phone
      </p>
      <!-- Family replies (phase 2): the Mandarin plays to the guide; a tap stops it. -->
      <button v-if="hub.replyPlaying !== null"
        class="rounded-2xl bg-sky-600 p-5 text-2xl font-bold text-white shadow" @click="hub.stopReply()">
        🔊 播放回覆中 · Playing a reply — tap to stop
      </button>
      <p v-else-if="hub.repliesWaiting" class="rounded-lg bg-sky-100 p-3 text-lg text-sky-900">
        {{ text.hubRepliesWaiting(hub.repliesWaiting) }}
      </p>
      <!-- Never deaf without saying so (weeks 6–7 step 2). -->
      <button v-if="hub.listening && hub.needTap"
        class="rounded-2xl bg-red-600 p-5 text-2xl font-bold text-white shadow" @click="hub.tapResume()">
        撳一下繼續收聽 · Tap to resume listening
      </button>
      <p v-else-if="hub.listening && hub.micLost" class="rounded-lg bg-red-600 p-3 text-lg font-semibold text-white">
        夾咪斷咗 · Clip-on mic lost: the phone's own mic is listening.
        Move closer to the guide; it switches back by itself.
      </p>

      <button
        class="rounded-2xl p-6 text-4xl font-bold text-white shadow"
        :class="hub.listening ? 'bg-red-600' : 'bg-emerald-600'"
        :disabled="hub.connection !== 'connected' && !hub.listening"
        @click="hub.toggleGuide()"
      >
        {{ hub.listening ? text.hubStop : text.hubGuide }}
      </button>
      <p v-if="hub.micError" class="rounded-lg bg-red-100 p-3 text-lg text-red-800">
        {{ hub.micError === "mic-denied"
          ? "Microphone access was refused. Allow it in Settings › Safari › Microphone."
          : "The microphone could not start." }}
      </p>

      <!-- Which mic the app hears, and how loud: a flat bar while the guide talks means the mic
           isn't reaching the app (owner decision 2026-11-03). -->
      <div v-if="hub.listening" class="flex items-center gap-3 text-sm text-slate-700">
        <span class="h-3 flex-1 overflow-hidden rounded-full bg-white">
          <span class="block h-full rounded-full bg-emerald-600 transition-[width] duration-100"
            :style="{ width: `${Math.round(hub.level * 100)}%` }"></span>
        </span>
        <span class="max-w-[55%] truncate">🎙 {{ hub.micLabel || "Microphone" }}</span>
      </div>
      <details class="text-base text-slate-700">
        <summary class="cursor-pointer select-none">Mic settings</summary>
        <div class="mt-2 flex flex-col gap-3 rounded-lg bg-white p-3">
          <label class="flex flex-col gap-1">
            Microphone
            <select class="rounded border border-slate-300 p-2" :value="hub.micId"
              @change="hub.setMic($event.target.value)" @focus="hub.listMics()">
              <option value="">Phone default</option>
              <option v-for="mic in hub.mics" :key="mic.id" :value="mic.id">{{ mic.label }}</option>
            </select>
            <span class="text-sm text-slate-500">Names appear after Guide has been on once.</span>
          </label>
          <label class="flex items-center gap-3">
            <input type="checkbox" class="h-5 w-5" :checked="hub.processing"
              @change="hub.setProcessing($event.target.checked)" />
            Phone voice processing (echo cancellation, noise suppression, auto gain)
          </label>
        </div>
      </details>

      <form class="flex gap-2" @submit.prevent="send">
        <input v-model="typed" type="text" :placeholder="text.hubTypePlaceholder"
          class="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white p-3 text-lg" />
        <button class="rounded-lg bg-blue-600 px-4 text-lg font-semibold text-white disabled:bg-slate-400"
          :disabled="!typed.trim() || hub.connection !== 'connected'">
          Send
        </button>
      </form>
    </header>

    <section ref="list" class="flex flex-col gap-3 p-4 pt-2">
      <p v-if="!hub.bubbles.length" class="py-10 text-center text-lg text-slate-500">
        {{ text.hubEmpty }}
      </p>
      <template v-for="bubble in hub.bubbles" :key="bubble.id">
      <!-- A family reply: on the right in green, the Mandarin (what the guide hears) large. -->
      <article v-if="hub.sentences[bubble.sentenceIds[0]]?.kind === 'reply'"
        class="ml-10 flex flex-col gap-1 self-end rounded-2xl bg-emerald-100 p-4 shadow-sm"
        :class="hub.replyPlaying === bubble.sentenceIds[0] ? 'ring-4 ring-sky-500' : ''">
        <div v-for="id in bubble.sentenceIds" :key="id" class="flex flex-col gap-1">
          <p class="text-right text-sm font-semibold text-emerald-800">{{ text.hubFamilyAsks }} 🙋</p>
          <p v-if="hub.sentences[id].status === 'ok'" class="text-3xl leading-snug text-slate-900">
            {{ hub.sentences[id].mandarin }}
          </p>
          <p v-else class="text-xl text-amber-800">{{ text.hubReplyNotTranslated }}</p>
          <p class="text-base text-slate-600">{{ hub.sentences[id].zh }}</p>
        </div>
      </article>
      <article v-else
        class="mr-6 flex flex-col gap-3 rounded-2xl bg-white p-4 shadow-sm">
        <div v-for="id in bubble.sentenceIds" :key="id" class="flex flex-col gap-1">
          <template v-if="hub.sentences[id].status === 'ok'">
            <p class="text-3xl leading-snug text-slate-900">{{ hub.sentences[id].yue }}</p>
            <p class="text-base text-slate-500">
              {{ hub.sentences[id].zh }}
              <span v-if="hub.sentences[id].clip === 'none'"> · no audio</span>
            </p>
          </template>
          <template v-else>
            <p class="text-xl text-amber-800">未能翻譯 · Not translated: please interpret</p>
            <p class="text-2xl">{{ hub.sentences[id].zh }}</p>
          </template>
        </div>
      </article>
      </template>
    </section>
  </main>
</template>
