"use strict";
const labels = Object.fromEntries([...document.querySelectorAll("#translations [data-key]")].map(el => [el.dataset.key, el.textContent]));
const t = key => labels[key] || labels.error;
const message = text => { document.getElementById("message").textContent = text; };
const csrf = () => decodeURIComponent(document.cookie.split("; ").find(c => c.startsWith("nowa_csrf="))?.split("=")[1] || "");
const intent = () => crypto.randomUUID();
async function api(path, method = "GET", body = null, key = null) {
  const options = {method, headers: {}};
  if (document.body.dataset.clinicSlug) options.headers["X-Clinic-Slug"] = document.body.dataset.clinicSlug;
  if (body !== null) {
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = csrf();
    options.body = JSON.stringify(key ? {...body, idempotency_key: key} : body);
  }
  const response = await fetch(path, options);
  if (response.status === 401 && !path.endsWith("/login")) { location.assign("/d/login"); throw new Error(t("error")); }
  if (response.status === 410) {
    const expired = document.getElementById("sandbox-expired");
    message(expired ? expired.textContent : t("error"));
    throw new Error(expired ? expired.textContent : t("error"));
  }
  const data = await response.json();
  if (!response.ok && response.status !== 409) {
    throw new Error(data.reason === "bookings_outside" ? t("bookings_outside") : t("error") + (data.fields ? ": " + data.fields.join(", ") : ""));
  }
  if (data.ok === false && data.reason !== "count_changed") throw new Error(t(path.startsWith("/d/api/questions/") ? "q_" + data.reason : data.reason));
  return data;
}
function bindButton(el, action) {
  if (!el) return;
  el.addEventListener("click", async () => {
    if (el.disabled) return;
    el.disabled = true;
    try { await action(); } catch (error) { message(error.message); }
    finally { el.disabled = false; }
  });
}
function bindForm(id, action) {
  const form = document.getElementById(id);
  if (!form) return;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = form.querySelector("button");
    if (button.disabled) return;
    button.disabled = true;
    try { await action(form, Object.fromEntries(new FormData(form))); }
    catch (error) { message(error.message); }
    finally { button.disabled = false; }
  });
}
bindForm("login", async (_, body) => { await api("/d/login", "POST", body); location.assign("/d"); });
bindForm("reset-request", async (_, body) => { const result = await api("/d/reset/request", "POST", body); message(t("reset_sent"));
  document.getElementById("reset-telegram")?.remove();
  if (result.telegram_url) {
    const a = document.createElement("a"); a.id = "reset-telegram"; a.href = result.telegram_url;
    a.textContent = t("telegram_open"); a.className = "btn btn-main"; a.target = "_blank"; a.rel = "noopener";
    document.getElementById("reset-request").after(a);
  } });
