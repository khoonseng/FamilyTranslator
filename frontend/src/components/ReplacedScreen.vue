<script setup>
// Another phone took over as hub: this one has stopped listening and left the room.
import { goTo } from "../lib/page.js";
import { useHubStore } from "../stores/hub.js";

const hub = useHubStore();

function takeBack() {
  if (confirm("Make this phone the hub again? The other phone stops listening.")) hub.start();
}
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 bg-white p-6">
    <h1 class="text-3xl font-bold">另一部手機而家係 Hub</h1>
    <p class="text-xl text-slate-700">Another phone is now the hub. This phone has stopped listening.</p>
    <button class="rounded-2xl bg-blue-600 p-5 text-2xl font-semibold text-white" @click="goTo('host')">
      喺呢部手機收聽 · Listen on this phone
    </button>
    <button class="rounded-2xl border border-slate-300 p-5 text-2xl text-slate-700" @click="takeBack">
      再做 Hub · Make this phone the hub again
    </button>
  </main>
</template>
