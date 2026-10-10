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
    if (response.status === 422 && detail.fields) error.fieldEls = detail.fields.map(findField).filter(Boolean);
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
  const marks = new WeakMap();
  let markCount = 0;
  function findField(key) {
    try {
      const name = String(key).split(".")[0];
      const field = document.querySelector?.('[name="' + name.replace(/"/g, "") + '"]');
      return field && !field.closest?.("[hidden]") && field.type !== "hidden" ? field : null;
    } catch { return null; }
  }
  function unmark(field) {
    const mark = marks.get(field);
    if (!mark) return;
    mark.node.remove(); field.removeAttribute("aria-invalid"); field.classList?.remove("is-invalid");
    if (mark.described == null) field.removeAttribute("aria-describedby"); else field.setAttribute("aria-describedby", mark.described);
    field.removeEventListener?.("input", mark.clear); field.removeEventListener?.("change", mark.clear);
    marks.delete(field);
  }
  function mark(field, text, {focus = true} = {}) {
    if (!field?.setAttribute || !document.createElement) return;
    unmark(field);
    const node = document.createElement("small");
    node.className = "field-error"; node.id = "field-error-" + (++markCount); node.textContent = text;
    const row = field.closest?.("[data-weekday]");
    if (row) { node.classList.add("hours-error"); row.append(node); }
    else if (field.closest?.("label")) field.closest("label").append(node);
    else field.after?.(node);
    const clear = () => unmark(field);
    marks.set(field, {node, clear, described: field.getAttribute?.("aria-describedby") ?? null});
    field.setAttribute("aria-invalid", "true"); field.classList?.add("is-invalid");
    field.setAttribute("aria-describedby", node.id);
    field.addEventListener?.("input", clear); field.addEventListener?.("change", clear);
    if (focus) {
      // Instant scroll: a smooth one is dropped when the status text changes the layout.
      field.scrollIntoView?.({block: "center", behavior: "auto"});
      field.focus?.({preventScroll: true});
    }
  }
  function fieldLabel(field) {
    let text = "";
    const label = field.closest?.("label");
    if (label?.cloneNode) {
      const clone = label.cloneNode(true);
      clone.querySelectorAll("input,textarea,select,small,.field-error").forEach(node => node.remove());
      text = clone.textContent.replace(/\s+/g, " ").trim();
    }
    if (!text) text = field.getAttribute?.("aria-label") || field.placeholder || field.name || "";
    const day = field.closest?.("[data-weekday]")?.querySelector(".hours-day")?.textContent.trim();
    return day ? day + " (" + text + ")" : text;
  }
  function fill(template, values) { return String(template).replace(/\{(\w+)\}/g, (_, name) => values[name] ?? ""); }
  function fieldProblem(field, value) {
    let key = field.required && (field.type === "checkbox" ? !field.checked : !value) ? (field.type === "checkbox" ? "field_agree" : "field_required") : null, vars = {};
    if (field.value && !value && ["text", "textarea", "tel"].includes(field.type)) key = "field_required";
    if (field.hasAttribute?.("data-time") && value && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(digits(value))) key = "field_time";
    if (value && field.minLength > 0 && value.length < field.minLength) { key = "field_min"; vars = {min: field.minLength}; }
    if (value && field.maxLength > 0 && value.length > field.maxLength) { key = "field_max"; vars = {max: field.maxLength}; }
    if (value && field.pattern && !new RegExp("^(?:" + field.pattern + ")$").test(value)) {
      const count = /\{(\d+)\}$/.exec(field.pattern);
      key = count ? "field_digits" : field.type === "tel" ? "field_mobile" : "field_invalid"; vars = {n: count?.[1]};
    }
    if (value && field.hasAttribute?.("data-egypt-mobile") && !/^(?:\+2|002)?01[0125]\d{8}$/.test(digits(value).replace(/[\s-]/g, ""))) key = "field_mobile";
    if (value && field.dataset.min != null) {
      const number = digits(value);
      if (!/^\d+$/.test(number) || Number(number) < Number(field.dataset.min) || Number(number) > Number(field.dataset.max)) { key = "field_range"; vars = {min: field.dataset.min, max: field.dataset.max}; }
    }
    if (value && ["time", "date", "url"].includes(field.type) && !field.validity.valid) key = "field_invalid";
    return key && {key, vars};
  }
  const generic = {field_required: "required_field", field_agree: "required_field", field_hours_order: "hours_order"};
  function fail(field, labels, key, vars = {}) {
    const template = labels[key] || labels[generic[key] || "invalid_field"] || labels.error;
    const text = fill(template, {...vars, field: fieldLabel(field)});
    mark(field, text);
    const error = new Error(text); error.marked = true;
    return error;
  }
  function validate(form, labels) {
    // Product validation: novalidate removes browser-language messages.
    const fields = form.querySelectorAll?.("input,textarea,select") || [];
    for (const field of fields) unmark(field);
    for (const field of fields) {
      if (field.closest?.("[hidden]") || field.disabled || field.type === "hidden" || field.closest?.("[data-weekday]")?.querySelector('[name="enabled"]')?.checked === false) continue;
      if (field.hasAttribute?.("data-time")) field.value = normalTime(field.value);
      const problem = fieldProblem(field, field.value.trim());
      if (problem) throw fail(field, labels, problem.key, problem.vars);
    }
    for (const row of form.querySelectorAll?.("[data-weekday]") || []) {
      const end = row.querySelector('[name="end"]');
      if (row.querySelector('[name="enabled"]').checked && digits(end.value) <= digits(row.querySelector('[name="start"]').value)) throw fail(end, labels, "field_hours_order");
    }
  }
  function normalTime(value) {
    const text = digits(String(value).trim());
    const match = /^(\d{1,2})(?::?(\d{2}))?$/.exec(text);
    if (!match) return value;
    const hour = match[1].padStart(2, "0");
    return /^(?:[01]\d|2[0-3])$/.test(hour) && match[2] ? hour + ":" + match[2] : value;
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
    let marked = false;
    try {
      const result = await promiseFactory();
      lastErrors.delete(statusEl);
      const message = typeof result === "string" ? result : result?.message;
      if (message !== undefined) statusEl.textContent = message;
      else if (adjacent && topStatus !== statusEl) statusEl.textContent = topStatus.textContent;
      return result;
    } catch (error) {
      const text = errorMap[error.status] || error.message;
      marked = Boolean(error.marked);
      if (error.fieldEls?.length) { error.fieldEls.forEach((el, index) => mark(el, text, {focus: index === 0})); marked = true; }
      if (lastErrors.get(statusEl) === text && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        statusEl.classList.remove("shake");
        void statusEl.offsetWidth; // Restart the animation even on the third identical error.
        statusEl.classList.add("shake");
        statusEl.addEventListener("animationend", () => statusEl.classList.remove("shake"), {once: true});
      }
      lastErrors.set(statusEl, text); statusEl.textContent = text;
    } finally {
      if (adjacent && statusEl.textContent) { topStatus.textContent = statusEl.textContent; if (!marked) statusEl.scrollIntoView?.({block: "nearest", behavior: "smooth"}); }
      control.disabled = control.dataset?.unavailable === "true" || control.closest?.("[data-emergency-locked]") != null; control.removeAttribute("aria-busy"); control.classList.remove("is-busy");
    }
  }
  return {pending, requestError, localStatus, validate, counters, digits, mark, unmark, normalTime};
})();
