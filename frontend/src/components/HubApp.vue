<script setup>
// The hub page (`/`): PIN and token once, then Start, then the hub.
import { useHubStore } from "../stores/hub.js";
import CredentialsScreen from "./CredentialsScreen.vue";
import HubScreen from "./HubScreen.vue";
import ReplacedScreen from "./ReplacedScreen.vue";
import StartScreen from "./StartScreen.vue";

const hub = useHubStore();
</script>

<template>
  <CredentialsScreen v-if="hub.screen === 'credentials'" title="Hub" :pin="hub.pin" :token="hub.token"
    :refused="hub.refused" @save="hub.saveCredentials" />
  <StartScreen v-else-if="hub.screen === 'start'" />
  <ReplacedScreen v-else-if="hub.screen === 'replaced'" />
  <HubScreen v-else />
</template>
