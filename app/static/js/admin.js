// Beat the Guard: /admin. No dependencies.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let demoOn = false;
  let pollHandle = null;

  async function api(path, body) {
    const r = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    if (r.status === 401 && path !== "/api/admin/login") { showLogin(); throw new Error("Logged out"); }
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Error ${r.status}`);
    return d;
  }

  function td(text, cls) {
    const c = document.createElement("td");
    if (cls) c.className = cls;
    c.textContent = text;
    return c;
  }

  function msg(t) { $("msg").textContent = t; }
  const fmtTime = (s) => new Date(s * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  function showLogin() {
    clearInterval(pollHandle);
    $("panel").classList.add("hidden");
    $("b-logout").classList.add("hidden");
    $("f-login").classList.remove("hidden");
  }

  function showPanel() {
    $("f-login").classList.add("hidden");
    $("panel").classList.remove("hidden");
    $("b-logout").classList.remove("hidden");
    refresh();
    clearInterval(pollHandle);
    pollHandle = setInterval(refresh, 5000);
  }

  $("f-login").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-err").textContent = "";
    try {
      await api("/api/admin/login", { password: $("in-pw").value });
      $("in-pw").value = "";
      showPanel();
    } catch (err) { $("login-err").textContent = err.message; }
  });

  $("b-logout").addEventListener("click", async () => { await api("/api/admin/logout", {}); showLogin(); });

  async function refresh() {
    let o;
    try { o = await api("/api/admin/overview"); } catch { return; }
    $("h-model").textContent = o.guard.ok ? "Loaded" : "DOWN";
    $("h-model-s").textContent = o.guard.ok ? `sentinel-v6 · API ${o.guard.ms} ms` : (o.guard.error || "not listed");
    $("h-lat").textContent = o.latency ? `${o.latency.median} ms` : "–";
    $("h-lat-s").textContent = o.latency ? `median of last ${o.latency.n} · max ${o.latency.max} ms` : "no decisions yet";
    $("h-gpu").textContent = o.gpu.ok ? `${o.gpu.temp_c}°C` : "?";
    $("h-gpu-s").textContent = o.gpu.ok ? `${o.gpu.util_pct}% util · ${o.gpu.power_w} W · ${o.memory.available_gb} of ${o.memory.total_gb} GB free` : o.gpu.error;
    const n = o.network;
    $("h-net").textContent = n.offline ? "OFFLINE" : (n.internet_reachable ? "ONLINE" : "LAN ONLY");
    $("h-net-s").textContent = n.offline ? "no default route · 0 bytes out" : `uplink ${n.uplinks.join(", ")}`;
    $("c-players").textContent = o.counts.players;
    $("c-leads").textContent = o.counts.leads;
    $("c-attempts").textContent = o.counts.attempts;
    $("c-gaps").textContent = o.counts.gaps_unreviewed;
    demoOn = o.demo_mode;
    $("b-demo").textContent = `Demo mode: ${demoOn ? "ON" : "off"}`;
    $("b-demo").classList.toggle("on", demoOn);
    $("play-url").textContent = o.mode === "station" ? "on this screen (station mode)" : o.play_url;
    $("wifi-line").textContent = o.mode === "station" && !o.wifi.active ? "· Wi-Fi: not used"
      : o.wifi.active ? `· Wi-Fi: ${o.wifi.ssid} (on)` : "· Wi-Fi hotspot: off";
    $("links-line").textContent = o.links_configured === 3 ? "· End-screen links: 3 set"
      : `· End-screen links: ${o.links_configured} of 3 set (edit config/booth.env)`;
    $("clock-line").textContent = `· Nano clock: ${new Date(o.server_time * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}`;
    loadGaps();
    loadBoard();
    loadUsb();
  }

  let usbBusy = false;
  async function loadUsb() {
    if (usbBusy) return;
    const u = await api("/api/admin/usb");
    $("usb-summary").textContent = u.drives.length
      ? `${u.leads_today} consented lead${u.leads_today === 1 ? "" : "s"} today (${u.today}). Writes one AES-256 encrypted zip (today's and all-time leads and attempts), then decrypts it from the drive to verify.`
      : "No USB drive detected. Plug one into the Nano; it appears here within a few seconds.";
    $("usb-drives").replaceChildren(...u.drives.map((d) => {
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = `Export today's leads to ${d.label} (${d.free_gb} GB free)`;
      b.disabled = !d.writable;
      b.onclick = async () => {
        usbBusy = true;
        $("usb-msg").textContent = "Writing…";
        try {
          const r = await api("/api/admin/usb-export", { path: d.path });
          $("usb-msg").textContent = `Done: lead report PDF + ${r.file} containing ${r.contents.map((f) => `${f.file} (${f.rows} rows)`).join(", ")}. ${r.note}`;
        } catch (err) { $("usb-msg").textContent = err.message; }
        usbBusy = false;
      };
      return b;
    }));
  }

  async function loadGaps() {
    const rows = await api("/api/admin/gaps");
    $("gaps").replaceChildren(...rows.map((g) => {
      const tr = document.createElement("tr");
      const b = document.createElement("button");
      b.textContent = g.reviewed ? "Reviewed" : "Mark reviewed";
      b.className = g.reviewed ? "on" : "";
      b.onclick = async () => { await api(`/api/admin/gaps/${g.id}/reviewed`, { reviewed: !g.reviewed }); loadGaps(); };
      const last = document.createElement("td");
      last.append(b);
      tr.append(td(fmtTime(g.created_at)), td(g.initials + (g.demo ? " (demo)" : "")), td(g.mission), td(g.text, "req"), last);
      return tr;
    }));
  }

  async function loadBoard() {
    const rows = await api("/api/admin/leaderboard");
    $("lb").replaceChildren(...rows.map((r, i) => {
      const tr = document.createElement("tr");
      const b = document.createElement("button");
      b.textContent = "Hide";
      b.onclick = async () => {
        if (!confirm(`Hide ${r.initials} from the leaderboard?`)) return;
        await api(`/api/admin/players/${r.player_id}/hidden`, { hidden: true });
        loadBoard();
      };
      const last = document.createElement("td");
      last.append(b);
      tr.append(td(String(i + 1)), td(r.initials), td(r.mission || r.mission_id), td(r.score.toLocaleString()), last);
      return tr;
    }));
  }

  $("b-test").addEventListener("click", async () => {
    msg("Running test verdict…");
    try {
      const r = await api("/api/admin/test-verdict", {});
      msg(`Test verdict: ${r.decision} in ${r.t_decision_ms} ms (full answer ${r.t_total_ms} ms, JSON ${r.json_ok ? "ok" : "malformed"})`);
    } catch (err) { msg(err.message); }
  });

  $("b-demo").addEventListener("click", async () => {
    await api("/api/admin/demo-mode", { on: !demoOn });
    refresh();
  });

  $("b-reset").addEventListener("click", async () => {
    if (!confirm("Start a fresh leaderboard? Players, leads and attempts are kept.")) return;
    await api("/api/admin/reset-board", {});
    msg("Leaderboard reset.");
    refresh();
  });

  $("b-restart").addEventListener("click", async () => {
    if (!confirm("Restart the model? Play is unavailable for about 1-2 minutes.")) return;
    try { const r = await api("/api/admin/restart-model", {}); msg(r.note); } catch (err) { msg(err.message); }
  });

  $("b-wipe").addEventListener("click", async () => {
    const t = prompt("This archives the database, then deletes all players, leads and attempts. Type WIPE to confirm.");
    if (t !== "WIPE") return;
    try { const r = await api("/api/admin/archive-wipe", { confirm: t }); msg(`Wiped. Archive saved to ${r.archive}`); refresh(); }
    catch (err) { msg(err.message); }
  });

  $("b-maint").addEventListener("click", async () => {
    if (!confirm("Unlock the Nano's desktop for maintenance? The board closes until you press Relock kiosk.")) return;
    try { const r = await api("/api/admin/kiosk", { mode: "maintenance" }); msg(`${r.note}. Terminal: Ctrl+Alt+T.`); } catch (err) { msg(err.message); }
  });

  $("b-relock").addEventListener("click", async () => {
    try { const r = await api("/api/admin/kiosk", { mode: "lock" }); msg(`${r.note}. The board reopens within a few seconds.`); } catch (err) { msg(err.message); }
  });

  function showOut(text) { $("check-out").textContent = text; $("check-out").classList.remove("hidden"); }

  $("b-preflight").addEventListener("click", async () => {
    showOut("Running preflight…");
    try { const r = await api("/api/admin/preflight", {}); showOut(r.output); } catch (err) { showOut(err.message); }
  });

  $("b-arm").addEventListener("click", async () => {
    try { const r = await api("/api/admin/rehearsal/arm", {}); showOut(r.note); } catch (err) { showOut(err.message); }
  });

  $("b-rehearsal").addEventListener("click", async () => {
    try {
      const r = await api("/api/admin/rehearsal");
      showOut(r.file ? `${r.file}${r.armed ? " (another run is armed for next boot)" : ""}\n\n${r.output}` : "No rehearsal has run yet. Arm it, then cold-boot.");
    } catch (err) { showOut(err.message); }
  });

  // Opened from the Nano's own kiosk screen (Ctrl+Alt+A on the board or the
  // station). That keyboard is public, so: always log in fresh, log out when
  // leaving, return automatically after 3 idle minutes, and use replace() so
  // the browser's Back key can never land on admin.
  const from = new URLSearchParams(location.search).get("from");
  const kioskBack = { board: "/board", station: "/play?station=1" }[from];
  function leaveAdmin() {
    fetch("/api/admin/logout", { method: "POST", keepalive: true }).finally(() => location.replace(kioskBack));
  }
  if (kioskBack) {
    $("b-board").classList.remove("hidden");
    $("b-board").textContent = from === "station" ? "Back to game" : "Back to board";
    $("b-board").addEventListener("click", (e) => { e.preventDefault(); leaveAdmin(); });
    window.addEventListener("pagehide", () => navigator.sendBeacon("/api/admin/logout"));
    let idle;
    const arm = () => { clearTimeout(idle); idle = setTimeout(leaveAdmin, 180000); };
    ["pointerdown", "keydown", "scroll"].forEach((ev) => document.addEventListener(ev, arm, { passive: true }));
    arm();
  }

  // try the session cookie first (never on the public kiosk keyboard)
  if (kioskBack) fetch("/api/admin/logout", { method: "POST" }).finally(showLogin);
  else api("/api/admin/overview").then(showPanel).catch(() => showLogin());
})();
