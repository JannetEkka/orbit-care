// Shared helpers. Every value from the server is inserted with textContent, never as HTML.
"use strict";

const Orbit = (() => {
  async function api(path, options = {}) {
    const init = { method: options.method || "GET", headers: { "x-orbit": "1" }, credentials: "same-origin" };
    if (options.body !== undefined) {
      init.headers["content-type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch (_) {
      throw new Error("No connection. Please check the internet and try again.");
    }
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      if (response.status === 401 && !options.allow401) {
        window.location.href = "/";
      }
      const detail = data && data.detail;
      const message = Array.isArray(detail)
        ? detail.map((d) => d.msg || "Invalid value").join(" ")
        : (detail || "Something went wrong. Please try again.");
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  // el("div", {class: "x", onclick: fn}, "text", child)
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  let toastTimer;
  function toast(message) {
    let node = document.getElementById("toast");
    if (!node) {
      node = el("div", { id: "toast", class: "toast", role: "status", "aria-live": "polite" });
      document.body.append(node);
    }
    node.textContent = message;
    node.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.add("hidden"), 3500);
  }

  function formData(form) {
    const out = {};
    for (const field of form.elements) {
      if (!field.name || field.disabled) continue;
      if (field.type === "checkbox") {
        if (field.dataset.list) {
          out[field.name] = out[field.name] || [];
          if (field.checked) out[field.name].push(field.value);
        } else out[field.name] = field.checked;
      } else if (field.type === "number") {
        out[field.name] = field.value === "" ? null : Number(field.value);
      } else out[field.name] = field.value;
    }
    return out;
  }

  function telLink(phone) { return "tel:" + String(phone).replace(/[^0-9+]/g, ""); }

  function fmtTime(iso) {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  }

  const pillClass = (colour) => "pill-dot pill-" + (colour || "white");

  return { api, el, clear, toast, formData, telLink, fmtTime, pillClass };
})();
