"use strict";
const config = JSON.parse(document.getElementById("chat-config").textContent);
const texts = config.demo_strings;
const base = "/c/" + encodeURIComponent(config.slug);
const chat = document.getElementById("chat"), controls = document.getElementById("controls");
const error = document.getElementById("error");
let session, locked = false;
// A bubble takes its direction from its own first letter, not from the page language.
const textDirection = text => { const letter = /[A-Za-z\u0590-\u08FF]/.exec(String(text)); return letter ? (/[A-Za-z]/.test(letter[0]) ? "ltr" : "rtl") : document.documentElement.dir; };
function line(text, mine = false) { const p = document.createElement("div"); p.className = mine ? "bubble me" : "bubble"; p.textContent = text; window.NowaText?.(p, text); p.setAttribute("dir", textDirection(text)); chat.insertBefore(p, controls); p.scrollIntoView?.({block: "nearest"}); }
async function tap(action, payload) {
  if (locked) return null;
  const response = await fetch(base + "/tap", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session, idempotency_key: crypto.randomUUID(), action, payload})}).catch(() => { throw new Error(texts.error); });
  const data = await response.json();
  if (!response.ok) throw window.NowaFeedback.requestError(response, data, texts, texts.error);
  return data;
}
function button(label, parent, callback) {
  const b = document.createElement("button"); b.textContent = label; parent.append(b);
  b.onclick = () => window.NowaFeedback.pending(b, async () => { line(label, true); return callback(); }, error, {});
  return b;
}
function identities() {
  telegramLink?.destroy(); controls.replaceChildren();
  config.fictional_names.forEach((name, identity) => {
    button(texts.book_as.replace("{name}", name), controls, async () => show(await tap("none", {identity})));
  });
}
let telegramLink = null;
function show(data) {
  if (!data || locked) return "";
  line(data.reply); telegramLink?.destroy(); controls.replaceChildren();
  if (data.state === "locked_emergency") {
    locked = true;
    document.querySelector(".chat-wrap")?.setAttribute("data-emergency-locked", "true");
    for (const el of document.querySelectorAll("button,input,select,textarea")) el.disabled = true;
    for (const a of document.querySelectorAll("a:not(.legal a)")) { a.removeAttribute("href"); a.setAttribute("aria-disabled", "true"); }
    const call = document.createElement("a"); call.href = "tel:123"; call.className = "btn btn-main";
    call.textContent = config.strings[data.lang].call_emergency; controls.append(call);
    call.scrollIntoView?.({block: "nearest"}); return "";
  }
  if (data.booking_confirmed) document.getElementById("chat-phone").hidden = false;
  if (data.telegram_url) {
    const cta = document.createElement("div"); cta.className = "tg-cta"; controls.append(cta);
    telegramLink = window.NowaTelegramLink(cta, data.telegram_url, config.strings[data.lang], {
      openLabel: config.open_telegram[data.lang],
      renew: async url => {
        const response = await fetch(base + "/tap", {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({session, idempotency_key: crypto.randomUUID(), action: "none", payload: {telegram_renew: url}})});
        if (!response.ok) throw window.NowaFeedback.requestError(response, await response.json(), config.strings[data.lang], config.strings[data.lang].error);
        return (await response.json()).telegram_url;
      },
    });
    const note = document.createElement("p"); note.textContent = config.strings[data.lang].telegram_note || "";
    cta.append(note);
  }
  const row = document.createElement("div"); row.className = "conversation-buttons"; controls.append(row);
  for (const b of data.buttons) {
    const el = button(b.label, row, async () => show(await tap(b.action.kind, b.action.payload)));
    el.className = b.action.kind === "confirm" ? "btn btn-main" : "btn btn-ghost";
  }
  if (!data.buttons.length && !data.booking_confirmed) identities();
  controls.scrollIntoView?.({block: "nearest"});
  return "";
}

(async () => {
  try {
    const response = await fetch(base + "/session?lang=" + (config.lang || "ar"), {method: "POST"}).catch(() => { throw new Error(texts.error); });
    if (!response.ok) throw new Error(String(response.status));
    session = (await response.json()).session; identities();
    for (const faq of config.faq) button(faq.label, document.getElementById("faq"), async () => {
      const data = await tap("none", faq.action.payload); line(data.reply);
      return "";
    });
    window.NowaPhone(document.getElementById("phone"), base + "/demo/phone?session=" + encodeURIComponent(session),
      () => { error.textContent = texts.phone_error; });
  } catch { error.textContent = texts.start_error; }
})();
