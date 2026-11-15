"use strict";
// The care circle: family, nurse (caretaker) and doctor. What each sees depends on their role.
(() => {
  const { api, el, clear, toast, formData, telLink, fmtTime, pillClass, avatar } = Orbit;
  const TAGS = ["tremor", "confusion", "fall", "sleepy", "nausea", "pain", "not_eating", "calm"];
  const COLOURS = ["white", "yellow", "pink", "blue", "green", "orange"];
  const ROLE_NAMES = { family: "Family", caretaker: "Nurse / caretaker", doctor: "Doctor (read-only)", elder: "Bedside screen" };
  const STATE_TEXT = { given: "given", skipped: "skipped", missed: "not given", due: "due now", upcoming: "later" };
  const PARTS = [["morning", 5, 12], ["afternoon", 12, 17], ["evening", 17, 21], ["night", 21, 29]];
  const partOf = (hhmm) => { const h = Number(hhmm.slice(0, 2)); const hour = h < 5 ? h + 24 : h; return PARTS.find(([, a, b]) => hour >= a && hour < b)[0]; };
  const who = () => (today && today.about && today.about.address_as) || (today && today.elder_name) || (me && me.elder_name) || "them";
  const memberById = (id) => (today && today.members.find((m) => m.id === id)) || null;
  const PHARMACIES = [
    ["Tata 1mg", (n) => `https://www.1mg.com/search/all?name=${encodeURIComponent(n)}`],
    ["PharmEasy", (n) => `https://pharmeasy.in/search/all?name=${encodeURIComponent(n)}`],
    ["Apollo Pharmacy", (n) => `https://www.apollopharmacy.in/search-medicines/${encodeURIComponent(n)}`],
  ];
  let me = null;
  let today = null;
  const label = (tag) => tag.replace("_", " ");
  const canEdit = () => me && (me.member.role === "family" || me.member.role === "caretaker");
  const isFamily = () => me && me.member.role === "family";
  const memberName = (id) => ((today && today.members.find((m) => m.id === id)) || {}).name || "anyone";

  // ---------- tabs ----------
  const TABS = [
    ["today", "Today", () => true],
    ["medicines", "Medicines", () => true],
    ["visits", "Visits", () => true],
    ["notes", "Care notes", () => true],
    ["summary", "Summary", () => true],
    ["people", "People & settings", isFamily],
    ["emails", "Emails", isFamily],
    ["history", "History", isFamily],
  ];
  const LOADERS = {
    today: loadToday, medicines: loadMedicines, visits: loadVisits, notes: loadNotes,
    summary: () => loadSummary(14), people: loadPeople, emails: loadEmails, history: loadHistory,
  };

  function buildTabs() {
    const nav = clear(document.getElementById("tabs"));
    for (const [id, name, visible] of TABS) {
      if (!visible()) continue;
      const button = el("button", { type: "button", role: "tab", id: `t-${id}`, "aria-controls": `tab-${id}`, "aria-selected": "false", text: name });
      button.addEventListener("click", () => showTab(id));
      button.addEventListener("keydown", (event) => {
        const tabs = [...nav.querySelectorAll("[role=tab]")];
        const index = tabs.indexOf(button);
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          const next = tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
          next.focus();
          next.click();
        }
      });
      nav.append(button);
    }
  }

  function showTab(id) {
    for (const [tabId] of TABS) {
      const panel = document.getElementById(`tab-${tabId}`);
      const tab = document.getElementById(`t-${tabId}`);
      panel.classList.toggle("hidden", tabId !== id);
      if (tab) { tab.setAttribute("aria-selected", String(tabId === id)); tab.tabIndex = tabId === id ? 0 : -1; }
    }
    try { sessionStorage.setItem("orbit_tab", id); } catch (_) { /* ignore */ }
    LOADERS[id]().catch((e) => toast(e.message));
  }

  // ---------- today ----------
  async function loadToday() {
    const pick = document.getElementById("day-pick");
    const query = pick.value ? `?day=${pick.value}` : "";
    today = await api(`/api/today${query}`);
    if (!pick.value) pick.value = today.date;
    document.getElementById("today-title").textContent = today.is_today ? "Today's doses" : `Doses on ${today.date}`;
    renderDoses();
    renderAlerts();
    renderShortcuts();
    renderAbout();
  }

  function emptyState(text, buttonText, onClick) {
    const box = el("div", { class: "empty" }, el("div", { class: "serif", text: "🌿" }), el("p", { text }));
    if (buttonText && canEdit()) box.append(el("button", { type: "button", class: "btn btn-primary", onclick: onClick }, buttonText));
    return box;
  }

  function renderGreeting() {
    const a = today.about || {};
    const name = a.address_as || today.elder_name;
    const total = today.doses.length;
    const given = today.doses.filter((d) => d.state === "given").length;
    const open = today.doses.filter((d) => d.state === "due" || d.state === "missed").length;
    document.getElementById("greet-title").textContent = today.is_today ? `${name}'s day` : `${name} on ${today.date}`;
    const line = clear(document.getElementById("greet-line"));
    line.append(el("span", { class: "chip given", text: `${given} of ${total} doses given` }));
    if (open) line.append(el("span", { class: "chip missed", text: `${open} need${open === 1 ? "s" : ""} someone` }));
    if (today.feeling) line.append(el("span", { class: today.feeling === "good" ? "chip given" : "chip missed", text: today.feeling === "good" ? `${who()} said: feeling good` : `${who()} said: not feeling good` }));
  }

  function renderDoses() {
    renderGreeting();
    const box = clear(document.getElementById("doses"));
    if (!today.doses.length) {
      box.append(emptyState(`No medicines yet. Add ${(today.about || {}).address_as || today.elder_name}'s first medicine to start the circle.`, "Add a medicine", () => { showTab("medicines"); medicineDialog(null); }));
      return;
    }
    for (const [part] of PARTS) {
      const doses = today.doses.filter((d) => partOf(d.time) === part);
      if (!doses.length) continue;
      const block = el("div", { class: "block" }, el("div", { class: "block-head", text: part }));
      for (const dose of doses) block.append(doseRow(dose));
      box.append(block);
    }
  }

  function doseRow(dose) {
    const acts = el("div", { class: "acts" });
    const markable = canEdit() && today.is_today !== false && dose.state !== "upcoming";
    if (markable && dose.state !== "given") acts.append(el("button", { type: "button", class: "btn btn-sage btn-sm", onclick: () => mark(dose, "given") }, "✓ Given"));
    if (markable && dose.state !== "skipped" && dose.state !== "given") acts.append(el("button", { type: "button", class: "btn btn-sm", onclick: () => mark(dose, "skipped") }, "Skipped"));
    const giver = memberById(dose.giver_id);
    const whoName = dose.by_name || (giver ? giver.name : "Family");
    const whoText = dose.by_name ? `${STATE_TEXT[dose.state]} by ${dose.by_name}` : `${giver ? giver.name : "anyone in the family"} gives it`;
    return el("div", { class: `dose state-${dose.state}`, id: `dose-${dose.key}` },
      el("div", { class: "time", text: dose.time }),
      el("div", {},
        el("div", { class: "what" }, el("span", { class: pillClass(dose.colour), "aria-hidden": "true" }),
          el("strong", { text: dose.name }), el("span", { class: "muted", text: dose.dose })),
        el("div", { class: "meta" }, avatar(whoName, dose.by_name || dose.giver_id),
          el("span", { class: `chip ${dose.state}`, text: STATE_TEXT[dose.state] }),
          el("span", { text: whoText + (dose.reason ? ` · ${dose.reason}` : "") }))),
      acts);
  }

  async function mark(dose, status) {
    let reason = "";
    if (status === "skipped") reason = window.prompt(`Why was ${dose.name} at ${dose.time} skipped? (optional)`, "") || "";
    try {
      await api(`/api/doses/${encodeURIComponent(dose.key)}/mark`, { method: "POST", body: { status, reason: reason.slice(0, 120) } });
      if (navigator.vibrate) navigator.vibrate(30);
      await loadToday();
      const row = document.getElementById(`dose-${dose.key}`);
      if (row) { row.classList.add("flash"); setTimeout(() => row.classList.remove("flash"), 1200); }
      toast(`${dose.name} at ${dose.time} marked ${status}.`, {
        action: "Undo",
        ms: 10000,
        onAction: async () => {
          try {
            await api(`/api/doses/${encodeURIComponent(dose.key)}/mark`, { method: "DELETE" });
            toast("Undone.");
            await loadToday();
          } catch (e) { toast(e.message); }
        },
      });
    } catch (e) { toast(e.message); }
  }

  function alertItem(icon, tone, title, detail, extra) {
    return el("div", { class: "alert-item" },
      el("span", { class: `ico ${tone}`, "aria-hidden": "true", text: icon }),
      el("div", {}, el("strong", { text: title }), detail ? el("div", { class: "small muted", text: detail }) : null, extra || null));
  }

  function supplyBar(daysLeft, warnDays) {
    const pct = Math.max(4, Math.min(100, Math.round((daysLeft / (warnDays * 4)) * 100)));
    const fill = el("div", { class: daysLeft <= 2 ? "fill out" : daysLeft <= warnDays ? "fill low" : "fill" });
    fill.style.width = `${pct}%`;
    return el("div", { class: "supply", role: "img", "aria-label": `About ${daysLeft} days of tablets left` }, el("div", { class: "track" }, fill));
  }

  function renderAlerts() {
    const box = clear(document.getElementById("alerts"));
    box.append(el("h2", { text: "Needs attention" }));
    const items = [];
    for (const dose of today.doses.filter((d) => d.state === "missed" || d.state === "due")) {
      items.push(alertItem("!", "", `${dose.time} ${dose.name} ${STATE_TEXT[dose.state]}`, `${(memberById(dose.giver_id) || {}).name || "Anyone in the family"} gives it`));
    }
    if (today.feeling === "not_good") items.push(alertItem("☹", "amber", `${who()} said they don't feel good today`, "Consider a call or a care note."));
    const warn = (today.settings && today.settings.refill_warn_days) || 5;
    for (const w of today.refill) items.push(alertItem("💊", "amber", `${w.name}: about ${w.days_left} days left`, `${w.stock} tablets in hand`, supplyBar(w.days_left, warn)));
    for (const c of today.checkups) {
      items.push(alertItem("🩺", "amber", `${c.doctor}: checkup ${c.overdue ? "overdue" : "due"} ${c.next_due}`, "Nothing is booked yet.",
        c.clinic_phone ? el("a", { class: "small", href: telLink(c.clinic_phone) }, "Call the clinic to book") : null));
    }
    if (!items.length) box.append(alertItem("✓", "sage", "All calm right now", "Nothing needs anyone at the moment."));
    else box.append(...items);
    if (today.upcoming_appointments.length) {
      box.append(el("h3", { class: "block", text: "Coming up" }));
      for (const a of today.upcoming_appointments) {
        const goer = memberById(a.accompany_id);
        box.append(alertItem("📅", "sage", a.doctor, `${fmtTime(a.when)}${goer ? ` · ${goer.name} goes along` : " · nobody assigned to go yet"}`));
      }
    }
  }

  function renderShortcuts() {
    const c = today.contacts || {};
    const help = clear(document.getElementById("help-shortcuts"));
    help.append(el("a", { class: "btn btn-accent", href: telLink(c.ambulance_phone || "108") }, `Ambulance ${c.ambulance_phone || "108"}`));
    help.append(el("a", { class: "btn", href: telLink("112") }, "Emergency 112"));
    if (c.hospital_phone) help.append(el("a", { class: "btn", href: telLink(c.hospital_phone) }, `Call ${c.hospital_name || "hospital"}`));
    if (c.doctor_phone) help.append(el("a", { class: "btn", href: telLink(c.doctor_phone) }, `Call ${c.doctor_name || "doctor"}`));
    help.append(el("a", { class: "btn", href: "https://www.google.com/maps/search/hospital+near+me", target: "_blank", rel: "noopener" }, "Hospitals near you (map)"));
    if (canEdit()) help.append(el("button", { type: "button", onclick: () => showTab("summary") }, "Ask the doctor for a call or visit"));
    for (const person of today.members.filter((m) => m.phone && m.role !== "elder")) {
      help.append(el("a", { class: "btn", href: telLink(person.phone) }, `Call ${person.name}`));
    }

    const buy = clear(document.getElementById("buy-shortcuts"));
    if (c.chemist_phone) buy.append(el("a", { class: "btn btn-primary", href: telLink(c.chemist_phone) }, `Call ${c.chemist_name || "your chemist"}`));
    buy.append(el("a", { class: "btn", href: "https://www.google.com/maps/search/pharmacy+near+me", target: "_blank", rel: "noopener" }, "Pharmacies near you (map)"));
    const low = today.refill.map((w) => w.name);
    const names = low.length ? low : [...new Set(today.doses.map((d) => d.name))].slice(0, 2);
    for (const name of names) {
      const links = el("div", { class: "row" });
      for (const [shop, url] of PHARMACIES) links.append(el("a", { class: "btn btn-sm", href: url(name), target: "_blank", rel: "noopener" }, shop));
      buy.append(el("details", { class: "order" }, el("summary", { text: `Order ${name}` }), links));
    }
    if (!c.chemist_phone && isFamily()) buy.append(el("p", { class: "muted small", text: "Save your chemist's number under People & settings for a one-tap call." }));
  }

  function renderAbout() {
    const box = clear(document.getElementById("about-card"));
    const a = today.about || {};
    box.append(el("h2", { text: `About ${a.address_as || today.elder_name}` }));
    if (!a.likes && !a.calms && !a.notes) {
      box.append(el("p", { class: "muted", text: "Tell every new nurse who they are: what they like and what calms them. Add it under People & settings." }));
      return;
    }
    const rows = [["Likes", a.likes], ["What calms them", a.calms], ["Good to know", a.notes]].filter(([, v]) => v);
    box.append(el("dl", {}, rows.flatMap(([k, v]) => [el("dt", {}, el("strong", { text: k })), el("dd", { text: v })])));
  }

  // ---------- notes ----------
  function buildTagPicker() {
    const box = clear(document.getElementById("tagpick"));
    for (const tag of TAGS) {
      box.append(el("label", {}, el("input", { type: "checkbox", name: "tags", value: tag, "data-list": "1" }), el("span", { text: label(tag) })));
    }
  }

  document.getElementById("note-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const note = await api("/api/notes", { method: "POST", body: formData(event.target) });
      event.target.reset();
      toast(`Note saved${note.tags.length ? ": " + note.tags.map(label).join(", ") : ""}.`);
    } catch (e) { toast(e.message); }
  });

  async function loadNotes() {
    const notes = await api("/api/notes");
    const box = clear(document.getElementById("note-list"));
    if (!notes.length) { box.append(emptyState("No care notes yet. A one-tap note about tremor, sleep or a fall helps the doctor see patterns.")); return; }
    for (const note of notes) {
      box.append(el("div", { class: "item" },
        el("div", { class: "spread" }, el("strong", { text: fmtTime(note.at) }), el("span", { class: "muted small", text: note.by_name })),
        el("div", { class: "row" }, note.tags.map((t) => el("span", { class: "chip", text: label(t) }))),
        note.text ? el("p", { text: note.text }) : null));
    }
  }

  // ---------- medicines ----------
  async function loadMedicines() {
    if (!today) today = await api("/api/today");
    const meds = await api("/api/medicines");
    document.getElementById("add-med").classList.toggle("hidden", !canEdit());
    const box = clear(document.getElementById("med-list"));
    if (!meds.length) box.append(emptyState("No medicines yet. Add the first one, with who gives it and when.", "Add a medicine", () => medicineDialog(null)));
    for (const med of meds) {
      const slots = med.slots.map((s) => `${s.time} (${memberName(s.giver_id)})`).join(", ");
      const stock = med.stock === null || med.stock === undefined ? "stock not tracked" : `${med.stock} left · about ${med.days_left} days`;
      const actions = canEdit() && med.active ? el("div", { class: "row" },
        el("button", { type: "button", onclick: () => medicineDialog(med) }, "Edit"),
        el("button", { type: "button", onclick: () => stopMedicine(med) }, "Stop")) : null;
      box.append(el("div", { class: "item" },
        el("div", { class: "spread" },
          el("div", { class: "what row" }, el("span", { class: pillClass(med.colour), "aria-hidden": "true" }),
            el("strong", { text: med.name }), el("span", { class: "muted", text: med.dose }),
            med.active ? null : el("span", { class: "chip skipped", text: `stopped ${med.end_date}` })),
          actions),
        el("div", { class: "small muted", text: `${slots} · ${stock}` }),
        med.active && med.days_left !== null && med.days_left !== undefined ? supplyBar(med.days_left, (today.settings && today.settings.refill_warn_days) || 5) : null,
        med.instructions ? el("div", { class: "small", text: med.instructions }) : null));
    }
  }

  function memberOptions(selected, roles) {
    const options = [el("option", { value: "" }, "Anyone in the family")];
    for (const m of today.members.filter((p) => roles.includes(p.role))) {
      options.push(el("option", { value: m.id, selected: m.id === selected }, m.name));
    }
    return options;
  }

  function field(id, text, input) { input.id = id; return [el("label", { for: id, text }), input]; }

  function medicineDialog(med) {
    const m = med || { name: "", dose: "", instructions: "", slots: [{ time: "08:00", giver_id: null }], stock: null, per_dose: 1, colour: "white" };
    const slotBox = el("div", { id: "slots" });
    const addSlot = (slot) => {
      const index = slotBox.children.length;
      slotBox.append(el("fieldset", {},
        el("legend", { text: `Time ${index + 1}` }),
        ...field(`slot-time-${index}`, "Time", el("input", { type: "time", name: "slot_time", value: slot.time, required: true })),
        ...field(`slot-giver-${index}`, "Who gives it", el("select", { name: "slot_giver" }, memberOptions(slot.giver_id, ["family", "caretaker"])))));
    };
    m.slots.forEach(addSlot);
    openDialog(med ? `Edit ${med.name}` : "Add medicine", [
      ...field("med-name", "Medicine name", el("input", { name: "name", value: m.name, maxlength: 80, required: true })),
      ...field("med-dose", "Dose (e.g. 5 mg)", el("input", { name: "dose", value: m.dose, maxlength: 120 })),
      ...field("med-inst", "How to give it", el("input", { name: "instructions", value: m.instructions, maxlength: 120, placeholder: "e.g. after food" })),
      ...field("med-colour", "Tablet colour (shown on the bedside screen)", el("select", { name: "colour" }, COLOURS.map((c) => el("option", { value: c, selected: c === m.colour }, c)))),
      slotBox,
      el("button", { type: "button", onclick: () => addSlot({ time: "20:00", giver_id: null }) }, "Add another time"),
      ...field("med-stock", "Tablets in hand (for refill alerts)", el("input", { type: "number", name: "stock", min: 0, max: 10000, value: m.stock ?? "" })),
      ...field("med-per", "Tablets per dose", el("input", { type: "number", name: "per_dose", min: 1, max: 20, value: m.per_dose || 1 })),
    ], async (form) => {
      const data = formData(form);
      const times = [...form.querySelectorAll("[name=slot_time]")].map((i) => i.value);
      const givers = [...form.querySelectorAll("[name=slot_giver]")].map((s) => s.value || null);
      const body = {
        name: data.name, dose: data.dose, instructions: data.instructions, colour: data.colour,
        stock: data.stock, per_dose: data.per_dose || 1, active: true,
        slots: times.filter(Boolean).map((time, i) => ({ time, giver_id: givers[i] })),
      };
      if (med) await api(`/api/medicines/${med.id}`, { method: "PUT", body });
      else await api("/api/medicines", { method: "POST", body });
      toast("Medicine saved.");
      await loadMedicines();
    });
  }

  async function stopMedicine(med) {
    if (!window.confirm(`Stop ${med.name} from today? Its history is kept.`)) return;
    try { await api(`/api/medicines/${med.id}`, { method: "DELETE" }); toast(`${med.name} stopped.`); await loadMedicines(); }
    catch (e) { toast(e.message); }
  }
  document.getElementById("add-med").addEventListener("click", () => medicineDialog(null));

  // ---------- visits ----------
  async function loadVisits() {
    if (!today) today = await api("/api/today");
    const appts = await api("/api/appointments");
    document.getElementById("add-appt").classList.toggle("hidden", !canEdit());
    const box = clear(document.getElementById("appt-list"));
    for (const checkup of today.checkups) {
      box.append(el("p", { class: "notice" }, `${checkup.doctor}: regular checkup ${checkup.overdue ? "overdue since" : "due"} ${checkup.next_due}. Nothing is booked.`));
    }
    if (!appts.length) box.append(emptyState("No visits yet. Add the next doctor's visit, and who goes along.", "Add a visit", () => visitDialog(null)));
    const nowIso = today.now;
    for (const appt of appts.slice().reverse()) {
      const past = appt.when < nowIso;
      box.append(el("div", { class: "item" },
        el("div", { class: "spread" },
          el("strong", { text: `${fmtTime(appt.when)} · ${appt.doctor}` }),
          canEdit() ? el("div", { class: "row" },
            el("button", { type: "button", onclick: () => visitDialog(appt) }, "Edit"),
            el("button", { type: "button", onclick: () => deleteVisit(appt) }, "Remove")) : null),
        el("div", { class: "small muted" },
          past ? "Past visit" : "Coming up",
          appt.purpose ? ` · ${appt.purpose}` : "",
          appt.accompany_id ? ` · going along: ${memberName(appt.accompany_id)}` : " · nobody assigned to go along",
          appt.repeat_days ? ` · repeats every ${appt.repeat_days} days` : ""),
        el("div", { class: "row small" },
          appt.clinic_phone ? el("a", { href: telLink(appt.clinic_phone) }, `Call clinic ${appt.clinic_phone}`) : null,
          past ? null : el("a", { href: calendarLink(appt), target: "_blank", rel: "noopener" }, "Add to Google Calendar"))));
    }
  }

  function calendarLink(appt) {
    // Times are the elder's local time; Google Calendar reads them in the given time zone.
    const start = appt.when.slice(0, 16).replace(/[-:]/g, "") + "00";
    const endDate = new Date(appt.when.slice(0, 16) + ":00Z");
    endDate.setUTCHours(endDate.getUTCHours() + 1);
    const end = endDate.toISOString().slice(0, 16).replace(/[-:]/g, "") + "00";
    const params = new URLSearchParams({
      action: "TEMPLATE",
      text: `${today.elder_name}: ${appt.doctor}`,
      dates: `${start}/${end}`,
      ctz: (today.settings && today.settings.timezone) || "Asia/Kolkata",
      details: [appt.purpose, appt.accompany_id ? `Going along: ${memberName(appt.accompany_id)}` : ""].filter(Boolean).join("\n"),
    });
    return `https://calendar.google.com/calendar/render?${params}`;
  }

  function visitDialog(appt) {
    const a = appt || { doctor: "", purpose: "", when: "", clinic_phone: "", accompany_id: null, repeat_days: null };
    openDialog(appt ? "Edit visit" : "Add a doctor visit", [
      ...field("ap-doc", "Doctor", el("input", { name: "doctor", value: a.doctor, maxlength: 80, required: true })),
      ...field("ap-when", "Date and time", el("input", { type: "datetime-local", name: "when", value: a.when ? a.when.slice(0, 16) : "", required: true })),
      ...field("ap-purpose", "For", el("input", { name: "purpose", value: a.purpose, maxlength: 120 })),
      ...field("ap-phone", "Clinic phone", el("input", { type: "tel", name: "clinic_phone", value: a.clinic_phone, maxlength: 20 })),
      ...field("ap-with", "Who goes along", el("select", { name: "accompany_id" }, memberOptions(a.accompany_id, ["family", "caretaker"]))),
      ...field("ap-repeat", "Regular checkup: repeat every (days, optional)", el("input", { type: "number", name: "repeat_days", min: 1, max: 730, value: a.repeat_days ?? "" })),
    ], async (form) => {
      const body = formData(form);
      body.accompany_id = body.accompany_id || null;
      if (appt) await api(`/api/appointments/${appt.id}`, { method: "PUT", body });
      else await api("/api/appointments", { method: "POST", body });
      toast("Visit saved.");
      await loadToday();
      await loadVisits();
    });
  }

  async function deleteVisit(appt) {
    if (!window.confirm(`Remove the visit to ${appt.doctor}?`)) return;
    try { await api(`/api/appointments/${appt.id}`, { method: "DELETE" }); await loadVisits(); } catch (e) { toast(e.message); }
  }
  document.getElementById("add-appt").addEventListener("click", () => visitDialog(null));

  // ---------- summary ----------
  function bars(container, rows) {
    clear(container);
    for (const [name, row] of rows) {
      if (row.percent === null || row.percent === undefined) continue;
      const fill = el("div", { class: row.percent < 80 ? "fill low" : "fill" });
      fill.style.width = `${row.percent}%`;
      container.append(el("div", { class: "bar" },
        el("span", { text: name }),
        el("div", { class: "track", role: "img", "aria-label": `${name}: ${row.percent}% of ${row.scheduled} doses given` }, fill),
        el("strong", { text: `${row.percent}%` })));
    }
  }

  let summaryRequest = 0;
  async function loadSummary(days) {
    const request = ++summaryRequest;
    for (const b of document.querySelectorAll("[data-days]")) b.setAttribute("aria-pressed", String(Number(b.dataset.days) === days));
    const result = await api(`/api/summary?days=${days}&write=false`);
    if (request !== summaryRequest) return;
    renderSummary(result);
    const source = document.getElementById("summary-source");
    source.textContent = "";
    source.append(el("span", { class: "spinner", "aria-hidden": "true" }), " Gemini is rewording this from the record…");
    document.getElementById("summary-text").classList.add("shimmer");
    document.getElementById("summary-text").setAttribute("aria-busy", "true");
    api(`/api/summary?days=${days}`).then((written) => {
      if (request === summaryRequest) renderSummary(written);
    }).catch(() => {
      if (request === summaryRequest) document.getElementById("summary-source").textContent = "Written from the record by a fixed template.";
    });
  }

  function renderSummary(result) {
    const f = result.facts;
    document.getElementById("summary-text").classList.toggle("shimmer", false);
    document.getElementById("summary-text").removeAttribute("aria-busy");
    document.getElementById("summary-text").textContent = result.summary.text;
    document.getElementById("summary-source").textContent = result.summary.source === "gemini"
      ? "Written by Gemini from the numbers below, and checked: it contains no number that is not in the record."
      : "Written from the record by a fixed template.";
    bars(document.getElementById("by-med"), f.adherence.by_medicine.map((r) => [r.name, r]));
    bars(document.getElementById("by-part"), Object.entries(f.adherence.by_part_of_day).map(([k, r]) => [k[0].toUpperCase() + k.slice(1), r]));
    const o = f.adherence.overall;
    document.getElementById("overall").textContent = o.percent === null ? "–" : `${o.percent}%`;
    document.getElementById("overall-note").textContent = `${o.given} of ${o.scheduled} doses given from ${f.from} to ${f.to}. ${o.missed} missed, ${o.skipped} skipped.`;
    document.getElementById("request-card").classList.toggle("hidden", !canEdit());
    document.getElementById("brief-name").textContent = me.elder_name;
    document.getElementById("brief-period").textContent = `${f.from} to ${f.to}`;
    renderTimeline(result.timeline);
  }

  function renderTimeline(rows) {
    const body = clear(document.getElementById("timeline-body"));
    for (const row of rows) {
      const count = (state) => row.doses.filter((d) => d.state === state).length;
      const dots = el("div", { class: "dots", role: "img", "aria-label": `${count("given")} given, ${count("missed")} missed, ${count("skipped")} skipped` }, row.doses.map((d) =>
        el("i", { class: d.state === "given" ? "" : d.state === "missed" ? "missed" : d.state === "skipped" ? "skipped" : "pending", title: `${d.time} ${d.name}: ${STATE_TEXT[d.state]}` })));
      const missed = row.doses.filter((d) => d.state === "missed").map((d) => `${d.time} ${d.name}`);
      body.append(el("tr", {},
        el("th", { scope: "row", text: new Date(row.date + "T00:00:00").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) }),
        el("td", {}, dots, missed.length ? el("div", { class: "small muted", text: `Missed: ${missed.join(", ")}` }) : null),
        el("td", {}, row.tags.map((t) => el("span", { class: t === "calm" ? "chip given" : "chip missed", text: label(t) }))),
        el("td", { text: row.feeling === "good" ? "😊 good" : row.feeling === "not_good" ? "☹️ not good" : "–" })));
    }
  }

  for (const b of document.querySelectorAll("[data-days]")) b.addEventListener("click", () => loadSummary(Number(b.dataset.days)).catch((e) => toast(e.message)));

  document.getElementById("request-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const kind = event.submitter ? event.submitter.value : "call";
    try {
      const result = await api("/api/doctor-request", { method: "POST", body: { kind, message: event.target.message.value } });
      toast(`Request sent to ${result.to.join(", ")}.${result.delivered ? "" : " " + result.detail}`);
      event.target.reset();
    } catch (e) { toast(e.message); }
  });

  // ---------- people & settings ----------
  async function loadPeople() {
    today = await api("/api/today");
    const box = clear(document.getElementById("people-list"));
    for (const person of today.members) {
      box.append(el("div", { class: "item spread" },
        el("div", {}, el("strong", { text: person.name }), el("div", { class: "small muted" },
          ROLE_NAMES[person.role], person.email ? ` · ${person.email}` : "", person.phone ? ` · ${person.phone}` : "")),
        el("div", { class: "row" },
          el("button", { type: "button", onclick: () => personDialog(person) }, "Edit"),
          person.id === me.member.id ? null : el("button", { type: "button", onclick: () => removePerson(person) }, "Remove"))));
    }
    renderProfileForm();
  }

  function personDialog(person) {
    const p = person || { name: "", role: "family", email: "", phone: "", digest: true };
    openDialog(person ? `Edit ${person.name}` : "Add a person", [
      ...field("p-name", "Name", el("input", { name: "name", value: p.name, maxlength: 80, required: true })),
      ...field("p-role", "Role", el("select", { name: "role" }, Object.entries(ROLE_NAMES).map(([v, t]) => el("option", { value: v, selected: v === p.role }, t)))),
      ...field("p-email", "Email (for reminders)", el("input", { type: "email", name: "email", value: p.email || "", maxlength: 254 })),
      ...field("p-phone", "Phone (for one-tap calls)", el("input", { type: "tel", name: "phone", value: p.phone || "", maxlength: 20 })),
      ...field("p-pass", person ? "New passcode (leave empty to keep)" : "Passcode for them (6–12 digits)",
        el("input", { type: "password", name: "passcode", inputmode: "numeric", maxlength: 12, autocomplete: "new-password" })),
      el("label", {}, el("input", { type: "checkbox", name: "digest", checked: p.digest !== false }), " Send the evening update"),
      el("p", { class: "muted small", text: "For the bedside screen choose the role 'Bedside screen' and sign in once on the bedside tablet with that passcode." }),
    ], async (form) => {
      const body = formData(form);
      if (!body.passcode) body.passcode = null;
      if (person) await api(`/api/members/${person.id}`, { method: "PUT", body });
      else await api("/api/members", { method: "POST", body });
      toast("Saved.");
      await loadPeople();
    });
  }

  async function removePerson(person) {
    if (!window.confirm(`Remove ${person.name} from the circle? Their passcode stops working.`)) return;
    try { await api(`/api/members/${person.id}`, { method: "DELETE" }); await loadPeople(); } catch (e) { toast(e.message); }
  }
  document.getElementById("add-person").addEventListener("click", () => personDialog(null));

  function renderProfileForm() {
    const form = clear(document.getElementById("profile-form"));
    const a = today.about || {}, c = today.contacts || {}, s = today.settings || {};
    const input = (id, name, labelText, value, extra = {}) => field(id, labelText, el("input", { name, value: value ?? "", ...extra }));
    form.append(
      ...input("pf-elder", "elder_name", "Their name", today.elder_name, { maxlength: 80, required: true }),
      el("fieldset", {}, el("legend", { text: "About them (shown to every new nurse)" }),
        ...input("pf-as", "about.address_as", "What they like to be called", a.address_as, { maxlength: 120 }),
        ...field("pf-likes", "What they like", el("textarea", { name: "about.likes", maxlength: 500 }, a.likes || "")),
        ...field("pf-calms", "What calms them", el("textarea", { name: "about.calms", maxlength: 500 }, a.calms || "")),
        ...field("pf-notes", "Good to know", el("textarea", { name: "about.notes", maxlength: 500 }, a.notes || ""))),
      el("fieldset", {}, el("legend", { text: "Contacts" }),
        ...input("pf-chem", "contacts.chemist_name", "Chemist", c.chemist_name, { maxlength: 120 }),
        ...input("pf-chemp", "contacts.chemist_phone", "Chemist phone", c.chemist_phone, { type: "tel", maxlength: 20 }),
        ...input("pf-hosp", "contacts.hospital_name", "Hospital", c.hospital_name, { maxlength: 120 }),
        ...input("pf-hospp", "contacts.hospital_phone", "Hospital phone", c.hospital_phone, { type: "tel", maxlength: 20 }),
        ...input("pf-doc", "contacts.doctor_name", "Local doctor", c.doctor_name, { maxlength: 120 }),
        ...input("pf-docp", "contacts.doctor_phone", "Doctor phone", c.doctor_phone, { type: "tel", maxlength: 20 }),
        ...input("pf-doce", "contacts.doctor_email", "Doctor email (for call and visit requests)", c.doctor_email, { type: "email", maxlength: 254 }),
        ...input("pf-amb", "contacts.ambulance_phone", "Ambulance number", c.ambulance_phone || "108", { type: "tel", maxlength: 20 })),
      el("fieldset", {}, el("legend", { text: "Reminder rules (minutes)" }),
        ...input("pf-lead", "settings.upcoming_lead_min", "Email the giver this long before a dose", s.upcoming_lead_min, { type: "number", min: 5, max: 120 }),
        ...input("pf-miss", "settings.missed_after_min", "Remind the giver if not marked after", s.missed_after_min, { type: "number", min: 5, max: 240 }),
        ...input("pf-esc", "settings.escalate_after_min", "Tell the whole family after", s.escalate_after_min, { type: "number", min: 10, max: 480 }),
        ...input("pf-refill", "settings.refill_warn_days", "Refill warning when this many days are left", s.refill_warn_days, { type: "number", min: 1, max: 30 })),
      el("p", { class: "error", id: "profile-error", role: "alert" }),
      el("div", { class: "form-actions" }, el("button", { class: "btn-primary", type: "submit" }, "Save")));
  }

  document.getElementById("profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const flat = formData(event.target);
    const body = { about: {}, contacts: {}, settings: {} };
    for (const [key, value] of Object.entries(flat)) {
      const [group, name] = key.split(".");
      if (name) body[group][name] = value;
      else body[group] = value;
    }
    try {
      await api("/api/profile", { method: "PUT", body });
      document.getElementById("profile-error").textContent = "";
      toast("Saved.");
      await loadPeople();
    } catch (e) { document.getElementById("profile-error").textContent = e.message; }
  });

  // ---------- emails and history ----------
  async function loadEmails() {
    const mails = await api("/api/outbox");
    const box = clear(document.getElementById("mail-list"));
    if (!mails.length) box.append(el("p", { class: "muted", text: "No emails yet. Reminders are checked every five minutes." }));
    for (const mail of mails) {
      box.append(el("details", { class: "item" },
        el("summary", {}, `${fmtTime(mail.created_at)} · ${mail.subject}`),
        el("div", { class: "small muted", text: `To: ${mail.to_names.join(", ") || "nobody"} · ${mail.delivered ? "delivered" : mail.detail}` }),
        el("div", { class: "mail", text: mail.body })));
    }
  }

  async function loadHistory() {
    const rows = await api("/api/audit");
    const box = clear(document.getElementById("audit-list"));
    box.append(el("table", {},
      el("caption", { class: "sr-only", text: "Changes to their care, newest first" }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "When" }), el("th", { scope: "col", text: "Who" }), el("th", { scope: "col", text: "What" }))),
      el("tbody", {}, rows.map((r) => el("tr", {},
        el("td", { text: fmtTime(r.at) }), el("td", { text: `${r.by_name} (${r.by_role})` }), el("td", { text: `${r.action}: ${r.detail}` }))))));
  }

  // ---------- dialog ----------
  const dialog = document.getElementById("dialog");
  let onSave = null;
  function openDialog(title, children, save) {
    document.getElementById("dialog-title").textContent = title;
    document.getElementById("dialog-error").textContent = "";
    clear(document.getElementById("dialog-body")).append(...children);
    onSave = save;
    dialog.showModal();
  }
  document.getElementById("dialog-cancel").addEventListener("click", () => dialog.close());
  document.getElementById("dialog-x").addEventListener("click", () => dialog.close());
  document.getElementById("dialog-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await onSave(event.target); dialog.close(); }
    catch (e) { document.getElementById("dialog-error").textContent = e.message; }
  });

  // ---------- start ----------
  document.getElementById("logout").addEventListener("click", async () => {
    try { await api("/api/logout", { method: "POST" }); } finally { window.location.href = "/"; }
  });
  document.getElementById("print-brief").addEventListener("click", () => window.print());
  document.getElementById("day-pick").addEventListener("change", () => loadToday().catch((e) => toast(e.message)));

  function buildSwitcher() {
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem("orbit_demo_codes") || "null"); } catch (_) { saved = null; }
    if (!saved || saved.code !== me.orbit_code) return;
    const views = [["wife", "Mary · family"], ["nurse", "Latha · nurse"], ["doctor", "Dr. Rao · doctor"], ["bedside", "Bedside screen"]];
    const bar = el("nav", { class: "switcher", "aria-label": "Switch sample view" }, el("span", { class: "label", text: "Sample: view as" }));
    for (const [slot, text] of views) {
      const current = (slot === "wife" && me.member.name.startsWith("Mary")) || (slot === "nurse" && me.member.role === "caretaker") || (slot === "doctor" && me.member.role === "doctor");
      bar.append(el("button", {
        type: "button", "aria-current": current ? "true" : null, class: current ? "on" : "",
        onclick: async () => {
          await api("/api/login", { method: "POST", body: { orbit_code: saved.code, passcode: saved.passcodes[slot] } });
          try { sessionStorage.removeItem("orbit_tab"); } catch (_) { /* ignore */ }
          window.location.href = slot === "bedside" ? "/bedside" : "/circle";
        },
      }, text));
    }
    document.body.append(bar);
  }

  async function start() {
    me = await api("/api/me");
    if (me.member.role === "elder") { window.location.href = "/bedside"; return; }
    document.getElementById("title").textContent = `${me.elder_name}'s circle`;
    document.getElementById("whoami").textContent = `${me.member.name} · ${ROLE_NAMES[me.member.role]} · code ${me.orbit_code}`;
    document.getElementById("to-bedside").classList.toggle("hidden", !canEdit());
    document.getElementById("note-card").classList.toggle("hidden", !canEdit());
    const banner = document.getElementById("banner");
    if (me.demo) {
      banner.textContent = "Sample family: a week of made-up history. No email leaves Orbit; you can read every reminder under Emails. Deleted after 24 hours.";
      banner.classList.remove("hidden");
    }
    buildTabs();
    buildTagPicker();
    if (me.demo) buildSwitcher();
    let first = me.member.role === "doctor" ? "summary" : "today";
    try { first = sessionStorage.getItem("orbit_tab") || first; } catch (_) { /* ignore */ }
    if (!document.getElementById(`t-${first}`)) first = "today";
    if (first !== "today") loadToday().catch(() => {});
    showTab(first);
  }
  start().catch((e) => toast(e.message));
})();
