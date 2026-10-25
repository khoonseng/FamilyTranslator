<script setup>
// The hub PIN and API token (hard rule 1), entered once per phone and remembered.
import { ref } from "vue";
import { useHubStore } from "../stores/hub.js";

const hub = useHubStore();
const pin = ref(hub.pin);
const token = ref(hub.token);

function save() {
  if (pin.value.trim() && token.value.trim()) hub.saveCredentials(pin.value, token.value);
}
</script>

<template>
  <main class="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-5 bg-white p-6">
    <h1 class="text-3xl font-bold">重慶翻譯 · Hub</h1>
    <p class="text-lg text-slate-600">Enter the hub PIN and the API token. This phone remembers them.</p>
    <p v-if="hub.refused" class="rounded-lg bg-red-100 p-3 text-lg text-red-800">
      The PIN or the token was not accepted.
    </p>
    <label class="flex flex-col gap-1 text-lg">
      Hub PIN
      <input v-model="pin" type="password" inputmode="numeric" autocomplete="off"
        class="rounded-lg border border-slate-300 p-3 text-2xl tracking-widest" />
    </label>
    <label class="flex flex-col gap-1 text-lg">
      API token
      <input v-model="token" type="password" inputmode="numeric" autocomplete="off"
        class="rounded-lg border border-slate-300 p-3 text-2xl tracking-widest" @keyup.enter="save" />
    </label>
    <button class="rounded-xl bg-blue-600 p-4 text-2xl font-semibold text-white disabled:bg-slate-400"
      :disabled="!pin.trim() || !token.trim()" @click="save">
      Save
    </button>
  </main>
</template>
