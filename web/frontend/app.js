/* ASTRA web frontend — vanilla JS, no build step. */
(() => {
  "use strict";

  // ---- state ---------------------------------------------------------------
  let currentSessionId = null;
  let streaming = false;
  let abortController = null;
  let sessionsCache = [];
  let settingsConfig = null;
  let selectedProvider = null;

  // ---- DOM -----------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const messagesEl = $("messages");
  const sessionListEl = $("session-list");
  const inputEl = $("input");
  const sendBtn = $("send");
  const stopBtn = $("stop");
  const newChatBtn = $("new-chat");
  const emptyState = $("empty-state");
  const chatTitleEl = $("chat-title-text");
  const statusDot = $("status-dot");
  const statusText = $("status-text");
  const modelBadge = $("model-badge");
  const headerModel = $("header-model");
  const sidebar = $("sidebar");
  const scrim = $("scrim");
  const menuToggle = $("menu-toggle");
  const settingsBtn = $("settings-btn");
  const settingsModal = $("settings-modal");
  const settingsClose = $("settings-close");
  const settingsScrim = $("settings-scrim");
  const settingsBody = $("settings-body");
  const toastWrap = $("toast-wrap");
  const composerHint = $("composer-hint");
  const voiceBtn = $("voice-btn");
  const voiceBanner = $("voice-banner");
  const voiceTextEl = $("voice-text");
  const voiceExitBtn = $("voice-exit");

  // ---- helpers -------------------------------------------------------------
  const escapeHtml = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const TOOL_ICONS = [
    [/^memory_/, "🧠"],
    [/^shell_/, "🖥️"],
    [/^(web_)/, "🌐"],
    [/^browser_/, "🧭"],
    [/^playwright_/, "🎭"],
    [/^file_read/, "📄"],
    [/^word_/, "📝"],
    [/^ppt_/, "📊"],
    [/^excel_|^csv_/, "📈"],
  ];
  function toolIcon(name) {
    for (const [re, icon] of TOOL_ICONS) if (re.test(name || "")) return icon;
    return "🔧";
  }

  function formatArgs(args) {
    if (args == null) return "";
    if (typeof args === "string") {
      try {
        args = JSON.parse(args);
      } catch {
        return args;
      }
    }
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      return String(args);
    }
  }

  function formatDate(value) {
    if (!value) return "";
    const iso = String(value).includes("T") ? value : String(value).replace(" ", "T") + "Z";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(value);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
    if (diff < 604800) return Math.floor(diff / 86400) + "d ago";
    return d.toLocaleDateString();
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // ---- file links ----------------------------------------------------------
  // Turn paths to generated files (docx/pptx/xlsx/pdf/...) into clickable
  // download pills that hit /api/files. Matches absolute, relative, ./  and
  // bare-filename paths without grabbing surrounding words or punctuation.
  const FILE_EXTS =
    "docx|doc|pptx|ppt|xlsx|xls|pdf|txt|csv|json|md|png|jpe?g|gif|webp|svg|zip|mp3|mp4|wav|html?|rtf";
  // Absolute path starting with a drive letter, /, ./ or ../, then any
  // number of segments:   /mnt/.../file.docx   C:\dir\file.docx   ./x/file.docx
  const PATH_ABS =
    "(?<![\\w.:/])(?:[A-Za-z]:[\\\\/]|\\.{1,2}[\\\\/]|[\\\\/])" +
    "(?:[\\w.@+()' -]+[\\\\/])*" +
    "[\\w][\\w.@+()' -]*\\.(?:" + FILE_EXTS + ")\\b";
  // Relative path with real directory separators. The lookahead stops a token
  // from starting on a quote (e.g. tool JSON 'path': 'file.pdf').
  const PATH_REL =
    "(?<![\\w.:/])(?!['\"])[\\w-]+[\\\\/]" +
    "(?:[\\w.@+()' -]+[\\\\/])*" +
    "[\\w][\\w.@+()' -]*\\.(?:" + FILE_EXTS + ")\\b";
  // Bare filename, single word, not glued to preceding path/word chars.
  const PATH_BARE = "(?<![\\w./])(?!['\"])[\\w][\\w.@+()-]*\\.(?:" + FILE_EXTS + ")\\b";
  const FILE_PATH_RE = new RegExp("(?:" + PATH_ABS + "|" + PATH_REL + "|" + PATH_BARE + ")", "gi");

  function linkifyTextNode(node) {
    const text = node.nodeValue || "";
    const re = new RegExp(FILE_PATH_RE.source, FILE_PATH_RE.flags);
    // exec() below must start from the beginning; calling test() first would
    // advance lastIndex and skip the first match.
    re.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0;
    let found = false;
    let m;
    while ((m = re.exec(text))) {
      found = true;
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      const full = m[0];
      const a = document.createElement("a");
      a.className = "file-link";
      a.href = "/api/files?path=" + encodeURIComponent(full);
      a.target = "_blank";
      a.rel = "noopener";
      a.title = "Open or download " + full;
      a.textContent = full;
      frag.appendChild(a);
      last = m.index + full.length;
    }
    if (!found) return;
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag, node);
  }

  function linkifyFilePaths(root) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(linkifyTextNode);
  }

  // ---- markdown ------------------------------------------------------------
  function renderMarkdown(md) {
    if (!md) return "";
    const codeBlocks = [];
    let text = String(md).replace(/```([^\n`]*)\n?([\s\S]*?)```/g, (_, _lang, code) => {
      const i = codeBlocks.length;
      codeBlocks.push('<pre class="code"><code>' + escapeHtml(code.replace(/\n$/, "")) + "</code></pre>");
      return "\u0000C" + i + "\u0000";
    });

    text = escapeHtml(text);
    text = text.replace(/`([^`\n]+)`/g, (_, c) => "<code>" + c + "</code>");
    text = text.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    text = text.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );
    text = text.replace(
      /(^|\s)(https?:\/\/[^\s<]+)/g,
      '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>'
    );

    const out = [];
    let listType = null;
    const closeList = () => {
      if (listType) {
        out.push("</" + listType + ">");
        listType = null;
      }
    };

    for (const raw of text.split("\n")) {
      const line = raw.replace(/\s+$/, "");
      const codeMatch = line.match(/^\u0000C(\d+)\u0000$/);
      if (codeMatch) {
        closeList();
        out.push(codeBlocks[+codeMatch[1]]);
        continue;
      }
      if (/^\s*$/.test(line)) {
        closeList();
        continue;
      }
      let m;
      if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
        closeList();
        const lvl = m[1].length;
        out.push("<h" + lvl + ">" + m[2] + "</h" + lvl + ">");
        continue;
      }
      if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
        if (listType !== "ul") {
          closeList();
          out.push("<ul>");
          listType = "ul";
        }
        out.push("<li>" + m[1] + "</li>");
        continue;
      }
      if ((m = line.match(/^\s*\d+\.\s+(.*)$/))) {
        if (listType !== "ol") {
          closeList();
          out.push("<ol>");
          listType = "ol";
        }
        out.push("<li>" + m[1] + "</li>");
        continue;
      }
      if ((m = line.match(/^&gt;\s?(.*)$/))) {
        closeList();
        out.push("<blockquote>" + m[1] + "</blockquote>");
        continue;
      }
      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
        closeList();
        out.push("<hr>");
        continue;
      }
      closeList();
      out.push("<p>" + line + "</p>");
    }
    closeList();

    return out.join("\n").replace(/<\/blockquote>\n<blockquote>/g, "\n");
  }

  // ---- API -----------------------------------------------------------------
  async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail || "Request failed");
    }
    return res.json();
  }

  // ---- rendering: sessions -------------------------------------------------
  function renderSessions(sessions) {
    sessionsCache = sessions || [];
    sessionListEl.innerHTML = "";
    if (!sessionsCache.length) {
      sessionListEl.innerHTML = '<div class="sessions-label" style="padding:8px 10px">No conversations yet</div>';
      return;
    }
    for (const s of sessionsCache) {
      const item = document.createElement("div");
      item.className = "session-item" + (s.session_id === currentSessionId ? " active" : "");
      item.innerHTML =
        '<div class="s-title">' +
        escapeHtml(s.title || "Untitled") +
        "</div>" +
        '<div class="s-meta">' +
        (s.message_count || 0) +
        " messages · " +
        escapeHtml(formatDate(s.updated_at)) +
        "</div>" +
        '<button class="s-del" title="Delete conversation">×</button>';
      item.addEventListener("click", () => selectSession(s.session_id));
      item.querySelector(".s-del").addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSession(s.session_id, s.title);
      });
      sessionListEl.appendChild(item);
    }
  }

  async function refreshSessions() {
    try {
      const data = await api("/api/sessions");
      currentSessionId = data.session_id;
      renderSessions(data.sessions);
      updateTitle();
    } catch (e) {
      /* non-fatal */
    }
  }

  function updateTitle() {
    const active = sessionsCache.find((s) => s.session_id === currentSessionId);
    chatTitleEl.textContent = active ? active.title || "Untitled" : "New conversation";
  }

  // ---- rendering: turns ----------------------------------------------------
  function showEmpty() {
    if (emptyState) emptyState.style.display = "";
  }
  function hideEmpty() {
    if (emptyState) emptyState.style.display = "none";
  }

  function appendUserTurn(text) {
    const el = document.createElement("div");
    el.className = "turn user";
    el.innerHTML = '<div class="avatar">You</div><div class="bubble"><div class="md"></div></div>';
    el.querySelector(".md").textContent = text;
    messagesEl.appendChild(el);
    return el;
  }

  function createAssistantTurn() {
    const el = document.createElement("div");
    el.className = "turn assistant";
    el.innerHTML =
      '<div class="avatar">A</div>' +
      '<div class="bubble"><div class="parts"></div><span class="cursor"></span></div>';
    messagesEl.appendChild(el);
    return {
      el,
      bubble: el.querySelector(".bubble"),
      parts: el.querySelector(".parts"),
      cursor: el.querySelector(".cursor"),
      thinking: null,
      thinkingBody: null,
      currentText: null,
      textBuf: "",
      fullText: "",
      raf: null,
    };
  }

  function appendThinking(turn, delta) {
    if (!turn.thinking) {
      const details = document.createElement("details");
      details.className = "thinking";
      details.open = true;
      details.innerHTML = "<summary>Reasoning</summary><div class=\"thinking-body\"></div>";
      turn.bubble.insertBefore(details, turn.parts);
      turn.thinking = details;
      turn.thinkingBody = details.querySelector(".thinking-body");
    }
    turn.thinkingBody.textContent += delta;
    if (turn.thinking.open) turn.thinkingBody.scrollTop = turn.thinkingBody.scrollHeight;
  }

  function appendContent(turn, delta) {
    if (!turn.currentText) {
      turn.currentText = document.createElement("div");
      turn.currentText.className = "md";
      turn.parts.appendChild(turn.currentText);
      turn.textBuf = "";
    }
    turn.textBuf += delta;
    turn.fullText += delta;
    turn.currentText._md = turn.textBuf;
    const node = turn.currentText;
    if (!turn.raf) {
      turn.raf = requestAnimationFrame(() => {
        turn.raf = null;
        node.innerHTML = renderMarkdown(node._md || "");
        linkifyFilePaths(node);
        scrollToBottom();
      });
    }
  }

  function addToolCard(turn, call) {
    if (turn.currentText) turn.currentText = null; // subsequent text goes in a new block
    const card = document.createElement("div");
    card.className = "tool";
    if (call.id != null) card.dataset.callId = call.id;
    card.dataset.pending = "1";
    card.innerHTML =
      '<div class="tool-head">' +
      '<span class="tool-icon">' + toolIcon(call.name) + "</span>" +
      '<span class="tool-name">' + escapeHtml(call.name) + "</span>" +
      '<span class="spinner"></span>' +
      '<span class="tool-status pending"></span>' +
      "</div>" +
      '<details class="tool-body" hidden><summary>Details</summary>' +
      '<div class="tool-args">' + escapeHtml(formatArgs(call.arguments)) + "</div>" +
      "<pre></pre></details>";
    turn.parts.appendChild(card);
    linkifyFilePaths(card.querySelector(".tool-args"));
    return card;
  }

  function completeToolCard(card, result) {
    if (!card) return;
    card.dataset.pending = "";
    const spinner = card.querySelector(".spinner");
    if (spinner) spinner.remove();
    const status = card.querySelector(".tool-status");
    if (status) {
      status.classList.remove("pending");
      status.classList.add(result.success === false ? "fail" : "ok");
    }
    const details = card.querySelector(".tool-body");
    const pre = card.querySelector("pre");
    if (pre) {
      pre.textContent = result.result == null ? "" : String(result.result);
      linkifyFilePaths(pre);
    }
    if (details) {
      details.hidden = false;
      if (result.autoOpen) details.open = true;
    }
    scrollToBottom();
  }

  function appendError(turn, message) {
    const el = document.createElement("div");
    el.className = "error-line";
    el.textContent = "⚠ " + message;
    (turn ? turn.parts : messagesEl).appendChild(el);
  }

  function finalizeTurn(turn) {
    if (!turn) return;
    if (turn.raf) {
      cancelAnimationFrame(turn.raf);
      turn.raf = null;
      // appendContent defers the markdown render to rAF; if finalize runs
      // first (e.g. while rendering persisted history) render now. The md
      // block may have been stashed on currentText or already live in parts.
      const md = turn.currentText || turn.parts.querySelector(".md:last-child");
      if (md) {
        md.innerHTML = renderMarkdown(md._md || "");
        linkifyFilePaths(md);
      }
    }
    if (turn.thinking) turn.thinking.open = false;
    if (turn.cursor) turn.cursor.remove();
    const hasContent =
      turn.parts.children.length > 0 && turn.parts.textContent.trim().length > 0;
    const hasCards = turn.parts.querySelector(".tool") !== null;
    const hasThinking = !!turn.thinking;
    if (!hasContent && !hasCards && !hasThinking) {
      turn.parts.innerHTML = '<div class="md" style="color:var(--muted)">(no response)</div>';
    }
    scrollToBottom();
  }

  // ---- rendering: history --------------------------------------------------
  function renderHistory(messages) {
    messagesEl.innerHTML = "";
    if (!messages || !messages.length) {
      messagesEl.appendChild(emptyState);
      showEmpty();
      return;
    }
    hideEmpty();
    const pendingCards = [];
    for (const m of messages) {
      if (m.role === "user") {
        appendUserTurn(m.content || "");
      } else if (m.role === "assistant") {
        const hasCalls = Array.isArray(m.tool_calls) && m.tool_calls.length > 0;
        if (!m.content && !hasCalls) continue; // empty placeholder turn
        const turn = createAssistantTurn();
        if (m.content) appendContent(turn, m.content);
        if (hasCalls) {
          for (const tc of m.tool_calls) {
            const fn = tc && tc.function ? tc.function : tc || {};
            const name = fn.name || "tool";
            const args = fn.arguments ?? {};
            const card = addToolCard(turn, { name, arguments: args });
            pendingCards.push(card);
          }
        }
        finalizeTurn(turn);
      } else if (m.role === "tool") {
        let card = pendingCards.shift();
        if (!card) {
          const turn = createAssistantTurn();
          card = addToolCard(turn, { name: "tool", arguments: {} });
          turn.currentText = null;
        }
        completeToolCard(card, { success: true, result: m.content || "" });
      }
    }
    scrollToBottom();
  }

  // ---- actions -------------------------------------------------------------
  async function loadMessages(sessionId) {
    try {
      const data = await api("/api/sessions/" + encodeURIComponent(sessionId) + "/messages");
      renderHistory(data.messages);
    } catch (e) {
      renderHistory([]);
    }
  }

  async function selectSession(sessionId) {
    if (streaming || sessionId === currentSessionId) {
      closeSidebar();
      return;
    }
    try {
      await api("/api/sessions/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
    } catch (e) {
      /* ignore, still show the session */
    }
    currentSessionId = sessionId;
    renderSessions(sessionsCache);
    updateTitle();
    await loadMessages(sessionId);
    closeSidebar();
  }

  async function createSession() {
    try {
      const data = await api("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      currentSessionId = data.session_id;
      await refreshSessions();
      renderHistory([]);
      inputEl.focus();
      closeSidebar();
    } catch (e) {
      appendError(null, "Could not create a new chat: " + e.message);
    }
  }

  async function deleteSession(sessionId, title) {
    if (!confirm('Delete "' + (title || "this conversation") + '"? This cannot be undone.')) return;
    try {
      await api("/api/sessions/" + encodeURIComponent(sessionId), { method: "DELETE" });
      const wasCurrent = sessionId === currentSessionId;
      await refreshSessions();
      if (wasCurrent) {
        await loadMessages(currentSessionId);
      }
    } catch (e) {
      alert("Could not delete conversation: " + e.message);
    }
  }

  function setStreaming(on) {
    streaming = on;
    sendBtn.hidden = on;
    stopBtn.hidden = !on;
    inputEl.disabled = on;
    if (!on) {
      sendBtn.disabled = !inputEl.value.trim();
      inputEl.focus();
    }
  }

  async function sendMessage(text) {
    text = (text || "").trim();
    if (!text || streaming) return "";

    hideEmpty();
    appendUserTurn(text);
    const turn = createAssistantTurn();
    scrollToBottom();
    inputEl.value = "";
    autoResize();
    setStreaming(true);
    sendBtn.disabled = true;

    const controller = new AbortController();
    abortController = controller;

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: currentSessionId }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error("HTTP " + res.status);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);
          if (line) handleEvent(JSON.parse(line), turn);
        }
      }
      const rest = buffer.trim();
      if (rest) {
        try {
          handleEvent(JSON.parse(rest), turn);
        } catch {
          /* ignore partial */
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") appendError(turn, e.message);
      else appendError(turn, "Stopped.");
    } finally {
      finalizeTurn(turn);
      setStreaming(false);
      abortController = null;
      refreshSessions();
    }
    // Callers (voice mode) use the accumulated reply text to speak it back.
    return turn.fullText || "";
  }

  function handleEvent(evt, turn) {
    switch (evt.type) {
      case "session":
        if (evt.session_id) currentSessionId = evt.session_id;
        break;
      case "thinking":
        appendThinking(turn, evt.delta || "");
        break;
      case "content":
        appendContent(turn, evt.delta || "");
        break;
      case "tool_call": {
        const card = addToolCard(turn, evt);
        card.dataset.callId = evt.id;
        scrollToBottom();
        break;
      }
      case "tool_result": {
        const card =
          (evt.id != null && turn.parts.querySelector('.tool[data-call-id="' + evt.id + '"]')) ||
          turn.parts.querySelector('.tool[data-pending="1"]');
        completeToolCard(card, evt);
        break;
      }
      case "error":
        appendError(turn, evt.message || "Unknown error");
        break;
      case "done":
        if (evt.session_id) currentSessionId = evt.session_id;
        break;
      default:
        break;
    }
  }

  // ---- composer UX ---------------------------------------------------------
  function autoResize() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + "px";
  }

  inputEl.addEventListener("input", () => {
    autoResize();
    sendBtn.disabled = streaming || !inputEl.value.trim();
  });

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputEl.value);
    }
  });

  sendBtn.addEventListener("click", () => sendMessage(inputEl.value));
  stopBtn.addEventListener("click", () => {
    if (abortController) abortController.abort();
  });
  newChatBtn.addEventListener("click", createSession);

  document.querySelectorAll(".suggestions button").forEach((btn) => {
    btn.addEventListener("click", () => sendMessage(btn.dataset.suggest || btn.textContent));
  });

  // ---- voice mode ----------------------------------------------------------
  // Optional, fully local speech. The browser captures the microphone and plays
  // the audio; the server runs whisper.cpp (STT) and piper (TTS). Click the mic
  // to listen hands-free ("speak, then pause"); click it again to stop.
  let voiceState = null;      // { stopped } while a voice session is open
  let voiceAudio = null;      // reply currently being played aloud
  let voiceAudioCtx = null;   // active AudioContext (for level metering)
  let voiceReady = false;     // server-side transcription is available
  let voiceTtsReady = false;  // replies can be spoken back

  const VOICE_SILENCE_MS = 1200;   // pause that ends an utterance
  const VOICE_MAX_MS = 15000;      // hard cap on one utterance
  const VOICE_NO_SPEECH_MS = 8000; // stop waiting if nothing is said
  const VOICE_MIN_BYTES = 2000;    // ignore empty/silent clips

  function voiceSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function setVoiceText(text) {
    if (voiceTextEl) voiceTextEl.textContent = text;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function refreshVoiceStatus() {
    try {
      const status = await api("/api/voice/status");
      voiceReady = !!status.ready;
      voiceTtsReady = !!status.tts_ready;
      return status;
    } catch (e) {
      voiceReady = false;
      voiceTtsReady = false;
      return { ready: false, problems: [e.message] };
    }
  }

  // Record one utterance, auto-stopping after a pause (energy-gated endpoint
  // detection, the same idea as the terminal /voice continuous mode).
  async function captureUtterance(state) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const ctx = new AudioCtx();
    voiceAudioCtx = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);

    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
    };
    recorder.start();

    const cleanup = () => {
      try { source.disconnect(); } catch { /* ignore */ }
      try { ctx.close(); } catch { /* ignore */ }
      if (voiceAudioCtx === ctx) voiceAudioCtx = null;
      stream.getTracks().forEach((t) => t.stop());
    };

    return new Promise((resolve) => {
      const samples = new Float32Array(analyser.fftSize);
      const start = performance.now();
      const ambient = [];
      let threshold = 0.02;
      let calibrated = false;
      let heardSpeech = false;
      let lastLoud = start;

      const finish = () => {
        clearInterval(timer);
        const build = () => {
          const blob = chunks.length
            ? new Blob(chunks, { type: recorder.mimeType || "audio/webm" })
            : null;
          cleanup();
          resolve(blob);
        };
        if (recorder.state !== "inactive") {
          recorder.onstop = build;
          try { recorder.stop(); } catch { build(); }
        } else {
          build();
        }
      };

      const tick = () => {
        if (state.stopped) return finish();
        analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
        const rms = Math.sqrt(sum / samples.length);
        const now = performance.now();

        if (!calibrated) {
          ambient.push(rms);
          if (now - start > 350) {
            ambient.sort((a, b) => a - b);
            const noise = ambient[Math.floor(ambient.length / 2)] || 0.004;
            threshold = Math.max(0.012, noise * 2.5);
            calibrated = true;
            lastLoud = now;
          }
          return;
        }

        if (rms > threshold) {
          if (!heardSpeech) setVoiceText("Listening… (recording)");
          heardSpeech = true;
          lastLoud = now;
        }

        if (heardSpeech && (now - lastLoud > VOICE_SILENCE_MS || now - start > VOICE_MAX_MS)) {
          return finish();
        }
        if (!heardSpeech && now - start > VOICE_NO_SPEECH_MS) {
          return finish();
        }
      };

      const timer = setInterval(tick, 60);
    });
  }

  function audioFormat(mime) {
    const type = (mime || "").toLowerCase();
    if (type.includes("ogg")) return "ogg";
    if (type.includes("mp4") || type.includes("aac") || type.includes("m4a")) return "mp4";
    if (type.includes("wav")) return "wav";
    return "webm";
  }

  async function transcribeClip(blob) {
    const format = audioFormat(blob.type);
    const res = await fetch("/api/voice/transcribe?format=" + format, {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob,
    });
    if (!res.ok) {
      let detail = "HTTP " + res.status;
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    const data = await res.json();
    return (data.text || "").trim();
  }

  function playUrl(url) {
    return new Promise((resolve) => {
      const audio = new Audio(url);
      voiceAudio = audio;
      const done = () => {
        if (voiceAudio === audio) voiceAudio = null;
        resolve();
      };
      audio.onended = done;
      audio.onerror = done;
      audio.play().catch(done);
    });
  }

  function browserSpeak(text) {
    if (!window.speechSynthesis) return Promise.resolve();
    return new Promise((resolve) => {
      try {
        const utter = new SpeechSynthesisUtterance(text);
        utter.onend = resolve;
        utter.onerror = resolve;
        speechSynthesis.cancel();
        speechSynthesis.speak(utter);
      } catch {
        resolve();
      }
    });
  }

  async function speakReply(text) {
    const clean = (text || "").trim();
    if (!clean) return;
    if (voiceTtsReady) {
      try {
        const res = await fetch("/api/voice/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: clean }),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const buf = await res.arrayBuffer();
        const url = URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
        try {
          await playUrl(url);
        } finally {
          URL.revokeObjectURL(url);
        }
        return;
      } catch {
        /* piper failed — fall back to the browser's own voice */
      }
    }
    await browserSpeak(clean);
  }

  async function voiceLoop(state) {
    while (!state.stopped) {
      setVoiceText("Listening… speak, then pause");
      let blob;
      try {
        blob = await captureUtterance(state);
      } catch (e) {
        if (!state.stopped) {
          toast("Microphone error: " + e.message, "error");
          exitVoiceMode();
        }
        return;
      }
      if (state.stopped) return;
      if (!blob || blob.size < VOICE_MIN_BYTES) continue; // silence — keep listening

      setVoiceText("Transcribing…");
      let transcript = "";
      try {
        transcript = await transcribeClip(blob);
      } catch (e) {
        if (state.stopped) return;
        setVoiceText("Couldn't transcribe (" + e.message + ")");
        await sleep(900);
        continue;
      }
      if (state.stopped) return;
      if (!transcript) {
        setVoiceText("Didn't catch that — still listening…");
        await sleep(400);
        continue;
      }

      setVoiceText("Thinking…");
      let reply = "";
      try {
        reply = await sendMessage(transcript);
      } catch {
        reply = "";
      }
      if (state.stopped) return;

      if (reply && voiceTtsReady) {
        setVoiceText("Speaking…");
        await speakReply(reply);
      }
      if (state.stopped) return;
      await sleep(200);
    }
  }

  async function enterVoiceMode() {
    if (voiceState) return;
    if (!voiceSupported()) {
      toast("Voice mode needs microphone access — this browser can't record audio.", "error");
      return;
    }
    if (streaming) {
      toast("Wait for the current reply to finish.", "error");
      return;
    }
    const status = await refreshVoiceStatus();
    if (!status.ready) {
      const detail = status.problems && status.problems[0]
        ? status.problems[0]
        : "run ./voice/astra-voice --setup";
      toast("Voice isn't set up yet — " + detail, "error");
      return;
    }

    voiceState = { stopped: false };
    voiceBtn.classList.add("on");
    voiceBtn.setAttribute("aria-pressed", "true");
    voiceBanner.hidden = false;
    setVoiceText("Listening… speak, then pause");
    toast("Voice mode on — speak, then pause. Click the mic to exit.", "success");
    voiceLoop(voiceState);
  }

  function exitVoiceMode() {
    if (!voiceState) return;
    voiceState.stopped = true;
    voiceState = null;
    if (voiceBtn) {
      voiceBtn.classList.remove("on");
      voiceBtn.setAttribute("aria-pressed", "false");
    }
    if (voiceBanner) voiceBanner.hidden = true;
    if (voiceAudio) {
      try { voiceAudio.pause(); } catch { /* ignore */ }
      voiceAudio = null;
    }
    if (window.speechSynthesis) {
      try { speechSynthesis.cancel(); } catch { /* ignore */ }
    }
  }

  if (voiceBtn) {
    voiceBtn.addEventListener("click", () => {
      if (voiceState) exitVoiceMode();
      else enterVoiceMode();
    });
  }
  if (voiceExitBtn) voiceExitBtn.addEventListener("click", exitVoiceMode);

  // ---- sidebar (mobile) ----------------------------------------------------
  function openSidebar() {
    sidebar.classList.add("open");
    scrim.classList.add("show");
  }
  function closeSidebar() {
    sidebar.classList.remove("open");
    scrim.classList.remove("show");
  }
  menuToggle.addEventListener("click", () => {
    sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
  });
  scrim.addEventListener("click", closeSidebar);

  // ---- model & provider settings ------------------------------------------
  function el(tag, props, children) {
    const node = document.createElement(tag);
    props = props || {};
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else {
        node.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const c of [].concat(children || [])) {
      if (c == null) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }

  function fieldEl(label, input, hint) {
    return el("div", { class: "field" }, [
      el("label", { text: label }),
      input,
      hint ? el("div", { class: "hint", text: hint }) : null,
    ]);
  }

  function applyConfigToUI(cfg) {
    if (!cfg) return;
    const live = cfg.live || {};
    const provider = live.provider || cfg.provider;
    const model = live.model || cfg.model || "";
    const label = (cfg.providers && cfg.providers[provider] && cfg.providers[provider].label) || provider || "model";
    if (modelBadge) {
      modelBadge.textContent = model || label;
      modelBadge.title = label + " · " + model + "  (click to change)";
    }
    if (headerModel) headerModel.textContent = model || label;
    if (composerHint) {
      composerHint.textContent =
        provider === "ollama"
          ? "ASTRA runs locally · powered by " + model
          : "ASTRA · powered by " + label + " (" + model + ")";
    }
  }

  function providerIcon(name) {
    return { ollama: "🖥️", openai: "✦", anthropic: "✳", gemini: "✧" }[name] || "•";
  }

  function renderThinkingRow(cfg) {
    const live = cfg.live || {};
    const enabled = live.thinking !== undefined ? !!live.thinking : !!cfg.thinking;
    const fromEnv = !!cfg.thinking_from_env;
    const model = live.model || cfg.model || "";

    const box = el("input", { type: "checkbox" });
    box.checked = enabled;
    box.disabled = fromEnv;

    const row = el("label", { class: "thinking-row" + (enabled ? " on" : "") }, [
      box,
      el("span", { class: "tr-text" }, [
        el("span", { class: "tr-title", text: "Thinking" }),
        el("span", {
          class: "tr-hint",
          text: fromEnv
            ? "Locked by the ASTRA_THINKING environment variable"
            : (enabled ? "Reasoning shown for " : "Reasoning hidden for ") + (model || "this model"),
        }),
      ]),
    ]);

    if (!fromEnv) {
      box.addEventListener("change", async () => {
        box.disabled = true;
        try {
          const res = await api("/api/thinking", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ thinking: box.checked }),
          });
          settingsConfig = res.config;
          applyConfigToUI(settingsConfig);
          toast("Thinking " + (res.thinking ? "on" : "off"), "success");
          renderSettings();
        } catch (e) {
          box.checked = !box.checked;
          box.disabled = false;
          toast("Could not update thinking: " + e.message, "error");
        }
      });
    }

    return row;
  }

  function toast(message, kind) {
    if (!toastWrap) return;
    const node = el("div", { class: "toast " + (kind || "info") }, [
      el("span", { class: "toast-dot" }),
      el("span", { text: message }),
    ]);
    toastWrap.appendChild(node);
    setTimeout(() => {
      node.classList.add("toast-out");
      setTimeout(() => node.remove(), 260);
    }, 3400);
  }

  function toggleSettings() {
    settingsModal.hidden ? openSettings() : closeSettings();
  }

  function openSettings() {
    settingsModal.hidden = false;
    settingsScrim.hidden = false;
    if (settingsBtn) settingsBtn.setAttribute("aria-expanded", "true");
    settingsBody.innerHTML = '<p class="modal-loading">Loading…</p>';
    loadConfig()
      .then(renderSettings)
      .catch((e) => {
        settingsBody.innerHTML = "";
        settingsBody.appendChild(
          el("p", { class: "settings-error", text: "Could not load settings: " + e.message })
        );
      });
  }

  function closeSettings() {
    settingsModal.hidden = true;
    settingsScrim.hidden = true;
    if (settingsBtn) settingsBtn.setAttribute("aria-expanded", "false");
  }

  async function loadConfig() {
    settingsConfig = await api("/api/providers");
    if (!selectedProvider) selectedProvider = settingsConfig.provider;
    applyConfigToUI(settingsConfig);
    return settingsConfig;
  }

  function renderSettings() {
    const cfg = settingsConfig;
    if (!cfg) return;
    if (!selectedProvider) selectedProvider = cfg.provider;
    settingsBody.innerHTML = "";

    // The currently-active provider, called out at the top.
    const live = cfg.live || {};
    const activeLabel = (cfg.providers[cfg.provider] || {}).label || cfg.provider;
    settingsBody.appendChild(
      el("div", { class: "active-banner" }, [
        el("span", { class: "ab-check", text: "✓" }),
        el("div", {}, [
          el("div", { class: "ab-title", text: "Currently active" }),
          el("div", { class: "ab-sub", text: activeLabel + " · " + (live.model || cfg.model) }),
        ]),
      ])
    );

    settingsBody.appendChild(renderThinkingRow(cfg));

    settingsBody.appendChild(el("h3", { class: "step-title", text: "Where should ASTRA run?" }));
    settingsBody.appendChild(
      el("p", {
        class: "step-sub",
        text: "Local models run on this machine. Cloud providers use your own API key.",
      })
    );

    // Provider list — tap a card to show its settings below.
    const grid = el("div", { class: "provider-grid" });
    for (const [name, info] of Object.entries(cfg.providers)) {
      const isActive = name === cfg.provider;
      const isSelected = name === selectedProvider;
      let dotClass, statusText;
      if (name === "ollama") {
        const running = !!(cfg.ollama && cfg.ollama.running);
        const installed = !!(cfg.ollama && cfg.ollama.installed);
        const count = cfg.ollama && cfg.ollama.models ? cfg.ollama.models.length : 0;
        dotClass = "pc-dot " + (running ? "ok" : "warn");
        statusText = running
          ? "Running · " + count + " model" + (count === 1 ? "" : "s")
          : installed
          ? "Installed · not running"
          : "Not installed yet";
      } else {
        dotClass = "pc-dot " + (info.configured ? "ok" : "warn");
        statusText = info.configured ? "API key saved" : "Needs an API key";
      }
      grid.appendChild(
        el(
          "button",
          {
            class:
              "provider-card" + (isSelected ? " selected" : "") + (isActive ? " active" : ""),
            type: "button",
            onclick: () => {
              selectedProvider = name;
              renderSettings();
            },
          },
          [
            el("div", { class: "pc-top" }, [
              el("span", { class: "pc-icon", text: providerIcon(name) }),
              el("span", { class: dotClass }),
              isActive ? el("span", { class: "pc-tag", text: "Active" }) : null,
            ]),
            el("div", { class: "pc-name", text: info.label }),
            el("div", { class: "pc-meta", text: statusText }),
          ]
        )
      );
    }
    settingsBody.appendChild(grid);

    // Settings for the selected provider, right below the list.
    const info = cfg.providers[selectedProvider] || {};
    const isActive = selectedProvider === cfg.provider;
    settingsBody.appendChild(
      el("div", { class: "configure-head" }, [
        el("span", { class: "pc-icon big", text: providerIcon(selectedProvider) }),
        el("div", {}, [
          el("div", { class: "configure-title", text: info.label || selectedProvider }),
          el("div", { class: "configure-sub", text: isActive ? "Active provider" : "Not active yet" }),
        ]),
        isActive ? el("span", { class: "pc-tag", text: "Active" }) : null,
      ])
    );

    if (selectedProvider === "ollama") renderOllamaSection(settingsBody, cfg);
    else renderCloudSection(settingsBody, cfg, selectedProvider);
  }

  function renderCloudSection(section, cfg, name) {
    const info = cfg.providers[name] || {};
    const isActive = name === cfg.provider;

    if (info.api_key_from_env) {
      section.appendChild(
        el("div", { class: "callout" }, [
          "This API key comes from an environment variable, which overrides anything saved here.",
        ])
      );
    }

    const keyInput = el("input", {
      type: "password",
      autocomplete: "off",
      placeholder: info.api_key_masked
        ? "Saved (" + info.api_key_masked + ") — type to replace"
        : "Paste your API key",
    });
    const modelInput = el("input", { type: "text", value: info.model || info.default_model || "" });

    section.appendChild(
      fieldEl(
        "API key",
        keyInput,
        info.api_key_from_env ? null : "Stored only on this machine and never sent back to the browser."
      )
    );
    section.appendChild(fieldEl("Model", modelInput, "Keep the default or type any model name."));

    const baseInput = el("input", { type: "text", value: info.base_url || "" });
    section.appendChild(
      el("details", { class: "advanced" }, [
        el("summary", { text: "Advanced — base URL" }),
        fieldEl("Base URL", baseInput, "For proxies or OpenAI-compatible endpoints."),
      ])
    );

    const defaultLabel = info.configured && isActive ? "Save changes" : "Connect & activate";
    const saveBtn = el("button", {
      class: "btn primary wide",
      type: "button",
      text: defaultLabel,
      onclick: async () => {
        saveBtn.disabled = true;
        saveBtn.textContent = "Connecting…";
        try {
          const payload = { provider: name, model: modelInput.value.trim() || undefined };
          if (keyInput.value.trim()) payload.api_key = keyInput.value.trim();
          const baseVal = baseInput.value.trim();
          if (baseVal && baseVal !== info.default_base_url) payload.base_url = baseVal;
          const res = await api("/api/providers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          settingsConfig = res.config;
          applyConfigToUI(settingsConfig);
          const used = (res.live && res.live.model) || modelInput.value.trim();
          toast("Now using " + (info.label || name) + " · " + used, "success");
          renderSettings();
        } catch (e) {
          toast("Could not connect: " + e.message, "error");
          saveBtn.disabled = false;
          saveBtn.textContent = defaultLabel;
        }
      },
    });
    section.appendChild(saveBtn);
  }

  function renderOllamaSection(section, cfg) {
    const local = cfg.ollama || {};
    const running = !!local.running;

    section.appendChild(
      el("div", { class: "status-row" }, [
        el("span", { class: "pc-dot " + (running ? "ok" : "warn") }),
        el("span", {
          text: running
            ? "Ollama is running"
            : local.installed
            ? "Ollama is installed but not running"
            : "Ollama is not installed on this machine",
        }),
        local.version ? el("span", { class: "muted", text: " · " + local.version }) : null,
      ])
    );

    const models = local.models || [];
    const activeModel = (cfg.live || {}).model;
    if (running && models.length) {
      section.appendChild(el("label", { class: "field-label", text: "Installed models — tap to use" }));
      const chips = el("div", { class: "chips" });
      for (const m of models) {
        chips.appendChild(
          el("button", {
            class: "chip" + (m.name === activeModel ? " active" : ""),
            type: "button",
            text: m.name,
            title: m.size_human || "",
            onclick: () => activateModel("ollama", m.name),
          })
        );
      }
      section.appendChild(chips);
    } else if (running) {
      section.appendChild(
        el("p", { class: "settings-note", text: "No models installed yet — download one below." })
      );
    }

    section.appendChild(el("div", { class: "divider" }));
    section.appendChild(el("label", { class: "field-label", text: "Download a model" }));
    section.appendChild(
      el("p", {
        class: "settings-note",
        text: "Pick a recommended model below or type any Ollama tag.",
      })
    );

    const rec = local.recommended || [];
    const modelInput = el("input", { type: "text", placeholder: "e.g. qwen3:14b" });
    if (rec.length) {
      const recChips = el("div", { class: "chips" });
      for (const r of rec) {
        recChips.appendChild(
          el("button", {
            class: "chip",
            type: "button",
            text: r.name,
            title: r.size + " — " + r.description,
            onclick: () => {
              modelInput.value = r.name;
            },
          })
        );
      }
      section.appendChild(recChips);
    }
    section.appendChild(modelInput);

    const install = el("input", { type: "checkbox", checked: true, id: "install-ollama" });
    const installLabel = el("label", { class: "check-row" }, [
      install,
      el("span", { text: "Install Ollama automatically if it's missing" }),
    ]);

    const progressBar = el("div", { class: "progress-bar-fill" });
    const progress = el("div", { class: "progress" }, [progressBar]);
    progress.hidden = true;
    const log = el("div", { class: "setup-log" });

    const runBtn = el("button", {
      class: "btn primary wide",
      type: "button",
      text: "Install & download",
      onclick: () =>
        runLocalSetup(modelInput.value.trim(), install.checked, log, runBtn, progress, progressBar),
    });

    section.appendChild(installLabel);
    section.appendChild(runBtn);
    section.appendChild(progress);
    section.appendChild(log);
  }

  async function activateModel(provider, model) {
    try {
      const res = await api("/api/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      });
      settingsConfig = res.config;
      applyConfigToUI(settingsConfig);
      toast("Now using " + model, "success");
      renderSettings();
    } catch (e) {
      toast("Could not switch model: " + e.message, "error");
    }
  }

  async function runLocalSetup(model, install, logEl, btn, progressEl, barEl) {
    logEl.textContent = "";
    if (!model) {
      toast("Enter or pick a model name first.", "error");
      return;
    }
    btn.disabled = true;
    btn.textContent = "Working…";
    if (progressEl) {
      progressEl.hidden = false;
      barEl.style.width = "0%";
    }
    const append = (t) => {
      logEl.textContent += String(t) + "\n";
      logEl.scrollTop = logEl.scrollHeight;
    };
    const setBar = (msg) => {
      const m = String(msg).match(/(\d+(?:\.\d+)?)%/);
      if (m && barEl) barEl.style.width = Math.min(100, parseFloat(m[1])) + "%";
    };
    let succeeded = false;
    try {
      const res = await fetch("/api/providers/ollama/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, install }),
      });
      if (!res.ok || !res.body) throw new Error("HTTP " + res.status);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);
          if (!line) continue;
          let evt;
          try {
            evt = JSON.parse(line);
          } catch {
            continue;
          }
          if (evt.type === "progress") {
            append(evt.message);
            setBar(evt.message);
          } else if (evt.type === "error") {
            append("⚠ " + evt.message);
          } else if (evt.type === "result") {
            succeeded = !!evt.ok;
            append(evt.ok ? "Done." : "Setup did not complete.");
          }
        }
      }
    } catch (e) {
      append("⚠ " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Install & download";
      if (barEl && succeeded) barEl.style.width = "100%";
      try {
        selectedProvider = "ollama";
        await loadConfig();
        if (succeeded) {
          toast("Model ready: " + model, "success");
        }
        renderSettings();
      } catch {
        /* ignore */
      }
    }
  }

  // ---- health / init -------------------------------------------------------
  async function checkHealth() {
    try {
      const data = await api("/api/health");
      statusDot.className = "dot ok";
      statusText.textContent = "online";
      modelBadge.textContent = data.model;
      headerModel.textContent = data.model;
      if (data.provider) modelBadge.title = data.provider + " · " + data.model + "  (click to change)";
    } catch (e) {
      statusDot.className = "dot err";
      statusText.textContent = "offline";
    }
  }

  // ---- settings wiring -----------------------------------------------------
  settingsBtn.addEventListener("click", toggleSettings);
  settingsClose.addEventListener("click", closeSettings);
  modelBadge.addEventListener("click", toggleSettings);
  settingsScrim.addEventListener("click", closeSettings);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!settingsModal.hidden) closeSettings();
    else if (voiceState) exitVoiceMode();
  });

  // The extension's "Voice mode" button opens this page with ?voice=1.
  const wantsVoice =
    new URLSearchParams(location.search).has("voice") ||
    location.hash.replace("#", "").toLowerCase() === "voice";

  async function init() {
    await checkHealth();
    await refreshSessions();
    if (currentSessionId) await loadMessages(currentSessionId);
    // Fetch provider config in the background so badges/hint show the real
    // provider without requiring the settings panel to be opened.
    loadConfig().catch(() => {});
    // Warm the voice status so the first mic click is instant, and honour the
    // deep link from the browser extension.
    refreshVoiceStatus().catch(() => {});
    autoResize();
    inputEl.focus();
    if (wantsVoice) enterVoiceMode();
  }

  init();
})();
