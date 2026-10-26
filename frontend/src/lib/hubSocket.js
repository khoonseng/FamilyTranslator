// The hub's WebSocket (backend/app/schemas.py has every message). It says hello with the hub PIN
// and API token (hard rule 1), routes each MP3 to the `clip` header just before it, and
// reconnects after a drop (hard rule 12), unless the credentials were refused.

export class HubSocket {
  constructor({ pin, token, onReady, onMessage, onClip, onStatus, onRefused }) {
    Object.assign(this, { pin, token, onReady, onMessage, onClip, onStatus, onRefused });
    this.ws = null;
    this.pendingClip = null;
    this.retry = 0;
    this.stopped = false;
  }

  connect() {
    this.stopped = false;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/ws/room`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    this.onStatus("connecting");
    ws.onopen = () =>
      ws.send(JSON.stringify({ type: "hello", role: "hub", pin: this.pin, token: this.token }));
    ws.onmessage = (event) => {
      if (typeof event.data !== "string") {
        if (this.pendingClip !== null) this.onClip(this.pendingClip, event.data);
        this.pendingClip = null;
        return;
      }
      const message = JSON.parse(event.data);
      if (message.type === "ready") {
        this.retry = 0;
        this.onStatus("connected");
        this.onReady();
      } else if (message.type === "error" && message.code === "bad_credentials") {
        this.stopped = true;
        this.onRefused();
      } else if (message.type === "clip") {
        this.pendingClip = message.sentence_id;
      } else {
        this.onMessage(message);
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.onStatus("offline");
      if (this.stopped) return;
      const delay = Math.min(8000, 1000 * 2 ** this.retry++);
      setTimeout(() => !this.stopped && this.connect(), delay);
    };
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
    this.ws?.close();
  }
}
