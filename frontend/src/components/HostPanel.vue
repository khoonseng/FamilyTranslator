<script setup>
// Host phones only (the owner's and wife's, page /host): today's spend, remote pause, Become hub
// and the family's join link. Pause, Become hub and Make a new link ask first. Never on the
// family's page, and the server refuses these from any phone that didn't sign in as host
// (hard rule 1). The spend is a warning only: translation never stops.
import { computed, ref } from "vue";
import { goTo } from "../lib/page.js";
import { useHubStore } from "../stores/hub.js";
import { useListenStore } from "../stores/listen.js";

const listen = useListenStore();
const open = ref(false);
const note = ref("");

const hubLabel = computed(() => {
  if (!listen.hub.online) return "Hub offline";
  if (listen.hub.listening) return "Guide listening";
  return listen.hub.remotePaused ? "Guide paused" : "Guide not listening";
});
const usd = (value) => `US$${value.toFixed(2)}`;

function pauseGuide() {
  if (confirm("Pause the guide's listening? Nothing is translated until you resume.")) {
    listen.setGuidePaused(true);
  }
}

function becomeHub() {
  if (!confirm("Make this phone the hub? The current hub stops listening.")) return;
  listen.leave();
  const hub = useHubStore();
  hub.saveCredentials(listen.pin, listen.apiToken);
  goTo("hub");
  hub.start();
}

async function shareLink() {
  note.value = "";
  const url = listen.joinUrl;
  if (navigator.share) {
    try {
      await navigator.share({ title: "重慶翻譯", text: "撳呢條連結，聽導遊講嘅廣東話：", url });
      return;
    } catch (error) {
      if (error?.name === "AbortError") return; // the share sheet was closed
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    note.value = "Link copied.";
  } catch {
    note.value = url; // shown, to copy by hand
  }
}

function newLink() {
  const sure = confirm(
    "Make a new link? The old link stops working at once, and phones on it are disconnected " +
      "until they open the new one.",
  );
  if (!sure) return;
  listen.newJoinLink();
  note.value = "New link made: share it in the family WhatsApp group.";
}
</script>

<template>
  <section class="flex flex-col gap-2">
    <p v-if="listen.spend?.warn" class="rounded-lg bg-red-600 px-3 py-2 text-lg font-semibold text-white">
      Today's spend {{ usd(listen.spend.usd) }} is over {{ usd(listen.spend.warnUsd) }}.
      Translation carries on.
    </p>

    <button class="flex items-center justify-between rounded-lg bg-white px-3 py-2 text-left text-base shadow-sm md:text-lg"
      @click="open = !open">
      <span>
        <b>Host</b>
        · Today {{ listen.spend ? usd(listen.spend.usd) : "…" }}
        · {{ hubLabel }}
      </span>
      <span class="text-slate-500">{{ open ? "▲" : "▼" }}</span>
    </button>

    <div v-if="open" class="grid grid-cols-2 gap-2 text-base md:text-lg">
      <button v-if="listen.hub.online && listen.hub.listening"
        class="rounded-lg bg-amber-500 p-3 font-semibold text-white" @click="pauseGuide">
        暫停導遊 Pause Guide
      </button>
      <button v-else class="rounded-lg bg-emerald-600 p-3 font-semibold text-white disabled:opacity-40"
        :disabled="!listen.hub.online" @click="listen.setGuidePaused(false)">
        繼續導遊 Resume Guide
      </button>
      <button class="rounded-lg bg-slate-700 p-3 font-semibold text-white" @click="becomeHub">
        做 Hub · Become hub
      </button>
      <button class="rounded-lg bg-blue-600 p-3 font-semibold text-white disabled:opacity-40"
        :disabled="!listen.joinUrl" @click="shareLink">
        分享連結 Share link
      </button>
      <button class="rounded-lg border border-slate-300 bg-white p-3 text-slate-700 disabled:opacity-40"
        :disabled="listen.connection !== 'connected'" @click="newLink">
        新連結 Make a new link
      </button>
      <p v-if="note" class="col-span-2 break-all rounded-lg bg-white p-2 text-slate-700">{{ note }}</p>
    </div>
  </section>
</template>
