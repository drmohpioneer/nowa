"use strict";
const config = JSON.parse(document.getElementById("chat-config").textContent);
const texts = config.demo_strings;
const base = "/c/" + encodeURIComponent(config.slug);
const chat = document.getElementById("chat"), controls = document.getElementById("controls");
const error = document.getElementById("error");
let session, selectedDay, selectedArea = null;
function line(text) { const p = document.createElement("div"); p.className = "bubble"; p.textContent = text; chat.insertBefore(p, controls); }
async function tap(action, payload) {
  const response = await fetch(base + "/tap", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session, idempotency_key: crypto.randomUUID(), action, payload})});
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}
function button(label, parent, callback) {
  const b = document.createElement("button"); b.textContent = label; parent.append(b);
  b.onclick = async () => { b.disabled = true; error.textContent = "";
    try { await callback(); } catch { error.textContent = texts.error; }
    finally { b.disabled = false; }
  };
}
function identities() {
  controls.replaceChildren();
  ["Ahmed Ali", "Nour Hassan", "Mona Adel"].forEach((name, identity) => {
    button(texts.book_as.replace("{name}", name), controls, async () => show(await tap("none", {identity})));
  });
}
function show(data) {
  line(data.reply); controls.replaceChildren();
  const days = data.buttons.filter(b => b.action.kind === "book_day");
  if (!days.length) { identities(); return; }
  line(days[0].action.payload.draft.name + " · " + days[0].action.payload.draft.phone);
  for (const day of days) button(day.label, controls, async () => {
    selectedDay = day; controls.replaceChildren(); line(texts.area);
    for (const area of config.areas) button(area.name_ar, controls, async () => { selectedArea = area.id; confirm(); });
    button(texts.area_other, controls, async () => { selectedArea = null; confirm(); });
  });
}
function confirm() {
  controls.replaceChildren(); line(texts.confirm_intro);
  button(texts.confirm, controls, async () => {
    const result = await tap("book_day", {...selectedDay.action.payload, area_id: selectedArea});
    show(result);
  });
  button(texts.change_day, controls, async () => identities());
}
(async () => {
  try {
    const response = await fetch(base + "/session", {method: "POST"});
    if (!response.ok) throw new Error(String(response.status));
    session = (await response.json()).session; identities();
    for (const faq of config.faq) button(faq.label, document.getElementById("faq"), async () => {
      line((await tap("none", faq.action.payload)).reply);
    });
    window.NowaPhone(document.getElementById("phone"), base + "/demo/phone?session=" + encodeURIComponent(session),
      () => { error.textContent = texts.phone_error; });
  } catch { error.textContent = texts.start_error; }
})();
