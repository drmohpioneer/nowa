"use strict";
// A view over the server's claim; it never proves a phone or completes sign-up.
window.NowaTelegramLink = function (parent, initialURL, labels, options = {}) {
  const root = document.createElement("div"); root.className = "tg-link";
  const open = document.createElement("a"); open.className = "btn btn-main";
  open.target = "_blank"; open.rel = "noopener"; open.textContent = options.openLabel;
  const renew = document.createElement("button"); renew.type = "button";
  renew.className = "btn btn-main"; renew.textContent = labels.telegram_renew; renew.hidden = true;
  const note = document.createElement("p"); note.textContent = labels.telegram_install;
  const qr = document.createElement("figure"); qr.className = "tg-link-qr";
  const img = document.createElement("img"); img.alt = labels.telegram_scan; img.width = 176; img.height = 176;
  const caption = document.createElement("figcaption"); caption.textContent = labels.telegram_scan;
  qr.append(img, caption);
  const message = document.createElement("p"); message.setAttribute("role", "status");
  const edit = document.createElement("button"); edit.type = "button"; edit.className = "btn btn-ghost";
  edit.textContent = labels.telegram_edit; edit.hidden = true;
  const retry = document.createElement("button"); retry.type = "button"; retry.className = "btn btn-ghost";
  retry.textContent = labels.telegram_retry; retry.hidden = true;
  root.append(open, renew, note, qr, message, edit, retry); parent.append(root);
  const wide = window.matchMedia("(min-width: 900px)");
  let url, timer, expiryTimer, stopped = false, generation = 0, deadline, usable = true, hasQR = false;
  function size() { qr.hidden = !wide.matches || !usable || !hasQR; }
  wide.addEventListener?.("change", size);
  function destroy() { stopped = true; generation++; clearTimeout(timer); clearTimeout(expiryTimer); wide.removeEventListener?.("change", size); }
  function expired() {
    clearTimeout(timer);
    usable = false; open.hidden = true; renew.hidden = !options.renew; size();
  }
  async function poll() {
    const version = generation;
    try {
      const response = await fetch("/telegram/link-status", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({url, qr: !hasQR})});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (stopped || version !== generation) return;
      retry.hidden = true;
      if (data.qr) { img.src = data.qr; hasQR = true; }
      deadline = Math.min(deadline, Date.now() + data.remaining_seconds * 1000);
      clearTimeout(expiryTimer); expiryTimer = setTimeout(expired, Math.max(0, deadline - Date.now()));
      usable = data.usable; open.hidden = !usable; size();
      message.textContent = data.status === "contact_mismatch" ? labels.telegram_mismatch : "";
      edit.hidden = !options.edit || data.status !== "contact_mismatch";
      if (data.status === "linked") {
        message.textContent = options.linkedLabel || labels.telegram_patient_linked;
        edit.hidden = true; renew.hidden = true; destroy(); return;
      }
      if (data.status === "expired" || Date.now() >= deadline) { expired(); return; }
      timer = setTimeout(poll, Math.min(3000, deadline - Date.now()));
    } catch {
      if (stopped || version !== generation) return;
      message.textContent = labels.telegram_error; retry.hidden = false;
      if (Date.now() >= deadline) expired();
    }
  }
  function replace(next) {
    generation++; clearTimeout(timer); url = next; open.href = url;
    deadline = Date.now() + 900000;
    clearTimeout(expiryTimer); expiryTimer = setTimeout(expired, 900000);
    usable = true; hasQR = false;
    img.removeAttribute("src"); open.hidden = false; renew.hidden = true; edit.hidden = true;
    message.textContent = ""; size(); poll();
  }
  renew.onclick = async () => {
    if (stopped || renew.disabled) return;
    renew.disabled = true;
    try { const next = await options.renew(url); if (!stopped) replace(next); }
    catch (error) { if (!stopped) message.textContent = error.message || labels.telegram_error; }
    finally { renew.disabled = false; }
  };
  retry.onclick = () => { retry.hidden = true; clearTimeout(timer); poll(); };
  edit.onclick = () => { destroy(); options.edit(); };
  replace(initialURL);
  return {root, destroy};
};
