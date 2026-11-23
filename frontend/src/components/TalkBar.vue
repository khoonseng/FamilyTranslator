<script setup>
// Replies to the guide (phase 2), at the bottom of the family and host pages: "Ask the guide"
// asks for the hub PIN once; then a text box (any time) and a large hold-to-talk button, which
// waits while the guide speaks or another phone talks, and stops itself after 30 s.
import { computed, ref } from "vue";
import { MAX_TALK_S, talkBlock } from "../audio/talk.js";
import { text } from "../lib/profile.js";
import { useListenStore } from "../stores/listen.js";

const listen = useListenStore();
const typed = ref("");
const unlocking = ref(false);
const pin = ref("");

const block = computed(() =>
  talkBlock({ ...listen.hub, canTalk: listen.canTalk, talking: listen.talking }),
);

const holdLabel = computed(() => {
  if (block.value === "guide") return text.talkGuideSpeaking;
  if (block.value === "someone") return text.talkSomeoneAsking;
  if (listen.talking && !listen.talkLive) return text.talkOpeningMic;
  if (listen.talking) return text.talkRelease(MAX_TALK_S - listen.talkSeconds);
  return text.talkHold;
});

const errorText = {
  "mic-denied": "Microphone refused: allow it in Settings › Safari › Microphone.",
  "mic-failed": "The microphone could not start.",
  guide_talking: text.talkGuideStarted,
  someone_talking: text.talkSomeoneElse,
};

function send() {
  if (listen.sendReply(typed.value)) typed.value = "";
}

function unlock() {
  if (!pin.value.trim()) return;
  listen.unlockTalk(pin.value);
  pin.value = "";
  unlocking.value = false;
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <template v-if="listen.canTalk">
      <p v-if="listen.talkError" class="rounded-lg bg-amber-100 p-2 text-base text-amber-900">
        {{ errorText[listen.talkError] }}
      </p>
      <form class="flex gap-2" @submit.prevent="send">
        <input v-model="typed" type="text" :placeholder="text.talkTypePlaceholder"
          class="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white p-3 text-lg md:text-xl" />
        <button class="rounded-xl bg-emerald-600 px-4 text-lg font-semibold text-white disabled:bg-slate-400"
          :disabled="!typed.trim() || listen.connection !== 'connected'">
          {{ text.talkSend }}
        </button>
      </form>
      <button
        class="w-full touch-none select-none rounded-2xl p-5 text-2xl font-bold shadow-lg [-webkit-touch-callout:none] md:text-3xl"
        :class="listen.talking ? 'bg-red-600 text-white'
          : block ? 'bg-slate-300 text-slate-600' : 'bg-emerald-600 text-white active:bg-emerald-700'"
        :disabled="!!block || listen.connection !== 'connected'"
        @pointerdown.prevent="listen.startTalk()"
        @pointerup="listen.stopTalk()"
        @pointerleave="listen.stopTalk()"
        @pointercancel="listen.stopTalk()"
        @contextmenu.prevent>
        {{ holdLabel }}
      </button>
    </template>

    <template v-else-if="!listen.host">
      <p v-if="listen.pinWrong" class="rounded-lg bg-amber-100 p-2 text-base text-amber-900">
        {{ text.talkPinWrong }}
      </p>
      <form v-if="unlocking" class="flex gap-2" @submit.prevent="unlock">
        <input v-model="pin" type="password" inputmode="numeric" autocomplete="off"
          placeholder="Hub PIN" class="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white p-3 text-xl tracking-widest" />
        <button class="rounded-xl bg-emerald-600 px-4 text-lg font-semibold text-white">OK</button>
      </form>
      <button v-else class="self-center rounded-full border border-slate-300 bg-white px-4 py-2 text-base text-slate-700"
        @click="unlocking = true">
        {{ text.talkAsk }}
      </button>
    </template>
  </div>
</template>
