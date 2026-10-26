<script setup>
// Pages by address: /join#<token> remembers the family's join link and moves to /listen (the
// token leaves the address bar); /listen is a listener phone; anything else is the hub.
// The token sits after the #, which the phone never sends anywhere: not to our server's
// request logs, nor to WhatsApp's link-preview fetcher (owner decision 2026-10-26).
import HubApp from "./components/HubApp.vue";
import ListenApp from "./components/ListenApp.vue";
import { rememberJoinToken } from "./stores/listen.js";

if (location.pathname === "/join") {
  const token = decodeURIComponent(location.hash.slice(1));
  if (token) rememberJoinToken(token);
  history.replaceState(null, "", "/listen");
}
const page = location.pathname === "/listen" ? "listen" : "hub";
</script>

<template>
  <ListenApp v-if="page === 'listen'" />
  <HubApp v-else />
</template>
