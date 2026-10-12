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
  const settingsBody = $("settings-body");
  const composerHint = $("composer-hint");

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
    if (!text || streaming) return;

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

  function openSettings() {
    settingsModal.hidden = false;
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

    const live = cfg.live || {};
    settingsBody.appendChild(
      el("p", { class: "current-line" }, [
        "Active: ",
        el("b", { text: (cfg.providers[cfg.provider] || {}).label || cfg.provider }),
        " · ",
        el("b", { text: live.model || cfg.model }),
      ])
    );

    const grid = el("div", { class: "provider-grid" });
    for (const [name, info] of Object.entries(cfg.providers)) {
      const isActive = name === cfg.provider;
      let dotClass, meta;
      if (name === "ollama") {
        const running = !!(cfg.ollama && cfg.ollama.running);
        dotClass = "pc-dot " + (running ? "ok" : "warn");
        const count = (cfg.ollama && cfg.ollama.models ? cfg.ollama.models.length : 0);
        meta = running ? count + " model" + (count === 1 ? "" : "s") + " installed" : "not running";
      } else {
        dotClass = "pc-dot " + (info.configured ? "ok" : "warn");
        meta = info.configured ? "key set · " + info.model : "no API key yet";
      }
      grid.appendChild(
        el(
          "button",
          {
            class: "provider-card" + (name === selectedProvider ? " active" : ""),
            type: "button",
            onclick: () => {
              selectedProvider = name;
              renderSettings();
            },
          },
          [
            el("div", { class: "pc-name" }, [
              el("span", { class: dotClass }),
              info.label + (isActive ? " ✓" : ""),
            ]),
            el("div", { class: "pc-meta", text: meta }),
          ]
        )
      );
    }
    settingsBody.appendChild(grid);

    const section = el("div", { class: "settings-section" });
    settingsBody.appendChild(section);
    if (selectedProvider === "ollama") renderOllamaSection(section, cfg);
    else renderCloudSection(section, cfg, selectedProvider);
  }

  function renderCloudSection(section, cfg, name) {
    const info = cfg.providers[name] || {};
    section.appendChild(el("h3", { text: info.label || name }));

    const keyInput = el("input", {
      type: "password",
      autocomplete: "off",
      placeholder: info.api_key_masked
        ? "saved (" + info.api_key_masked + ") — type to replace"
        : "paste your API key",
    });
    const modelInput = el("input", { type: "text", value: info.model || info.default_model || "" });
    const baseInput = el("input", { type: "text", value: info.base_url || "" });

    section.appendChild(
      fieldEl(
        "API key",
        keyInput,
        info.api_key_from_env
          ? "Set by an environment variable (overrides this field)."
          : "Stored locally in core/config/settings.json (file mode 600)."
      )
    );
    section.appendChild(fieldEl("Model", modelInput, ""));
    section.appendChild(
      el("details", { class: "advanced" }, [
        el("summary", { text: "Advanced (base URL)" }),
        fieldEl("Base URL", baseInput, "For proxies or OpenAI-compatible endpoints."),
      ])
    );

    const msg = el("p", { class: "settings-note" });
    const saveBtn = el("button", {
      class: "btn primary",
      type: "button",
      text: "Save & activate",
      onclick: async () => {
        saveBtn.disabled = true;
        msg.className = "settings-note";
        msg.textContent = "Saving…";
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
          selectedProvider = name;
          applyConfigToUI(settingsConfig);
          renderSettings();
        } catch (e) {
          msg.className = "settings-error";
          msg.textContent = e.message;
          saveBtn.disabled = false;
        }
      },
    });
    section.appendChild(el("div", { class: "btn-row" }, [saveBtn]));
    section.appendChild(msg);
  }

  function renderOllamaSection(section, cfg) {
    const local = cfg.ollama || {};
    const running = !!local.running;
    section.appendChild(el("h3", { text: "Local models (Ollama)" }));
    section.appendChild(
      el("div", { class: "status-row" }, [
        el("span", { class: "pc-dot " + (running ? "ok" : "warn") }),
        running
          ? "Ollama is running"
          : local.installed
          ? "Ollama is installed but not running"
          : "Ollama is not installed on this machine",
        local.version ? el("span", { text: " · " + local.version }) : null,
      ])
    );

    const models = local.models || [];
    const chips = el("div", { class: "chips" });
    const activeModel = (cfg.live || {}).model;
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

    section.appendChild(
      el("p", {
        class: "settings-note",
        text: "Download another model. On a fresh machine, tick “Install Ollama” to set everything up.",
      })
    );

    const modelInput = el("input", { type: "text", placeholder: "e.g. qwen3:14b" });
    const rec = local.recommended || [];
    if (rec.length) {
      modelInput.setAttribute("list", "rec-models");
      const datalist = el("datalist", { id: "rec-models" });
      for (const r of rec) datalist.appendChild(el("option", { value: r.name, label: r.name }));
      section.appendChild(fieldEl("Model", modelInput, ""));
      section.appendChild(datalist);
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
    } else {
      section.appendChild(fieldEl("Model", modelInput, ""));
    }

    const install = el("input", { type: "checkbox", checked: true, id: "install-ollama" });
    const installLabel = el("label", { class: "settings-note", style: "display:flex;gap:8px;align-items:center;cursor:pointer" }, [
      install,
      "Install Ollama if missing",
    ]);
    const log = el("div", { class: "setup-log" });
    const runBtn = el("button", {
      class: "btn",
      type: "button",
      text: "Install & download",
      onclick: () => runLocalSetup(modelInput.value.trim(), install.checked, log, runBtn),
    });
    section.appendChild(el("div", { class: "btn-row" }, [installLabel, runBtn]));
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
      renderSettings();
    } catch (e) {
      alert("Could not switch model: " + e.message);
    }
  }

  async function runLocalSetup(model, install, logEl, btn) {
    logEl.textContent = "";
    if (!model) {
      logEl.textContent = "Enter or pick a model name first.\n";
      return;
    }
    btn.disabled = true;
    const append = (t) => {
      logEl.textContent += String(t) + "\n";
      logEl.scrollTop = logEl.scrollHeight;
    };
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
          if (evt.type === "progress") append(evt.message);
          else if (evt.type === "error") append("⚠ " + evt.message);
          else if (evt.type === "result") append(evt.ok ? "Done." : "Setup did not complete.");
        }
      }
    } catch (e) {
      append("⚠ " + e.message);
    } finally {
      btn.disabled = false;
      try {
        selectedProvider = "ollama";
        await loadConfig();
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
  settingsBtn.addEventListener("click", openSettings);
  settingsClose.addEventListener("click", closeSettings);
  modelBadge.addEventListener("click", openSettings);
  settingsModal.addEventListener("click", (e) => {
    if (e.target === settingsModal) closeSettings();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !settingsModal.hidden) closeSettings();
  });

  async function init() {
    await checkHealth();
    await refreshSessions();
    if (currentSessionId) await loadMessages(currentSessionId);
    // Fetch provider config in the background so badges/hint show the real
    // provider without requiring the settings panel to be opened.
    loadConfig().catch(() => {});
    autoResize();
    inputEl.focus();
  }

  init();
})();
