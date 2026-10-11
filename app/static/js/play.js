// Beat the Guard: /play kiosk flow. No dependencies.
(() => {
  "use strict";
  // kiosk: no right-click / long-press menus
  document.addEventListener("contextmenu", (e) => e.preventDefault());

  const $ = (id) => document.getElementById(id);
  const IDLE_RESET_MS = 120000;   // any screen, no touches
  const END_RESET_MS = 60000;     // result screen

  const VERDICT_TEXT = {
    YES: "Allowed. The agent may proceed.",
    NO: "Blocked by policy.",
    CONDITIONAL: "Held. Conditions not met yet.",
    INSUFFICIENT: "Held. Not enough verified evidence.",
  };

  let state = {};
  let timerHandle = null;
  let idleHandle = null;

  // ---------- helpers ----------
  const STEPS = ["s-start", "s-missions", "s-game", "s-end"];
  function show(id) {
    document.querySelectorAll(".screen").forEach((s) => s.classList.add("hidden"));
    $(id).classList.remove("hidden");
    const at = STEPS.indexOf(id);
    document.querySelectorAll("#steps li").forEach((li, i) => {
      li.classList.toggle("done", i < at);
      li.classList.toggle("current", i === at);
      if (i === at) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    window.scrollTo(0, 0);
  }

  function el(tag, attrs = {}, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(c));
    return n;
  }

  async function api(path, body) {
    const r = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please check your entries.");
    return data;
  }

  async function postStream(path, body, onEvent) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(typeof d.detail === "string" ? d.detail : "Request failed.");
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        let ev = "message", data = "";
        for (const line of chunk.split("\n")) {
          if (line.startsWith("event: ")) ev = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (data) onEvent(ev, JSON.parse(data));
      }
    }
  }

  function resetIdle() {
    clearTimeout(idleHandle);
    const onEnd = !$("s-end").classList.contains("hidden");
    const onStart = !$("s-start").classList.contains("hidden");
    if (onStart && !$("in-initials").value) return;
    idleHandle = setTimeout(hardReset, onEnd ? END_RESET_MS : IDLE_RESET_MS);
  }
  ["pointerdown", "keydown"].forEach((e) => document.addEventListener(e, resetIdle, { passive: true }));

  function hardReset() {
    clearInterval(timerHandle);
    clearTimeout(idleHandle);
    const g = state.game;
    if (g && !state.finished) api(`/api/games/${g.game_id}/finish`, {}).catch(() => {});
    state = {};
    $("f-start").reset();
    $("start-err").textContent = "";
    show("s-start");
    armAttract();
  }

  // ---------- 1. start ----------
  $("in-initials").addEventListener("input", (e) => {
    e.target.value = e.target.value.replace(/[^a-z]/gi, "").toUpperCase().slice(0, 3);
  });

  $("f-start").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("start-err").textContent = "";
    try {
      const p = await api("/api/players", {
        initials: $("in-initials").value,
        name: $("in-name").value,
        email: $("in-email").value,
        institution: $("in-inst").value,
        role: $("in-role").value,
        consent: $("in-consent").checked,
      });
      state.player = p;
      await showMissions();
    } catch (err) {
      $("start-err").textContent = err.message;
    }
  });

  // ---------- 2. missions ----------
  async function showMissions() {
    const list = await api("/api/missions");
    const box = $("mission-list");
    box.replaceChildren();
    for (const m of list) {
      box.append(el("button", { class: "mission", type: "button", onclick: () => startGame(m.id) },
        el("div", { class: "label" }, m.role),
        el("h2", {}, m.title),
        el("p", {}, m.short),
        el("div", { class: "foot-row" }, difficultyMeter(m.difficulty), el("span", { class: "go" }, "Start mission →"))));
    }
    show("s-missions");
    resetIdle();
    if (list.length === 1) startGame(list[0].id);   // single-mission build: skip the picker
  }

  const DIFFICULTY = ["", "Standard", "Hard", "Expert"];
  function difficultyMeter(d) {
    return el("div", { class: "difficulty" },
      el("span", { class: "pips" }, ...[1, 2, 3].map((i) => el("i", { class: i <= d ? "on" : "" }))),
      el("span", { class: "label" }, DIFFICULTY[d] || ""));
  }

  // ---------- 3. game ----------
  async function startGame(missionId) {
    const g = await api("/api/games", { player_id: state.player.player_id, mission_id: missionId });
    state.game = g;
    state.finished = false;
    state.used = 0;
    state.busy = false;
    const m = g.mission;
    $("g-role").textContent = `Mission · ${m.role}`;
    $("g-title").textContent = m.title;
    $("g-scenario").textContent = m.scenario;
    $("g-goal").textContent = m.goal;
    $("g-agent").textContent = m.agent;
    $("g-sample").replaceChildren(...(m.sample || []).map((r) => el("li", {}, r)));
    $("g-facts").replaceChildren(...m.facts.map((f) => el("li", {}, el("b", {}, f.label), f.plain)));
    $("in-attempt").value = "";
    $("g-count").textContent = `0 / 600`;
    $("history").replaceChildren();
    $("verdict").classList.add("hidden");
    $("game-err").textContent = "";
    $("b-send").disabled = false;
    $("in-attempt").disabled = false;
    resetEndButton();
    drawAttempts();
    show("s-game");
    $("in-attempt").focus();

    const endAt = Date.now() + g.seconds * 1000;
    clearInterval(timerHandle);
    const tick = () => {
      const left = Math.max(0, Math.ceil((endAt - Date.now()) / 1000));
      $("g-timer").textContent = left;
      $("g-timer").classList.toggle("low", left <= 15);
      $("g-timebar").style.width = `${Math.max(0, (endAt - Date.now()) / (g.seconds * 1000)) * 100}%`;
      if (left === 0) {
        clearInterval(timerHandle);
        $("b-send").disabled = true;
        $("in-attempt").disabled = true;
        // an in-flight verdict still lands; the server waits for it
        if (!state.busy) endGame();
      }
    };
    tick();
    timerHandle = setInterval(tick, 250);
    resetIdle();
  }

  function drawAttempts() {
    const max = state.game.max_attempts;
    $("g-attempts").replaceChildren(
      ...Array.from({ length: max }, (_, i) => el("i", { class: i < state.used ? "used" : "" })));
  }

  $("in-attempt").addEventListener("input", (e) => {
    $("g-count").textContent = `${e.target.value.length} / 600`;
  });

  $("f-attempt").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.busy || state.finished) return;
    const text = $("in-attempt").value.trim();
    if (text.length < 3) {
      $("game-err").textContent = "Write a request for the AI agent first.";
      return;
    }
    state.busy = true;
    $("game-err").textContent = "";
    $("b-send").disabled = true;
    const v = $("verdict");
    v.classList.remove("hidden", "win");
    v.dataset.decision = "pending";
    $("v-word").textContent = "Judging…";
    $("v-word").className = "verdict-word pending";
    $("v-sub").textContent = "";
    $("v-meta").textContent = "";
    $("v-reasons-wrap").classList.add("hidden");

    let result = null;
    try {
      await postStream(`/api/games/${state.game.game_id}/attempts`, { text }, (ev, d) => {
        if (ev === "verdict") {
          $("v-word").textContent = d.decision;
          $("v-word").className = "verdict-word";
          v.dataset.decision = d.decision;
          $("v-sub").textContent = VERDICT_TEXT[d.decision] || "";
          $("v-meta").textContent = `${d.t_decision_ms} ms · on-device`;
          v.classList.toggle("win", d.decision === "YES");
          v.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } else if (ev === "result") {
          result = d;
        } else if (ev === "error") {
          throw new Error(d.message);
        }
      });
    } catch (err) {
      $("v-word").textContent = "…";
      $("v-word").className = "verdict-word";
      v.dataset.decision = "error";
      $("v-sub").textContent = err.message;
      state.busy = false;
      $("b-send").disabled = timeLeft() === 0;
      if (timeLeft() === 0) endGame();
      return;
    }
    state.busy = false;
    if (!result) return;

    state.used = result.attempt;
    drawAttempts();
    if (result.reasons.length) {
      $("v-reasons").replaceChildren(...result.reasons.map((r) => el("li", {}, el("b", {}, `${r.label}: `), r.plain)));
      $("v-reasons-wrap").classList.remove("hidden");
    }
    v.scrollIntoView({ behavior: "smooth", block: "end" });
    $("history").prepend(el("li", {}, el("b", {}, `#${result.attempt} ${result.decision}`),
      text.length > 90 ? text.slice(0, 90) + "…" : text));

    if (result.game_over) {
      $("in-attempt").disabled = true;
      setTimeout(endGame, result.gap ? 2600 : 2200);
    } else if (timeLeft() === 0) {
      endGame();
    } else {
      $("b-send").disabled = false;
      $("in-attempt").select();
    }
  });

  // End mission early: the button opens a confirm strip with two big
  // buttons (no double-tap: quick taps on touch screens can be swallowed).
  let confirmTimer = null;
  function resetEndButton() {
    clearTimeout(confirmTimer);
    $("end-confirm").classList.add("hidden");
    $("b-end").disabled = false;
    $("b-end").textContent = "End mission";
  }
  $("b-end").addEventListener("click", () => {
    if (state.finished || !state.game) return;
    $("end-confirm").classList.remove("hidden");
    clearTimeout(confirmTimer);
    confirmTimer = setTimeout(resetEndButton, 10000);   // untouched: keep playing
  });
  $("b-end-no").addEventListener("click", resetEndButton);
  $("b-end-yes").addEventListener("click", () => {
    if (state.finished || !state.game) return;
    clearTimeout(confirmTimer);
    $("end-confirm").classList.add("hidden");
    $("b-end").disabled = true;
    $("b-end").textContent = state.busy ? "Ending after this verdict…" : "Ending…";
    $("b-send").disabled = true;
    $("in-attempt").disabled = true;
    endGame({ quit: true });     // the server waits for any verdict still in flight
  });

  function timeLeft() {
    return parseInt($("g-timer").textContent, 10) || 0;
  }

  // ---------- 4. end ----------
  async function endGame(opts = {}) {
    if (state.finished) return;
    state.finished = true;
    clearInterval(timerHandle);
    clearTimeout(confirmTimer);
    $("end-confirm").classList.add("hidden");   // keep the "Ending…" feedback
    let s;
    try {
      s = await api(`/api/games/${state.game.game_id}/finish`, { quit: !!opts.quit });
    } catch {
      hardReset();
      return;
    }
    state.summary = s;
    $("end-banner").classList.toggle("hidden", !s.beat);
    $("result-hero").classList.toggle("beat", s.beat);
    $("end-status").textContent = s.beat ? "Final score"
      : s.status === "timeout" ? "Time's up. The guard held."
      : s.status === "ended" ? "You ended the mission. The guard held."
      : "The guard held.";
    $("end-score").textContent = s.score.toLocaleString();
    $("end-rank").textContent = `Rank #${s.rank} of ${s.of}` + (s.creative ? " · Creativity bonus" : "");
    $("end-takeaways").replaceChildren(...s.takeaways.map((t) => el("li", {}, t)));
    document.querySelectorAll(".offer").forEach((b) =>
      b.classList.toggle("chosen", s.player.interests.includes(b.dataset.offer)));
    $("f-interest").classList.add("hidden");
    $("thanks").classList.add("hidden");
    loadLinks();
    show("s-end");
    resetIdle();
  }

  // QR codes only; the kiosk never navigates to external sites
  let linksLoaded = false;
  async function loadLinks() {
    if (linksLoaded) return;
    try {
      const links = await api("/api/links");
      $("ext-grid").replaceChildren(...links.map((l) => el("div", { class: "ext-item" },
        el("img", { src: `/api/qr.svg?kind=link&id=${encodeURIComponent(l.id)}`, alt: `QR code: ${l.label}` }),
        el("div", { class: "ext-label" }, l.label),
        el("div", { class: "ext-url" }, l.display))));
      $("ext").classList.toggle("hidden", links.length === 0);
      linksLoaded = true;
    } catch { /* links are optional */ }
  }

  async function sendInterest(offer, extra = {}) {
    await api(`/api/players/${state.player.player_id}/interest`, { offer, consent: true, ...extra });
    state.summary.player.consent = true;
    state.summary.player.has_email = true;
    document.querySelector(`.offer[data-offer="${offer}"]`).classList.add("chosen");
    $("f-interest").classList.add("hidden");
    $("thanks").textContent = "Thanks. An HP Z specialist will follow up after the show.";
    $("thanks").classList.remove("hidden");
  }

  document.querySelectorAll(".offer").forEach((b) => b.addEventListener("click", async () => {
    const p = state.summary.player;
    state.pendingOffer = b.dataset.offer;
    if (p.consent && p.has_email) {
      try { await sendInterest(b.dataset.offer); } catch (err) { $("i-err").textContent = err.message; }
    } else {
      $("i-err").textContent = "";
      $("f-interest").classList.remove("hidden");
      $("i-email").focus();
    }
  }));

  $("f-interest").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await sendInterest(state.pendingOffer, {
        email: $("i-email").value, name: $("i-name").value,
        consent: $("i-consent").checked,
      });
      $("f-interest").reset();
    } catch (err) {
      $("i-err").textContent = err.message;
    }
  });

  // Station mode: the game runs on the Nano's own screen. Staff reach admin
  // with Ctrl+Alt+A; after 30 s untouched on the start screen, show the board
  // as an attract loop (any key or tap there comes straight back here).
  const STATION = new URLSearchParams(location.search).get("station") === "1";
  const ATTRACT_MS = 30000;
  let attractTimer = null;
  function armAttract() {
    clearTimeout(attractTimer);
    if (!STATION) return;
    attractTimer = setTimeout(() => {
      const onStart = !$("s-start").classList.contains("hidden");
      const typing = $("in-initials").value || document.activeElement?.tagName === "INPUT";
      if (onStart && !typing) location.replace("/board?attract=1");
      else armAttract();
    }, ATTRACT_MS);
  }
  if (STATION) {
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.altKey && (e.key === "a" || e.key === "A")) {
        e.preventDefault();
        location.replace("/admin?from=station");
      }
    });
    ["pointerdown", "keydown", "input"].forEach((ev) =>
      document.addEventListener(ev, armAttract, { passive: true }));
    armAttract();
  }

  // kiosk status: demo tag, and hold the start button until the guard is up
  let demoTagged = false;
  async function pollKiosk() {
    let k;
    try { k = await api("/api/kiosk"); } catch { k = { guard_ready: false }; }
    if (k.demo_mode && !demoTagged) {
      demoTagged = true;
      document.querySelector(".foot .label").textContent += " · DEMO MODE";
    }
    $("warming").classList.toggle("hidden", k.guard_ready);
    $("b-start").disabled = !k.guard_ready;
    $("guard-chip").classList.toggle("warn", !k.guard_ready);
    $("guard-chip-text").textContent = k.guard_ready ? "Guard ready · on-device" : "Guard starting up";
    setTimeout(pollKiosk, k.guard_ready ? 15000 : 3000);
  }
  show("s-start");
  pollKiosk();

  $("b-again").addEventListener("click", () => showMissions());
  $("b-done").addEventListener("click", hardReset);
})();
