// Which page this phone shows, from its address:
// - /join#<token> remembers the family's join link and moves to /listen (the token leaves the
//   address bar). The token sits after the #, which the phone never sends anywhere: not to our
//   server's request logs, nor to WhatsApp's link-preview fetcher (owner decision 2026-10-26);
// - /listen: a family listener; /host: the owner's and wife's phones; anything else: the hub.
// Become hub (host page) and "Listen on this phone" (a replaced hub) switch pages in place.

import { ref } from "vue";
import { rememberJoinToken } from "../stores/listen.js";

const PATHS = { hub: "/", listen: "/listen", host: "/host" };

function initial() {
  if (location.pathname === "/join") {
    const token = decodeURIComponent(location.hash.slice(1));
    if (token) rememberJoinToken(token);
    history.replaceState(null, "", PATHS.listen);
    return "listen";
  }
  return Object.keys(PATHS).find((name) => PATHS[name] === location.pathname) ?? "hub";
}

export const page = ref(initial());

export function goTo(name) {
  history.replaceState(null, "", PATHS[name]);
  page.value = name;
}
