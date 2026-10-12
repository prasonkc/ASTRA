// ASTRA browser extension - content script
//
// Two jobs:
//   1. When integration is on, stream a snapshot of the page (URL, title, HTML,
//      visible text, selected text) plus the live mouse position to the
//      background script, which forwards it to the local ASTRA backend.
//   2. Receive "run-command" messages from the background script and execute
//      browser-automation commands (click, type, press key, scroll, eval JS,
//      read page) against the real page DOM.

let integrated = false;
let contextTimer = null;
let lastMouseSend = 0;

const CONTEXT_DEBOUNCE_MS = 600;
const MOUSE_THROTTLE_MS = 100;

const state = { mouse: null };

/* ---------------------------------------------------------------- helpers -- */

function getSelectedText() {
  const selection = window.getSelection();
  return selection ? selection.toString().trim() : "";
}

function visibleText() {
  return (document.body || document.documentElement).innerText || "";
}

function buildContext() {
  const doctype = document.doctype ? `<!DOCTYPE ${document.doctype.name}>\n` : "";
  const html = doctype + document.documentElement.outerHTML;

  return {
    url: location.href,
    title: document.title,
    html,
    text: visibleText(),
    selection: getSelectedText(),
    mouse: state.mouse,
    timestamp: Date.now(),
  };
}

function sendContext() {
  if (!integrated) return;
  let context;
  try {
    context = buildContext();
  } catch (err) {
    return;
  }
  try {
    browser.runtime.sendMessage({ type: "page-context", context }).catch(() => {});
  } catch (err) {
    // Extension reloaded while the page stayed open; ignore.
  }
}

function scheduleContext() {
  if (!integrated) return;
  clearTimeout(contextTimer);
  contextTimer = setTimeout(sendContext, CONTEXT_DEBOUNCE_MS);
}

/* ---------------------------------------------------------------- mouse ---- */

document.addEventListener(
  "mousemove",
  (event) => {
    state.mouse = {
      x: event.clientX,
      y: event.clientY,
      pageX: event.pageX,
      pageY: event.pageY,
    };

    if (!integrated) return;
    const now = Date.now();
    if (now - lastMouseSend < MOUSE_THROTTLE_MS) return;
    lastMouseSend = now;
    try {
      browser.runtime
        .sendMessage({ type: "mouse-position", mouse: state.mouse, url: location.href })
        .catch(() => {});
    } catch (err) {
      /* ignore */
    }
  },
  { passive: true }
);

document.addEventListener("selectionchange", scheduleContext);

// Single-page apps rewrite the URL without a reload; catch that too.
let lastHref = location.href;
setInterval(() => {
  if (location.href !== lastHref) {
    lastHref = location.href;
    scheduleContext();
  }
}, 2000);
window.addEventListener("popstate", scheduleContext);

/* --------------------------------------------------- DOM command execution -- */

function executeDomCommand(name, args) {
  switch (name) {
    case "ext_click":
      return clickElement(args);
    case "ext_type":
      return typeText(args);
    case "ext_press_key":
      return pressKey(args);
    case "ext_scroll":
      return scrollPage(args);
    case "ext_eval_js":
      return evalJs(args);
    case "ext_read_page":
      return readPage(args);
    default:
      return { ok: false, error: `Unknown DOM command: ${name}` };
  }
}

function isVisible(element) {
  if (!element) return false;
  const style = window.getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden") return false;
  return !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
}

function describe(element) {
  if (!element) return null;
  const text = ((element.innerText || element.value || "").trim() || "").slice(0, 120);
  return {
    tag: element.tagName.toLowerCase(),
    id: element.id || undefined,
    class: typeof element.className === "string" ? element.className : undefined,
    text,
  };
}

// Find an element by its visible text; prefers interactive elements.
function findByText(text) {
  const needle = String(text).trim().toLowerCase();
  if (!needle) return null;

  const INTERACTIVE = new Set([
    "a", "button", "summary", "label", "select",
    "input", "textarea", "option", "legend",
  ]);
  const candidates = document.querySelectorAll("*");
  let fallback = null;

  for (const el of candidates) {
    if (!isVisible(el)) continue;
    const ownText = ((el.innerText || el.textContent || "").trim()).toLowerCase();
    if (!ownText) continue;
    if (ownText === needle) {
      if (INTERACTIVE.has(el.tagName.toLowerCase()) || el.hasAttribute("role")) {
        return el;
      }
      if (!fallback) fallback = el;
    }
  }
  for (const el of candidates) {
    if (!isVisible(el)) continue;
    const ownText = ((el.innerText || el.textContent || "").trim()).toLowerCase();
    if (!ownText) continue;
    if (ownText.includes(needle)) {
      if (INTERACTIVE.has(el.tagName.toLowerCase()) || el.getAttribute("role") === "button") {
        return el;
      }
      if (!fallback) fallback = el;
    }
  }
  return fallback;
}

