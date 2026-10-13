// ASTRA browser extension - background script
//
// Three jobs:
//   1. Own the integration toggle (persisted in storage).
//   2. Forward page context + mouse data from the active tab's content script
//      to the local ASTRA backend.
//   3. Reverse command channel: poll the backend for queued browser commands
//      ("ext_*" tools), execute them against the user's real browser (tabs API
//      + content scripts), and post the result back.

const DEFAULT_ENDPOINT = "http://127.0.0.1:8765";
const PAGE_POST_THROTTLE_MS = 500;
const MOUSE_POST_THROTTLE_MS = 1000;
const COMMAND_POLL_MS = 500;
const TAB_LOAD_TIMEOUT_MS = 30000;

let integrated = false;
let endpoint = DEFAULT_ENDPOINT;
let activeTabId = null;
let lastStatus = null; // { ok, message, at }

// Last (and current) popup chat exchange. The background owns the request so it
// survives the popup closing; the popup polls this via "chat-state".
let chatState = { pending: false, message: "", reply: "", error: null, session_id: null, at: null };

const tabState = new Map(); // tabId -> { context, mouse }

let pageTimer = null;
let mouseTimer = null;
let pollTimer = null;

/* ----------------------------------------------------------------- state -- */

async function loadState() {
  const stored = await browser.storage.local.get({
    integrated: false,
    endpoint: DEFAULT_ENDPOINT,
  });
  integrated = !!stored.integrated;
  endpoint = stored.endpoint || DEFAULT_ENDPOINT;
}

function tabEntry(id) {
  let entry = tabState.get(id);
  if (!entry) {
    entry = { context: null, mouse: null };
    tabState.set(id, entry);
  }
  return entry;
}

async function refreshActiveTab() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  activeTabId = tabs[0] ? tabs[0].id : null;
  return activeTabId;
}

async function ensureActiveTab() {
  if (activeTabId == null) await refreshActiveTab();
  return activeTabId;
}

/* ------------------------------------------------------------- forwarding -- */

function mergedContext(id) {
  const entry = tabState.get(id);
  if (!entry || !entry.context) return null;
  return { ...entry.context, mouse: entry.mouse || entry.context.mouse || null };
}

