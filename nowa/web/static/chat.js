"use strict";
const config = JSON.parse(document.getElementById("chat-config").textContent);
const base = "/c/" + encodeURIComponent(config.slug);
let phoneStarted = false;
const faqChips = [];
let session, lang = config.lang || "ar", history = [], locked = false;
const chat = document.getElementById("chat"), controls = document.getElementById("controls");
const error = document.getElementById("error"), send = document.getElementById("send");
const bookChip = document.getElementById("book-chip");
const strings = () => config.strings[lang];
// A bubble takes its direction from its own first letter, not from the page language.
const textDirection = text => { const letter = /[A-Za-z\u0590-\u08FF]/.exec(String(text)); return letter ? (/[A-Za-z]/.test(letter[0]) ? "ltr" : "rtl") : document.documentElement.dir; };
function line(text, mine = false) { const p = document.createElement("div"); p.className = mine ? "bubble me" : "bubble"; p.textContent = text; window.NowaText?.(p, text); p.setAttribute("dir", textDirection(text)); chat.insertBefore(p, controls); p.scrollIntoView?.({block: "nearest"}); }
function labels() {
    for (const {el, key} of faqChips) el.textContent = strings()["faq_" + key];
    send.setAttribute("aria-label", strings().send);
    document.getElementById("message").placeholder = strings().message;
    bookChip.textContent = strings().book_chip;
    document.getElementById("chat-emergency").textContent = strings().emergency;
    document.getElementById("message-label").textContent = strings().message;
    document.documentElement.lang = lang === "ar" ? "ar" : "en";
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.title = strings().title;
    document.getElementById("faq").setAttribute("aria-label", strings().faq_label);
    document.getElementById("phone")?.setAttribute("aria-label", strings().phone_label);
    const phoneTitle = document.getElementById("phone-title");
    if (phoneTitle) phoneTitle.textContent = strings().phone_label;
    const name = config.names?.[lang];
    if (name) {
        for (const el of document.querySelectorAll("[data-clinic-title]")) el.textContent = strings().clinic_title.replace("{name}", name);
        const greeting = document.getElementById("greeting"); greeting.textContent = strings().greeting.replace("{name}", name); greeting.setAttribute?.("dir", textDirection(greeting.textContent));
    }
    const language = document.getElementById("chat-language");
    if (language) {
        language.textContent = strings().switch_language;
        language.href = "?lang=" + (lang === "ar" ? "en" : "ar") + (document.getElementById("chat-back") ? "&from=demo" : "");
    }
    const back = document.getElementById("chat-back");
    if (back) { back.textContent = strings().back_demo; back.href = "/demo?lang=" + lang; }
}
function emergencyLock() {
    locked = true;
    document.querySelector(".chat-wrap")?.setAttribute("data-emergency-locked", "true");
    for (const el of document.querySelectorAll("button,input,select,textarea")) el.disabled = true;
    for (const a of document.querySelectorAll("a:not(.legal a):not([href='tel:123'])")) { a.removeAttribute("href"); a.setAttribute("aria-disabled", "true"); }
    const call = document.createElement("a"); call.href = "tel:123"; call.className = "btn btn-main";
    call.textContent = strings().call_emergency; controls.replaceChildren(call);
    call.scrollIntoView?.({block: "nearest"});
}
async function post(path, data) {
    const response = await fetch(base + path, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)}).catch(() => { throw new Error(strings().error); });
    const result = await response.json();
    if (!response.ok) throw window.NowaFeedback.requestError(response, result, strings(), strings().error);
    return result;
}
async function command(path, data) {
    error.textContent = "";
    if (locked) return null;
    return post(path, {session, idempotency_key: crypto.randomUUID(), ...data});
}
function distance(a, lat, lng) {
    const rad = Math.PI / 180;
    const dlat = (a.lat - lat) * rad, dlng = (a.lng - lng) * rad;
    return Math.sin(dlat / 2) ** 2 + Math.cos(lat * rad) * Math.cos(a.lat * rad) * Math.sin(dlng / 2) ** 2;
}
function lookupForm(previous = null) {
    const f = document.createElement("form"); f.className = "card";
    const name = document.createElement("input"), last4 = document.createElement("input");
    if (previous) { name.value = previous.name; last4.value = previous.last4; }
    name.required = true; name.maxLength = 60; name.placeholder = strings().name;
    name.setAttribute("aria-label", strings().name);
    last4.required = true; last4.pattern = "[0-9٠-٩۰-۹]{4}"; last4.maxLength = 4;
    last4.inputMode = "numeric"; last4.placeholder = strings().last4;
    last4.setAttribute("aria-label", strings().last4);
    const submit = document.createElement("button"); submit.textContent = strings().submit_lookup;
    f.append(name, last4, submit); controls.append(f);
    f.onsubmit = e => { e.preventDefault();
        return window.NowaFeedback.pending(submit, async () => { line(submit.textContent, true); return show(await command("/lookup", {name: name.value, last4: last4.value}), {name: name.value, last4: last4.value}); }, error);
    };
}
let standbyPoll;
function pollStandby() {
    clearTimeout(standbyPoll);
    standbyPoll = setTimeout(async () => {
        if (locked) return;
        try {
            const data = await command("/tap", {action: "none", payload: {standby_status: true}});
            if (data.standby_pending) pollStandby(); else show(data);
        } catch (_) { error.textContent = strings().error; }
    }, 3000);
}
let telegramLink = null;
function show(data, lookupValues = null) {
    clearTimeout(standbyPoll);
    if (data?.standby_pending) pollStandby();
    if (!data || locked) return "";
    lang = data.lang; labels();
    const body = data.source && data.reply.endsWith("\n" + data.source.label)
        ? data.reply.slice(0, -(data.source.label.length + 1)) : data.reply;
    line(body); telegramLink?.destroy(); controls.replaceChildren();
    if (data.state === "locked_emergency") { emergencyLock(); return ""; }
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
    if (data.booking_confirmed && document.getElementById("chat-phone")) {
        document.getElementById("chat-phone").hidden = false;
        if (!phoneStarted) {
            phoneStarted = true;
            window.NowaPhone(document.getElementById("phone"), base + "/demo/phone?session=" + encodeURIComponent(session),
                () => { error.textContent = config.demo_strings.phone_error; });
        }
    }
    const row = document.createElement("div"); row.className = "conversation-buttons";
    controls.append(row);
    for (const b of data.buttons) {
        if (b.action.kind === "lookup") { lookupForm(lookupValues); continue; }
        if (b.action.kind === "set_area" && b.action.payload.current_location &&
            (!navigator.geolocation || !window.isSecureContext)) continue;
        const el = document.createElement("button"); el.textContent = b.label;
        el.className = b.action.kind === "confirm" ? "btn btn-main" : "btn btn-ghost";
        row.append(el);
        el.onclick = () => window.NowaFeedback.pending(el, async () => {
            if (locked) return "";
            line(b.label, true);
            let payload = b.action.payload;
            if (b.action.kind === "set_area" && payload.current_location) {
                let position;
                try {
                    if (!navigator.geolocation || !window.isSecureContext) throw {code: 1};
                    position = await new Promise((resolve, reject) =>
                        navigator.geolocation.getCurrentPosition(resolve, reject, {maximumAge: 0, timeout: 8000}));
                } catch (cause) {
                    if (locked) return "";
                    const key = cause?.code === 1 ? "location_denied" : cause?.code === 3 ? "location_timeout" : "location_error";
                    line(strings()[key]);
                    return show(data, lookupValues);
                }
                if (locked) return "";
                const {latitude, longitude} = position.coords;
                const nearest = config.areas.reduce((a, c) => distance(a, latitude, longitude) <
                    distance(c, latitude, longitude) ? a : c);
                payload = {area_id: nearest.id};
            }
            return show(await command("/tap", {action: b.action.kind, payload}));
        }, error);
    }
    if (data.source && /^https:\/\//.test(data.source.url)) {
        const a = document.createElement("a"); a.href = data.source.url; a.textContent = data.source.label;
        a.title = data.source.attribution; a.setAttribute("dir", textDirection(a.textContent));
        a.rel = "noopener noreferrer"; a.target = "_blank"; a.className = "bubble"; chat.insertBefore(a, controls);
    }
    controls.scrollIntoView?.({block: "nearest"});
    return "";
}
labels(); send.disabled = true;
post("/session?lang=" + lang, {}).then(data => { session = data.session; send.disabled = false; bookChip.disabled = false;
    const day = new URLSearchParams(location.search).get("day");
    if (day) command("/tap", {action: "book", payload: {date: day}}).then(show).catch(() => { error.textContent = strings().error; }); }).catch(() => { error.textContent = strings().error; });
