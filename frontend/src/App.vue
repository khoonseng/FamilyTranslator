<script setup>
// One app, three pages by address (src/lib/page.js): the hub, a family listener, a host phone.
import HubApp from "./components/HubApp.vue";
import ListenApp from "./components/ListenApp.vue";
import { page } from "./lib/page.js";
</script>

<template>
  <HubApp v-if="page === 'hub'" />
  <ListenApp v-else :key="page" :host="page === 'host'" />
</template>
