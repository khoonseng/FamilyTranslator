<script setup>
// The tap that unlocks audio on iOS (hard rule 12), or why this phone can't join.
import { text } from "../lib/profile.js";
import { useListenStore } from "../stores/listen.js";

const listen = useListenStore();
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 bg-white p-6 md:max-w-xl">
    <h1 class="text-4xl font-bold md:text-5xl">{{ text.appName }}<span v-if="listen.host"> · Host</span></h1>

    <template v-if="listen.refused && !listen.host">
      <p class="rounded-xl bg-amber-100 p-4 text-2xl leading-snug text-amber-900 md:text-3xl">
        {{ text.linkRevoked }}
      </p>
      <p class="text-lg text-slate-600">This link no longer works. Tap the new link in the family WhatsApp group.</p>
    </template>

    <template v-else-if="!listen.host && !listen.token">
      <p class="text-2xl leading-snug md:text-3xl">{{ text.openLink }}</p>
      <p class="text-lg text-slate-600">Open the link from the family WhatsApp group.</p>
    </template>

    <template v-else>
      <p class="text-2xl leading-snug md:text-3xl">{{ text.earphones }}</p>
      <p class="text-lg text-slate-600">Put your earphones in, then tap Start.</p>
      <button class="rounded-2xl bg-emerald-600 p-8 text-4xl font-bold text-white active:bg-emerald-700"
        @click="listen.start()">
        {{ text.start }}
      </button>
      <p v-if="!listen.sound" class="text-lg text-slate-500">{{ text.soundOffTextOnly }}</p>
      <button v-if="listen.host" class="text-lg text-slate-500 underline" @click="listen.screen = 'credentials'">
        Use a different PIN or token
      </button>
    </template>
  </main>
</template>
