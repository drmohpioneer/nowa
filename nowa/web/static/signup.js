"use strict";
(() => {
  const labels = Object.fromEntries([...document.querySelectorAll("#signup-translations [data-key]")].map(el => [el.dataset.key, el.textContent]));
  const t = key => labels[key];
  const status = text => { document.getElementById("signup-message").textContent = text; };
  let token = "", mobile = "", pin = null, stopPhone = null;
  const completionKey = crypto.randomUUID();
  async function post(path, body) {
    const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.reason === "not open yet" ? t("not_open") : data.reason === "paste the full link or pick the area" ? t("map_error") : t("error"));
    return data;
  }
  function bind(id, action) {
    const form = document.getElementById(id);
    if (!form) return;
    form.addEventListener("submit", async event => {
      event.preventDefault(); const button = form.querySelector("button");
      if (button.disabled) return; button.disabled = true;
      try { await action(form, Object.fromEntries(new FormData(form))); }
      catch (error) { status(error.message); }
      finally { button.disabled = false; }
    });
  }
  function ready(value) {
    token = value;
    document.getElementById("verification").hidden = true;
    document.getElementById("complete-form").hidden = false;
    const judge = document.getElementById("judge-form"); if (judge) judge.hidden = true;
    status("");
  }
  bind("judge-form", async (_, data) => { ready((await post("/judge/start", data)).signup_token); });
  bind("code-form", async (_, data) => {
    mobile = data.mobile;
    await post("/signup/code", {...data, lang: document.documentElement.lang});
    document.getElementById("verify-form").hidden = false; status(t("sent"));
    const phone = document.getElementById("signup-phone");
    if (phone) { if (stopPhone) stopPhone(); phone.replaceChildren(); phone.hidden = false; stopPhone = window.NowaPhone(phone, "/signup/phone", () => status(t("error"))); }
  });
  bind("verify-form", async (_, data) => { ready((await post("/signup/verify", {...data, mobile})).signup_token); });
  const pinKind = document.getElementById("pin-kind");
  pinKind.addEventListener("change", () => {
    pin = null;
    for (const kind of ["area", "here", "link"]) document.getElementById("pin-" + kind).hidden = pinKind.value !== kind;
  });
  document.getElementById("locate").addEventListener("click", () => {
    if (!navigator.geolocation) { status(t("location_error")); return; }
    navigator.geolocation.getCurrentPosition(position => {
      pin = {lat: position.coords.latitude, lng: position.coords.longitude};
      document.getElementById("location-status").textContent = t("here");
    }, () => status(t("location_error")), {timeout: 10000, maximumAge: 0});
  });
  bind("complete-form", async (form, data) => {
    const hours = [...form.querySelectorAll("fieldset")].filter(row => row.querySelector('[name="enabled"]').checked).map(row => ({weekday: Number(row.dataset.weekday), start: row.querySelector('[name="start"]').value, end: row.querySelector('[name="end"]').value}));
    const body = {signup_token: token, mobile, hours, idempotency_key: completionKey};
    for (const key of ["name_ar", "name_en", "specialty", "address", "pin_kind", "map_link", "clinic_phone", "password", "agreement_version"]) body[key] = data[key];
    body.price_egp = Number(data.price_egp); body.agree = form.elements.agree.checked;
    if (data.pin_kind === "area") body.area_id = Number(data.area_id);
    if (data.pin_kind === "here" && pin) Object.assign(body, pin);
    const result = await post("/signup/complete", body);
    if (stopPhone) stopPhone();
    form.hidden = true; document.getElementById("signup-success").hidden = false;
    document.getElementById("chat-url").href = result.chat_url;
    document.getElementById("poster-url").href = result.poster_url;
    document.getElementById("success-mobile").textContent = result.mobile ? t("mobile") + ": " + result.mobile : "";
    status("");
  });
})();
