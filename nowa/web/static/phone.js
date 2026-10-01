"use strict";
const phoneCards = new WeakMap();
window.NowaPhoneCards = function (element, messages) {
  let cards = phoneCards.get(element);
  if (!cards) { cards = new Map(); phoneCards.set(element, cards); }
  for (const msg of messages) {
    let card = cards.get(msg.outbox_id);
    if (!card) { card = document.createElement("article"); card.className = "bubble"; cards.set(msg.outbox_id, card); element.append(card); }
    const title = document.createElement("strong"); title.textContent = msg.recipient;
    const body = document.createElement("p"); body.textContent = msg.body;
    const status = document.createElement("small"); status.textContent = msg.created_at + " · " + msg.status;
    card.replaceChildren(title, body, status);
    for (const match of msg.body.matchAll(/\/([lwr])\/([A-Za-z0-9_-]{22})(?![A-Za-z0-9_-])/g)) {
      const link = document.createElement("a"); link.href = "/" + match[1] + "/" + match[2];
      link.textContent = match[0]; link.target = "_blank";
      link.rel = "noopener noreferrer"; card.append(link);
    }
  }
};
window.NowaPhone = function (element, url, onError) {
  let after = 0, stopped = false;
  async function poll() {
    try {
      const response = await fetch(url + (url.includes("?") ? "&" : "?") + "after_id=0");
      if (!response.ok) { stopped = true; onError(response.status); return; }
      const messages = await response.json();
      window.NowaPhoneCards(element, messages);
      for (const msg of messages) after = Math.max(after, msg.outbox_id);
    } catch (error) { onError(null); }
    if (!stopped) setTimeout(poll, 2000);
  }
  poll();
  return () => { stopped = true; return after; };
};
