"use strict";
const config = JSON.parse(document.getElementById("chat-config").textContent);
const base = "/c/" + encodeURIComponent(config.slug);
let session, lang = "ar", history = [], areaId = null;
const chat = document.getElementById("chat"), controls = document.getElementById("controls");
const error = document.getElementById("error"), send = document.getElementById("send");
const bookChip = document.getElementById("book-chip");
const strings = () => config.strings[lang];
function line(text, mine = false) { const p = document.createElement("div"); p.className = mine ? "bubble me" : "bubble"; p.textContent = text; chat.insertBefore(p, controls); }
function labels() {
    send.setAttribute("aria-label", strings().send);
    document.getElementById("message").placeholder = strings().message;
    bookChip.textContent = strings().book_chip;
    document.getElementById("chat-emergency").textContent = strings().emergency;
    document.getElementById("message-label").textContent = strings().message;
    document.documentElement.lang = lang === "ar" ? "ar" : "en";
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
}
async function post(path, data) {
    const response = await fetch(base + path, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)});
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
}
async function command(path, data) {
    error.textContent = "";
    return post(path, {session, idempotency_key: crypto.randomUUID(), ...data});
}
function distance(a, lat, lng) {
    const rad = Math.PI / 180;
    const dlat = (a.lat - lat) * rad, dlng = (a.lng - lng) * rad;
    return Math.sin(dlat / 2) ** 2 + Math.cos(lat * rad) * Math.cos(a.lat * rad) * Math.sin(dlng / 2) ** 2;
}
function lookupForm() {
    const f = document.createElement("form"); f.className = "card";
    const name = document.createElement("input"), last4 = document.createElement("input");
    name.required = true; name.maxLength = 60; name.placeholder = strings().name;
    name.setAttribute("aria-label", strings().name);
    last4.required = true; last4.pattern = "[0-9]{4}"; last4.maxLength = 4;
    last4.inputMode = "numeric"; last4.placeholder = strings().last4;
    last4.setAttribute("aria-label", strings().last4);
    const submit = document.createElement("button"); submit.textContent = strings().submit_lookup;
    f.append(name, last4, submit); controls.append(f);
    f.onsubmit = async e => { e.preventDefault(); submit.disabled = true;
        try { show(await command("/lookup", {name: name.value, last4: last4.value})); }
        catch { error.textContent = strings().error; submit.disabled = false; }
    };
}
function show(data) {
    lang = data.lang; labels(); line(data.reply); controls.replaceChildren();
    areaId = data.buttons.find(b => b.action.kind === "book_day")?.action.payload.area_id ?? null;
    const days = [], needsConsent = data.buttons.some(b => b.action.kind === "consent");
    const draft = data.buttons.find(b => b.action.kind === "book_day")?.action.payload.draft;
    if (draft) { const p = document.createElement("p"); p.textContent = draft.name + " · " + draft.phone; controls.append(p); }
    for (const b of data.buttons) {
        if (b.action.kind === "lookup") { lookupForm(); continue; }
        const el = document.createElement("button"); el.textContent = b.label;
        controls.append(el);
        if (b.action.kind === "book_day") { days.push(el); el.disabled = needsConsent; }
        el.onclick = async () => {
            try {
                if (b.action.kind === "area") {
                    if (b.action.payload.current_location) {
                        navigator.geolocation.getCurrentPosition(position => {
                            const {latitude, longitude} = position.coords;
                            const nearest = config.areas.reduce((a, c) => distance(a, latitude, longitude) <
                                distance(c, latitude, longitude) ? a : c);
                            areaId = nearest.id; el.textContent = nearest[lang === "ar" ? "name_ar" : "name_en"];
                        }, () => { error.textContent = strings().location_error; }, {maximumAge: 0, timeout: 8000});
                    } else { areaId = b.action.payload.area_id;
                        for (const other of controls.querySelectorAll('[aria-pressed]')) other.setAttribute("aria-pressed", "false");
                        el.setAttribute("aria-pressed", "true"); }
                    return;
                }
                if (b.action.kind === "consent") {
                    const consent = await command("/consent", {booking_for: "other"});
                    if (consent.state === "locked_emergency") { show(consent); return; }
                    line(consent.reply); for (const day of days) day.disabled = false; return;
                }
                el.disabled = true;
                show(await command("/tap", {action: b.action.kind, payload: {...b.action.payload,
                    ...(b.action.kind === "book_day" ? {area_id: areaId} : {})}}));
            } catch { error.textContent = strings().error; el.disabled = false; }
        };
    }
    // Health sources are rendered as safe links, never executable markup from a reply.
    const last = data.reply.split("\n").at(-1);
    if (/^https:\/\//.test(last)) {
        const a = document.createElement("a"); a.href = last; a.textContent = data.reply.split("\n").at(-2);
        a.rel = "noopener noreferrer"; a.target = "_blank"; a.className = "bubble"; chat.insertBefore(a, controls);
    }
}
labels(); send.disabled = true;
post("/session", {}).then(data => { session = data.session; send.disabled = false; bookChip.disabled = false; }).catch(() => { error.textContent = strings().error; });
bookChip.onclick = () => submitText(strings().book_text);
for (const b of config.faq) {
    const el = document.createElement("button"); el.textContent = b.label;
    document.getElementById("faq").append(el);
    el.onclick = async () => { if (!session) return; try { show(await command("/tap", {action: "none", payload: b.action.payload})); }
        catch { error.textContent = strings().error; } };
}
async function submitText(text) {
    if (!session || send.disabled) return;
    send.disabled = true; bookChip.disabled = true; controls.replaceChildren(); line(text, true);
    try {
        const data = await command("/turn", {text, history: history.slice(-10)});
        history.push({role: "user", text});
        if (!data.buttons.some(b => ["book_day", "lookup"].includes(b.action.kind))) {
            history.push({role: "assistant", text: data.reply.slice(0, 1000)});
        }
        history = history.slice(-10);
        // Booking and lookup cards never become model context.
        show(data);
    } catch { error.textContent = strings().error; }
    finally { send.disabled = false; bookChip.disabled = false; }
}
document.getElementById("message-form").onsubmit = e => {
    e.preventDefault();
    if (!session || send.disabled) return;
    const input = document.getElementById("message"), text = input.value;
    input.value = "";
    return submitText(text);
};
