<script setup>
// A listener phone: the family's page (`/listen`, through the join link) or a host phone
// (`/host`, signed in with the hub PIN and API token).
import { useListenStore } from "../stores/listen.js";
import CredentialsScreen from "./CredentialsScreen.vue";
import ListenScreen from "./ListenScreen.vue";
import ListenStartScreen from "./ListenStartScreen.vue";

const props = defineProps({ host: { type: Boolean, default: false } });
const listen = useListenStore();
listen.setHost(props.host);
</script>

<template>
  <CredentialsScreen v-if="listen.screen === 'credentials'" title="Host" :pin="listen.pin"
    :token="listen.apiToken" :refused="!!listen.refused" @save="listen.saveHostCredentials" />
  <ListenStartScreen v-else-if="listen.screen === 'start'" />
  <ListenScreen v-else />
</template>
