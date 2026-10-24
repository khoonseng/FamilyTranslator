// Shared by both pages. The probe token is asked for once, checked against the server, and
// remembered on this phone. A Home Screen app keeps its own storage, so it asks once there too.
// A token in the address (?t=...) still works, and is then removed from the address bar.
const probe = (() => {
  let token = new URLSearchParams(location.search).get("t") || "";
  try {
    token = token || localStorage.getItem("probeToken") || "";
  } catch {}

  const api = (path) => path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(token);

  async function valid() {
    if (!token) return false;
    const r = await fetch(api("/api/ping"), { cache: "no-store" });
    return r.ok;
  }

  // Shows the token box until a token works, then calls onReady once.
  async function start(onReady) {
    const box = document.getElementById("tokenBox");
    const input = document.getElementById("tokenInput");
    const msg = document.getElementById("tokenMsg");
    const offline = "Can't reach the server. Is mobile data on?";
    const accept = () => {
      try {
        localStorage.setItem("probeToken", token);
      } catch {}
      history.replaceState(null, "", location.pathname);
      box.hidden = true;
      onReady();
    };
    try {
      if (await valid()) return accept();
    } catch {
      msg.textContent = offline;
    }
    box.hidden = false;
    document.getElementById("tokenSave").onclick = async () => {
      token = input.value.trim();
      msg.textContent = "Checking…";
      try {
        if (await valid()) {
          msg.textContent = "";
          accept();
        } else {
          msg.textContent = "That token didn't work.";
        }
      } catch {
        msg.textContent = offline;
      }
    };
  }

  function forget() {
    try {
      localStorage.removeItem("probeToken");
    } catch {}
    location.href = location.pathname;
  }

  return { api, start, forget };
})();