bindForm("reset-confirm", async (_, body) => { await api("/d/reset/confirm", "POST", body); location.assign("/d/login"); });
bindButton(document.getElementById("logout"), async () => { await api("/d/logout", "POST", {}); location.assign("/d/login"); });
let queueRefresh;
async function refresh() {
  const data = await api("/d/api/tonight");
  document.getElementById("evening-dot").classList.toggle("live", Boolean(data.evening_id));
  const reportLink = document.getElementById("latest-report");
  reportLink.hidden = !data.latest_report_id;
  if (data.latest_report_id) reportLink.href = "/d/report/" + data.latest_report_id;
  const queue = document.getElementById("queue");
  queue.replaceChildren();
  if (!data.evening_id) { queue.textContent = t("no_evening"); }
  const make = (tag, className, text) => {
    const el = document.createElement(tag); el.className = className; el.textContent = text; return el;
  };
  const booked = data.rows.filter(row => row.state !== "cancelled").length;
  const seen = data.rows.filter(row => row.state === "seen").length;
  const remaining = data.rows.filter(row => row.remaining);
  const stats = document.getElementById("stats"); stats.replaceChildren();
  for (const [count, key] of [[booked, "booked_count"], [seen, "seen_count"], [remaining.length, "remaining_count"]]) {
    const stat = make("div", "stat", ""); stat.append(make("b", "num", String(count)), make("span", "", t(key))); stats.append(stat);
  }
  const room = data.in_room;
  const doctor = data.doctor;
  const onWay = document.getElementById("on-way"), onWayState = document.getElementById("onway-state");
  onWay.hidden = Boolean(doctor.on_way_at || doctor.arrived_at);
  onWayState.hidden = !onWay.hidden;
  if (onWay.hidden) {
    document.getElementById("area-form").hidden = true;
    const at = doctor.arrived_at || doctor.on_way_at;
    const time = new Date(at).toLocaleTimeString("en-GB", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"});
    onWayState.textContent = t(doctor.arrived_at ? "arrived_since" : "on_way_since").replace("{time}", time);
  }
  document.getElementById("in-room").textContent = room ? room.queue_number + " · " + (room.first_name || t("walk_in")) : t("empty");
  const who = document.getElementById("who");
  who.querySelectorAll("button:not(.walk)").forEach(button => button.remove());
  const hero = document.getElementById("next-hero"); hero.hidden = !remaining.length;
  document.getElementById("next-patient").replaceChildren();
  document.getElementById("next-action").replaceChildren();
  for (const [index, row] of remaining.slice(0, 4).entries()) {
    const button = make("button", "", "");
    button.append(make("span", "num", String(row.queue_number)), make("span", "", row.patient_first_name || t("walk_in")));
    if (row.no_show_count > 0) button.append(make("span", "warn", "⚠️" + row.no_show_count));
    bindButton(button, async () => { await command("who-comes-in", {booking_id: row.booking_id}); });
    if (index === 0) {
      const name = row.patient_first_name || t("walk_in");
      const details = make("div"), state = make("span", "state-pill", t(row.state));
      state.dataset.state = row.state;
      const sub = make("small"); sub.append(state);
      if (row.no_show_count > 0) sub.append(make("span", "warn", t("didnt_come") + " ×" + row.no_show_count));
      details.append(make("b", "", name), sub);
      document.getElementById("next-patient").append(make("span", "num", String(row.queue_number)), details);
      button.className = "btn btn-main btn-xl"; button.textContent = t("call_in").replace("{name}", name);
      document.getElementById("next-action").append(button);
    } else who.insertBefore(button, who.querySelector(".walk"));
  }
  document.getElementById("pace-count").textContent = seen + " / " + booked;
  document.getElementById("pace-progress").style.width = (booked ? seen / booked * 100 : 0) + "%";
  for (const stored of data.rows) {
    const row = {...stored, state: stored.booking_id === room?.booking_id ? "in_room" : stored.state};
    const card = make("div", "qrow" + (["seen", "didnt_come", "cancelled"].includes(row.state) ? " done" : ""), "");
    const name = (row.patient_first_name || t("walk_in")) + (row.no_show_count > 0 ? " ⚠️" + row.no_show_count : "");
    const title = make(row.remaining ? "button" : "span", "name", name); title.setAttribute("dir", "auto");
    if (row.remaining) bindButton(title, async () => { await command("who-comes-in", {booking_id: row.booking_id}); });
    const state = make("span", "state-pill", [t(row.state === "in_room" ? "in_room" : row.state), row.silent ? t("silent") : "", row.source === "walkin_tap" ? t("walk_in") : ""].filter(Boolean).join(" · "));
    if (row.state === "in_room") state.prepend(make("span", "dot live", ""));
    state.dataset.state = row.state; card.dataset.state = row.state;
    const expected = row.expected_shown ? new Date(row.expected_shown).toLocaleTimeString("en-GB", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"}) : "";
    card.append(make("span", "n", String(row.queue_number)), title, make("span", "exp", expected), state); queue.append(card);
  }
  const select = document.getElementById("areas");
  const previous = select.value;
  select.replaceChildren();
  for (const area of data.areas) {
    const option = document.createElement("option"); option.value = area.id;
    option.textContent = document.documentElement.lang === "ar" ? area.name_ar : area.name_en;
    select.append(option);
  }
  if (previous) select.value = previous;
}
async function command(path, body = {}, key = intent()) {
  const result = await api("/d/api/" + path, "POST", body, key);
  await refresh(); return result;
}
if (document.body.dataset.mode === "tonight") {
  queueRefresh = () => refresh().catch(error => message(error.message));
  queueRefresh(); setInterval(queueRefresh, 15000);
  for (const button of document.querySelectorAll("[data-command]")) {
    bindButton(button, () => command(button.dataset.command, button.dataset.walkIn ? {walk_in: true} : {}));
  }
  bindButton(document.getElementById("close"), async () => {
    let preview = await api("/d/api/close/preview");
    while (true) {
      const prompt = preview.untold_count > 0 ? t("close_untold").replace("{count}", preview.untold_count) : t("close_confirm");
      if (!window.confirm(prompt)) return;
      const result = await command("close", {expected_untold: preview.untold_count});
      if (result.reason !== "count_changed") return;
      preview = result;
    }
  });
  bindButton(document.getElementById("cancel"), async () => {
    const result = await command("cancel-tonight/request");
    if (window.confirm(t("cancel_confirm").replace("{count}", result.active_count))) await command("cancel-tonight/confirm", {confirm_token: result.confirm_token});
  });
  let locationKey;
  bindButton(document.getElementById("on-way"), async () => {
    locationKey = intent();
    const location = await new Promise(resolve => {
      if (!navigator.geolocation) return resolve(null);
      const timer = setTimeout(() => resolve(null), 10000);
      navigator.geolocation.getCurrentPosition(position => { clearTimeout(timer); resolve(position); }, () => { clearTimeout(timer); resolve(null); }, {timeout: 10000, enableHighAccuracy: false, maximumAge: 0});
    });
    if (location) { await command("on-my-way", {lat: location.coords.latitude, lng: location.coords.longitude}, locationKey); }
    else { document.getElementById("area-form").hidden = false; document.getElementById("areas").focus(); }
  });
  bindForm("area-form", async () => {
    await command("on-my-way", {area_id: Number(document.getElementById("areas").value)}, locationKey);
    document.getElementById("area-form").hidden = true;
  });
}
if (document.body.dataset.mode === "settings") {
  let current;
  const field = (form, name) => form.elements.namedItem(name);
  async function loadSettings() {
    current = await api("/d/api/settings");
    for (const day of document.querySelectorAll("[data-weekday]")) {
      const hours = current.hours.find(h => h.weekday === Number(day.dataset.weekday));
      day.querySelector('[name="enabled"]').checked = Boolean(hours);
      if (hours) for (const name of ["start", "end"]) day.querySelector(`[name="${name}"]`).value = hours[name];
    }
    const timing = document.getElementById("timing");
    for (const name of ["usual_visit_min", "safe_drive_min", "cushion_min", "max_per_evening"]) field(timing, name).value = current[name] ?? "";
    const info = document.getElementById("info");
    for (const name of ["price", "address", "what_to_bring", "other"]) field(info, name).value = current.items.find(i => i.key === name)?.text || "";
    field(document.getElementById("lang"), "lang").value = current.lang;
    field(document.getElementById("secretary_alerts"), "on").checked = current.on;
    const select = document.getElementById("saved-overrides");
    select.replaceChildren(new Option("", ""));
    for (const override of current.overrides) select.append(new Option(override.date, override.date));
  }
  async function saveSettings(kind, payload) {
    await api("/d/api/settings/" + kind, "PUT", payload, intent());
    message(t("saved"));
    if (kind === "lang") location.reload(); else await loadSettings();
  }
  bindForm("hours", () => saveSettings("hours", {hours: [...document.querySelectorAll("[data-weekday]")].filter(day => day.querySelector('[name="enabled"]').checked).map(day => ({weekday: Number(day.dataset.weekday), start: day.querySelector('[name="start"]').value, end: day.querySelector('[name="end"]').value}))}));
  bindForm("overrides", (form, body) => saveSettings("overrides", {date: body.date, closed: field(form, "closed").checked, start: body.start || null, end: body.end || null}));
  document.getElementById("saved-overrides").addEventListener("change", event => {
    const value = current.overrides.find(o => o.date === event.target.value);
    if (!value) return;
    const form = document.getElementById("overrides");
    for (const name of ["date", "start", "end"]) field(form, name).value = value[name] || "";
    field(form, "closed").checked = value.closed;
  });
  bindButton(document.getElementById("delete-override"), async () => {
    const day = field(document.getElementById("overrides"), "date").value;
    if (!day) throw new Error(t("date"));
    await api("/d/api/settings/overrides/" + day, "DELETE", {}, intent());
    await loadSettings(); message(t("saved"));
  });
  bindForm("timing", (_, body) => saveSettings("timing", {usual_visit_min: Number(body.usual_visit_min), safe_drive_min: Number(body.safe_drive_min), cushion_min: Number(body.cushion_min), max_per_evening: body.max_per_evening === "" ? null : Number(body.max_per_evening)}));
  bindForm("info", (_, body) => saveSettings("info", {items: Object.entries(body).filter(([, text]) => text !== "").map(([key, text]) => ({key, text}))}));
  bindForm("lang", (_, body) => saveSettings("lang", body));
  bindForm("secretary_alerts", form => saveSettings("secretary_alerts", {on: field(form, "on").checked}));
  bindButton(document.getElementById("telegram"), async () => {
    const data = await api("/d/api/telegram-link", "POST", {}, intent());
    const link = document.getElementById("telegram-url");
    if (data.url) { link.href = data.url; link.hidden = false; }
    else message(t("telegram_repeated"));
  });
  loadSettings().catch(error => message(error.message));
}

const sandboxControls = document.getElementById("sandbox-controls");
if (sandboxControls) {
  const slug = document.body.dataset.clinicSlug;
  const pageURL = new URL(location.href); pageURL.searchParams.set("clinic", slug);
  history.replaceState(null, "", pageURL);
  async function advance(minutes) {
    if (minutes < 1) return;
    // The worker owns due timers; each bounded command only advances its clock.
    while (minutes > 0) {
      const chunk = Math.min(minutes, 180);
      const result = await api("/d/api/sandbox/advance", "POST", {minutes: chunk}, intent());
      document.getElementById("sandbox-clock").textContent = result.now; minutes -= chunk;
    }
    await refresh();
  }
  for (const button of sandboxControls.querySelectorAll("[data-advance]")) bindButton(button, () => advance(Number(button.dataset.advance)));
  bindButton(document.getElementById("sandbox-jump"), () => advance(Math.ceil((Date.parse(sandboxControls.dataset.paperStart) - Date.parse(document.getElementById("sandbox-clock").textContent)) / 60000)));
  window.NowaPhone(document.getElementById("sandbox-phone"), "/d/api/sandbox/phone", status => {
    if (status === 401) {
      fetch("/c/" + encodeURIComponent(slug)).then(response => { if (response.status === 410) message(document.getElementById("sandbox-expired").textContent); else location.assign("/d/login"); }).catch(() => message(t("error")));
    } else message(t("error"));
  });
}


async function loadQuestions() {
  const panel = document.getElementById("questions");
  if (!panel) return;
  const data = await api("/d/api/questions");
  panel.replaceChildren();
  for (const question of data) {
    const card = document.createElement("form"); card.className = "ask";
    const title = document.createElement("p"); title.textContent = question.text_display;
    const count = document.createElement("span"); count.textContent = question.count > 1 ? String(question.count) : "";
    const draft = document.createElement("textarea"); draft.minLength = 1; draft.maxLength = 1000;
    draft.className = "field"; draft.required = true; draft.value = question.draft_answer || ""; draft.setAttribute("aria-label", t("q_answer"));
    card.append(title, count, draft);
    const acts = document.createElement("div"); acts.className = "acts"; card.append(acts);
    for (const action of ["draft", "save", "later", "dismiss"]) {
      const button = document.createElement("button"); button.type = "button";
      button.textContent = t(action === "draft" ? "q_answer" : "q_" + action);
      bindButton(button, async () => {
        if (action === "draft" && !draft.reportValidity()) return;
        const result = await api("/d/api/questions/" + question.id + "/" + action, "POST",
                                 action === "draft" ? {text: draft.value} : {}, intent());
        message(t(result.reason === "saved" ? "saved" : "q_" + result.reason));
        await loadQuestions();
      });
      acts.append(button);
    }
    card.addEventListener("submit", event => event.preventDefault());
    panel.append(card);
  }
}
if (document.getElementById("questions")) loadQuestions().catch(error => message(error.message));
if (document.body.dataset.mode === "report") {
  api("/d/api/report/" + document.body.dataset.eveningId).then(data => {
    document.getElementById("report-text").textContent = data.text
      .replace("والـ AI رد عليها", "واتجاوب عليها")
      .replace("answered by the AI", "answered");
    const list = document.getElementById("health-answers");
    for (const answer of data.health_answers) {
      const card = document.createElement("article"); card.className = "card section";
      for (const field of ["question", "answer", "why", "at_display", "model"]) {
        const line = document.createElement("p"); line.textContent = answer[field] || ""; card.append(line);
      }
      const link = document.createElement("a"); link.textContent = answer.source_title;
      if (answer.source_url) {
        const url = new URL(answer.source_url);
        if (url.protocol === "https:") { link.href = url.href; link.rel = "noreferrer"; }
      }
      card.append(link); list.append(card);
    }
  }).catch(error => message(error.message));
}
