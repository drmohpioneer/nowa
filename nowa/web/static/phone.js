"use strict";
function patientTime(value) {
  const time = new Date(value).toLocaleTimeString("en-US", {timeZone: "Africa/Cairo", hour: "numeric", minute: "2-digit", hour12: true});
  return document.documentElement.lang === "ar" ? time.replace("AM", phoneLabels.time_am).replace("PM", phoneLabels.time_pm) : time;
}
const phoneCards = new WeakMap();
const phoneLabels = Object.fromEntries([...document.querySelectorAll("#phone-translations [data-key]")].map(el => [el.dataset.key, el.textContent]));
window.NowaPhoneCards = function (element, messages) {
  let cards = phoneCards.get(element);
  if (!cards) { cards = new Map(); phoneCards.set(element, cards); }
  for (const msg of messages) {
    let card = cards.get(msg.outbox_id), fresh = !card;
    if (!card) { card = document.createElement("article"); card.className = "tg-msg"; cards.set(msg.outbox_id, card); element.append(card); }
    const title = document.createElement("strong"); title.textContent = msg.recipient_name || msg.recipient; window.NowaText?.(title, title.textContent);
    const body = document.createElement("p"); body.setAttribute("dir", document.documentElement.dir);
    const pattern = /(?:https?:\/\/[^\s]+)?\/([lwr])\/([A-Za-z0-9_-]{22})(?![A-Za-z0-9_-])/g;
    let at = 0;
    for (const match of msg.body.matchAll(pattern)) {
      const text = document.createElement("span"); text.textContent = msg.body.slice(at, match.index).trim(); window.NowaText?.(text, text.textContent); body.append(text);
      const link = document.createElement("a"); link.href = "/" + match[1] + "/" + match[2];
      link.textContent = phoneLabels[{l: "link_booking", w: "link_way", r: "link_rebook"}[match[1]]];
      link.className = "link-chip"; link.target = "_blank"; link.rel = "noopener noreferrer"; body.append(link); at = match.index + match[0].length;
    }
    const tail = document.createElement("span"); tail.textContent = msg.body.slice(at).trim(); window.NowaText?.(tail, tail.textContent); body.append(tail);
    const status = document.createElement("small"); status.className = "tg-meta";
    const shownTime = element.closest?.(".chat-wrap") ? patientTime(msg.created_at) : new Date(msg.created_at).toLocaleTimeString("en-GB", {timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit"});
    status.textContent = shownTime + " · " + (msg.status === "failed" ? phoneLabels.failed : msg.status === "delivered" ? "✓✓" : "✓");
    const avatar = document.createElement("span"); avatar.className = "tg-av";
    avatar.textContent = (msg.recipient_name || msg.recipient || "").slice(0, 1);
    const content = document.createElement("div"), who = document.createElement("div"); who.className = "tg-who"; who.append(title);
    const bubble = document.createElement("div"); bubble.className = "tg-bubble"; bubble.setAttribute("dir", document.documentElement.dir); bubble.append(body, status);
    content.append(who, bubble); card.replaceChildren(avatar, content);
    if (fresh) { card.classList.add("is-new"); setTimeout(() => card.classList.remove("is-new"), 300); }
  }
};
window.NowaPhone = function (element, url, onError) {
  let after = 0, stopped = false;
  async function poll() {
    if (stopped) return;
    try {
      const response = await fetch(url + (url.includes("?") ? "&" : "?") + "after_id=0");
      if (stopped) return;
      if (!response.ok) { stopped = true; onError(response.status); return; }
      const messages = await response.json();
      if (stopped) return;
      window.NowaPhoneCards(element, messages);
      for (const msg of messages) after = Math.max(after, msg.outbox_id);
    } catch (error) { if (!stopped) onError(null); }
    if (!stopped) setTimeout(poll, 2000);
  }
  poll();
  return () => { stopped = true; return after; };
};
