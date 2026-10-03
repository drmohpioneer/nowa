"use strict";
(() => {
  const form = document.getElementById("judge-form"), status = document.getElementById("signup-message");
  const labels = Object.fromEntries([...document.querySelectorAll("#signup-translations [data-key]")].map(el => [el.dataset.key, el.textContent]));
  form.addEventListener("submit", async event => {
    event.preventDefault(); const button = form.querySelector("button"); if (button.disabled) return;
    button.disabled = true;
    try {
      const response = await fetch("/judge/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: form.elements.code.value})});
      const data = await response.json(); if (!response.ok || !data.signup_token) throw new Error(labels.error);
      sessionStorage.setItem("nowa-judge-signup", data.signup_token);
      const explicit = new URL(location.href).searchParams.get("lang");
      location.assign("/start" + (["ar", "en"].includes(explicit) ? "?lang=" + explicit : ""));
    } catch (error) { status.textContent = error.message; button.disabled = false; }
  });
})();
