"use strict";
// The bedside screen: one thing at a time, no reading needed, speaks when a dose is due.
(() => {
  const { api, el, clear, telLink } = Orbit;
  const stage = document.getElementById("stage");
  const soundButton = document.getElementById("sound");
  const HOLD_MS = 2000;
  const PILL_COLOURS = {
    white: ["#ffffff", "#c9c4ba"], yellow: ["#f6d36b", "#c9a23c"], pink: ["#f3a6c2", "#c97a96"],
    blue: ["#8cb8f0", "#5a86c0"], green: ["#8fd19e", "#5fa06f"], orange: ["#f5a65b", "#c47a33"],
  };
  let state = null;
  let voiceOn = false;
  let lastSpokenKey = "";
  let offsetMs = 0;
  let justDone = false;

  const storageGet = (key) => { try { return localStorage.getItem(key); } catch (_) { return null; } };
  const storageSet = (key, value) => { try { localStorage.setItem(key, value); } catch (_) { /* private mode */ } };

  // ---------- sound, voice, touch feedback ----------
  let audio = null;
  function chime() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const now = audio.currentTime;
      [523.25, 659.25, 783.99].forEach((freq, i) => {
        const osc = audio.createOscillator();
        const gain = audio.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, now + i * 0.12);
        gain.gain.exponentialRampToValueAtTime(0.18, now + i * 0.12 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.12 + 0.6);
        osc.connect(gain).connect(audio.destination);
        osc.start(now + i * 0.12);
        osc.stop(now + i * 0.12 + 0.65);
      });
    } catch (_) { /* no audio */ }
  }
  const buzz = (pattern) => { if (navigator.vibrate) navigator.vibrate(pattern); };

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
    if (voiceOn) speak(currentSentence() || "Voice is on.");
  });
  document.getElementById("repeat").addEventListener("click", () => {
    const wasOn = voiceOn;
    voiceOn = true;
    speak(currentSentence() || `Hello ${state ? state.name : ""}.`);
    voiceOn = wasOn;
  });

  function currentSentence() {
    if (!state) return "";
    if (state.due.length) return `${state.name}, it is time for your medicine. ${tabletWords(state.due[0])}. Tap the screen when you have taken it.`;
    return state.next ? `All done for now. Your next medicine is at ${state.next.time}.` : "All done for today.";
  }
  const tabletWords = (dose) => `${dose.name}, the ${dose.colour && dose.colour !== "white" ? dose.colour : "white"} tablet`;

  // ---------- clock in his own time zone ----------
  function tickClock() {
    const now = new Date(Date.now() + offsetMs);
    const opts = { timeZone: "UTC" };
    document.getElementById("clock").textContent = now.toLocaleTimeString([], { ...opts, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    document.getElementById("dayname").textContent = now.toLocaleDateString([], { ...opts, weekday: "long", day: "numeric", month: "long" });
  }

  // ---------- drawing ----------
  function svg(tag, attrs, ...children) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    node.append(...children);
    return node;
  }

  function pillSvg(colour) {
    const [fill, edge] = PILL_COLOURS[colour] || PILL_COLOURS.white;
    return svg("svg", { viewBox: "0 0 120 80", class: "pill-svg", "aria-hidden": "true" },
      svg("ellipse", { cx: "60", cy: "40", rx: "54", ry: "34", fill, stroke: "#fff", "stroke-width": "5" }),
      svg("path", { d: "M34 40h52", stroke: edge, "stroke-width": "5", "stroke-linecap": "round" }),
      svg("ellipse", { cx: "42", cy: "26", rx: "14", ry: "6", fill: "#fff", opacity: ".45" }));
  }

  function tickSvg() {
    return svg("svg", { viewBox: "0 0 96 96", class: "tick", "aria-hidden": "true" },
      svg("circle", { cx: "48", cy: "48", r: "42", fill: "none", stroke: "currentColor", "stroke-width": "6" }),
      svg("path", { d: "M28 50 l13 13 l27 -29", fill: "none", stroke: "currentColor", "stroke-width": "7", "stroke-linecap": "round", "stroke-linejoin": "round" }));
  }

  function circleWords() {
    const names = (state && state.circle) || [];
    if (!names.length) return "Your family can see it.";
    if (names.length === 1) return `${names[0]} can see it.`;
    return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]} can see it.`;
  }

  function render() {
    clear(stage);
    document.getElementById("main").classList.toggle("night", Boolean(state.night));
    document.getElementById("greeting").textContent = `Hello ${state.name}`;
    const due = state.due[0];
    if (due) {
      const button = el("button", { class: "take", type: "button", "aria-label": `${tabletWords(due)}. Tap when taken.` },
        el("span", { class: "ripple" }),
        el("span", { class: "prompt", text: `${state.name}, it's time for your medicine` }),
        pillSvg(due.colour),
        el("span", { class: "med", text: `${due.name}` }),
        el("span", { class: "how", text: [due.dose, due.instructions].filter(Boolean).join(" · ") }),
        el("span", { class: "cta", text: "Tap when taken" }));
      button.addEventListener("click", (event) => markTaken(due, button, event));
      stage.append(button);
      if (lastSpokenKey !== due.key) {
        lastSpokenKey = due.key;
        chime();
        speak(currentSentence());
      }
    } else {
      const rest = el("div", { class: justDone ? "rest just-done" : "rest" },
        tickSvg(),
        el("div", { class: "big", text: justDone ? "Done. Thank you." : state.done_today ? "All done for now" : `Hello ${state.name}` }),
        el("div", { class: "sub", text: justDone ? circleWords() : state.next ? `Next medicine at ${state.next.time}` : "No more medicine today" }));
      stage.append(rest);
      justDone = false;
    }
    document.getElementById("feel").classList.toggle("hidden", Boolean(state.feeling) || Boolean(due));
    renderCalls();
  }

  function renderCalls() {
    const box = clear(document.getElementById("calls"));
    box.append(el("a", { class: "btn btn-terra", href: telLink(state.ambulance_phone) }, `🚑 Ambulance ${state.ambulance_phone}`));
    for (const person of state.people) box.append(el("a", { class: "btn", href: telLink(person.phone) }, `📞 ${person.name}`));
  }

  async function markTaken(dose, button, event) {
    button.disabled = true;
    const ripple = button.querySelector(".ripple");
    const rect = button.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 2.2;
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${(event.clientX || rect.left + rect.width / 2) - rect.left - size / 2}px`;
    ripple.style.top = `${(event.clientY || rect.top + rect.height / 2) - rect.top - size / 2}px`;
    button.classList.add("done");
    buzz(60);
    chime();
    try {
      await api(`/api/doses/${encodeURIComponent(dose.key)}/mark`, { method: "POST", body: { status: "given" } });
      speak(`Thank you. ${circleWords()}`);
      justDone = true;
      setTimeout(load, 700);
    } catch (e) {
      Orbit.toast(e.message);
      button.classList.remove("done");
      button.disabled = false;
    }
  }

  // ---------- Help: hold for two seconds, so a brushing hand never raises an alarm ----------
  const help = document.getElementById("help");
  const helpText = document.getElementById("help-text");
  let holdTimer = null;
  let tickTimer = null;
  function startHold(event) {
    if (help.disabled || holdTimer) return;
    if (event.type === "pointerdown") help.setPointerCapture(event.pointerId);
    help.classList.add("holding");
    helpText.textContent = "Keep holding…";
    buzz(30);
    let left = 2;
    tickTimer = setInterval(() => { buzz(25); left -= 0.5; if (left > 0) helpText.textContent = `Keep holding… ${Math.ceil(left)}`; }, 500);
    holdTimer = setTimeout(sendHelp, HOLD_MS);
  }
  function cancelHold() {
    clearInterval(tickTimer);
    if (!holdTimer) return;
    clearTimeout(holdTimer);
    holdTimer = null;
    help.classList.remove("holding");
    helpText.textContent = "Hold for Help";
  }
  help.addEventListener("pointerdown", startHold);
  for (const type of ["pointerup", "pointercancel", "pointerleave"]) help.addEventListener(type, cancelHold);
  help.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); sendHelp(); } });
  help.addEventListener("contextmenu", (event) => event.preventDefault());

  async function sendHelp() {
    clearInterval(tickTimer);
    holdTimer = null;
    help.classList.remove("holding");
    help.disabled = true;
    document.getElementById("calls").classList.remove("hidden");
    buzz([80, 60, 80]);
    try {
      const result = await api("/api/help", { method: "POST" });
      help.classList.add("sent");
      helpText.textContent = `Help is coming. ${result.told.length ? result.told.map((n) => n.split(" (")[0]).join(", ") : "Your family"} told.`;
      speak("Help is coming. Your family has been told.");
    } catch (e) {
      helpText.textContent = "Could not send. Use the call buttons below.";
    }
    setTimeout(() => { help.disabled = false; help.classList.remove("sent"); helpText.textContent = "Hold for Help"; }, 60000);
  }

  // ---------- how are you feeling ----------
  for (const button of document.querySelectorAll("[data-feel]")) {
    button.addEventListener("click", async () => {
      try {
        await api("/api/feeling", { method: "POST", body: { value: button.dataset.feel } });
        buzz(40);
        speak(button.dataset.feel === "good" ? "Good. Thank you." : "Thank you. Your family will know.");
        await load();
      } catch (e) { Orbit.toast(e.message); }
    });
  }

  // ---------- connection ----------
  const conn = document.getElementById("conn");
  function setConnected(ok) {
    conn.classList.toggle("off", !ok);
    conn.textContent = ok ? "Connected to family" : "Offline · will try again";
  }
  window.addEventListener("offline", () => setConnected(false));
  window.addEventListener("online", load);

  async function load() {
    try {
      state = await api("/api/bedside");
      offsetMs = new Date(state.now + "Z").getTime() - Date.now();
      setConnected(true);
      tickClock();
      render();
    } catch (e) {
      setConnected(false);
      if (!state) clear(stage).append(el("div", { class: "rest" }, el("div", { class: "big", text: "Connecting…" })));
    }
  }

  api("/api/me").then((me) => {
    const back = document.getElementById("back");
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem("orbit_demo_codes") || "null"); } catch (_) { saved = null; }
    if (me.member.role === "elder" && me.demo && saved && saved.code === me.orbit_code) {
      back.textContent = "Back to the sample";
      back.addEventListener("click", async (event) => {
        event.preventDefault();
        await api("/api/login", { method: "POST", body: { orbit_code: saved.code, passcode: saved.passcodes.wife } });
        window.location.href = "/circle";
      });
    } else {
      back.classList.toggle("hidden", me.member.role === "elder");
    }
  }).catch(() => {});

  // ---------- keep the screen awake on its stand ----------
  let wakeLock = null;
  async function keepAwake() {
    try {
      if ("wakeLock" in navigator && document.visibilityState === "visible") wakeLock = await navigator.wakeLock.request("screen");
    } catch (_) { wakeLock = null; }
    document.getElementById("awake").classList.toggle("hidden", Boolean(wakeLock));
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") keepAwake(); });
  document.addEventListener("pointerdown", () => { if (!wakeLock) keepAwake(); }, { once: true });
  keepAwake();

  setVoice(storageGet("orbit_voice") === "1");
  tickClock();
  setInterval(tickClock, 15000);
  load();
  setInterval(load, 30000);
})();
