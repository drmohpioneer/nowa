"use strict";
// Display only: retain the server's ISO instant for sandbox commands.
window.NowaClock = function (node, iso, pattern) {
  const arabic = document.documentElement.lang === "ar";
  const parts = new Intl.DateTimeFormat(arabic ? "ar-EG" : "en-GB", {
    timeZone: "Africa/Cairo", calendar: "gregory", numberingSystem: "latn",
    weekday: arabic ? "long" : "short", day: "numeric", month: arabic ? "long" : "short",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  node.dataset.iso = iso;
  node.textContent = pattern.replace(/\{(\w+)\}/g, (_, key) => values[key]);
};