function clickElement(args) {
  let element = null;
  if (args.selector) {
    try {
      element = document.querySelector(args.selector);
    } catch (err) {
      return { ok: false, error: `Invalid selector "${args.selector}": ${err}` };
    }
  }
  if (!element && args.text) element = findByText(args.text);
  if (!element) {
    const hint = args.selector ? `selector "${args.selector}"` : `text "${args.text}"`;
    return { ok: false, error: `No visible element found for ${hint}` };
  }

  element.scrollIntoView({ block: "center", behavior: "smooth" });
  element.click();
  return { ok: true, clicked: describe(element) };
}

function typeText(args) {
  const text = String(args.text ?? "");
  let element = args.selector ? document.querySelector(args.selector) : null;
  if (!element) element = document.activeElement;

  if (!element) return { ok: false, error: "No input element to type into" };
  const editable =
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element.isContentEditable ||
    element.tagName === "SELECT";

  if (!editable) {
    return { ok: false, error: `Element is not an input (${describe(element)})` };
  }

  element.focus();
  if (element.isContentEditable) {
    element.textContent = text;
  } else {
    element.value = text;
  }
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true, typed: text, target: describe(element) };
}

function pressKey(args) {
  const key = String(args.key || "").trim();
  if (!key) return { ok: false, error: "No key given" };
  const target = document.activeElement || document.body;
  const options = { key, code: key, bubbles: true, cancelable: true, composed: true };
  target.dispatchEvent(new KeyboardEvent("keydown", options));
  target.dispatchEvent(new KeyboardEvent("keypress", options));
  target.dispatchEvent(new KeyboardEvent("keyup", options));
  return { ok: true, key, target: describe(target) };
}

function scrollPage(args) {
  const direction = String(args.direction || "down").toLowerCase();
  const amount = Number(args.amount) || 600;

  if (direction === "top") {
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (direction === "bottom") {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  } else {
    const sign = direction === "up" ? -1 : 1;
    window.scrollBy({ top: sign * amount, behavior: "smooth" });
  }
  return { ok: true, direction, scrollY: window.scrollY };
}

function evalJs(args) {
  const expression = String(args.expression || "").trim();
  if (!expression) return { ok: false, error: "Empty JS expression" };
  try {
    // Runs in the content-script world: DOM access works; page-private JS
    // variables are not visible (Firefox X-ray vision).
    const fn = new Function(`return (${expression});`);
    return { ok: true, value: serialize(fn()) };
  } catch (err) {
    return { ok: false, error: `JS error: ${err}` };
  }
}

function serialize(value) {
  try {
    if (
      value === null ||
      value === undefined ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      return value === undefined ? null : value;
    }
    if (typeof value === "function") return `[function ${value.name || "anonymous"}]`;
    if (Array.isArray(value)) return value.map(serialize);
    if (value instanceof Element) {
      return {
        element: value.tagName.toLowerCase(),
        id: value.id || undefined,
        text: String(value.innerText || "").slice(0, 200),
      };
    }
    if (typeof value === "object") {
      const out = {};
      for (const key of Object.keys(value)) out[key] = serialize(value[key]);
      return out;
    }
    return String(value);
  } catch (err) {
    return `[unserializable: ${err}]`;
  }
}

function readPage(args) {
  const base = { url: location.href, title: document.title };
  const part = String(args.part || "text").toLowerCase();

  if (part === "url") return { ok: true, ...base };
  if (part === "html") return { ok: true, ...base, html: document.documentElement.outerHTML };
  if (part === "selection") return { ok: true, ...base, selection: getSelectedText() };
  if (part === "all") {
    return {
      ok: true,
      ...base,
      text: visibleText(),
      html: document.documentElement.outerHTML,
      selection: getSelectedText(),
    };
  }
  return { ok: true, ...base, text: visibleText() };
}

/* -------------------------------------------------------------- routing ---- */

browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return;

  if (message.type === "run-command") {
    let outcome;
    try {
      outcome = executeDomCommand(message.name, message.arguments || {});
    } catch (err) {
      outcome = { ok: false, error: String(err) };
    }
    sendResponse(outcome);
    return;
  }

  if (message.type === "set-integration") {
    integrated = !!message.enabled;
    if (integrated) sendContext();
    sendResponse({ enabled: integrated });
    return;
  }

  if (message.type === "get-context") {
    try {
      sendResponse(buildContext());
    } catch (err) {
      sendResponse(null);
    }
    return;
  }
});

/* ----------------------------------------------------------------- boot ---- */

browser.runtime
  .sendMessage({ type: "content-ready" })
  .then((response) => {
    if (response && response.enabled) {
      integrated = true;
      sendContext();
    }
  })
  .catch(() => {});