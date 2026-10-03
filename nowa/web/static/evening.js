"use strict";
const texts = JSON.parse(document.getElementById("demo-texts").textContent);
const lang = document.documentElement.lang, explicitLang = new URL(location.href).searchParams.get("lang");
const t = (key, values = {}) => (texts[key] || "").replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ""));
const el = id => document.getElementById(id);
const make = (tag, cls = "", text = "") => { const node = document.createElement(tag); node.className = cls; node.textContent = String(text); return node; };
const icon = name => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#i-" + name); svg.setAttribute("aria-hidden", "true"); svg.append(use); return svg;
};
const time = value => new Date(value).toLocaleTimeString("en-GB", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"});
let run = null;
try { run = JSON.parse(sessionStorage.getItem("nowa-watch") || "null"); } catch { sessionStorage.removeItem("nowa-watch"); }
let minute = 0, playing = Boolean(run?.playing), busy = false, timer, speed = 2, lastData = null;
const previousStates = new Map(), messageCards = new Map();
function remember() { if (run) { run.playing = playing; sessionStorage.setItem("nowa-watch", JSON.stringify(run)); } }
function runState() {
  el("stage").dataset.run = lastData?.closed ? "closed" : !lastData ? "idle" : playing ? "playing" : "paused";
  el("play").hidden = playing; el("pause").hidden = !playing;
}
async function call(path, body) {
  const response = await fetch(path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
  if (!response.ok) throw new Error(t("watch_error") + " (" + response.status + ")");
  return response.json();
}
function flash(node, cls) {
  node.classList.add(cls);
  node.addEventListener("animationend", () => node.classList.remove(cls), {once: true});
  // Reduced motion has no animationend. Never leave a stale entrance class behind.
  setTimeout(() => node.classList.remove(cls), 1000);
}
function showRail(data, onWay, arrival) {
  const rail = el("rail"); rail.replaceChildren();
  const first = data.evening.start_minute, last = data.evening.last_minute;
  const ratio = m => Math.max(0, Math.min(100, (m - first) / (last - first) * 100));
  const zero = Date.parse(data.clock) - data.minute * 60000;
  const track = make("div", "track"), fill = make("div", "fill"); fill.style.width = (data.closed ? 100 : ratio(data.minute)) + "%"; track.append(fill); rail.append(track);
  for (const [m, end] of [[first, false], [last, true]]) {
    const tick = make("span", "tick"), number = make("span", "num", time(zero + m * 60000)); number.setAttribute("dir", "ltr"); tick.append(number); tick.style[end ? "insetInlineEnd" : "insetInlineStart"] = "0"; tick.style.transform = "none"; rail.append(tick);
  }
  for (const event of [onWay, arrival].filter(Boolean)) {
    const marker = make("span", "mk"); marker.style.insetInlineStart = ratio((Date.parse(event.at) - zero) / 60000) + "%";
    marker.title = time(event.at); rail.append(marker);
  }
  const now = make("span", "mk now"); now.style.insetInlineStart = (data.closed ? 100 : ratio(data.minute)) + "%"; rail.append(now);
}
function showNow(data, rows) {
  const band = el("now-band"); band.replaceChildren();
  const room = data.in_room ? {...rows.find(row => row.booking_id === data.in_room.booking_id), patient_first_name: data.in_room.first_name, started_at: data.in_room.since} : null, next = rows.find(row => row.remaining);
  for (const [key, row] of [["room", room], ["next", next]]) {
    const cell = make("div", "now-cell" + (room && key === "room" ? " room" : "")); cell.append(make("div", "k", t(key)));
    const value = make("div", "v");
    if (row) {
      value.append(make("span", "num", row.queue_number), make("b", "", row.patient_first_name || t("walkin")));
      const sub = make("div", "s");
      if (key === "next") { const pill = make("span", "state-pill", t(row.state)); pill.dataset.state = row.state; sub.append(pill); }
      if (key === "room" && row.started_at) sub.textContent = t("room_minutes", {m: Math.max(0, Math.floor((Date.parse(data.clock) - Date.parse(row.started_at)) / 60000))});
      cell.append(value, sub);
    } else { value.append(make("b", "", t(key === "room" ? "empty_room" : "no_next"))); cell.append(value); }
    band.append(cell);
  }
  if (data.learned_pace != null) {
    const cell = make("div", "now-cell pace"); cell.append(make("div", "k", t("pace")));
    const value = make("div", "v"); value.append(make("span", "num", data.learned_pace), make("b", "", t("minutes")));
    cell.append(value, make("div", "s", t("learned"))); band.append(cell);
  }
}
function showTiles(data) {
  const rows = data.queue.map(row => ({...row, state: row.booking_id === data.in_room?.booking_id ? "in_room" : row.state}));
  // Display the visit order for walk-ins without changing the engine's order_key.
  const visits = data.timeline.filter(event => event.kind === "who_comes_in" && !event.undone_at && event.booking);
  for (const [index, event] of visits.entries()) {
    if (event.booking.source !== "walkin_tap" || !index) continue;
    const at = rows.findIndex(row => row.booking_id === event.booking.booking_id);
    if (at < 0) continue;
    const [walk] = rows.splice(at, 1);
    const after = rows.findIndex(row => row.booking_id === visits[index - 1].booking.booking_id);
    rows.splice(after + 1, 0, walk);
  }
  const queue = el("queue"); queue.replaceChildren();
  for (const row of rows) {
    const tile = make("div", "tile"); tile.dataset.state = row.state; tile.dataset.bookingId = String(row.booking_id);
    if (row.source === "walkin_tap") tile.dataset.source = "walk_in";
    const name = make("span", "t-name", row.source === "walkin_tap" ? t("walkin") : row.patient_first_name); name.setAttribute("dir", "auto");
    tile.append(make("span", "t-n", row.source === "walkin_tap" ? "+" : row.queue_number), name, make("span", "t-st", t(row.state)));
    if (row.state === "seen") { const check = icon("check"); check.classList.add("t-ic"); tile.prepend(check); }
    if (previousStates.has(row.booking_id) && previousStates.get(row.booking_id) !== row.state) flash(tile, "is-changed");
    previousStates.set(row.booking_id, row.state); queue.append(tile);
  }
}
function messageBody(node, body) {
  // Remove each private URL from printed text. Stage buttons are labels only.
  const pattern = /(?:https?:\/\/[^\s]+)?\/([lwr])\/[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])/g;
  let at = 0;
  for (const match of body.matchAll(pattern)) {
    node.append(make("span", "", body.slice(at, match.index)));
    const chip = make("span", "link-chip", t({l: "link_booking", w: "link_way", r: "link_rebook"}[match[1]])); chip.prepend(icon("link")); node.append(chip); at = match.index + match[0].length;
  }
  node.append(make("span", "", body.slice(at)));
}
function showFeed(data, rows) {
  const feed = el("feed");
  const messages = [...data.phones].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.outbox_id - a.outbox_id);
  const fragments = [];
  for (const msg of messages) {
    let card = messageCards.get(msg.outbox_id), fresh = !card;
    if (!card) { card = make("div", "tg-msg"); messageCards.set(msg.outbox_id, card); }
    const doctor = msg.audience === "doctor", row = doctor ? null : rows.find(row => row.booking_id === msg.booking_id);
    const name = doctor ? t("doctor") : msg.recipient_name;
    card.dataset.status = msg.status;
    const avatar = make("span", "tg-av" + (doctor ? " doc" : ""), name?.slice(0, 1) || "");
    const content = make("div"), who = make("div", "tg-who"); who.append(make("b", "", name));
    if (row) who.append(make("span", "muted", t("number", {n: row.queue_number})));
    who.append(make("span", "t num", time(msg.created_at)));
    const bubble = make("div", "tg-bubble"); messageBody(bubble, msg.body);
    const meta = make("div", "tg-meta");
    if (msg.status === "failed") meta.append(make("span", "tg-fail", t("failed")));
    else meta.append(make("span", "num", time(msg.created_at)), make("span", "tick", msg.status === "delivered" ? "✓✓" : "✓"));
    bubble.append(meta); content.append(who); if (msg.label && texts[msg.label]) content.append(make("span", "tg-kind", t(msg.label))); content.append(bubble); card.replaceChildren(avatar, content);
    if (fresh) flash(card, "is-new"); fragments.push(card);
  }
  feed.replaceChildren(...fragments); el("message-count").textContent = messages.length;
}
function showTimeline(data, rows) {
  const timeline = el("timeline"); timeline.replaceChildren(); let arrived = false;
  for (const event of data.timeline) {
    if (["booking_created", "chat_in", "chat_out:normal", "question_logged", "message_result", "message_delivery", "send_attempt", "doctor_login", "demo_copy_created"].includes(event.kind)) continue;
    if (event.undone_at) continue;
    const row = event.booking ? {patient_first_name: event.booking.first_name, queue_number: event.booking.queue_number, source: event.booking.source} : rows.find(row => row.booking_id === event.booking_id);
    const values = {name: row?.patient_first_name || t("walkin"), n: row?.queue_number || ""};
    let key = "kind_" + event.kind, isKey = ["doctor_on_my_way", "close_evening"].includes(event.kind);
    if (event.kind === "message_enqueue") {
      // The existing action carries no template id; match against the real phone rows.
      const msg = data.phones.find(msg => msg.booking_id === event.booking_id && Date.parse(msg.created_at) === Date.parse(event.at));
      if (msg?.template_id === "2" && row) { key = "action_leave_now"; isKey = true; }
      else if (msg?.template_id === "5") key = "action_reminder";
      else continue;
    }
    if (event.kind === "message_failure" && !row) key = "failed";
    if (event.kind === "booking_cancelled" && !row) continue;
    if (event.kind === "who_comes_in") { isKey = !arrived; arrived = true; if (row) key = row.source === "walkin_tap" ? "action_walk_in" : "action_named_who"; }
    if (row && event.kind === "patient_on_my_way") key = "action_patient_named_way";
    if (row && event.kind === "patient_undo_on_my_way") key = "action_patient_named_undo";
    if (!texts[key]) continue;
    const line = appendTimeline(timeline, time(event.at), t(key, values), isKey ? "is-key" : ""); line.dataset.eventId = String(event.id);
  }
  appendTimeline(timeline, time(data.clock), t("now"), "is-now");
}
function appendTimeline(timeline, at, text, cls) {
  const line = make("li", "tl-item " + cls), dot = make("span", "tdot"); dot.append(make("i"));
  line.append(make("span", "tm", at), dot, make("span", "tx", text)); timeline.append(line); return line;
}
function showReport(data) {
  el("report-card").hidden = !data.report; if (!data.report) return;
  const stats = el("report-stats"); stats.replaceChildren();
  for (const key of ["booked", "came", "no_show_count", "walk_ins", "avg_wait"]) {
    if (data.report[key] == null) continue;
    const stat = make("div", "big-stat" + (key === "avg_wait" ? " hl" : "")), number = make("b", "num", data.report[key]);
    stat.dataset.stat = key;
    if (key === "avg_wait") number.append(make("small", "", t("minutes")));
    stat.append(number, make("span", "", t("report_" + key))); stats.append(stat);
  }
  const comparison = el("comparison"); comparison.replaceChildren(); comparison.hidden = data.report.avg_wait == null;
  if (!comparison.hidden) {
    for (const withNowa of [true, false]) {
      const line = make("div", "cmp" + (withNowa ? " nowa" : "")), bar = make("span", "bar"), fill = make("i");
      fill.style.width = (withNowa ? Math.min(100, data.report.avg_wait / 229 * 100) : 100) + "%"; bar.append(fill);
      line.append(make("span", "", t(withNowa ? "with_nowa" : "without_nowa")), bar, make("span", "v", withNowa ? data.report.avg_wait + " " + t("minutes") : t("baseline"))); comparison.append(line);
    }
  }
  const link = el("report"); link.hidden = !data.report_url;
  if (data.report_url) link.href = data.report_url + (["ar", "en"].includes(explicitLang) ? "?lang=" + explicitLang : "");
}
function show(data) {
  lastData = data; minute = data.minute;
  if (data.closed) pause();
  runState(); el("idle").hidden = true; el("stage-body").hidden = false; el("rail-wrap").hidden = false;
  el("stage-body").classList.toggle("end-grid", data.closed);
  const clock = time(data.minute < data.evening.start_minute ? data.evening.start_at : data.clock).split(":"); el("clock").replaceChildren(make("span", "", clock[0]), make("span", "colon", ":"), make("span", "", clock[1]));
  // Seed clinic identity is bilingual static copy; metadata is authoritative for other clinics.
  if (lang === "ar") el("clinic-name").textContent = data.clinic.name;
  const onWay = data.timeline.find(e => e.kind === "doctor_on_my_way" && !e.undone_at), arrival = data.timeline.find(e => e.kind === "who_comes_in" && !e.undone_at);
  const doctorState = data.closed ? "closed" : arrival ? "arrived" : onWay ? "on_way" : "waiting";
  el("doctor-chip").dataset.doctor = doctorState;
  el("doctor-label").textContent = t("doctor_" + doctorState, {m: data.doctor_travel_min, time: arrival ? time(arrival.at) : ""});
  el("status").textContent = time(data.clock) + " · " + el("doctor-label").textContent;
  el("queue-heading").textContent = t(data.closed ? "final_queue" : "queue");
  showRail(data, onWay, arrival); showNow(data, data.queue); showTiles(data); showFeed(data, data.queue); showTimeline(data, data.queue); showReport(data);
}
async function load() { show(await call("/demo/evening/" + run.run_id + "/state?token=" + encodeURIComponent(run.token))); }
async function start() {
  const intent = sessionStorage.getItem("nowa-watch-intent") || crypto.randomUUID(); sessionStorage.setItem("nowa-watch-intent", intent);
  run = await call("/demo/evening/start", {idempotency_key: intent}); sessionStorage.removeItem("nowa-watch-intent"); remember(); await load();
}
function pause() { playing = false; remember(); clearTimeout(timer); runState(); }
async function tick() {
  if (!playing || busy) return; busy = true;
  try { show(await call("/demo/evening/" + run.run_id + "/advance", {token: run.token, to_minute: Math.min(600, minute + speed)})); }
  catch (e) { el("error").textContent = e.message; pause(); }
  finally { busy = false; if (playing) timer = setTimeout(tick, 500); }
}
async function replayStart() {
  if (minute < lastData.evening.start_minute) show(await call("/demo/evening/" + run.run_id + "/advance", {token: run.token, to_minute: lastData.evening.start_minute}));
}
async function play() {
  if (busy || playing || lastData?.closed) return; busy = true;
  try { el("error").textContent = ""; if (!run) await start(); await replayStart(); if (!lastData.closed) { playing = true; remember(); runState(); } }
  catch (e) { el("error").textContent = e.message; }
  finally { busy = false; if (playing) tick(); }
}
async function restart() {
  if (busy) return; pause(); busy = true; sessionStorage.removeItem("nowa-watch-intent");
  previousStates.clear(); messageCards.clear();
  try { el("error").textContent = ""; await start(); }
  catch (e) { el("error").textContent = e.message; } finally { busy = false; }
}
el("play").onclick = play; el("start-play").onclick = play; el("pause").onclick = pause;
el("restart").onclick = restart; el("report-restart").onclick = restart;
for (const button of el("speed").querySelectorAll("button")) button.onclick = () => {
  speed = Number(button.dataset.speed); for (const other of el("speed").querySelectorAll("button")) other.setAttribute("aria-pressed", String(other === button));
};
if (run) load().then(async () => { if (playing) { await replayStart(); tick(); } }).catch(e => { el("error").textContent = e.message; pause(); });