async function postContext(body) {
  try {
    const response = await fetch(`${endpoint}/api/browser/context`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    lastStatus = { ok: true, message: "Connected", at: Date.now() };
  } catch (err) {
    lastStatus = { ok: false, message: String(err), at: Date.now() };
  }
}

function schedulePagePost() {
  if (pageTimer) return;
  pageTimer = setTimeout(() => {
    pageTimer = null;
    if (!integrated) return;
    const context = mergedContext(activeTabId);
    if (context) postContext(context);
  }, PAGE_POST_THROTTLE_MS);
}

function scheduleMousePost() {
  if (mouseTimer) return;
  mouseTimer = setTimeout(() => {
    mouseTimer = null;
    if (!integrated) return;
    const entry = tabState.get(activeTabId);
    if (entry && entry.mouse) postContext({ mouse: entry.mouse, timestamp: Date.now() });
  }, MOUSE_POST_THROTTLE_MS);
}

async function requestActiveContext() {
  if (activeTabId == null) await refreshActiveTab();
  if (activeTabId == null) return null;
  try {
    const context = await browser.tabs.sendMessage(activeTabId, { type: "get-context" });
    if (context) tabEntry(activeTabId).context = context;
    return context;
  } catch (err) {
    return null;
  }
}

/* --------------------------------------------------------------- toggle --- */

async function setIntegration(enabled) {
  integrated = enabled;
  await browser.storage.local.set({ integrated });

  const tabs = await browser.tabs.query({});
  for (const tab of tabs) {
    browser.tabs.sendMessage(tab.id, { type: "set-integration", enabled }).catch(() => {});
  }

  await refreshActiveTab();

  if (enabled) {
    await requestActiveContext();
    const context = mergedContext(activeTabId);
    if (context) await postContext(context);
  } else {
    try {
      await fetch(`${endpoint}/api/browser/context`, { method: "DELETE" });
    } catch (err) {
      /* backend not running — nothing to clear */
    }
    tabState.clear();
    lastStatus = { ok: true, message: "Disconnected", at: Date.now() };
  }

  return { enabled: integrated, endpoint, status: lastStatus };
}

/* ------------------------------------------------------------- chat send --- */

function resetChatState() {
  chatState = { pending: false, message: "", reply: "", error: null, session_id: null, at: null };
  return { ...chatState };
}

function beginChat(message) {
  chatState = { pending: true, message, reply: "", error: null, session_id: null, at: Date.now() };
  runChatSend(message);
  return { ...chatState, ok: true };
}

async function runChatSend(message) {
  try {
    const response = await fetch(`${endpoint}/api/browser/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });

    let data = {};
    try {
      data = await response.json();
    } catch (err) {
      data = {};
    }

    if (!response.ok) {
      chatState = { ...chatState, pending: false, error: data.error || `HTTP ${response.status}` };
    } else if (data.ok === false) {
      chatState = { ...chatState, pending: false, error: data.error || "ASTRA could not answer." };
    } else {
      chatState = {
        ...chatState,
        pending: false,
        reply: data.reply || "",
        error: null,
        session_id: data.session_id || null,
      };
    }
  } catch (err) {
    chatState = { ...chatState, pending: false, error: `Could not reach ASTRA: ${err}` };
  }
  chatState.at = Date.now();
}

/* ------------------------------------------------- command execution ----- */

async function executeCommand(command) {
  const name = command.name;
  const args = command.arguments || {};
  try {
    switch (name) {
      case "ext_open_tab":
        return await runOpenTab(args);
      case "ext_list_tabs":
        return await runListTabs();
      case "ext_switch_tab":
        return await runSwitchTab(args);
      case "ext_close_tab":
        return await runCloseTab(args);
      case "ext_navigate":
        return await runNavigate(args);
      case "ext_search":
        return await runSearch(args);
      default:
        // DOM commands executed by the content script in the active tab.
        return await runInActiveTab(name, args);
    }
  } catch (err) {
    return { ok: false, error: String((err && err.message) || err) };
  }
}

async function runOpenTab(args) {
  const url = String(args.url || "").trim();
  const tab = await browser.tabs.create(url ? { url } : {});
  activeTabId = tab.id;
  return { ok: true, tabId: tab.id, url: tab.url, title: tab.title || "" };
}

async function runListTabs() {
  const tabs = await browser.tabs.query({});
  await refreshActiveTab();
  return {
    ok: true,
    activeTabId,
    tabs: tabs.map((t) => ({
      id: t.id,
      index: t.index,
      title: t.title || "",
      url: t.url || "",
      active: !!t.active,
      pinned: !!t.pinned,
    })),
  };
}

async function runSwitchTab(args) {
  const target = String(args.target ?? "").trim();
  if (!target) return { ok: false, error: "No target given (index, URL or title substring)" };

  const tabs = await browser.tabs.query({ currentWindow: true });
  let tabId = null;

  if (/^\d+$/.test(target)) {
    const index = parseInt(target, 10);
    const found = tabs.find((t) => t.index === index);
    if (found) tabId = found.id;
  } else {
    const needle = target.toLowerCase();
    const found = tabs.find(
      (t) =>
        (t.url && t.url.toLowerCase().includes(needle)) ||
        (t.title && t.title.toLowerCase().includes(needle))
    );
    if (found) tabId = found.id;
  }

  if (tabId == null) {
    return {
      ok: false,
      error: `No tab matches "${target}"`,
      tabs: tabs.map((t) => ({ index: t.index, url: t.url || "", title: t.title || "" })),
    };
  }

  const tab = await browser.tabs.update(tabId, { active: true });
  await browser.windows.update(tab.windowId, { focused: true });
  activeTabId = tabId;
  return { ok: true, tabId, ...(tab.url ? { url: tab.url } : {}) };
}

async function runCloseTab() {
  await ensureActiveTab();
  if (activeTabId == null) return { ok: false, error: "No active tab to close" };
  await browser.tabs.remove(activeTabId);
  tabState.delete(activeTabId);
  activeTabId = null;
  return { ok: true };
}

async function runNavigate(args) {
  const url = String(args.url || "").trim();
  if (!url) return { ok: false, error: "No URL given" };
  await ensureActiveTab();
  if (activeTabId == null) return { ok: false, error: "No active tab" };

  // Register the load listener *before* navigating so we never miss a fast load.
  const loaded = waitForTabComplete(activeTabId);
  await browser.tabs.update(activeTabId, { url });
  await loaded;
  return { ok: true, url };
}

function searchUrl(engine, query) {
  const q = encodeURIComponent(query);
  switch (engine) {
    case "google":
      return `https://www.google.com/search?q=${q}`;
    case "duckduckgo":
      return `https://duckduckgo.com/?q=${q}`;
    case "bing":
      return `https://www.bing.com/search?q=${q}`;
    default:
      return null;
  }
}

async function runSearch(args) {
  const query = String(args.query || "").trim();
  if (!query) return { ok: false, error: "No search query" };

  const engine = String(args.engine || "google").toLowerCase();
  const url = searchUrl(engine, query);
  if (!url) return { ok: false, error: `Unknown search engine "${engine}"` };

  await ensureActiveTab();
  if (activeTabId == null) return { ok: false, error: "No active tab" };

  const loaded = waitForTabComplete(activeTabId);
  await browser.tabs.update(activeTabId, { url });
  await loaded;

  // The content script re-injects on the new page; retry until it answers.
  const page = await readActivePageWithRetry();
  return { ok: page.ok, engine, query, ...(page.ok ? { text: page.text } : { error: page.error }) };
}

async function readActivePageWithRetry(attempts = 6, delayMs = 300) {
  let last = { ok: false, error: "no attempt" };
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    last = await runInActiveTab("ext_read_page", { part: "text" });
    if (last && last.ok) return last;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return last;
}

async function runInActiveTab(name, args) {
  await ensureActiveTab();
  if (activeTabId == null) return { ok: false, error: "No active tab" };
  try {
    const response = await browser.tabs.sendMessage(activeTabId, {
      type: "run-command",
      name,
      arguments: args || {},
    });
    if (!response) {
      return {
        ok: false,
        error:
          "No response from the page. It may not have a content script " +
          "(about:, add-ons pages) or it was still loading.",
      };
    }
    return response;
  } catch (err) {
    return {
      ok: false,
      error: `Could not reach the page: ${(err && err.message) || err} (content script missing or page still loading)`,
    };
  }
}

function waitForTabComplete(tabId, timeoutMs = TAB_LOAD_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let finished = false;
    const timer = setTimeout(() => finish(() => reject(new Error("timed out waiting for page to load"))), timeoutMs);

    function finish(callback) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      browser.tabs.onUpdated.removeListener(onUpdated);
      browser.tabs.onRemoved.removeListener(onRemoved);
      callback();
    }

    function onUpdated(id, changeInfo) {
      if (id === tabId && changeInfo.status === "complete") finish(() => resolve());
    }
    function onRemoved(id) {
      if (id === tabId) finish(() => reject(new Error("tab was closed while loading")));
    }

    browser.tabs.onUpdated.addListener(onUpdated);
    browser.tabs.onRemoved.addListener(onRemoved);
  });
}

