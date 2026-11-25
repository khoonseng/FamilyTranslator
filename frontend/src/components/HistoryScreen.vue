<script setup>
import { computed, watch } from "vue";
import { profileName, text } from "../lib/profile.js";
import { useListenStore } from "../stores/listen.js";
import ConversationBubble from "./ConversationBubble.vue";

const listen = useListenStore();
const locale = profileName() === "cantonese-guide" ? "zh-CN" : "zh-HK";
const dateFormat = new Intl.DateTimeFormat(locale, {
  timeZone: "Asia/Shanghai", year: "numeric", month: "long", day: "numeric", weekday: "long",
});
const label = (day) => dateFormat.format(new Date(day));
const online = computed(() => listen.connection === "connected");
const playingId = computed(() => {
  const key = listen.player.playingId;
  return typeof key === "string" ? Number(key.split("/")[1]) : null;
});
const button = "rounded-xl border border-slate-300 bg-white px-4 py-3 text-lg text-slate-800";
watch(() => listen.historyDate, () => window.scrollTo({ top: 0, behavior: "instant" }), {
  immediate: true, flush: "post",
});
</script>

<template>
  <main class="min-h-dvh bg-slate-100">
    <header class="sticky top-0 z-10 bg-slate-100/95 p-3 pt-[max(0.75rem,env(safe-area-inset-top))] backdrop-blur">
      <div class="mx-auto flex max-w-3xl flex-wrap items-center gap-2">
        <button :class="button" @click="listen.closeHistory()">← {{ text.historyLive }}</button>
        <button v-if="listen.historyDate" :class="button" @click="listen.backToHistoryDates()">
          {{ text.historyDates }}
        </button>
        <button v-if="playingId !== null" :class="button" @click="listen.stopHistoryReplay()">
          {{ text.historyStop }}
        </button>
        <p v-if="listen.historyAudioMissing" role="status" class="w-full text-lg text-amber-800">
          {{ text.historyAudioMissing }}
        </p>
      </div>
    </header>

    <section class="mx-auto flex max-w-3xl flex-col gap-3 px-3 pb-12 pt-3">
      <h1 class="text-3xl font-semibold text-slate-900 md:text-4xl">
        {{ listen.historyDate ? label(listen.historyDate) : text.history }}
      </h1>
      <p v-if="!online" role="status" class="text-lg text-amber-800">{{ text.historyOffline }}</p>
      <p v-if="!listen.historyDate && listen.historyDatesLoading" role="status" class="text-lg text-slate-600">
        {{ text.historyLoading }}
      </p>

      <template v-if="!listen.historyDate">
        <button v-for="day in listen.historyDates" :key="day" :class="button"
          class="flex items-center justify-between text-start" @click="listen.openHistoryDay(day)">
          <time :datetime="day" class="text-2xl md:text-3xl">{{ label(day) }}</time>
          <span aria-hidden="true" class="ms-3 text-slate-500">›</span>
        </button>
        <p v-if="online && !listen.historyDates.length && !listen.historyDatesLoading && !listen.historyDatesError"
          class="py-10 text-center text-xl text-slate-600">
          {{ text.historyEmpty }}
        </p>
        <button v-if="online && listen.historyDatesError" :class="button" @click="listen.refreshHistoryDates()">
          {{ text.historyRetry }}
        </button>
      </template>

      <template v-else>
        <ConversationBubble v-for="bubble in listen.historyBubbles" :key="bubble.id" history
          :bubble="bubble" :sentences="listen.historySentences" :playing-id="playingId"
          :device="listen.device" :sound="listen.sound" :english="listen.english" :host="listen.host"
          @play-bubble="listen.replayHistory($event.sentenceIds)" @play-sentence="listen.replayHistory([$event])" />
        <p v-if="listen.historyLoading" role="status" class="text-center text-lg text-slate-600">
          {{ text.historyLoading }}
        </p>
        <p v-if="online && !listen.historyBubbles.length && listen.historyAfter === null"
          class="py-10 text-center text-xl text-slate-600">
          {{ text.historyEmptyDay }}
        </p>
        <button v-if="online && !listen.historyLoading && listen.historyAfter !== null" :class="button"
          @click="listen.loadHistoryPage()">
          {{ listen.historyError ? text.historyRetry : text.historyMore }}
        </button>
      </template>
    </section>
    <div v-if="listen.audioBlocked" class="fixed inset-0 z-20 flex items-center justify-center bg-black/60 p-6">
      <button class="w-full max-w-md rounded-2xl bg-emerald-600 p-8 text-3xl font-bold text-white shadow-xl"
        @click="listen.resumeAudio()">
        {{ text.tapToResume }}
      </button>
    </div>
  </main>
</template>
