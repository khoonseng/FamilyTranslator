<script setup>
import CredentialsScreen from "./components/CredentialsScreen.vue";
import HubScreen from "./components/HubScreen.vue";
import StartScreen from "./components/StartScreen.vue";
import { useHubStore } from "./stores/hub.js";

const hub = useHubStore();
</script>

<template>
  <CredentialsScreen v-if="hub.screen === 'credentials'" />
  <StartScreen v-else-if="hub.screen === 'start'" />
  <HubScreen v-else />
</template>