bookChip.onclick = () => submitText(strings().book_text);
for (const b of config.faq) {
    const el = document.createElement("button"); el.textContent = b.label;
    document.getElementById("faq").append(el);
    faqChips.push({el, key: b.action.payload.faq});
    el.onclick = () => { if (!session || locked) return; return window.NowaFeedback.pending(el, async () => { line(el.textContent, true); return show(await command("/tap", {action: "none", payload: b.action.payload})); }, error); };
}
async function submitText(text) {
    if (!session || send.disabled || locked) return;
    bookChip.disabled = true; bookChip.setAttribute("aria-busy", "true");
    telegramLink?.destroy(); controls.replaceChildren(); line(text, true);
    await window.NowaFeedback.pending(send, async () => {
        const data = await command("/turn", {text, history: history.slice(-10)});
        history.push({role: "user", text});
        if (!data.buttons.some(b => ["book", "set_for", "set_area", "more_days", "confirm", "lookup"].includes(b.action.kind))) {
            history.push({role: "assistant", text: data.reply.slice(0, 1000)});
        }
        history = history.slice(-10);
        // Booking and lookup cards never become model context.
        return show(data);
    }, error);
    bookChip.disabled = locked; send.disabled = locked; bookChip.removeAttribute("aria-busy");
}
document.getElementById("message-form").onsubmit = e => {
    e.preventDefault();
    if (!session || send.disabled || locked) return;
    const input = document.getElementById("message"), text = input.value;
    input.value = "";
    return submitText(text);
};
