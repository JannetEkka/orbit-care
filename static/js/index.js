"use strict";
(() => {
  const { api, el, clear } = Orbit;

  function go(role) {
    window.location.href = role === "elder" ? "/bedside" : "/circle";
  }

  document.getElementById("signin").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = document.getElementById("login-error");
    error.textContent = "";
    const body = Orbit.formData(event.target);
    body.orbit_code = body.orbit_code.trim().toUpperCase();
    try {
      const result = await api("/api/login", { method: "POST", body, allow401: true });
      go(result.role);
    } catch (e) {
      error.textContent = e.message;
    }
  });

  document.getElementById("start").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = document.getElementById("start-error");
    error.textContent = "";
    try {
      const result = await api("/api/orbits", { method: "POST", body: Orbit.formData(event.target), allow401: true });
      sessionStorage.setItem("orbit_new_code", result.orbit_code);
      go(result.role);
    } catch (e) {
      error.textContent = e.message;
    }
  });

  const labels = {
    wife: "Mary, his wife (family)",
    son: "Arun, his son (family)",
    nurse: "Sister Latha (nurse)",
    doctor: "Dr. Rao (doctor, read-only)",
    bedside: "His bedside screen",
  };

  document.getElementById("try-demo").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const box = document.getElementById("demo-result");
    button.disabled = true;
    button.textContent = "Setting up…";
    try {
      const result = await api("/api/demo", { method: "POST", allow401: true });
      clear(box).classList.remove("hidden");
      const rows = Object.entries(result.passcodes).map(([slot, code]) => [
        el("span", { text: labels[slot] }),
        el("code", { text: code }),
        el("span"),
      ]);
      box.append(
        el("h2", { text: "Your sample family is ready" }),
        el("p", {}, "You are signed in as Mary. Orbit code ", el("code", { text: result.orbit_code }),
          ". To see another person's view, sign in with their passcode:"),
        el("div", { class: "codes" }, rows.flat()),
        el("div", { class: "form-actions" },
          el("a", { class: "btn btn-primary", href: "/circle" }, "Open Mary's view"),
          el("a", { class: "btn", href: "/bedside" }, "See his bedside screen")),
      );
      sessionStorage.setItem("orbit_demo_codes", JSON.stringify({ code: result.orbit_code, passcodes: result.passcodes }));
      box.focus();
    } catch (e) {
      clear(box).classList.remove("hidden");
      box.append(el("p", { class: "error", text: e.message }));
    } finally {
      button.disabled = false;
      button.textContent = "Open a sample family";
    }
  });
})();
