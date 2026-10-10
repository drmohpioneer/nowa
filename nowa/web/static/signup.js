"use strict";
(() => {
  const labels = Object.fromEntries([...document.querySelectorAll("#signup-translations [data-key]")].map(el => [el.dataset.key, el.textContent]));
  const t = key => labels[key];
  const status = text => { document.getElementById("signup-message").textContent = text; };
  let token = "", mobile = "", pin = null, stopPhone = null, linking = null;
  window.NowaFeedback.counters(document, labels);
  const completionKey = crypto.randomUUID();
  async function post(path, body) {
    const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}).catch(() => { throw new Error(t("error")); });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail || data;
      const specific = {invalid_mobile: t("invalid_mobile"), wrong_code: t("wrong_code"), no_working_days: t("no_working_days")}[detail.reason];
      const generic = specific || (detail.reason === "not open yet" ? t("not_open") : detail.reason === "paste the full link or pick the area" ? t("map_error") : t("error"));
      const error = window.NowaFeedback.requestError(response, data, labels, generic);
      const target = {invalid_mobile: "#code-form [name=mobile]", wrong_code: "#verify-form [name=code]"}[detail.reason];
      if (target && !error.fieldEls) error.fieldEls = [document.querySelector?.(target)].filter(Boolean);
      throw error;
    }
    return data;
  }
  function bind(id, action) {
    const form = document.getElementById(id);
    if (!form) return;
    form.addEventListener("submit", async event => {
      event.preventDefault(); status(""); const button = form.querySelector('button[type="submit"], button:not([type])');
      await window.NowaFeedback.pending(button, () => { window.NowaFeedback.validate(form, labels); return action(form, Object.fromEntries(new FormData(form))); }, document.getElementById("signup-message"), {adjacent: true});
    });
  }
  function ready(value) {
    linking?.destroy();
    token = value;
    document.getElementById("verification").hidden = true;
    document.getElementById("complete-form").hidden = false;
    const judge = document.getElementById("judge-form"); if (judge) judge.hidden = true;
    status("");
  }
  const judgeToken = sessionStorage.getItem("nowa-judge-signup");
  if (judgeToken) { sessionStorage.removeItem("nowa-judge-signup"); ready(judgeToken); }
  bind("judge-form", async (_, data) => { ready((await post("/judge/start", data)).signup_token); });
  bind("code-form", async (_, data) => {
    mobile = data.mobile;
    const result = await post("/signup/code", {...data, lang: document.documentElement.lang});
    linking?.destroy();
    document.getElementById("signup-telegram")?.remove();
    document.getElementById("code-form").hidden = Boolean(result.telegram_url);
    if (result.telegram_url) {
      const card = document.createElement("div"); card.id = "signup-telegram";
      document.getElementById("why-telegram").before(card);
      linking = window.NowaTelegramLink(card, result.telegram_url, labels, {
        openLabel: t("request_code"), linkedLabel: t("telegram_linked"),
        renew: async () => (await post("/signup/code", {mobile, lang: document.documentElement.lang})).telegram_url,
        edit: () => {
          card.remove(); document.getElementById("code-form").hidden = false;
          document.getElementById("verify-form").hidden = true;
          document.getElementById("code-form").elements.mobile.focus();
          status("");
        },
      });
    }
    document.getElementById("verify-form").hidden = false; status(t("sent"));
    const phone = document.getElementById("signup-phone");
    if (phone && !result.telegram_url) { if (stopPhone) stopPhone(); phone.replaceChildren(); phone.hidden = false; stopPhone = window.NowaPhone(phone, "/signup/phone?lang=" + document.documentElement.lang, () => status(t("error"))); }
  });
  bind("verify-form", async (_, data) => { ready((await post("/signup/verify", {...data, mobile})).signup_token); });
  const pinKind = document.getElementById("pin-kind");
  pinKind.addEventListener("change", () => {
    pin = null;
    for (const kind of ["area", "here", "link"]) document.getElementById("pin-" + kind).hidden = pinKind.value !== kind;
  });
  const locate = document.getElementById("locate");
  locate.addEventListener("click", () => window.NowaFeedback.pending(locate, async () => {
    if (!navigator.geolocation) throw new Error(t("location_error"));
    const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, () => reject(new Error(t("location_error"))), {timeout: 10000, maximumAge: 0}));
    pin = {lat: position.coords.latitude, lng: position.coords.longitude};
    return t("here");
  }, document.getElementById("location-status")));
  bind("complete-form", async (form, data) => {
    const hours = window.NowaHours.values(form);
    const body = {signup_token: token, mobile, hours, idempotency_key: completionKey};
    for (const key of ["name_ar", "name_en", "specialty", "address", "address_en", "pin_kind", "map_link", "clinic_phone", "password", "agreement_version"]) body[key] = data[key];
    body.price_egp = Number(window.NowaFeedback.digits(data.price_egp)); body.agree = form.elements.agree.checked;
    if (data.pin_kind === "area") body.area_id = Number(data.area_id);
    if (data.pin_kind === "here" && pin) Object.assign(body, pin);
    const result = await post("/signup/complete", body);
    if (stopPhone) { stopPhone(); stopPhone = null; }
    const phone = document.getElementById("signup-phone");
    if (phone) { phone.replaceChildren(); const final = document.createElement("p"); final.textContent = t("phone_complete"); phone.append(final); }
    linking?.destroy();
    document.getElementById("signup-telegram")?.remove();
    form.hidden = true; document.getElementById("signup-success").hidden = false;
    document.getElementById("chat-url").href = result.chat_url;
    document.getElementById("poster-url").href = result.poster_url;
    document.getElementById("success-mobile").textContent = result.mobile ? t("mobile") + ": " + result.mobile : "";
    status("");
  });
})();
