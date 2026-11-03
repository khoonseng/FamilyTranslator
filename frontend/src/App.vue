<script setup>
// One app, four pages by address (src/lib/page.js): the hub, a family listener, a host phone,
// and the mic test.
import HubApp from "./components/HubApp.vue";
import ListenApp from "./components/ListenApp.vue";
import MicTestScreen from "./components/MicTestScreen.vue";
import { page } from "./lib/page.js";
</script>

<template>
  <HubApp v-if="page === 'hub'" />
  <MicTestScreen v-else-if="page === 'mictest'" />
  <ListenApp v-else :key="page" :host="page === 'host'" />
</template>
