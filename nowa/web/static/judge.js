"use strict";
(() => {
  const form = document.getElementById("judge-form"), status = document.getElementById("signup-message");
  const labels = Object.fromEntries([...document.querySelectorAll("#signup-translations [data-key]")].map(el => [el.dataset.key, el.textContent]));
  const explicit = new URL(location.href).searchParams.get("lang");
  let token = "";
  form.addEventListener("submit", async event => {
    event.preventDefault(); const button = form.querySelector("button"); if (button.disabled) return;
    await window.NowaFeedback.pending(button, async () => {
      const response = await fetch("/judge/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: form.elements.code.value})}).catch(() => { throw new Error(labels.error); });
      const data = await response.json();
      if (!response.ok && (data.detail || data).reason === "wrong_code" && labels.judge_wrong_code) {
        form.elements.code.value = "";
        const error = new Error(labels.judge_wrong_code); error.fieldEls = [form.elements.code];
        throw error;
      }
      if (!response.ok) throw window.NowaFeedback.requestError(response, data, labels, labels.error);
      if (!data.signup_token) throw new Error(labels.error);
      token = data.signup_token;
      form.hidden = true; document.getElementById("judge-choice").hidden = false;
    }, status);
  });
  const ownButton = document.getElementById("own-clinic");
  ownButton.addEventListener("click", () => {
    sessionStorage.setItem("nowa-judge-signup", token);
    location.assign("/start" + (["ar", "en"].includes(explicit) ? "?lang=" + explicit : ""));
  });
  const readyButton = document.getElementById("ready-clinic");
  readyButton.addEventListener("click", () => window.NowaFeedback.pending(readyButton, async () => {
    const agree = document.getElementById("ready-agree");
    if (!agree.checked) { const error = new Error(labels.field_agree); error.fieldEls = [agree]; throw error; }
    const response = await fetch("/judge/ready", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({signup_token: token, agree: true})}).catch(() => { throw new Error(labels.error); });
    const data = await response.json();
    if (!response.ok) throw window.NowaFeedback.requestError(response, data, labels, labels.error);
    document.getElementById("ready-chat").href = data.chat_url;
    document.getElementById("ready-poster").href = data.poster_url;
    const shown = document.getElementById("ready-credentials"); shown.replaceChildren();
    const [before, rest] = labels.judge_credentials.split("{mobile}"), [between, after] = rest.split("{password}");
    const part = value => { const el = document.createElement("bdi"); el.dir = "ltr"; el.textContent = value; return el; };
    shown.append(before, part(data.mobile), between, part(data.password), after);
    document.getElementById("judge-choice").hidden = true; document.getElementById("ready-success").hidden = false;
    token = "";
  }, status));
})();