/* ------------------------------------------------------------ command poll -- */

async function pollCommands() {
  const delay = integrated ? COMMAND_POLL_MS : 2000;

  try {
    if (integrated) {
      let command = null;
      try {
        const response = await fetch(`${endpoint}/api/browser/commands`, { method: "GET" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        command = data && data.command;
      } catch (err) {
        lastStatus = { ok: false, message: `Poll failed: ${err}`, at: Date.now() };
      }

      if (command) {
        const outcome = await executeCommand(command);
        const body =
          outcome && typeof outcome.ok === "boolean" ? outcome : { ok: false, error: "unserializable result" };
        try {
          const response = await fetch(`${endpoint}/api/browser/commands/${command.id}/result`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          lastStatus = { ok: true, message: `Executed ${command.name}`, at: Date.now() };
        } catch (err) {
          lastStatus = { ok: false, message: `Result post failed: ${err}`, at: Date.now() };
        }
      }
    }
  } catch (err) {
    lastStatus = { ok: false, message: `Command loop error: ${err}`, at: Date.now() };
  } finally {
    // Never let a thrown error stop the poll chain.
    schedulePoll(delay);
  }
}

function schedulePoll(delay = integrated ? COMMAND_POLL_MS : 2000) {
  if (pollTimer) return;
  pollTimer = setTimeout(() => {
    pollTimer = null;
    pollCommands();
  }, delay);
}

/* -------------------------------------------------------------- routing --- */

browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return;

  if (message.type === "content-ready") {
    sendResponse({ enabled: integrated });
    return true;
  }

  if (message.type === "mouse-position") {
    const id = sender.tab ? sender.tab.id : null;
    if (id != null) {
      tabEntry(id).mouse = message.mouse || null;
      if (integrated && id === activeTabId) scheduleMousePost();
    }
    return;
  }

  if (message.type === "page-context") {
    const id = sender.tab ? sender.tab.id : null;
    if (id != null) {
      const entry = tabEntry(id);
      entry.context = message.context || null;
      if (entry.context && entry.context.mouse) entry.mouse = entry.context.mouse;
      if (integrated && id === activeTabId) schedulePagePost();
    }
    return;
  }

  if (message.type === "get-integration") {
    sendResponse({ enabled: integrated, endpoint, status: lastStatus });
    return true;
  }

  if (message.type === "set-integration") {
    setIntegration(!!message.enabled)
      .then((state) => sendResponse(state))
      .catch((err) =>
        sendResponse({ enabled: integrated, endpoint, status: { ok: false, message: String(err) } })
      );
    return true;
  }

  if (message.type === "chat-send") {
    const text = String(message.message || "").trim();
    if (!text) {
      sendResponse({ ...chatState, ok: false, error: "Message cannot be empty" });
      return true;
    }
    if (chatState.pending) {
      sendResponse({ ...chatState, ok: false, error: "ASTRA is still replying\u2026" });
      return true;
    }
    sendResponse(beginChat(text));
    return true;
  }

  if (message.type === "chat-state") {
    sendResponse({ ...chatState, endpoint });
    return true;
  }

  if (message.type === "chat-clear") {
    sendResponse(resetChatState());
    return true;
  }
});

/* -------------------------------------------------------------- events ---- */

browser.tabs.onActivated.addListener(async (info) => {
  activeTabId = info.tabId;
  if (!integrated) return;
  if (!tabState.get(activeTabId) || !tabState.get(activeTabId).context) {
    await requestActiveContext();
  }
  const context = mergedContext(activeTabId);
  if (context) postContext(context);
});

browser.tabs.onRemoved.addListener((tabId) => {
  tabState.delete(tabId);
  if (tabId === activeTabId) activeTabId = null;
});

browser.runtime.onStartup.addListener(() => {
  loadState().then(refreshActiveTab).then(() => schedulePoll());
});
browser.runtime.onInstalled.addListener(() => {
  loadState().then(refreshActiveTab).then(() => schedulePoll());
});

// Warm the in-memory state for this background page instance.
loadState().then(refreshActiveTab).then(() => schedulePoll());