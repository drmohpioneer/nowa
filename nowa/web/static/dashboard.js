"use strict";
const labels = Object.fromEntries([...document.querySelectorAll("#translations [data-key]")].map(el => [el.dataset.key, el.textContent]));
const missingLabels = new Set();
const t = key => {
  if (Object.hasOwn(labels, key)) return labels[key];
  if (!missingLabels.has(key)) {
    missingLabels.add(key);
    console.warn("Missing dashboard label: " + key);
  }
  return "";
};
const message = text => { document.getElementById("message").textContent = text; };
const csrfCookie = () => document.querySelector('meta[name="csrf-cookie"]')?.content || "nowa_csrf";
const csrf = () => decodeURIComponent(document.cookie.split("; ").find(c => c.startsWith(csrfCookie() + "="))?.split("=")[1] || "");
const intent = () => crypto.randomUUID();
async function api(path, method = "GET", body = null, key = null) {
  const options = {method, headers: {}};
  if (document.body.dataset.clinicSlug) options.headers["X-Clinic-Slug"] = document.body.dataset.clinicSlug;
  if (body !== null) {
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = csrf();
    options.body = JSON.stringify(key ? {...body, idempotency_key: key} : body);
  }
  const requestPath = path + (path.includes("?") ? "&" : "?") + "lang=" + document.documentElement.lang;
  const response = await fetch(requestPath, options).catch(() => { throw new Error(t("error")); });
  if (response.status === 401 && !path.endsWith("/login")) { location.assign("/d/login?lang=" + document.documentElement.lang); throw new Error(t("error")); }
  if (response.status === 410) {
    const expired = document.getElementById("sandbox-expired");
    message(expired ? expired.textContent : t("error"));
    throw new Error(expired ? expired.textContent : t("error"));
  }
  const data = await response.json();
  if (!response.ok && response.status !== 409) {
    const detail = data.detail || data;
    throw detail.reason === "bookings_outside" ? new Error(t("bookings_outside")) : detail.reason === "past_date" ? new Error(t("past_date")) : detail.reason === "wrong_code" ? new Error(t("wrong_code").replace("{count}", detail.attempts_left)) : window.NowaFeedback.requestError(response, data, labels, t("error"));
  }
  if (data.ok === false && data.reason !== "count_changed") throw new Error(t(path.startsWith("/d/api/questions/") ? "q_" + data.reason : data.reason) || t("error"));
  return data;
}
function bindButton(el, action) {
  if (!el) return;
  el.addEventListener("click", async () => {
    if (el.disabled) return;
    await window.NowaFeedback.pending(el, action, document.getElementById("message"), {adjacent: true});
  });
}
function bindForm(id, action) {
  const form = document.getElementById(id);
  if (!form) return;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    message("");
    const button = form.querySelector('button[type="submit"], button:not([type])');
    if (button.disabled) return;
    await window.NowaFeedback.pending(button, () => { window.NowaFeedback.validate(form, labels); return action(form, Object.fromEntries(new FormData(form))); }, document.getElementById("message"), {adjacent: true});
  });
}
bindForm("login", async (_, body) => { await api("/d/login", "POST", body); location.assign("/d?lang=" + document.documentElement.lang); });
bindForm("reset-request", async (_, body) => { const result = await api("/d/reset/request", "POST", body); message(t("reset_sent"));
  document.getElementById("reset-request").hidden = true;
  const confirmation = document.getElementById("reset-confirm"); confirmation.hidden = false;
  confirmation.elements.namedItem("mobile").value = body.mobile;
  confirmation.elements.namedItem("code").focus();
  if (!result.telegram_url) { const phone = document.getElementById("reset-phone"); phone.hidden = false;
    window.NowaPhone(phone, "/d/reset/phone?lang=" + document.documentElement.lang, () => message(t("error"))); }
  document.getElementById("reset-telegram")?.remove();
  if (result.telegram_url) {
    const a = document.createElement("a"); a.id = "reset-telegram"; a.href = result.telegram_url;
    a.textContent = t("telegram_open"); a.className = "btn btn-main"; a.target = "_blank"; a.rel = "noopener";
    document.getElementById("reset-request").after(a);
  } });
