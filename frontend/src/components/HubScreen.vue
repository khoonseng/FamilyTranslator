<script setup>
// The hub: the Guide latch tints the whole screen (hard rule 8); bubbles show the Cantonese
// large and the guide's Mandarin small, as text only (the listener phones play the audio).
import { nextTick, ref, watch } from "vue";
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

      <button
        class="rounded-2xl p-6 text-4xl font-bold text-white shadow"
        :class="hub.listening ? 'bg-red-600' : 'bg-emerald-600'"
        :disabled="hub.connection !== 'connected' && !hub.listening"
        @click="hub.toggleGuide()"
      >
        {{ hub.listening ? "停止 Stop" : "导游 Guide" }}
      </button>
      <p v-if="hub.micError" class="rounded-lg bg-red-100 p-3 text-lg text-red-800">
        {{ hub.micError === "mic-denied"
          ? "Microphone access was refused. Allow it in Settings › Safari › Microphone."
          : "The microphone could not start." }}
      </p>

      <form class="flex gap-2" @submit.prevent="send">
        <input v-model="typed" type="text" placeholder="输入普通话 Type Mandarin"
          class="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white p-3 text-lg" />
        <button class="rounded-lg bg-blue-600 px-4 text-lg font-semibold text-white disabled:bg-slate-400"
          :disabled="!typed.trim() || hub.connection !== 'connected'">
          Send
        </button>
      </form>
    </header>

    <section ref="list" class="flex flex-col gap-3 p-4 pt-2">
      <p v-if="!hub.bubbles.length" class="py-10 text-center text-lg text-slate-500">
        Tap Guide and speak Mandarin, or type it above.
      </p>
      <article v-for="bubble in hub.bubbles" :key="bubble.id"
        class="flex flex-col gap-3 rounded-2xl bg-white p-4 shadow-sm">
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
    </section>
  </main>
</template>
