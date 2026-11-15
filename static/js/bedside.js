"use strict";
// The bedside screen: one thing at a time, no reading needed, speaks when a dose is due.
(() => {
  const { api, el, clear, telLink, pillClass } = Orbit;
  const stage = document.getElementById("stage");
  const soundButton = document.getElementById("sound");
  let state = null;
  let voiceOn = false;
  let lastSpokenKey = "";

  function storageGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* private mode */ } }

  function speak(text) {
    if (!voiceOn || !text || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.85;
    window.speechSynthesis.speak(utterance);
  }

  function setVoice(on) {
    voiceOn = on;
    storageSet("orbit_voice", on ? "1" : "0");
    soundButton.setAttribute("aria-pressed", String(on));
    soundButton.textContent = on ? "Voice on" : "Turn on voice";
  }

  soundButton.addEventListener("click", () => {
    setVoice(!voiceOn);
    if (voiceOn) speak(state && state.speak ? state.speak : "Voice is on.");
  });

  // The clock shows the elder's own time (from the server), whatever the device is set to.
  let offsetMs = 0;
  function tickClock() {
    const now = new Date(Date.now() + offsetMs);
    const opts = { timeZone: "UTC" };
    document.getElementById("clock").textContent = now.toLocaleTimeString([], { ...opts, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    document.getElementById("dayname").textContent = now.toLocaleDateString([], { ...opts, weekday: "long", day: "numeric", month: "long" });
  }

  function tablets(dose) {
    const colour = dose.colour && dose.colour !== "white" ? dose.colour + " " : "";
    return `${dose.name} · ${colour}tablet`.trim();
  }

  function render() {
    clear(stage);
    document.getElementById("greeting").textContent = `Hello ${state.name}`;
    const due = state.due[0];
    if (due) {
      const button = el("button", { class: "take", type: "button", "aria-label": `Tap when ${due.name} has been taken` },
        el("span", { class: "prompt", text: `${state.name}, it's time for your medicine` }),
        el("span", { class: pillClass(due.colour) }),
        el("span", { class: "med", text: tablets(due) }),
        due.instructions ? el("span", { text: due.instructions }) : null,
        el("span", { class: "cta", text: "Tap when taken" }));
      button.addEventListener("click", () => markTaken(due, button));
      stage.append(button);
      if (lastSpokenKey !== due.key) {
        lastSpokenKey = due.key;
        speak(state.speak);
      }
    } else {
      const next = state.next;
      stage.append(el("div", { class: "rest" },
        svgTick(),
        el("div", { class: "big", text: state.done_today ? "All done for now" : `Hello ${state.name}` }),
        el("div", { class: "dayname", text: next ? `Next medicine at ${next.time}` : "No more medicine today" })));
    }
    document.getElementById("feel").classList.toggle("hidden", Boolean(state.feeling) || Boolean(due));
    renderCalls();
  }

  function svgTick() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 96 96");
    svg.setAttribute("class", "tick");
    svg.setAttribute("aria-hidden", "true");
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", "48"); circle.setAttribute("cy", "48"); circle.setAttribute("r", "42");
    circle.setAttribute("fill", "none"); circle.setAttribute("stroke", "currentColor"); circle.setAttribute("stroke-width", "6");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", "M28 50 l13 13 l27 -29");
    path.setAttribute("fill", "none"); path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "7"); path.setAttribute("stroke-linecap", "round"); path.setAttribute("stroke-linejoin", "round");
    svg.append(circle, path);
    return svg;
  }

  function renderCalls() {
    const box = clear(document.getElementById("calls"));
    box.append(el("a", { class: "btn btn-accent", href: telLink(state.ambulance_phone) }, `Ambulance ${state.ambulance_phone}`));
    for (const person of state.people) {
      box.append(el("a", { class: "btn", href: telLink(person.phone) }, `Call ${person.name}`));
    }
  }

  async function markTaken(dose, button) {
    button.disabled = true;
    try {
      await api(`/api/doses/${encodeURIComponent(dose.key)}/mark`, { method: "POST", body: { status: "given" } });
      speak("Thank you.");
      await load();
    } catch (e) {
      Orbit.toast(e.message);
      button.disabled = false;
    }
  }

  document.getElementById("help").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    document.getElementById("calls").classList.remove("hidden");
    try {
      const result = await api("/api/help", { method: "POST" });
      const names = result.told.length ? result.told.join(", ") : "your family";
      button.textContent = `Help is coming. ${names} told.`;
      speak("Help is coming. Your family has been told.");
    } catch (e) {
      button.textContent = "Could not send. Use the call buttons.";
    } finally {
      setTimeout(() => { button.disabled = false; button.textContent = "Help"; }, 60000);
    }
  });

  for (const button of document.querySelectorAll("[data-feel]")) {
    button.addEventListener("click", async () => {
      try {
        await api("/api/feeling", { method: "POST", body: { value: button.dataset.feel } });
        speak(button.dataset.feel === "good" ? "Good. Thank you." : "Thank you. Your family will know.");
        await load();
      } catch (e) {
        Orbit.toast(e.message);
      }
    });
  }

  async function load() {
    try {
      state = await api("/api/bedside");
      offsetMs = new Date(state.now + "Z").getTime() - Date.now();
      tickClock();
      render();
    } catch (e) {
      clear(stage).append(el("div", { class: "rest" }, el("div", { class: "big", text: "Reconnecting…" })));
    }
  }

  api("/api/me").then((me) => {
    document.getElementById("back").classList.toggle("hidden", me.member.role === "elder");
  }).catch(() => {});

  setVoice(storageGet("orbit_voice") === "1");
  tickClock();
  setInterval(tickClock, 15000);
  load();
  setInterval(load, 30000);
})();
