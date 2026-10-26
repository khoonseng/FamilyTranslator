// The phone's own copy of each day's sentences and clips (hard rule 10): replays never call TTS
// again and work in a tunnel, and a reloaded page shows its bubbles at once and catches up only
// from its last sentence. IndexedDB through `idb`; in memory if IndexedDB is unavailable (some
// private modes). Kept after the day ends (hard rule 14). A failed write never stops playback.

import { openDB } from "idb";

const STORES = ["sentences", "clips"]; // both keyed by [day, sentence id]

function idbBackend(db) {
  return {
    put: (store, value, key) => db.put(store, value, key),
    get: (store, key) => db.get(store, key),
    sentencesOf: (day) => db.getAll("sentences", IDBKeyRange.bound([day, 0], [day, Infinity])),
  };
}

export function memoryBackend() {
  const maps = Object.fromEntries(STORES.map((s) => [s, new Map()]));
  const name = ([day, id]) => `${day}/${id}`;
  return {
    put: async (store, value, key) => maps[store].set(name(key ?? [value.day, value.id]), value),
    get: async (store, key) => maps[store].get(name(key)),
    sentencesOf: async (day) => [...maps.sentences.values()].filter((s) => s.day === day),
  };
}

export class ClipCache {
  constructor(backend) {
    this.backend = backend;
  }

  static async open() {
    try {
      const db = await openDB("cq-translator", 1, {
        upgrade(db) {
          db.createObjectStore("sentences", { keyPath: ["day", "id"] });
          db.createObjectStore("clips");
        },
      });
      return new ClipCache(idbBackend(db));
    } catch {
      return new ClipCache(memoryBackend());
    }
  }

  // The day's sentences, oldest first.
  async loadDay(day) {
    try {
      return (await this.backend.sentencesOf(day)).sort((a, b) => a.id - b.id);
    } catch {
      return [];
    }
  }

  // A plain copy: Vue's reactive proxies can't be stored.
  async putSentence(day, sentence) {
    try {
      await this.backend.put("sentences", { ...sentence, day });
    } catch {
      // a full or blocked store: the bubble still shows, it just won't survive a reload
    }
  }

  // MP3 bytes as an ArrayBuffer (safer than a Blob in Safari's IndexedDB).
  async putClip(day, id, data) {
    try {
      await this.backend.put("clips", data, [day, id]);
    } catch {
      // as above
    }
  }

  async getClip(day, id) {
    try {
      return await this.backend.get("clips", [day, id]);
    } catch {
      return undefined;
    }
  }
}
