<script setup>
// A listener phone (`/listen`, reached through the family's join link).
import { useListenStore } from "../stores/listen.js";
import ListenScreen from "./ListenScreen.vue";
import ListenStartScreen from "./ListenStartScreen.vue";

const listen = useListenStore();
</script>

<template>
  <ListenStartScreen v-if="listen.screen === 'start'" />
  <ListenScreen v-else />
</template>
