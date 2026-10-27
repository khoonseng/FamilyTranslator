// Every phone's WebSocket to the room (backend/app/schemas.py has every message). `hello()` is
// called at each connect, so a listener can say which sentence it has up to (catch-up). It
// routes each MP3 to the `clip` header just before it, and reconnects after a drop (hard rule
// 12), unless the server refused the phone (wrong credentials, or a join link replaced by a new
// one).

const REFUSALS = ["bad_credentials", "link_changed"];

export class RoomSocket {
  constructor({ hello, onReady, onMessage, onClip, onStatus, onRefused }) {
    Object.assign(this, { hello, onReady, onMessage, onClip, onStatus, onRefused });
    this.ws = null;
    this.pendingClip = null;
    this.retry = 0;
    this.timer = null;
    this.stopped = false;
  }

  connect() {
    this.stopped = false;
    clearTimeout(this.timer);
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/ws/room`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    this.pendingClip = null;
    this.onStatus("connecting");
    ws.onopen = () => ws.send(JSON.stringify({ type: "hello", ...this.hello() }));
    ws.onmessage = (event) => {
      if (typeof event.data !== "string") {
        const header = this.pendingClip;
        if (header !== null) this.onClip(header.sentence_id, event.data, header);
        this.pendingClip = null;
        return;
      }
      const message = JSON.parse(event.data);
      if (message.type === "ready") {
        this.retry = 0;
        this.onStatus("connected");
        this.onReady(message);
      } else if (message.type === "error" && REFUSALS.includes(message.code)) {
        this.stopped = true;
        this.onRefused(message.code);
      } else if (message.type === "clip") {
        this.pendingClip = message; // its MP3 is the next binary frame
      } else {
        this.onMessage(message);
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.onStatus("offline");
      if (this.stopped) return;
      const delay = Math.min(8000, 1000 * 2 ** this.retry++);
      this.timer = setTimeout(() => !this.stopped && this.connect(), delay);
    };
  }

  // The page woke up (unlocked, back online): if the socket died meanwhile, reconnect now
  // instead of waiting out the backoff.
  wake() {
    if (this.stopped) return;
    const state = this.ws?.readyState;
    if (state === WebSocket.CLOSING || state === WebSocket.CLOSED) {
      this.retry = 0;
      this.connect();
    }
  }

  get open() {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  sendJson(message) {
    if (this.open) this.ws.send(JSON.stringify(message));
  }

  sendAudio(buffer) {
    if (this.open) this.ws.send(buffer);
  }

  close() {
    this.stopped = true;
    clearTimeout(this.timer);
    this.ws?.close();
  }
}
