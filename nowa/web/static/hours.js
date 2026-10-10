"use strict";
window.NowaHours = {
  sync(row) {
    const closed = !row.querySelector('[name="enabled"]').checked;
    row.classList.toggle("is-closed", closed);
    row.querySelector(".hours-times").hidden = closed;
    const text = row.querySelector('[name="enabled"]').nextElementSibling;
    if (text?.dataset?.on) text.textContent = closed ? text.dataset.off : text.dataset.on;
    const day = row.querySelector(".hours-day")?.textContent;
    if (text?.dataset?.on && day) row.querySelector('[name="enabled"]').setAttribute("aria-label", day + ": " + text.textContent);
  },
  values(root) {
    return [...root.querySelectorAll("[data-weekday]")]
      .filter(row => row.querySelector('[name="enabled"]').checked)
      .map(row => ({weekday: Number(row.dataset.weekday),
        start: window.NowaFeedback.digits(row.querySelector('[name="start"]').value),
        end: window.NowaFeedback.digits(row.querySelector('[name="end"]').value)}));
  }
};
for (const row of document.querySelectorAll("[data-weekday]")) {
  row.querySelector('[name="enabled"]').addEventListener("change", () => window.NowaHours.sync(row));
  window.NowaHours.sync(row);
  for (const input of row.querySelectorAll?.("[data-time]") || []) {
    input.addEventListener("blur", () => { input.value = window.NowaFeedback.normalTime(input.value); });
  }
}
