// ASTRA browser extension - popup
//
// Two things live here:
//   1. The integration toggle (stream the pages the user visits to ASTRA).
//   2. A small chat box that sends a message to the running ASTRA agent and
//      shows the reply. The background script owns the request so it survives
//      the popup closing; this popup just sends and polls for the result.

const button = document.getElementById("integrate");
const statusEl = document.getElementById("status");
const endpointEl = document.getElementById("endpoint");

const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("chat-send");
const clearBtn = document.getElementById("chat-clear");
const logEl = document.getElementById("chat-log");

const voiceBtn = document.getElementById("voice");
const voiceStatusEl = document.getElementById("voice-status");

let enabled = false;
let chatPending = false;
let pollTimer = null;
let currentEndpoint = "";

/* ------------------------------------------------------------ integration -- */

function apply(state) {
  if (!state) return;
  enabled = !!state.enabled;
  currentEndpoint = state.endpoint || currentEndpoint;
  endpointEl.textContent = state.endpoint || "";

  if (enabled) {
    button.textContent = "ASTRA is integrated \u2014 click to stop";
    button.classList.add("on");
  } else {
    button.textContent = "Integrate ASTRA with webpages";
    button.classList.remove("on");
  }

  const status = state.status;
  if (!status) {
    statusEl.textContent = "";
    statusEl.className = "";
  } else if (status.ok) {
    statusEl.textContent = enabled ? "Connected to ASTRA." : "Disconnected from ASTRA.";
    statusEl.className = "ok";
  } else {
    statusEl.textContent = `Could not reach ASTRA: ${status.message}`;
    statusEl.className = "err";
  }
}

async function refresh() {
  try {
    apply(await browser.runtime.sendMessage({ type: "get-integration" }));
  } catch (err) {
    statusEl.textContent = `Extension error: ${err}`;
    statusEl.className = "err";
  }
}

button.addEventListener("click", async () => {
  button.disabled = true;
  try {
    apply(await browser.runtime.sendMessage({ type: "set-integration", enabled: !enabled }));
  } catch (err) {
    statusEl.textContent = `Extension error: ${err}`;
    statusEl.className = "err";
  } finally {
    button.disabled = false;
  }
});

/* ------------------------------------------------------------------- chat --- */

function bubble(className, text) {
  const el = document.createElement("div");
  el.className = `bubble ${className}`;
  el.textContent = text;
  return el;
}

function renderChat(state) {
  if (!state) return;
  chatPending = !!state.pending;

  logEl.replaceChildren();
  if (state.message) logEl.appendChild(bubble("user", state.message));

  if (state.pending) {
    logEl.appendChild(bubble("astra pending", "ASTRA is thinking\u2026"));
  } else if (state.error) {
    logEl.appendChild(bubble("astra error", state.error));
  } else if (state.reply) {
    logEl.appendChild(bubble("astra", state.reply));
  }

  input.disabled = chatPending;
  sendBtn.disabled = chatPending;
  sendBtn.textContent = chatPending ? "Thinking\u2026" : "Send";
  logEl.scrollTop = logEl.scrollHeight;
}

async function chatRefresh() {
  try {
    renderChat(await browser.runtime.sendMessage({ type: "chat-state" }));
  } catch (err) {
    renderChat({ pending: false, error: `Extension error: ${err}` });
  }
  if (chatPending) scheduleChatPoll();
}

function scheduleChatPoll() {
  if (pollTimer) return;
  pollTimer = setTimeout(() => {
    pollTimer = null;
    chatRefresh();
  }, 600);
}

async function sendChat() {
  const message = input.value.trim();
  if (!message) return;

  let state;
  try {
    state = await browser.runtime.sendMessage({ type: "chat-send", message });
  } catch (err) {
    renderChat({ pending: false, message, error: `Extension error: ${err}` });
    return;
  }

  if (state && state.ok === false && !state.pending) {
    // Rejected immediately (empty / already busy) - show it without polling.
    renderChat({ message, pending: false, error: state.error || "Could not send." });
    return;
  }

  input.value = "";
  renderChat(state);
  scheduleChatPoll();
}

sendBtn.addEventListener("click", sendChat);

clearBtn.addEventListener("click", async () => {
  try {
    renderChat(await browser.runtime.sendMessage({ type: "chat-clear" }));
  } catch (err) {
    renderChat({ pending: false });
  }
});

/* ------------------------------------------------------------------ voice --- */

function voiceBaseUrl() {
  return (currentEndpoint || "http://127.0.0.1:8765").replace(/\/+$/, "");
}

function setVoiceStatus(text, kind) {
  if (!voiceStatusEl) return;
  voiceStatusEl.textContent = text || "";
  voiceStatusEl.className = kind || "";
}

// Voice mode lives in the web app (it owns the microphone UI). Check that it is
// reachable and the local speech layer is installed, then open it with the
// ?voice=1 deep link so the page enters voice mode on load.
async function openVoiceMode() {
  const base = voiceBaseUrl();
  voiceBtn.disabled = true;
  setVoiceStatus("Checking voice\u2026");
  try {
    const res = await fetch(`${base}/api/voice/status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const status = await res.json();
    if (!status.ready) {
      const detail = (status.problems && status.problems[0]) || "run ./voice/astra-voice --setup";
      setVoiceStatus(`Voice not ready \u2014 ${detail}`, "err");
      return;
    }
    await browser.tabs.create({ url: `${base}/?voice=1` });
    setVoiceStatus("Opening voice mode\u2026", "ok");
    window.close();
  } catch (err) {
    setVoiceStatus("Voice mode needs the web app (./web/astra-web) running.", "err");
  } finally {
    voiceBtn.disabled = false;
  }
}

voiceBtn.addEventListener("click", openVoiceMode);

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendChat();
  }
});

/* ------------------------------------------------------------------ boot ---- */

refresh().then(chatRefresh);
