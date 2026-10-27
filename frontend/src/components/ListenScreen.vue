<script setup>
// The listener's voice-note thread (architecture doc, "Listener experience"): the Cantonese
// large, the guide's Mandarin small, English if switched on. ▶ replays a bubble; tapping a
// sentence replays just that sentence (hard rule 11). Unplayed sentences carry a blue marker.
// Host phones also see which speech-to-text and translator produced each sentence.
// Phones and tablets alike: one centred column, with larger text on an iPad.
import { nextTick, onMounted, watch } from "vue";
import { sourceLabel } from "../lib/sources.js";
import { useListenStore } from "../stores/listen.js";
import HostPanel from "./HostPanel.vue";

const listen = useListenStore();

const unplayed = (id) => {
  const s = listen.sentences[id];
  return listen.sound && !s.played && s.clip !== "none";
};

const atBottom = () => window.innerHeight + window.scrollY >= document.body.scrollHeight - 300;
const toBottom = (behavior) => window.scrollTo({ top: document.body.scrollHeight, behavior });

// Keep the newest bubble in view, unless the listener scrolled up to read.
watch(
  () => listen.lastId,
  async () => {
    const follow = atBottom(); // measured before the new bubble is drawn
    await nextTick();
    if (follow) toBottom("smooth");
  },
);
onMounted(() => toBottom("instant"));

const pill = (on) =>
  on ? "bg-blue-600 text-white border-blue-600" : "bg-white text-slate-700 border-slate-300";
</script>

<template>
  <main class="min-h-dvh bg-slate-100">
    <header class="sticky top-0 z-10 bg-slate-100/95 p-3 pt-[max(0.75rem,env(safe-area-inset-top))] backdrop-blur">
      <div class="mx-auto flex max-w-3xl flex-col gap-2">
        <p v-if="listen.connection !== 'connected'"
          class="rounded-lg bg-amber-200 px-3 py-2 text-xl text-amber-950 md:text-2xl">
          重新連線中… · Reconnecting…
        </p>
        <p v-else-if="!listen.hub.online"
          class="rounded-lg bg-slate-300 px-3 py-2 text-xl text-slate-900 md:text-2xl">
          導遊手機離線 · Hub offline
        </p>
        <p v-else-if="listen.hub.remotePaused"
          class="rounded-lg bg-slate-200 px-3 py-2 text-lg text-slate-800 md:text-xl">
          暫停收聽 · Guide listening paused
        </p>

        <HostPanel v-if="listen.host" />

        <div class="flex flex-wrap gap-2 text-base md:text-lg">
          <button class="rounded-full border px-4 py-2 disabled:opacity-40"
            :class="pill(listen.sound && listen.player.state === 'live')" :disabled="!listen.sound"
            @click="listen.setAutoPlay(listen.player.state !== 'live')">
            自動播放 Auto-play
          </button>
          <button class="rounded-full border px-4 py-2" :class="pill(listen.english)"
            @click="listen.setEnglish(!listen.english)">
            英文 English
          </button>
          <button class="rounded-full border px-4 py-2" :class="pill(!listen.sound)"
            @click="listen.setSound(!listen.sound)">
            靜音 Sound off
          </button>
        </div>
      </div>
    </header>

    <section class="mx-auto flex max-w-3xl flex-col gap-3 p-3 pb-36">
      <p v-if="!listen.bubbles.length" class="py-16 text-center text-2xl text-slate-500 md:text-3xl">
        等緊導遊講嘢… · Waiting for the guide…
      </p>

      <article v-for="bubble in listen.bubbles" :key="bubble.id"
        class="flex gap-3 rounded-2xl bg-white p-3 shadow-sm md:gap-4 md:p-5"
        :class="bubble.sentenceIds.some(unplayed) ? 'ring-2 ring-blue-500' : ''">
        <button class="h-14 w-14 shrink-0 rounded-full bg-blue-100 text-2xl text-blue-800 active:bg-blue-200 disabled:opacity-30 md:h-16 md:w-16"
          :disabled="!listen.sound" aria-label="播放 Play" @click="listen.replayBubble(bubble)">
          ▶
        </button>

        <div class="flex min-w-0 flex-1 flex-col gap-3">
          <div v-for="id in bubble.sentenceIds" :key="id" class="-m-1 rounded-lg p-1"
            :class="listen.player.playingId === id ? 'bg-amber-100' : ''" @click="listen.replaySentence(id)">
            <template v-if="listen.sentences[id].status === 'ok'">
              <p class="text-3xl leading-snug md:text-5xl md:leading-tight"
                :class="unplayed(id) ? 'text-blue-900' : 'text-slate-900'">
                <span v-if="unplayed(id)" class="mr-2 inline-block h-3 w-3 rounded-full bg-blue-500 align-middle md:h-4 md:w-4"></span>{{ listen.sentences[id].yue }}
              </p>
              <p v-if="listen.english && listen.sentences[id].en" class="mt-1 text-xl text-slate-700 md:text-2xl">
                {{ listen.sentences[id].en }}
              </p>
              <p class="mt-1 text-base text-slate-500 md:text-xl">
                {{ listen.sentences[id].zh }}
                <span v-if="listen.sound && listen.sentences[id].clip === 'pending'"> · 🔈…</span>
              </p>
            </template>
            <template v-else>
              <p class="text-xl text-amber-800 md:text-2xl">未能翻譯 · Not translated</p>
              <p class="text-2xl md:text-3xl">{{ listen.sentences[id].zh }}</p>
            </template>
            <p v-if="listen.host && sourceLabel(listen.sentences[id]).text" class="text-sm md:text-base"
              :class="sourceLabel(listen.sentences[id]).fallback ? 'text-amber-700' : 'text-slate-400'">
              {{ sourceLabel(listen.sentences[id]).text }}
            </p>
          </div>
        </div>
      </article>
    </section>

    <footer v-if="listen.player.showJump || (listen.player.state !== 'live' && listen.player.waiting)"
      class="fixed inset-x-0 bottom-0 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <div class="mx-auto max-w-3xl">
        <button v-if="listen.player.showJump"
          class="w-full rounded-2xl bg-amber-500 p-5 text-3xl font-bold text-white shadow-lg active:bg-amber-600"
          @click="listen.jumpToLatest()">
          跳到最新 · Jump to latest
        </button>
        <button v-else
          class="w-full rounded-2xl bg-blue-600 p-5 text-3xl font-bold text-white shadow-lg active:bg-blue-700"
          @click="listen.playNew()">
          播放 {{ listen.player.waiting }} 句新嘅 · Play {{ listen.player.waiting }} new
        </button>
      </div>
    </footer>

    <div v-if="listen.audioBlocked" class="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-6">
      <button class="w-full max-w-md rounded-2xl bg-emerald-600 p-8 text-3xl font-bold text-white shadow-xl"
        @click="listen.resumeAudio()">
        撳呢度繼續播放 · Tap to resume audio
      </button>
    </div>
  </main>
</template>
