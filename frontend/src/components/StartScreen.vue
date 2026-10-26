<script setup>
// Start makes this phone the hub: it takes over from any other hub.
import { useHubStore } from "../stores/hub.js";

const hub = useHubStore();
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 bg-white p-6">
    <h1 class="text-3xl font-bold">重慶翻譯 · Hub</h1>
    <p class="text-lg text-slate-600">
      Start makes this phone the hub. If another phone is the hub, it stops listening.
    </p>
    <button class="rounded-2xl bg-emerald-600 p-8 text-4xl font-bold text-white" @click="hub.start()">
      開始 Start
    </button>
    <button class="text-lg text-slate-500 underline" @click="hub.forgetCredentials()">
      Use a different PIN or token
    </button>
  </main>
</template>
