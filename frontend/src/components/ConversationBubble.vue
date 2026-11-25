<script setup>
import { computed } from "vue";
import { text } from "../lib/profile.js";
import { sourceLabel } from "../lib/sources.js";

const props = defineProps({
  bubble: { type: Object, required: true },
  sentences: { type: Object, required: true },
  playingId: { type: Number, default: null },
  device: { type: String, required: true },
  sound: Boolean,
  english: Boolean,
  host: Boolean,
  history: Boolean,
});
const emit = defineEmits(["play-bubble", "play-sentence"]);

const hasAudio = computed(() => props.bubble.sentenceIds.some((id) => props.sentences[id].clip === "ready"));
const unplayed = (id) => {
  const sentence = props.sentences[id];
  return !props.history && props.sound && !sentence.played && sentence.clip !== "none";
};
</script>

<template>
  <!-- A family reply to the guide: on the right, in green; text only (its Mandarin is for
       the guide, played by the hub). -->
  <article v-if="sentences[bubble.sentenceIds[0]]?.kind === 'reply'"
    class="ml-10 flex flex-col gap-1 self-end rounded-2xl bg-emerald-100 p-3 shadow-sm md:ml-24 md:p-5">
    <div v-for="id in bubble.sentenceIds" :key="id" class="flex flex-col gap-1">
      <p class="text-right text-sm font-semibold text-emerald-800 md:text-base">
        {{ sentences[id].asker === device ? text.you : text.family }} 🙋
      </p>
      <p class="text-2xl leading-snug text-slate-900 md:text-4xl">{{ sentences[id].zh }}</p>
      <p v-if="sentences[id].status !== 'ok'" class="text-base text-amber-800 md:text-xl">
        {{ text.notTranslated }}
      </p>
      <p v-else-if="sentences[id].en" class="text-lg text-slate-700 md:text-2xl">
        {{ sentences[id].en }}
      </p>
      <p v-if="host && sourceLabel(sentences[id]).text" class="text-sm md:text-base"
        :class="sourceLabel(sentences[id]).fallback ? 'text-amber-700' : 'text-slate-400'">
        {{ sentences[id].mandarin }} · {{ sourceLabel(sentences[id]).text }}
      </p>
    </div>
  </article>

  <article v-else
    class="mr-6 flex gap-3 rounded-2xl bg-white p-3 shadow-sm md:mr-16 md:gap-4 md:p-5"
    :class="bubble.sentenceIds.some(unplayed) ? 'ring-2 ring-blue-500' : ''">
    <button class="h-14 w-14 shrink-0 rounded-full bg-blue-100 text-2xl text-blue-800 active:bg-blue-200 disabled:opacity-30 md:h-16 md:w-16"
      :disabled="!sound || (history && !hasAudio)" :aria-label="text.play" @click="emit('play-bubble', bubble)">
      ▶
    </button>

    <div class="flex min-w-0 flex-1 flex-col gap-3">
      <div v-for="id in bubble.sentenceIds" :key="id" class="-m-1 rounded-lg p-1"
        :class="playingId === id ? 'bg-amber-100' : ''" @click="emit('play-sentence', id)">
        <template v-if="sentences[id].status === 'ok'">
          <p class="text-3xl leading-snug md:text-5xl md:leading-tight"
            :class="unplayed(id) ? 'text-blue-900' : 'text-slate-900'">
            <span v-if="unplayed(id)" class="mr-2 inline-block h-3 w-3 rounded-full bg-blue-500 align-middle md:h-4 md:w-4"></span>{{ sentences[id].yue }}
          </p>
          <p v-if="english && sentences[id].en" class="mt-1 text-xl text-slate-700 md:text-2xl">
            {{ sentences[id].en }}
          </p>
          <p class="mt-1 text-base text-slate-500 md:text-xl">
            {{ sentences[id].zh }}
            <span v-if="!history && sound && sentences[id].clip === 'pending'"> · 🔈…</span>
          </p>
        </template>
        <template v-else>
          <p class="text-xl text-amber-800 md:text-2xl">{{ text.notTranslated }}</p>
          <p class="text-2xl md:text-3xl">{{ sentences[id].zh }}</p>
        </template>
        <p v-if="host && sourceLabel(sentences[id]).text" class="text-sm md:text-base"
          :class="sourceLabel(sentences[id]).fallback ? 'text-amber-700' : 'text-slate-400'">
          {{ sourceLabel(sentences[id]).text }}
        </p>
      </div>
    </div>
  </article>
</template>