bindForm("reset-confirm", async (_, body) => { await api("/d/reset/confirm", "POST", body); location.assign("/d/login?lang=" + document.documentElement.lang); });
bindButton(document.getElementById("logout"), async () => { await api("/d/logout", "POST", {}); location.assign("/d/login?lang=" + document.documentElement.lang); });
let queueRefresh;
async function refresh() {
  const data = await api("/d/api/tonight");
  document.getElementById("evening-dot").classList.toggle("live", Boolean(data.evening_id));
  const standbyCount = document.getElementById("standby-count");
  if (standbyCount) { standbyCount.hidden = !(data.standby_count > 0);
    standbyCount.textContent = t("standby_count").replace("{count}", data.standby_count || 0); }
  const reportLink = document.getElementById("latest-report");
  reportLink.hidden = !data.latest_report_id;
  if (data.latest_report_id) reportLink.href = "/d/report/" + data.latest_report_id;
  const noEvening = data.evening_id == null;
  const undo = document.getElementById("undo");
  if (undo) { undo.disabled = !data.can_undo; undo.dataset.unavailable = String(!data.can_undo);
    undo.title = (data.can_undo ? t("undo") : t("undo_empty")); undo.setAttribute("aria-label", undo.title); }
  for (const id of ["onway", "area-form", "who", "close", "cancel", "stats", "next-hero", "undo", "room-section", "progress-section", "who-label"]) {
    const node = document.getElementById(id); if (node && noEvening) node.hidden = true;
    else if (node && ["onway", "who", "close", "cancel", "stats", "undo", "room-section", "progress-section", "who-label"].includes(id)) node.hidden = false;
  }
  const queue = document.getElementById("queue");
  queue.replaceChildren();
  if (!data.evening_id) { queue.textContent = t("no_evening"); }
  else if (!data.rows.length) queue.textContent = t("empty_bookings");
  const make = (tag, className, text) => {
    const el = document.createElement(tag); el.className = className || ""; el.textContent = text ?? "";
    if (text) globalThis.NowaText?.(el, text);
    return el;
  };
  const booked = data.rows.filter(row => row.source === "chat" && row.state !== "cancelled").length;
  const withoutBooking = data.rows.filter(row => row.source === "walkin_tap").length;
  const seen = data.rows.filter(row => row.state === "seen").length;
  const remaining = data.rows.filter(row => row.remaining);
  const stats = document.getElementById("stats"); stats.replaceChildren();
  for (const [count, key] of [[booked, "booked_count"], [seen, "seen_count"], [remaining.length, "remaining_count"], [withoutBooking, "without_booking_count"]]) {
    const stat = make("div", "stat", ""); stat.append(make("b", "num", String(count)), make("span", "", t(key))); stats.append(stat);
  }
  const room = data.in_room;
  document.getElementById("who-heading").textContent = t(room ? "who_next" : "who_first");
  const doctor = data.doctor;
  const onWay = document.getElementById("on-way"), onWayState = document.getElementById("onway-state");
  onWay.hidden = noEvening || Boolean(doctor.on_way_at || doctor.arrived_at);
  onWayState.hidden = !onWay.hidden;
  if (onWay.hidden && !noEvening) {
    document.getElementById("area-form").hidden = true;
    const at = doctor.arrived_at || doctor.on_way_at;
    const time = new Date(at).toLocaleTimeString("en-GB", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"});
    const arrival = new Date(Date.parse(doctor.on_way_at) + doctor.eta_min * 60000).toLocaleTimeString("en-GB", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"});
    onWayState.textContent = t(doctor.arrived_at ? "arrived_since" : "on_way_arrival").replace("{time}", time).replace("{arrival}", arrival);
  }
  document.getElementById("in-room").textContent = room ? room.queue_number + " · " + (room.first_name || t("walk_in")) : t("empty");
  const who = document.getElementById("who");
  who.querySelectorAll("button:not(.walk)").forEach(button => button.remove());
  const hero = document.getElementById("next-hero"); hero.hidden = noEvening || !remaining.length;
  document.getElementById("next-patient").replaceChildren();
  document.getElementById("next-action").replaceChildren();
  for (const [index, row] of remaining.slice(0, 4).entries()) {
    const button = make("button", "", "");
    button.append(make("span", "num", String(row.queue_number)), make("span", "", row.patient_first_name || t("walk_in")));
    if (row.no_show_count > 0) button.append(make("span", "warn", t("didnt_come") + " ×" + row.no_show_count));
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
    const name = (row.patient_first_name || t("walk_in")) + (row.no_show_count > 0 ? " · " + t("didnt_come") + " ×" + row.no_show_count : "");
    const title = make(row.remaining ? "button" : "span", "name", name); title.setAttribute("dir", document.documentElement.dir);
    if (row.remaining) bindButton(title, async () => { await command("who-comes-in", {booking_id: row.booking_id}); });
    const state = make("span", "state-pill", [t(row.state === "in_room" ? "in_room" : row.state), row.silent ? t("silent") : "", row.source === "walkin_tap" ? t("walk_in") : ""].filter(Boolean).join(" · "));
    if (row.state === "in_room") state.prepend(make("span", "dot live", ""));
    state.dataset.state = row.state; card.dataset.state = row.state;
    const expected = row.expected_shown ? new Date(row.expected_shown).toLocaleTimeString("en-GB", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"}) : "";
    if (row.origin_display) title.append(make("small", "muted", row.origin_display));
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
  const closePanel = document.getElementById("close-panel");
  let closePreview;
  function showClose(preview) {
    closePreview = preview; closePanel.hidden = false;
    document.getElementById("close-details").textContent = preview.untold_count > 0 ? t("close_untold").replace("{count}", preview.untold_count) : t("close_confirm");
    document.getElementById("close-confirm").focus();
  }
  bindButton(document.getElementById("close"), async () => showClose(await api("/d/api/close/preview")));
  bindButton(document.getElementById("close-confirm"), async () => {
    const result = await command("close", {expected_untold: closePreview.untold_count});
    if (result.reason === "count_changed") showClose(result);
    else { closePanel.hidden = true; document.getElementById("latest-report").focus(); }
  });
  document.getElementById("close-back").addEventListener("click", () => { closePanel.hidden = true; document.getElementById("close").focus(); });
  closePanel.addEventListener("keydown", event => {
    if (event.key === "Escape") { closePanel.hidden = true; document.getElementById("close").focus(); }
    if (event.key === "Tab") { event.preventDefault(); const confirm = document.getElementById("close-confirm"), back = document.getElementById("close-back"); (document.activeElement === confirm ? back : confirm).focus(); }
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
      window.NowaHours.sync(day);
    }
    const timing = document.getElementById("timing");
    for (const name of ["usual_visit_min", "safe_drive_min", "cushion_min"]) field(timing, name).value = current[name] ?? "";
    const few = n => Number.isInteger(n) && n >= 3 && n <= 10;
    const unit = (name, n) => t("unit_" + name + (few(n) ? "_few" : "_many"));
    for (const output of document.querySelectorAll("[data-learned]")) {
      const key = output.dataset.learned, learned = current.learned[key];
      const value = Number(learned.value.toFixed(1));
      output.textContent = t("learned_" + key + "_value").replace("{value}", value).replace("{n}", learned.n)
        .replace("{minutes}", unit("minutes", value)).replace("{evenings}", unit("evenings", learned.n)).replace("{visits}", unit("visits", learned.n));
      if (learned.still_learning) output.textContent += " · " + t("still_learning");
    }
    const info = document.getElementById("info");
    for (const name of ["address", "address_en"]) field(info, name).value = current[name] || "";
    for (const name of ["price", "what_to_bring", "other"]) field(info, name).value = current.items.find(i => i.key === name)?.text || "";
    for (const text of info.querySelectorAll("[data-counter]")) text.nowaCounter?.();
    field(document.getElementById("lang"), "lang").value = current.lang;
    const select = document.getElementById("saved-overrides");
    select.replaceChildren();
    for (const override of current.overrides) {
      const row = document.createElement("div"); row.className = "saved-override";
      const date = document.createElement("button"); date.type = "button"; date.className = "quiet-link";
      date.textContent = override.date_display;
      bindButton(date, () => {
        const form = document.getElementById("overrides");
        for (const name of ["date", "start", "end"]) field(form, name).value = override[name] || "";
        field(form, "closed").checked = override.closed;
      });
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "btn btn-ghost";
      remove.textContent = t("delete_override"); remove.setAttribute("aria-label", t("delete_override") + " " + override.date_display);
      bindButton(remove, async () => {
        await api("/d/api/settings/overrides/" + override.date, "DELETE", {}, intent());
        await loadSettings(); message(t("saved"));
      });
      row.append(date, remove); select.append(row);
    }
  }
  async function saveSettings(kind, payload) {
    await api("/d/api/settings/" + kind, "PUT", payload, intent());
    message(t("saved"));
    if (kind === "lang") location.assign("/d/settings?lang=" + payload.lang); else await loadSettings();
  }
  bindForm("hours", form => saveSettings("hours", {hours: window.NowaHours.values(form)}));
  bindForm("overrides", (form, body) => saveSettings("overrides", {date: body.date, closed: field(form, "closed").checked, start: body.start ? window.NowaFeedback.digits(body.start) : null, end: body.end ? window.NowaFeedback.digits(body.end) : null}));
  bindForm("timing", (_, body) => saveSettings("timing", {usual_visit_min: Number(window.NowaFeedback.digits(body.usual_visit_min)), safe_drive_min: Number(window.NowaFeedback.digits(body.safe_drive_min)), cushion_min: Number(body.cushion_min), max_per_evening: null}));
  bindForm("info", (_, body) => saveSettings("info", {address: body.address, address_en: body.address_en, items: Object.entries(body).filter(([key, text]) => !["address", "address_en"].includes(key) && text !== "").map(([key, text]) => ({key, text}))}));
  bindForm("lang", (_, body) => saveSettings("lang", body));
  const telegramButton = document.getElementById("telegram");
  if (telegramButton) telegramButton.addEventListener("click", () => window.NowaFeedback.pending(telegramButton, async () => {
    const data = await api("/d/api/telegram-link", "POST", {}, intent());
    const link = document.getElementById("telegram-url");
    if (data.url) {
      window.open(data.url, "_blank", "noopener");
      link.href = data.url; link.hidden = false; return t("telegram_fallback");
    }
    return t("telegram_repeated");
  }, document.getElementById("telegram-status")));
  loadSettings().catch(error => message(error.message));
}

const sandboxControls = document.getElementById("sandbox-controls");
if (sandboxControls) {
  const clock = document.getElementById("sandbox-clock");
  window.NowaClock(clock, clock.dataset.iso, t("clock_format"));
  const slug = document.body.dataset.clinicSlug;
  const pageURL = new URL(location.href); pageURL.searchParams.set("clinic", slug);
  history.replaceState(null, "", pageURL);
  async function advance(minutes) {
    if (minutes < 1) return;
    // The worker owns due timers; each bounded command only advances its clock.
    while (minutes > 0) {
      const chunk = Math.min(minutes, 180);
      const result = await api("/d/api/sandbox/advance", "POST", {minutes: chunk}, intent());
      window.NowaClock(clock, result.now, t("clock_format")); minutes -= chunk;
    }
    await refresh();
  }
  for (const button of sandboxControls.querySelectorAll("[data-advance]")) bindButton(button, () => advance(Number(button.dataset.advance)));
  bindButton(document.getElementById("sandbox-jump"), () => advance(Math.ceil((Date.parse(sandboxControls.dataset.paperStart) - Date.parse(clock.dataset.iso)) / 60000)));
  window.NowaPhone(document.getElementById("sandbox-phone"), "/d/api/sandbox/phone", status => {
    if (status === 401) {
      fetch("/c/" + encodeURIComponent(slug)).then(response => { if (response.status === 410) message(document.getElementById("sandbox-expired").textContent); else location.assign("/d/login?lang=" + document.documentElement.lang); }).catch(() => message(t("error")));
    } else message(t("error"));
  });
}


function questionIcon(kind) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", "action-icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use"); use.setAttribute("href", "#i-" + kind); svg.append(use); return svg;
}
async function loadQuestions(outcome = "") {
  const panel = document.getElementById("questions"); if (!panel) return;
  const data = await api("/d/api/questions"); panel.replaceChildren();
  if (outcome) { const line = document.createElement("p"); line.className = "local-feedback"; line.setAttribute("role", "status"); line.textContent = outcome; panel.append(line); line.scrollIntoView?.({block: "nearest"}); }
  if (!data.length) { const empty = document.createElement("p"); empty.textContent = t("empty_questions"); panel.append(empty); }
  for (const state of ["open", "later"]) {
    const group = document.createElement("section"); group.dataset.group = state;
    const questions = data.filter(question => question.status === state);
    if (state === "later" && questions.length) { const heading = document.createElement("h3"); heading.textContent = t("later_group"); group.append(heading); }
    for (const question of questions) {
      const card = document.createElement("form"); card.className = "ask"; card.noValidate = true; card.dataset.questionId = question.id;
      const title = document.createElement("p"); title.textContent = question.text_display; card.append(title);
      for (const asker of (question.askers || []).slice(0, 3)) {
        const line = document.createElement("p"); line.textContent = asker.name && asker.queue_number != null && asker.day ? t("question_asker").replace("{name}", asker.name).replace("{number}", asker.queue_number).replace("{day}", asker.day) : t("question_anonymous"); globalThis.NowaText?.(line, line.textContent); card.append(line);
      }
      if ((question.askers || []).length > 3) { const more = document.createElement("p"); more.textContent = "+" + (question.askers.length - 3); card.append(more); }
      if (question.count > 1) { const count = document.createElement("span"); count.textContent = question.count; card.append(count); }
      const draft = document.createElement("textarea"); draft.minLength = 1; draft.maxLength = 1000; draft.required = true; draft.value = question.draft_answer || ""; draft.setAttribute("aria-label", t("q_answer")); draft.hidden = !question.answering_at; card.append(draft);
      const acts = document.createElement("div"); acts.className = "acts"; card.append(acts);
      for (const action of ["draft", "save", "later", "dismiss"]) {
        const button = document.createElement("button"); button.type = "button";
        button.append(questionIcon({draft: "chat", save: "check", later: "pause", dismiss: "back"}[action]), document.createTextNode(t(action === "draft" ? "q_answer" : "q_" + action)));
        button.disabled = action === "save" && (!question.draft_answer || state !== "open") || action === "later" && state === "later";
        bindButton(button, async () => {
          if (action === "draft" && draft.hidden) { draft.hidden = false; draft.focus(); return t("q_answer_prompt"); }
          if (action === "draft" && !draft.value.trim()) throw new Error(t("q_text_only"));
          const result = await api("/d/api/questions/" + question.id + "/" + action, "POST", action === "draft" ? {text: draft.value.trim()} : {}, intent());
          const outcomeKey = {saved: "q_saved", later: "q_deferred", dismiss: "q_dismissed", draft_ready: "q_draft_ready"}[result.reason] || "q_" + result.reason;
          const outcome = t(outcomeKey);
          message(outcome); await loadQuestions(outcome); return outcome;
        }); acts.append(button);
      }
      card.addEventListener("submit", event => event.preventDefault()); group.append(card);
    }
    panel.append(group);
  }
}
if (document.getElementById("questions")) loadQuestions().catch(error => message(error.message));
if (document.body.dataset.mode === "report") {
  api("/d/api/report/" + document.body.dataset.eveningId).then(data => {
    const summary = document.getElementById("report-summary");
    for (const [key, label] of [["standby_taken", "report_standby_taken"], ["booked", "report_booked"], ["seen_booked", "report_seen"], ["cancelled", "report_cancelled"], ["cancelled_at_close", "report_close_cancelled"], ["no_show_count", "report_no_show"], ["walk_ins", "report_walk_ins"], ["total_seen", "report_total"], ["doctor_arrival_display", "report_arrival"], ["clinic_start_display", "report_start"], ["avg_visit", "report_avg_visit"], ["avg_wait", "report_avg_wait"]]) {
      if (data[key] == null) continue;
      const card = document.createElement("article"); card.className = "card report-metric";
      const name = document.createElement("span"); name.textContent = t(label);
      const value = document.createElement("b"); value.className = "num ltr"; value.dir = "ltr"; value.textContent = data[key]; card.append(name, value); summary.append(card);
    }
    for (const [key, label] of [["no_show_names", "report_no_show"], ["failed_names", "report_failed"]]) {
      if (!data[key]?.length) continue;
      const line = document.createElement("p"); line.textContent = t(label) + ": " + data[key].join(", "); globalThis.NowaText?.(line, line.textContent); summary.append(line);
    }
    for (const row of data.origins || []) {
      const line = document.createElement("p");
      line.textContent = row.queue_number + " · " + row.origin_display;
      globalThis.NowaText?.(line, line.textContent); summary.append(line);
    }
    const list = document.getElementById("health-answers");
    for (const answer of data.health_answers) {
      const card = document.createElement("article"); card.className = "card section health-answer";
      const question = document.createElement("h3"); question.textContent = answer.question;
      const reply = document.createElement("p"); reply.textContent = answer.answer;
      const time = document.createElement("time"); time.className = "muted num ltr"; time.textContent = answer.at_display;
      const link = document.createElement("a"); link.className = "health-source"; link.textContent = answer.source_label;
      if (answer.source_url) { const url = new URL(answer.source_url); if (url.protocol === "https:") { link.href = url.href; link.rel = "noreferrer"; } }
      card.append(question, reply, time, link); list.append(card);
    }
  }).catch(error => message(error.message));
}
window.NowaFeedback.counters(document, labels);
