// Small per-phone helpers shared by the hub and listener pages.

export function stored(key) {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

export function store(key, value) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // private mode: the phone just asks again next time
  }
}

let wakeLock = null;
let watching = false;

async function requestWakeLock() {
  try {
    wakeLock = await navigator.wakeLock?.request("screen");
  } catch {
    wakeLock = null; // not fatal: the screen may dim
  }
}

// Screen Wake Lock while in the room (hard rule 12). iOS drops it when the page is hidden, so it
// is asked for again each time the page comes back.
export function keepScreenOn() {
  requestWakeLock();
  if (watching) return;
  watching = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") requestWakeLock();
  });
}
