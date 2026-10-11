// Beat the Guard: /board attract loop. Polls the local API.
(() => {
  "use strict";
  // kiosk: no right-click / long-press menus
  document.addEventListener("contextmenu", (e) => e.preventDefault());
  // Ctrl+Alt+A on the Nano's keyboard: switch this screen to admin. Admin
  // itself only answers on localhost/Tailscale (404 anywhere else).
  const ATTRACT = new URLSearchParams(location.search).get("attract") === "1";
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.altKey && (e.key === "a" || e.key === "A")) {
      e.preventDefault();
      location.replace(ATTRACT ? "/admin?from=station" : "/admin?from=board");
      return;
    }
    if (ATTRACT && !["Control", "Alt", "Shift", "Meta"].includes(e.key)) location.replace("/play?station=1");
  });
  // Station attract loop: any tap or click goes straight back to the game.
  if (ATTRACT) document.addEventListener("pointerdown", () => location.replace("/play?station=1"));
  const $ = (id) => document.getElementById(id);
  const CARD_MS = 9000;
  let lastPlay = "";
  let lastWifi = null;
  let cards = [];
  let cardIdx = 0;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function renderNetwork(n) {
    const badge = $("net-badge");
    if (n.offline) {
      badge.classList.add("ok");
      $("net-text").textContent = "OFFLINE: 0 bytes left the building";
      $("net-sub").textContent = "No internet route. Every decision is made on this device.";
    } else if (n.unknown) {
      badge.classList.remove("ok");
      $("net-text").textContent = "Network status unknown";
      $("net-sub").textContent = "The guard decides on-device either way.";
    } else {
      badge.classList.remove("ok");
      $("net-text").textContent = n.internet_reachable ? "Uplink connected" : "LAN only";
      $("net-sub").textContent = "The guard still decides on-device. No prompts go to the cloud.";
    }
  }

  // Shrink the card's text until it fits the block (any screen, any card).
  function fitCard() {
    const box = $("card"), big = $("card-big"), text = $("card-text");
    big.style.fontSize = ""; text.style.fontSize = "";
    let scale = 1;
    const base = [parseFloat(getComputedStyle(big).fontSize), parseFloat(getComputedStyle(text).fontSize)];
    while (box.scrollHeight > box.clientHeight + 1 && scale > 0.5) {
      scale -= 0.05;
      big.style.fontSize = `${base[0] * scale}px`;
      text.style.fontSize = `${base[1] * scale}px`;
    }
  }
  window.addEventListener("resize", fitCard);

  function showCard() {
    if (!cards.length) return;
    const c = cards[cardIdx % cards.length];
    const box = $("card");
    box.classList.add("fade");
    setTimeout(() => {
      $("card-big").textContent = c.big;
      $("card-text").textContent = c.text;
      $("card-src").textContent = `Source: ${c.source}`;
      fitCard();
      box.classList.remove("fade");
    }, 400);
    cardIdx++;
  }

  async function refresh() {
    try {
      const r = await fetch("/api/board", { cache: "no-store" });
      const d = await r.json();
      const s = d.stats;
      $("st-attempts").textContent = s.attempts.toLocaleString();
      $("st-blocked").textContent = s.blocked_pct === null ? "–" : `${s.blocked_pct}%`;
      $("st-ms").textContent = s.avg_decision_ms === null ? "–" : `${s.avg_decision_ms} ms`;
      $("st-gaps").textContent = s.gaps.toLocaleString();

      $("lb").replaceChildren(...d.leaderboard.map((row, i) => {
        const li = el("li");
        li.append(el("span", "pos", String(i + 1)), el("span", "ini", row.initials));
        const beat = row.status === "beat";
        li.append(el("span", "mis", row.mission), el("span", beat ? "beat" : "", beat ? "BEAT" : ""),
                  el("span", beat ? "pts won" : "pts", row.score.toLocaleString()));
        return li;
      }));
      $("lb-empty").classList.toggle("hidden", d.leaderboard.length > 0);

      renderNetwork(d.network);

      // Station mode with no hotspot: the game is right here on this screen
      const here = d.mode === "station" && !d.wifi;
      $("play-here").classList.toggle("hidden", !here);
      document.querySelector(".qrs").classList.toggle("hidden", here);
      $("attract-bar").classList.toggle("hidden", !(ATTRACT || here));
      document.body.classList.toggle("attract", ATTRACT || here);

      const ssid = d.wifi ? d.wifi.ssid : "";
      if (ssid !== lastWifi) {
        lastWifi = ssid;
        $("step-wifi").classList.toggle("hidden", !ssid);
        document.querySelector(".qrs").classList.toggle("single", !ssid);
        $("wifi-ssid").textContent = ssid;
        $("play-step").textContent = ssid ? "2 · Open the game" : "Scan to play";
        if (ssid) $("qr-wifi").src = `/api/qr.svg?kind=wifi&s=${encodeURIComponent(ssid)}`;
      }
      if (d.play_url !== lastPlay) {
        lastPlay = d.play_url;
        $("play-url").textContent = d.play_url.replace(/^https?:\/\//, "");
        $("qr-play").src = `/api/qr.svg?kind=play&u=${encodeURIComponent(d.play_url)}`;
      }

      if (!cards.length && d.cards.length) {
        cards = d.cards;
        showCard();
        setInterval(showCard, CARD_MS);
      }
    } catch {
      /* keep the last good frame on screen */
    }
  }

  refresh();
  setInterval(refresh, 3000);
})();
