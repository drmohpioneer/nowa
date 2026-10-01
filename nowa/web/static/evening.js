"use strict";
const texts = JSON.parse(document.getElementById("demo-texts").textContent);
let run = JSON.parse(sessionStorage.getItem("nowa-watch") || "null"), minute = 0;
let playing = Boolean(run?.playing), busy = false, timer;
const error = document.getElementById("error"), phoneElements = new Map();
function remember() { if (run) { run.playing = playing; sessionStorage.setItem("nowa-watch", JSON.stringify(run)); } }
async function call(path, body) {
  const response = await fetch(path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
  if (!response.ok) throw new Error(texts.watch_error + " (" + response.status + ")");
  return response.json();
}
function show(data) {
  minute = data.minute;
  document.getElementById("status").textContent = new Date(data.clock).toLocaleString("ar-EG", {timeZone: "Africa/Cairo"}) + " · " + texts.travel + " " + data.doctor_travel_min + " " + texts.minutes + " · " + (data.closed ? texts.closed : texts.minutes + " " + minute);
  const queue = document.getElementById("queue"); queue.replaceChildren();
  for (const row of data.queue) { const p = document.createElement("p"); p.className = "qrow" + (["seen", "didnt_come", "cancelled"].includes(row.state) ? " done" : ""); p.textContent = row.queue_number + " · " + (row.patient_first_name || texts.walkin) + " · " + row.state + " · " + (row.expected_shown ? new Date(row.expected_shown).toLocaleTimeString("ar-EG", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"}) : "") + " · " + (row.no_show_count ? "⚠ " + row.no_show_count : ""); queue.append(p); }
  const groups = new Map();
  for (const message of data.phones) {
    if (!groups.has(message.recipient)) groups.set(message.recipient, []);
    groups.get(message.recipient).push(message);
  }
  for (const [recipient, messages] of groups) {
    let phone = phoneElements.get(recipient);
    if (!phone) { phone = document.createElement("section"); phone.className = "phone card thread"; phone.setAttribute("aria-label", recipient); phoneElements.set(recipient, phone); document.getElementById("phones").append(phone); }
    window.NowaPhoneCards(phone, messages);
  }
  const timeline = document.getElementById("timeline"); timeline.replaceChildren();
  for (const event of data.timeline) { const li = document.createElement("li"); li.className = "row"; li.textContent = new Date(event.at).toLocaleTimeString("ar-EG", {timeZone: "Africa/Cairo"}) + " · " + event.kind; timeline.append(li); }
  const report = document.getElementById("report"); report.hidden = !data.report_url;
  if (data.report_url) report.href = data.report_url;
  if (data.closed) pause();
}
async function load() { show(await call("/demo/evening/" + run.run_id + "/state?token=" + encodeURIComponent(run.token))); }
async function start() {
  const intent = sessionStorage.getItem("nowa-watch-intent") || crypto.randomUUID();
  sessionStorage.setItem("nowa-watch-intent", intent);
  run = await call("/demo/evening/start", {idempotency_key: intent});
  sessionStorage.removeItem("nowa-watch-intent"); remember(); await load();
}
function pause() { playing = false; remember(); clearTimeout(timer); }
async function tick() {
  if (!playing || busy) return; busy = true;
  try { show(await call("/demo/evening/" + run.run_id + "/advance", {token: run.token, to_minute: Math.min(600, minute + Number(document.getElementById("speed").value))})); }
  catch (e) { error.textContent = e.message; pause(); }
  finally { busy = false; if (playing) timer = setTimeout(tick, 500); }
}
document.getElementById("play").onclick = async () => {
  if (busy || playing) return; busy = true;
  try { error.textContent = ""; if (!run) await start(); playing = true; remember(); }
  catch (e) { error.textContent = e.message; } finally { busy = false; if (playing) tick(); }
};
document.getElementById("pause").onclick = pause;
document.getElementById("restart").onclick = async () => {
  if (busy) return; pause(); busy = true; sessionStorage.removeItem("nowa-watch-intent");
  try { document.getElementById("phones").replaceChildren(); phoneElements.clear(); await start(); }
  catch (e) { error.textContent = e.message; } finally { busy = false; }
};
if (run) load().then(() => { if (playing) tick(); }).catch(e => { error.textContent = e.message; pause(); });
