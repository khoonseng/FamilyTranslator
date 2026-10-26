<script setup>
// The hub page (`/`): PIN and token once, then the start tap, then the hub.
import { useHubStore } from "../stores/hub.js";
import CredentialsScreen from "./CredentialsScreen.vue";
import HubScreen from "./HubScreen.vue";
import StartScreen from "./StartScreen.vue";

const hub = useHubStore();
</script>

<template>
  <CredentialsScreen v-if="hub.screen === 'credentials'" />
  <StartScreen v-else-if="hub.screen === 'start'" />
  <HubScreen v-else />
</template>
