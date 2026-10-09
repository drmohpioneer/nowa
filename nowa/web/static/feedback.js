"use strict";
window.NowaFeedback = (() => {
  const lastErrors = new WeakMap();
  function requestError(response, data, labels, generic) {
    const detail = data.detail || data;
    let text = generic;
    if (response.status === 401 && detail.reason === "refused") text = labels.login_refused || generic;
    else if (response.status === 429) text = labels.too_many_attempts || generic;
    else if (response.status === 422 && detail.fields) text = (labels.check_fields || "") + detail.fields.map(key => labels[key] || labels[key.split(".")[0]] || labels.invalid_field || generic).join(", ");
    const error = new Error(text); error.status = response.status; error.reason = detail.reason; error.fields = detail.fields;
    return error;
  }
  function localStatus(control) {
    const parent = control.closest?.("form, .card, .tools") || control.parentElement;
    if (!parent?.querySelector) return null;
    let status = parent.querySelector(".local-feedback");
    if (!status) { status = document.createElement("p"); status.className = "local-feedback";
      status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite"); control.after(status); }
    return status;
  }
  function digits(value) { return String(value).replace(/[٠-٩۰-۹]/g, char => String(char.charCodeAt(0) - (char <= "٩" ? 1632 : 1776))); }
  function validate(form, labels) {
    // Product validation: novalidate removes browser-language messages.
    for (const field of form.querySelectorAll?.("input,textarea,select") || []) {
      if (field.closest?.("[hidden]") || field.disabled || field.type === "hidden" || field.closest?.("[data-weekday]")?.querySelector('[name="enabled"]')?.checked === false) continue;
      const value = field.value.trim();
      let key = field.required && (field.type === "checkbox" ? !field.checked : !value) ? "required_field" : null;
      if (field.value && !value && ["text", "textarea", "tel"].includes(field.type)) key = "required_field";
      if (field.hasAttribute?.("data-time") && value && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(digits(value))) key = "invalid_field";
      if (value && ((field.minLength > 0 && value.length < field.minLength) || (field.maxLength > 0 && value.length > field.maxLength))) key = "invalid_field";
      if (value && field.pattern && !new RegExp("^(?:" + field.pattern + ")$").test(value)) key = "invalid_field";
      if (value && field.dataset.min != null) {
        const number = digits(value);
        if (!/^\d+$/.test(number) || Number(number) < Number(field.dataset.min) || Number(number) > Number(field.dataset.max)) key = "invalid_field";
      }
      if (value && ["time", "date", "url"].includes(field.type) && !field.validity.valid) key = "invalid_field";
      if (key) { field.focus(); throw new Error(labels[key] || labels.error); }
    }
    for (const row of form.querySelectorAll?.("[data-weekday]") || []) {
      if (row.querySelector('[name="enabled"]').checked && digits(row.querySelector('[name="end"]').value) <= digits(row.querySelector('[name="start"]').value)) throw new Error(labels.hours_order);
    }
  }
  function counters(root, labels) {
    for (const field of root.querySelectorAll?.("[data-counter]") || []) {
      const counter = document.createElement("small"); counter.className = "help counter num"; counter.dir = "ltr"; field.after(counter);
      const update = () => { counter.textContent = labels.limit_counter.replace("{count}", field.value.length).replace("{limit}", field.maxLength); };
      field.nowaCounter = update; field.addEventListener("input", update); update();
    }
  }
  async function pending(control, promiseFactory, statusEl, {errorMap = {}, adjacent = false} = {}) {
    if (control.disabled) return;
    control.disabled = true; control.setAttribute("aria-busy", "true"); control.classList.add("is-busy");
    const topStatus = statusEl;
    if (adjacent) statusEl = localStatus(control) || statusEl;
    topStatus.textContent = ""; statusEl.textContent = "";
    try {
      const result = await promiseFactory();
      lastErrors.delete(statusEl);
      const message = typeof result === "string" ? result : result?.message;
      if (message !== undefined) statusEl.textContent = message;
      else if (adjacent && topStatus !== statusEl) statusEl.textContent = topStatus.textContent;
      return result;
    } catch (error) {
      const text = errorMap[error.status] || error.message;
      if (lastErrors.get(statusEl) === text && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        statusEl.classList.remove("shake");
        void statusEl.offsetWidth; // Restart the animation even on the third identical error.
        statusEl.classList.add("shake");
        statusEl.addEventListener("animationend", () => statusEl.classList.remove("shake"), {once: true});
      }
      lastErrors.set(statusEl, text); statusEl.textContent = text;
    } finally {
      if (adjacent && statusEl.textContent) { topStatus.textContent = statusEl.textContent; statusEl.scrollIntoView?.({block: "nearest", behavior: "smooth"}); }
      control.disabled = control.dataset?.unavailable === "true" || control.closest?.("[data-emergency-locked]") != null; control.removeAttribute("aria-busy"); control.classList.remove("is-busy");
    }
  }
  return {pending, requestError, localStatus, validate, counters, digits};
})();
