"use strict";
(() => {
  const { api, el, clear } = Orbit;
  const go = (role) => { window.location.href = role === "elder" ? "/bedside" : "/circle"; };

  // ---------- dialogs ----------
  for (const opener of document.querySelectorAll("[data-open]")) {
    opener.addEventListener("click", () => {
      const dialog = document.getElementById(opener.dataset.open);
      dialog.showModal();
      const first = dialog.querySelector("input");
      if (first) first.focus();
    });
  }
  for (const closer of document.querySelectorAll("[data-close]")) {
    closer.addEventListener("click", () => closer.closest("dialog").close());
  }

  // ---------- sign in ----------
  document.getElementById("signin").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = document.getElementById("login-error");
    error.textContent = "";
    const body = Orbit.formData(event.target);
    body.orbit_code = body.orbit_code.trim().toUpperCase();
    try {
      const result = await api("/api/login", { method: "POST", body, allow401: true });
      go(result.role);
    } catch (e) { error.textContent = e.message; }
  });

  // ---------- start: a calm 3-step flow ----------
  const form = document.getElementById("start");
  const next = document.getElementById("step-next");
  const back = document.getElementById("step-back");
  const error = document.getElementById("start-error");
  let step = 1;
  let created = null;

  function showStep(n) {
    step = n;
    for (const panel of form.querySelectorAll("[data-step]")) panel.classList.toggle("hidden", panel.dataset.step !== String(n));
    form.querySelectorAll(".steps span").forEach((bar, i) => bar.classList.toggle("on", n === "done" || i < n));
    document.getElementById("step-label").textContent = n === "done" ? "Done" : `Step ${n} of 3`;
    back.classList.toggle("hidden", n === 1 || n === "done");
    next.textContent = n === 3 ? "Create the circle" : n === "done" ? "Open the circle" : "Next";
    error.textContent = "";
    const input = form.querySelector(`[data-step="${n}"] input`);
    if (input) input.focus();
  }

  function check(n) {
    if (n === 1 && !form.elder_name.value.trim()) return "Please enter a name.";
    if (n === 2 && !form.your_name.value.trim()) return "Please enter your name.";
    if (n === 2 && form.your_email.value && !form.your_email.checkValidity()) return "That email doesn't look right.";
    if (n === 3 && !/^\d{6,12}$/.test(form.passcode.value)) return "Use 6 to 12 digits.";
    return "";
  }

  back.addEventListener("click", () => showStep(step - 1));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (step === "done") { go(created.role); return; }
    const problem = check(step);
    if (problem) { error.textContent = problem; return; }
    if (step < 3) { showStep(step + 1); return; }
    next.disabled = true;
    try {
      created = await api("/api/orbits", { method: "POST", body: Orbit.formData(form), allow401: true });
      document.getElementById("new-code").textContent = created.orbit_code;
      showStep("done");
    } catch (e) {
      error.textContent = e.message;
    } finally { next.disabled = false; }
  });

  const pinDots = document.getElementById("pin-dots");
  form.passcode.addEventListener("input", () => {
    clear(pinDots);
    const length = Math.max(6, form.passcode.value.length);
    for (let i = 0; i < length; i++) pinDots.append(el("span", { class: i < form.passcode.value.length ? "on" : "" }));
  });
  form.passcode.dispatchEvent(new Event("input"));

  // ---------- sample family ----------
  const labels = {
    wife: "Mary, his wife (family)",
    son: "Arun, his son (family)",
    nurse: "Sister Latha (nurse)",
    doctor: "Dr. Rao (doctor, read-only)",
    bedside: "His bedside screen",
  };

  async function openDemo(event) {
    const button = event.currentTarget;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Setting up Papa's week…";
    try {
      const result = await api("/api/demo", { method: "POST", allow401: true });
      document.getElementById("demo-code").textContent = result.orbit_code;
      const box = clear(document.getElementById("demo-codes"));
      for (const [slot, code] of Object.entries(result.passcodes)) {
        box.append(el("span", { text: labels[slot] }), el("code", { text: code }));
      }
      document.getElementById("demo-dialog").showModal();
    } catch (e) {
      Orbit.toast(e.message);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }
  document.getElementById("try-demo").addEventListener("click", openDemo);
  document.getElementById("try-demo-2").addEventListener("click", openDemo);

  // ---------- day / night preview ----------
  const toggle = document.getElementById("toggle-night");
  toggle.addEventListener("click", () => {
    const night = document.getElementById("preview-tablet").classList.toggle("night");
    toggle.setAttribute("aria-pressed", String(night));
    toggle.textContent = night ? "See it by day" : "See it at night";
    document.getElementById("preview-clock").textContent = night ? "22:00" : "13:00";
  });
  for (const fill of document.querySelectorAll(".preview-fill")) fill.style.width = "18%";
})();
