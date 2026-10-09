"use strict";
(() => {
  const form = document.getElementById("patient-telegram-form");
  if (!form) return;
  const labels = JSON.parse(document.getElementById("linking-texts").textContent);
  const card = document.getElementById("patient-telegram-card");
  const message = document.createElement("p"); message.setAttribute("role", "status"); form.append(message);
  let linking;
  async function mint() {
    const response = await fetch(form.action, {method: "POST", headers: {Accept: "application/json"}, body: new FormData(form)});
    if (!response.ok || response.redirected) throw new Error(labels.telegram_error);
    const data = await response.json();
    if (!data.telegram_url) throw new Error(labels.telegram_error);
    form.elements.form_token.value = data.form_token; form.elements.exp.value = data.exp;
    return data.telegram_url;
  }
  form.addEventListener("submit", async event => {
    event.preventDefault(); const submit = form.querySelector("button");
    if (submit.disabled) return;
    submit.disabled = true; message.textContent = "";
    try {
      const url = await mint(); linking?.destroy(); card.replaceChildren(); form.hidden = true;
      linking = window.NowaTelegramLink(card, url, labels, {openLabel: labels.open_label,
        renew: async () => {
          try { return await mint(); }
          catch (error) { form.hidden = false; throw error; }
        },
      });
    } catch (error) { message.textContent = error.message || labels.telegram_error; }
    finally { submit.disabled = false; }
  });
})();
