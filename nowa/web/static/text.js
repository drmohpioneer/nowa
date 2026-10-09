"use strict";
// Plain text only: isolate Latin runs, numbers and URLs without interpreting markup.
window.NowaText = function (node, text) {
  node.replaceChildren();
  const value = String(text), pattern = /https?:\/\/[^\s]+|[+A-Za-z0-9][A-Za-z0-9@._:+/ -]*/g;
  let at = 0;
  for (const match of value.matchAll(pattern)) {
    node.append(document.createTextNode(value.slice(at, match.index)));
    const token = document.createElement("bdi"); token.dir = "ltr"; token.textContent = match[0];
    node.append(token); at = match.index + match[0].length;
  }
  node.append(document.createTextNode(value.slice(at)));
};
