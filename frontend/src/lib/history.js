const REQUEST_TIMEOUT_MS = 30_000;
const HISTORY_DAYS = 30;
const DAY_MS = 86_400_000;
const tripDay = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short" });

// The server uses the configured trip timezone. Use the same calendar for cached dates
// when the room is offline, regardless of the phone's own timezone.
export function availableHistoryDays(days, now = new Date()) {
  const today = tripDay.format(now);
  const first = new Date(Date.parse(today) - HISTORY_DAYS * DAY_MS).toISOString().slice(0, 10);
  return [...new Set(days)].filter((day) => day >= first && day < today).sort().reverse();
}

export function historyBubbles(sentences) {
  const bubbles = new Map();
  for (const sentence of Object.values(sentences).sort((a, b) => a.id - b.id)) {
    if (!bubbles.has(sentence.bubbleId)) {
      bubbles.set(sentence.bubbleId, { id: sentence.bubbleId, sentenceIds: [] });
    }
    bubbles.get(sentence.bubbleId).sentenceIds.push(sentence.id);
  }
  return [...bubbles.values()];
}

// History replies share the socket with Live. Match each to its request, including the
// MP3 frame, and release any waiters if the connection drops.
export class HistoryRequests {
  constructor(socket) {
    this.socket = socket;
    this.pending = new Map();
    this.nextId = 0;
  }

  send(type, fields = {}) {
    if (!this.socket.open) return Promise.reject(new Error("Room is offline"));
    const request_id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(request_id);
        reject(new Error("History request timed out"));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(request_id, { resolve, reject, timer });
      this.socket.sendJson({ type, request_id, ...fields });
    });
  }

  receive(message, audio) {
    const pending = this.pending.get(message.request_id);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(message.request_id);
    if (message.type === "history_error") pending.reject(new Error("History is unavailable"));
    else pending.resolve({ ...message, audio });
  }

  disconnect() {
    for (const { reject, timer } of this.pending.values()) {
      clearTimeout(timer);
      reject(new Error("Room is offline"));
    }
    this.pending.clear();
  }
}
