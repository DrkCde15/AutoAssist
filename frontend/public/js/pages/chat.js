/**
 * chat.js — Página de Chat com IA (NOG).
 *
 * Endpoints:
 *   POST /api/chat            — envia mensagem (message, vehicle_id?, session_id?, image?, attachment?)
 *   POST /api/voice           — envia áudio para transcrição (audio, vehicle_id?, session_id?)
 *   GET  /api/chat/history     — histórico do usuário (chats[])
 *   GET  /api/chat/conversations — conversas agrupadas por session_id
 *   GET  /api/veiculos         — lista de veículos do usuário
 *   DELETE /api/chat/history/:id — deleta um registro
 *   DELETE /api/chat/session/:id — deleta uma sessão inteira
 */
(function () {
  "use strict";

  var CHAT_ENDPOINT = "/api/chat";
  var HISTORY_ENDPOINT = "/api/chat/history";
  var CONVERSATIONS_ENDPOINT = "/api/chat/conversations";
  var VEICULOS_ENDPOINT = "/api/veiculos";

  var state = {
    messages: [],
    conversations: [],
    vehicles: [],
    activeSessionId: null,
    sending: false,
    latestId: 0,
    // Local conversation tracking (keyed by session_id)
    localMessages: {},
    localConversationMeta: {},
  };

  function generateSessionId() {
    return "s_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
  }

  // ── DOM refs ──
  var messagesEl = null;
  var textareaEl = null;
  var sendBtn = null;
  var fileInput = null;
  var vehicleSelect = null;
  var conversationsList = null;
  var sidebarEl = null;
  var mainEl = null;
  var emptyStateEl = null;
  var typingEl = null;
  var chatWrapper = null;
  var sidebarBackdrop = null;

  // ── Helpers ──
  function escapeHTML(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatTime(isoStr) {
    if (!isoStr) return "";
    try {
      var d = new Date(isoStr);
      if (isNaN(d.getTime())) return "";
      return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    } catch (_) {
      return "";
    }
  }

  function sendChatFeedback(chatId, avaliacao) {
    if (!isLoggedIn() || !chatId) return;
    window.api.post("/api/chat/feedback", {
      avaliacao: avaliacao,
      chat_id: chatId
    }).catch(function () {});
  }

  function deleteChatMessage(chatId, element) {
    if (!isLoggedIn() || !chatId) return;
    window.api.delete("/api/chat/history/" + chatId).then(function () {
      if (element) element.remove();
    }).catch(function () {});
  }

  function formatDate(isoStr) {
    if (!isoStr) return "";
    try {
      var d = new Date(isoStr);
      if (isNaN(d.getTime())) return "";
      var today = new Date();
      var yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);

      if (d.toDateString() === today.toDateString()) return "Hoje";
      if (d.toDateString() === yesterday.toDateString()) return "Ontem";
      return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
    } catch (_) {
      return "";
    }
  }

  function formatFileSize(bytes) {
    if (!bytes) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function scrollToBottom(smooth) {
    if (!messagesEl) return;
    if (smooth) {
      messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" });
    } else {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  function isNearBottom() {
    if (!messagesEl) return true;
    var distance = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight;
    return distance < 120;
  }

  function scrollToBottomIfNear(smooth, wasNearBottom) {
    if (wasNearBottom === false) return;
    scrollToBottom(smooth);
  }

  function nl2br(str) {
    if (!str) return "";
    return escapeHTML(str).replace(/\n/g, "<br>");
  }

  function vehicleLabel(v) {
    var parts = [v.marca, v.modelo].filter(Boolean);
    var label = parts.join(" ") || "Veículo #" + v.id;
    if (v.ano_fabricacao) label += " (" + v.ano_fabricacao + ")";
    return label;
  }

  function extractDomain(url) {
    if (!url) return "";
    try {
      var u = new URL(url);
      return u.hostname.replace("www.", "");
    } catch (_) {
      return "";
    }
  }

  function friendlyDomainName(url) {
    var domain = extractDomain(url);
    if (!domain) return "Link";
    var map = {
      "youtube.com": "YouTube",
      "youtu.be": "YouTube",
      "webmotors.com.br": "Webmotors",
      "icarros.com.br": "iCarros",
      "olx.com.br": "OLX",
      "mercadolivre.com.br": "Mercado Livre",
      "mercadolibre.com.ar": "Mercado Libre",
      "autoassist.com.br": "AutoAssist",
      "google.com": "Google",
      "github.com": "GitHub",
    };
    for (var key in map) {
      if (domain.indexOf(key) !== -1) return map[key];
    }
    return domain.charAt(0).toUpperCase() + domain.slice(1);
  }

  var DESKTOP_BP = 1024;

  // ── Build UI ──
  function buildUI() {
    var container = document.querySelector("main") || document.querySelector("body");

    // Inject chat-specific responsive styles
    if (!document.getElementById("chat-responsive-css")) {
      var chatCss = document.createElement("style");
      chatCss.id = "chat-responsive-css";
      chatCss.textContent =
        "html { font-size: 16px; }" +
        ".w-80 { width: 20rem; }" +
        ".w-fit { width: fit-content; }" +
        ".h-full { height: 100%; }" +
        ".min-h-0 { min-height: 0; }" +
        ".max-h-32 { max-height: 8rem; }" +
        ".max-w-sm { max-width: 24rem; }" +
        ".z-10 { z-index: 10; }" +
        ".opacity-100 { opacity: 1; }" +
        ".pointer-events-auto { pointer-events: auto; }" +
        ".translate-y-0 { transform: translateY(0); }" +
        ".translate-y-2 { transform: translateY(0.5rem); }" +
        ".font-normal { font-weight: 400; }" +
        ".ml-auto { margin-left: auto; }" +
        ".col-span-full { grid-column: 1 / -1; }" +
        ".bg-zinc-700 { background-color: #3f3f46; }" +
        ".bg-zinc-800 { background-color: #27272a; }" +
        ".bg-muted { background-color: var(--color-text-muted); }" +
        ".text-primary { color: var(--color-text-primary); }" +
        ".text-secondary { color: var(--color-text-secondary); }" +
        ".text-muted { color: var(--color-text-muted); }" +
        ".bg-card { background-color: var(--color-bg-card); }" +
        ".bg-primary { background-color: var(--color-bg-primary); }" +
        ".bg-primary\\/30 { background-color: color-mix(in srgb, var(--color-bg-primary) 30%, transparent); }" +
        ".bg-primary\\/50 { background-color: color-mix(in srgb, var(--color-bg-primary) 50%, transparent); }" +
        ".bg-accent\\/10 { background-color: color-mix(in srgb, var(--color-accent) 10%, transparent); }" +
        ".bg-accent\\/15 { background-color: color-mix(in srgb, var(--color-accent) 15%, transparent); }" +
        ".bg-black\\/60 { background-color: rgba(0,0,0,0.6); }" +
        ".text-amber-500 { color: #f59e0b; }" +
        ".text-emerald-600 { color: #059669; }" +
        ".text-green-500 { color: #22c55e; }" +
        ".text-gray-500 { color: #6b7280; }" +
        ".hover\\:bg-white\\/5:hover { background-color: rgba(255,255,255,0.05); }" +
        ".hover\\:text-primary:hover { color: var(--color-text-primary); }" +
        ".hover\\:border-accent\\/50:hover { border-color: color-mix(in srgb, var(--color-accent) 50%, transparent); }" +
        ".hover\\:text-red-400:hover { color: #f87171; }" +
        ".focus\\:outline-none:focus { outline: 2px solid transparent; outline-offset: 2px; }" +
        ".focus\\:ring-2:focus { box-shadow: 0 0 0 2px var(--color-bg-primary), 0 0 0 4px var(--color-accent); }" +
        ".disabled\\:opacity-40:disabled { opacity: 0.4; }" +
        "#chat-messages { max-width: 900px; margin: 0 auto; width: 100%; }" +
        "#chat-messages > div { padding-left: 0; padding-right: 0; }" +
        "#chat-empty-state { box-sizing: border-box; min-height: 100%; }" +
        ".h-\\[calc\\(100vh-64px\\)\\] { height: calc(100vh - 64px); height: calc(100dvh - 64px); }" +
        "#chat-messages { scrollbar-width: none; -ms-overflow-style: none; }" +
        "#chat-messages::-webkit-scrollbar { display: none; }" +
        "@keyframes typing-dot { 0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); } 40% { opacity: 1; transform: scale(1); } }" +
        "#chat-sidebar-backdrop { z-index: 900; }" +
        "#chat-sidebar { z-index: 1000; position: fixed; top: 64px; left: 0; bottom: 0; width: 20rem; transform: translateX(-100%); transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), visibility 0s 0.3s; will-change: transform; pointer-events: none; visibility: hidden; }" +
        "#chat-sidebar.mobile-open { transform: translateX(0); pointer-events: auto; visibility: visible; transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), visibility 0s 0s; }" +
        "#chat-sidebar.mobile-closing { transform: translateX(-100%); pointer-events: none; visibility: hidden; transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), visibility 0s 0.3s; }" +
        "@media (min-width: 1024px) {" +
          "#chat-sidebar { position: static !important; transform: none !important; transition: none !important; pointer-events: auto !important; visibility: visible !important; z-index: auto !important; width: 20rem; }" +
        "}" +
        "@media (max-width: 768px) {" +
          "#chat-messages { max-width: 100%; padding-left: 12px; padding-right: 12px; }" +
          "#chat-empty-state { padding-top: 24px; padding-bottom: 24px; }" +
          "#chat-empty-state img { height: 96px; margin-bottom: 16px; }" +
          "#chat-empty-state .chat-suggestion { padding: 12px; }" +
          "#chat-messages > div > div:last-child { max-width: calc(100% - 44px) !important; }" +
          "#chat-messages > div > div:last-child > div { word-break: break-word; }" +
        "}";
      document.head.appendChild(chatCss);
    }

    // Main wrapper
    chatWrapper = document.createElement("div");
    chatWrapper.id = "chat-wrapper";
    chatWrapper.className = "flex h-[calc(100vh-64px)] min-h-0";

    // ── Sidebar backdrop (mobile) ──
    sidebarBackdrop = document.createElement("div");
    sidebarBackdrop.id = "chat-sidebar-backdrop";
    sidebarBackdrop.className = "fixed inset-0 bg-black/60 backdrop-blur-sm opacity-0 pointer-events-none transition-opacity duration-300";
    if (isLoggedIn()) document.body.appendChild(sidebarBackdrop);

    // ── Sidebar ──
    sidebarEl = document.createElement("aside");
    sidebarEl.id = "chat-sidebar";
    sidebarEl.className = "flex flex-col w-80 border-r border-border bg-primary shrink-0";
    sidebarEl.setAttribute("role", "complementary");
    sidebarEl.setAttribute("aria-label", "Conversas");
    if (!isLoggedIn()) sidebarEl.style.display = "none";

    var sidebarHeader = document.createElement("div");
    sidebarHeader.className = "flex items-center justify-between p-4 border-b border-border";
    sidebarHeader.innerHTML =
      '<h2 class="text-sm font-semibold text-primary">Conversas</h2>' +
      '<div class="flex items-center gap-1">' +
        '<button type="button" id="chat-new-btn" class="rounded-lg bg-accent/10 p-1.5 text-accent hover:bg-accent/20 transition-colors" title="Nova conversa" aria-label="Nova conversa">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="5" y2="19"></line><line x1="5" x2="19" y1="12" y2="12"></line></svg>' +
        '</button>' +
        '<button type="button" id="chat-close-sidebar" class="rounded-lg p-1.5 text-secondary hover:bg-white/5 hover:text-primary transition-colors" title="Fechar menu" aria-label="Fechar menu">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>' +
        '</button>' +
      '</div>';
    sidebarEl.appendChild(sidebarHeader);

    var searchWrap = document.createElement("div");
    searchWrap.className = "px-3 py-2";
    var searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.placeholder = "Buscar conversas...";
    searchInput.className = "w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-primary placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50";
    searchInput.id = "chat-search-input";
    searchWrap.appendChild(searchInput);
    sidebarEl.appendChild(searchWrap);

    conversationsList = document.createElement("div");
    conversationsList.id = "chat-conversations-list";
    conversationsList.className = "flex-1 overflow-y-auto";
    sidebarEl.appendChild(conversationsList);

    chatWrapper.appendChild(sidebarEl);

    // ── Main chat area ──
    mainEl = document.createElement("div");
    mainEl.className = "flex flex-col flex-1 min-w-0 min-h-0";

    // Chat header
    var chatHeader = document.createElement("div");
    chatHeader.className = "flex items-center gap-3 border-b border-border bg-primary/30 px-4 py-3 shrink-0";

    // Sidebar toggle (mobile only)
    var toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "rounded-lg p-2 text-secondary hover:bg-white/5 transition-colors";
    toggleBtn.setAttribute("aria-label", "Abrir menu de conversas");
    toggleBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" x2="21" y1="6" y2="6"></line><line x1="3" x2="21" y1="12" y2="12"></line><line x1="3" x2="21" y1="18" y2="18"></line></svg>';
    if (!isLoggedIn()) toggleBtn.style.display = "none";

    function isDesktop() {
      return window.innerWidth >= DESKTOP_BP;
    }

    function openSidebar() {
      sidebarEl.classList.remove("mobile-closing");
      sidebarEl.style.display = "";
      // Force reflow so the browser registers the initial state before adding the class
      void sidebarEl.offsetHeight;
      sidebarEl.classList.add("mobile-open");
      sidebarBackdrop.classList.remove("pointer-events-none", "opacity-0");
      sidebarBackdrop.classList.add("pointer-events-auto", "opacity-100");
      document.body.style.overflow = "hidden";
    }

    function closeSidebar() {
      sidebarEl.classList.remove("mobile-open");
      sidebarEl.classList.add("mobile-closing");
      sidebarBackdrop.classList.add("pointer-events-none", "opacity-0");
      sidebarBackdrop.classList.remove("pointer-events-auto", "opacity-100");
      document.body.style.overflow = "";

      function finishClose() {
        sidebarEl.classList.remove("mobile-closing");
        sidebarEl.style.display = "none";
        syncViewport();
      }

      var closed = false;
      function onDone() {
        if (closed) return;
        closed = true;
        finishClose();
      }

      sidebarEl.addEventListener("transitionend", function handler(e) {
        if (e.propertyName === "transform") {
          sidebarEl.removeEventListener("transitionend", handler);
          onDone();
        }
      });

      setTimeout(onDone, 350);
    }

    var closeSidebarBtn = sidebarHeader.querySelector("#chat-close-sidebar");
    if (closeSidebarBtn) {
      closeSidebarBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        closeSidebar();
      });
    }

    function syncViewport() {
      if (isDesktop()) {
        sidebarEl.style.display = "";
        sidebarEl.classList.remove("mobile-open", "mobile-closing");
        sidebarBackdrop.classList.add("pointer-events-none", "opacity-0");
        sidebarBackdrop.classList.remove("pointer-events-auto", "opacity-100");
        sidebarBackdrop.style.display = "none";
        toggleBtn.style.display = "none";
        vehicleWrap.style.display = "flex";
        document.body.style.overflow = "";
      } else {
        if (!sidebarEl.classList.contains("mobile-open")) {
          sidebarEl.style.display = "none";
        }
        sidebarEl.classList.remove("mobile-closing");
        sidebarBackdrop.style.display = "";
        toggleBtn.style.display = "";
        vehicleWrap.style.display = "none";
      }
    }

    toggleBtn.addEventListener("click", function () {
      if (isDesktop()) return;
      var isOpen = sidebarEl.classList.contains("mobile-open");
      if (isOpen) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });

    sidebarBackdrop.addEventListener("click", closeSidebar);

    // Close sidebar on ESC key
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && sidebarEl.classList.contains("mobile-open")) {
        closeSidebar();
      }
    });

    chatHeader.appendChild(toggleBtn);

    var headerInfo = document.createElement("div");
    headerInfo.className = "flex-1 min-w-0";
    headerInfo.innerHTML =
      '<p class="text-sm font-semibold text-primary truncate">NOG - Consultor Automotivo</p>' +
      '<p class="text-xs text-muted truncate" id="chat-session-label">Nova conversa</p>';
    chatHeader.appendChild(headerInfo);

    // Vehicle selector
    var vehicleWrap = document.createElement("div");
    vehicleWrap.className = "items-center gap-2";
    vehicleWrap.style.display = "none";
    vehicleSelect = document.createElement("select");
    vehicleSelect.id = "chat-vehicle-select";
    vehicleSelect.className = "rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs text-secondary focus:outline-none focus:ring-2 focus:ring-accent/50 max-w-[200px]";
    var defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "Sem veículo";
    vehicleSelect.appendChild(defaultOpt);
    vehicleWrap.appendChild(vehicleSelect);
    chatHeader.appendChild(vehicleWrap);

    // Init viewport-dependent visibility
    syncViewport();
    window.addEventListener("resize", syncViewport);

    // Attach header
    mainEl.appendChild(chatHeader);

    // Messages area
    messagesEl = document.createElement("div");
    messagesEl.id = "chat-messages";
    messagesEl.className = "flex flex-col flex-1 min-h-0 overflow-y-auto px-4 py-6 space-y-5";
    mainEl.appendChild(messagesEl);

    // Attachment preview (hidden by default)
    var attachmentPreview = document.createElement("div");
    attachmentPreview.id = "chat-attachment-preview";
    attachmentPreview.className = "hidden px-4 py-2 border-t border-border bg-primary/30 shrink-0";
    mainEl.appendChild(attachmentPreview);

    // File input (hidden)
    fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.className = "hidden";
    fileInput.accept = "image/jpeg,image/png,image/webp,image/gif,application/pdf,text/plain,text/csv,text/markdown,application/json";
    mainEl.appendChild(fileInput);

    // Input area
    var inputArea = document.createElement("div");
    inputArea.className = "border-t border-border bg-primary/50 px-4 py-3 shrink-0";

    var inputRow = document.createElement("div");
    inputRow.className = "flex items-end gap-2 max-w-5xl mx-auto";

    // Action button (plus icon) with dropdown
    var actionWrap = document.createElement("div");
    actionWrap.className = "relative shrink-0";

    var actionBtn = document.createElement("button");
    actionBtn.type = "button";
    actionBtn.className = "rounded-xl p-3 text-secondary border border-border bg-card hover:bg-white/5 hover:text-primary transition-colors";
    actionBtn.setAttribute("aria-label", "Ações");
    actionBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="5" y2="19"></line><line x1="5" x2="19" y1="12" y2="12"></line></svg>';
    actionWrap.appendChild(actionBtn);

    // Dropdown menu
    var actionMenu = document.createElement("div");
    actionMenu.className = "absolute bottom-full left-0 mb-2 w-52 rounded-xl border border-border bg-card shadow-xl opacity-0 pointer-events-none transition-all duration-200 translate-y-2 z-50";
    actionMenu.innerHTML =
      '<div class="py-1">' +
        '<button type="button" class="chat-action-item flex w-full items-center gap-3 px-4 py-2.5 text-sm text-secondary hover:bg-accent/10 hover:text-primary transition-colors" data-action="photo">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path></svg>' +
          '<span>Enviar foto</span>' +
        '</button>' +
        '<button type="button" class="chat-action-item flex w-full items-center gap-3 px-4 py-2.5 text-sm text-secondary hover:bg-accent/10 hover:text-primary transition-colors" data-action="file">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"></path><path d="M14 2v4a2 2 0 0 0 2 2h4"></path></svg>' +
          '<span>Enviar arquivo</span>' +
        '</button>' +
        '<div class="my-1 border-t border-border"></div>' +
        '<button type="button" class="chat-action-item flex w-full items-center gap-3 px-4 py-2.5 text-sm text-secondary hover:bg-accent/10 hover:text-primary transition-colors" data-action="report">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" x2="12" y1="15" y2="3"></line></svg>' +
          '<span>Baixar laudo</span>' +
        '</button>' +
      '</div>';
    actionWrap.appendChild(actionMenu);

    // Toggle dropdown
    actionBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var isOpen = !actionMenu.classList.contains("opacity-0");
      if (isOpen) {
        actionMenu.classList.add("opacity-0", "pointer-events-none", "translate-y-2");
        actionMenu.classList.remove("opacity-100", "pointer-events-auto", "translate-y-0");
      } else {
        actionMenu.classList.remove("opacity-0", "pointer-events-none", "translate-y-2");
        actionMenu.classList.add("opacity-100", "pointer-events-auto", "translate-y-0");
      }
    });

    // Close on outside click
    document.addEventListener("click", function () {
      actionMenu.classList.add("opacity-0", "pointer-events-none", "translate-y-2");
      actionMenu.classList.remove("opacity-100", "pointer-events-auto", "translate-y-0");
    });

    // Action handlers
    var actionItems = actionMenu.querySelectorAll(".chat-action-item");
    for (var ai = 0; ai < actionItems.length; ai++) {
      (function (item) {
        item.addEventListener("click", function () {
          var action = item.getAttribute("data-action");
          actionMenu.classList.add("opacity-0", "pointer-events-none", "translate-y-2");
          actionMenu.classList.remove("opacity-100", "pointer-events-auto", "translate-y-0");
          if (action === "photo") {
            fileInput.accept = "image/jpeg,image/png,image/webp,image/gif";
            fileInput.click();
          } else if (action === "file") {
            fileInput.accept = "application/pdf,text/plain,text/csv,text/markdown,application/json";
            fileInput.click();
          } else if (action === "report") {
            downloadChatReport();
          }
        });
      })(actionItems[ai]);
    }

    textareaEl = document.createElement("textarea");
    textareaEl.id = "chat-textarea";
    textareaEl.rows = 1;
    textareaEl.placeholder = "Pergunte ao NOG sobre seu veículo...";
    textareaEl.className = "flex-1 resize-none rounded-xl border border-border bg-card px-4 py-3 text-sm text-primary placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 max-h-32 overflow-y-auto";
    textareaEl.style.minHeight = "44px";

    var micBtn = document.createElement("button");
    micBtn.type = "button";
    micBtn.id = "chat-mic-btn";
    micBtn.className = "rounded-xl p-3 text-secondary border border-border bg-card hover:bg-white/5 hover:text-primary transition-colors shrink-0";
    micBtn.setAttribute("aria-label", "Gravar áudio");
    micBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>';

    // ── Voice recording ──
    var mediaRecorder = null;
    var audioChunks = [];
    var isRecording = false;

    micBtn.addEventListener("click", function () {
      if (isRecording) {
        mediaRecorder.stop();
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert("Gravação de áudio não suportada neste navegador.");
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then(function (stream) {
          audioChunks = [];
          mediaRecorder = new MediaRecorder(stream);
          mediaRecorder.ondataavailable = function (e) {
            if (e.data.size > 0) audioChunks.push(e.data);
          };
          mediaRecorder.onstop = function () {
            stream.getTracks().forEach(function (t) { t.stop(); });
            isRecording = false;
            micBtn.classList.remove("bg-red-500/20", "text-red-400", "border-red-500/50");
            micBtn.classList.add("text-secondary", "border-border", "bg-card");
            micBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>';
            if (audioChunks.length > 0) {
              var blob = new Blob(audioChunks, { type: "audio/webm" });
              sendVoice(blob);
            }
          };
          mediaRecorder.start();
          isRecording = true;
          micBtn.classList.remove("text-secondary", "border-border", "bg-card");
          micBtn.classList.add("bg-red-500/20", "text-red-400", "border-red-500/50");
          micBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="3" fill="currentColor"></circle></svg>';
        })
        .catch(function () {
          alert("Permissão de microfone negada.");
        });
    });

    function sendVoice(blob) {
      if (state.sending) return;

      // Ensure there is always a session_id
      if (!state.activeSessionId) {
        state.activeSessionId = generateSessionId();
      }

      state.sending = true;
      updateSendBtn();
      hideEmptyState();

      var userMsg = { role: "user", content: "[Áudio]", timestamp: new Date().toISOString() };
      renderMessage(userMsg);
      scrollToBottom(true);

      // Track locally
      var sid = state.activeSessionId;
      if (!state.localMessages[sid]) state.localMessages[sid] = [];
      state.localMessages[sid].push(userMsg);
      persistGuestCache();
      if (!state.localConversationMeta[sid]) {
        state.localConversationMeta[sid] = {
          session_id: sid,
          title: "Áudio",
          preview: "[Áudio]",
          count: 1,
          updated_at: userMsg.timestamp,
        };
      } else {
        state.localConversationMeta[sid].count = state.localMessages[sid].length;
        state.localConversationMeta[sid].updated_at = userMsg.timestamp;
      }

      textareaEl.value = "";
      autoResize();
      updateSendBtn();
      showTyping();

      var fd = new FormData();
      fd.append("audio", blob, "recording.webm");
      var vehicleVal = vehicleSelect ? vehicleSelect.value : "";
      if (vehicleVal) fd.append("vehicle_id", vehicleVal);
      fd.append("session_id", state.activeSessionId);

      var token = localStorage.getItem("autoassist_access_token");
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      if (!isLoggedIn()) headers["X-AutoAssist-Guest-Id"] = getGuestId();

      fetch("/api/voice", {
        method: "POST",
        headers: headers,
        credentials: "include",
        body: fd,
      })
        .then(function (res) {
          if (!res.ok) return res.json().then(function (b) { throw new Error(b.error || "Erro ao enviar áudio"); });
          return res.json();
        })
        .then(function (data) {
          var shouldFollow = isNearBottom();
          hideTyping();
          if (!data) return;
          var aiMsg = { role: "assistant", content: data.response || data.text || "", timestamp: new Date().toISOString() };
          renderMessage(aiMsg);
          scrollToBottomIfNear(true, shouldFollow);

          // Track assistant message locally
          if (sid) {
            state.localMessages[sid].push(aiMsg);
            if (state.localConversationMeta[sid]) {
              state.localConversationMeta[sid].count = state.localMessages[sid].length;
              state.localConversationMeta[sid].updated_at = aiMsg.timestamp;
            }
          }

          if (data.chat && data.chat.id) {
            state.latestId = data.chat.id;
          }

          if (data.guest_messages_remaining !== undefined) {
            var remaining = data.guest_messages_remaining;
            var limit = data.guest_limit || 5;
            if (remaining <= 2 && remaining > 0) {
              renderMessage({ role: "assistant", content: "Você tem " + remaining + " mensagem" + (remaining > 1 ? "s" : "") + " restante" + (remaining > 1 ? "s" : "") + ". Crie uma conta para continuar.", timestamp: new Date().toISOString() });
              scrollToBottomIfNear(true, shouldFollow);
            } else if (remaining === 0) {
              renderMessage({ role: "assistant", content: "Você atingiu o limite de " + limit + " mensagens gratuitas. Crie uma conta ou faça login para continuar.", timestamp: new Date().toISOString() });
              scrollToBottomIfNear(true, shouldFollow);
              textareaEl.disabled = true;
              sendBtn.disabled = true;
              micBtn.disabled = true;
            }
          }

          if (isLoggedIn()) {
            fetchConversations().then(function () {
              mergeLocalConversations();
              renderConversations();
            });
          } else {
            renderConversations();
          }
        })
        .catch(function (err) {
          var shouldFollow = isNearBottom();
          hideTyping();
          renderMessage({ role: "assistant", content: "Desculpe, não consegui processar o áudio. " + (err.message || "Tente novamente."), timestamp: new Date().toISOString() });
          scrollToBottomIfNear(true, shouldFollow);
        })
        .finally(function () {
          state.sending = false;
          updateSendBtn();
        });
    }

    sendBtn = document.createElement("button");
    sendBtn.type = "button";
    sendBtn.id = "chat-send-btn";
    sendBtn.disabled = true;
    sendBtn.className = "rounded-xl bg-accent p-3 text-white transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed shrink-0";
    sendBtn.setAttribute("aria-label", "Enviar mensagem");
    sendBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" x2="11" y1="2" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';

    inputRow.appendChild(actionWrap);
    inputRow.appendChild(textareaEl);
    inputRow.appendChild(micBtn);
    inputRow.appendChild(sendBtn);
    inputArea.appendChild(inputRow);
    mainEl.appendChild(inputArea);

    chatWrapper.appendChild(mainEl);
    container.appendChild(chatWrapper);
  }

  // ── Typing indicator ──
  function showTyping() {
    if (typingEl) return;
    var shouldFollow = isNearBottom();
    typingEl = document.createElement("div");
    typingEl.className = "flex items-end gap-3 justify-start";
    typingEl.innerHTML =
      '<div class="shrink-0">' +
        '<div class="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 overflow-hidden">' +
          '<img src="/logo2.png" alt="NOG" class="h-full w-full object-cover" />' +
        '</div>' +
      '</div>' +
      '<div class="rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3">' +
        '<div class="flex items-center gap-1.5">' +
          '<span class="h-2 w-2 rounded-full bg-muted" style="animation: typing-dot 1.4s infinite ease-in-out; animation-delay:0ms"></span>' +
          '<span class="h-2 w-2 rounded-full bg-muted" style="animation: typing-dot 1.4s infinite ease-in-out; animation-delay:200ms"></span>' +
          '<span class="h-2 w-2 rounded-full bg-muted" style="animation: typing-dot 1.4s infinite ease-in-out; animation-delay:400ms"></span>' +
        '</div>' +
      '</div>';
    messagesEl.appendChild(typingEl);
    scrollToBottomIfNear(true, shouldFollow);
  }

  function hideTyping() {
    if (typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  }

  // ── Message rendering ──
  function renderMessage(msg, prepend) {
    if (!msg) return;
    var isUser = msg.role === "user";

    // Wrapper: flex row with avatar + bubble
    var wrapper = document.createElement("div");
    wrapper.className = "flex items-end gap-3 " + (isUser ? "justify-end" : "justify-start");

    // Avatar
    var avatar = document.createElement("div");
    avatar.className = "shrink-0";
    if (isUser) {
      avatar.innerHTML =
        '<div class="flex h-8 w-8 items-center justify-center rounded-full bg-zinc-700">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-zinc-300"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>' +
        '</div>';
    } else {
      avatar.innerHTML =
        '<div class="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 overflow-hidden">' +
          '<img src="/logo2.png" alt="NOG" class="h-full w-full object-cover" />' +
        '</div>';
    }
    wrapper.appendChild(avatar);

    // Bubble container: controls max-width
    var bubbleWrap = document.createElement("div");
    bubbleWrap.className = isUser ? "flex flex-col items-end max-w-[75%]" : "flex flex-col items-start max-w-[80%]";

    // Bubble
    var bubble = document.createElement("div");
    bubble.className = isUser
      ? "rounded-2xl rounded-br-md bg-accent/10 px-4 py-3 text-sm text-primary leading-relaxed"
      : "rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3 text-sm text-primary leading-relaxed";

    // Content
    var contentHtml = nl2br(msg.content);
    contentHtml = contentHtml.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    contentHtml = contentHtml.replace(/\*(.+?)\*/g, "<em>$1</em>");
    bubble.innerHTML = contentHtml;

    bubbleWrap.appendChild(bubble);

    // Timestamp
    if (msg.timestamp) {
      var timeEl = document.createElement("div");
      timeEl.className = "mt-1 text-[10px] text-muted px-1 " + (isUser ? "text-right" : "text-left");
      timeEl.textContent = formatTime(msg.timestamp);
      bubbleWrap.appendChild(timeEl);
    }

    // Action buttons for AI messages
    if (!isUser && isLoggedIn() && msg.id) {
      var actionsRow = document.createElement("div");
      actionsRow.className = "flex items-center gap-1 mt-1 px-1";

      var thumbsUp = document.createElement("button");
      thumbsUp.type = "button";
      thumbsUp.className = "text-muted hover:text-green-400 transition-colors p-1 rounded";
      thumbsUp.title = "Util";
      thumbsUp.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z"/></svg>';
      thumbsUp.addEventListener("click", function () {
        sendChatFeedback(msg.id, 1);
        thumbsUp.classList.replace("text-muted", "text-green-400");
        thumbsDown.classList.replace("text-red-400", "text-muted");
      });

      var thumbsDown = document.createElement("button");
      thumbsDown.type = "button";
      thumbsDown.className = "text-muted hover:text-red-400 transition-colors p-1 rounded";
      thumbsDown.title = "Não util";
      thumbsDown.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z"/></svg>';
      thumbsDown.addEventListener("click", function () {
        sendChatFeedback(msg.id, -1);
        thumbsDown.classList.replace("text-muted", "text-red-400");
        thumbsUp.classList.replace("text-green-400", "text-muted");
      });

      var deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "text-muted hover:text-red-400 transition-colors p-1 rounded ml-auto";
      deleteBtn.title = "Excluir mensagem";
      deleteBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>';
      deleteBtn.addEventListener("click", function () {
        if (confirm("Excluir esta mensagem?")) {
          deleteChatMessage(msg.id, wrapper);
        }
      });

      actionsRow.appendChild(thumbsUp);
      actionsRow.appendChild(thumbsDown);
      actionsRow.appendChild(deleteBtn);
      bubbleWrap.appendChild(actionsRow);
    }

    // Delete button for user messages
    if (isUser && isLoggedIn() && msg.id) {
      var userActionsRow = document.createElement("div");
      userActionsRow.className = "flex justify-end mt-1 px-1";

      var userDeleteBtn = document.createElement("button");
      userDeleteBtn.type = "button";
      userDeleteBtn.className = "text-muted hover:text-red-400 transition-colors p-1 rounded";
      userDeleteBtn.title = "Excluir mensagem";
      userDeleteBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>';
      userDeleteBtn.addEventListener("click", function () {
        if (confirm("Excluir esta mensagem?")) {
          deleteChatMessage(msg.id, wrapper);
        }
      });

      userActionsRow.appendChild(userDeleteBtn);
      bubbleWrap.appendChild(userActionsRow);
    }

    // Videos section
    if (msg.videos && msg.videos.length > 0) {
      var videosSection = document.createElement("div");
      videosSection.className = "mt-2 w-full";
      videosSection.innerHTML = '<p class="text-xs font-medium text-muted mb-2">Vídeos relacionados</p>';

      var videosList = document.createElement("div");
      videosList.className = "flex flex-col gap-1.5";

      msg.videos.forEach(function (v) {
        var videoLink = document.createElement("a");
        videoLink.href = v.url || "#";
        videoLink.target = "_blank";
        videoLink.rel = "noopener noreferrer";
        videoLink.className = "group flex items-center gap-3 rounded-lg border border-border/60 bg-primary/30 px-3 py-2.5 text-left transition-all duration-150 hover:border-accent/30 hover:bg-accent/5";

        var playIcon = document.createElement("div");
        playIcon.className = "flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-red-500/15 text-red-400 transition-colors group-hover:bg-red-500/25";
        playIcon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>';

        var videoInfo = document.createElement("div");
        videoInfo.className = "flex-1 min-w-0";

        var titleText = v.title || extractDomain(v.url) || "Vídeo";
        videoInfo.innerHTML =
          '<p class="text-xs font-medium text-primary truncate">' + escapeHTML(titleText) + '</p>' +
          '<p class="text-[10px] text-muted truncate mt-0.5">' + escapeHTML(v.url || "") + '</p>';

        var externalIcon = document.createElement("div");
        externalIcon.className = "shrink-0 text-muted transition-colors group-hover:text-accent";
        externalIcon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" x2="21" y1="14" y2="3"></line></svg>';

        videoLink.appendChild(playIcon);
        videoLink.appendChild(videoInfo);
        videoLink.appendChild(externalIcon);
        videosList.appendChild(videoLink);
      });

      videosSection.appendChild(videosList);
      bubbleWrap.appendChild(videosSection);
    }

    // Links section
    if (msg.links && msg.links.length > 0) {
      var linksSection = document.createElement("div");
      linksSection.className = "mt-2 w-full";
      linksSection.innerHTML = '<p class="text-xs font-medium text-muted mb-2">Links úteis</p>';

      var linksList = document.createElement("div");
      linksList.className = "flex flex-col gap-1.5";

      msg.links.forEach(function (l) {
        var linkEl = document.createElement("a");
        linkEl.href = l.url || "#";
        linkEl.target = "_blank";
        linkEl.rel = "noopener noreferrer";
        linkEl.className = "group flex items-center gap-3 rounded-lg border border-border/60 bg-primary/30 px-3 py-2.5 text-left transition-all duration-150 hover:border-accent/30 hover:bg-accent/5";

        var linkIcon = document.createElement("div");
        linkIcon.className = "flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent transition-colors group-hover:bg-accent/20";
        linkIcon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>';

        var linkInfo = document.createElement("div");
        linkInfo.className = "flex-1 min-w-0";

        var friendlyName = l.title || l.name || friendlyDomainName(l.url) || "Link";
        var description = l.description || extractDomain(l.url) || "";
        linkInfo.innerHTML =
          '<p class="text-xs font-medium text-primary truncate">' + escapeHTML(friendlyName) + '</p>' +
          (description ? '<p class="text-[10px] text-muted truncate mt-0.5">' + escapeHTML(description) + '</p>' : '');

        var arrowIcon = document.createElement("div");
        arrowIcon.className = "shrink-0 text-muted transition-colors group-hover:text-accent";
        arrowIcon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" x2="21" y1="14" y2="3"></line></svg>';

        linkEl.appendChild(linkIcon);
        linkEl.appendChild(linkInfo);
        linkEl.appendChild(arrowIcon);
        linksList.appendChild(linkEl);
      });

      linksSection.appendChild(linksList);
      bubbleWrap.appendChild(linksSection);
    }

    wrapper.appendChild(bubbleWrap);

    if (prepend && messagesEl.firstChild) {
      messagesEl.insertBefore(wrapper, messagesEl.firstChild);
    } else {
      messagesEl.appendChild(wrapper);
    }

    return wrapper;
  }

  // ── Empty state ──
  function renderEmptyState() {
    if (!emptyStateEl) {
      emptyStateEl = document.createElement("div");
      emptyStateEl.id = "chat-empty-state";
      emptyStateEl.className = "flex flex-1 flex-col items-center justify-center text-center px-6 py-12";
      emptyStateEl.innerHTML =
        '<img src="/logo.png" alt="AutoAssist" class="mb-6 h-32 w-auto object-contain opacity-90" />' +
        '<h3 class="text-lg font-semibold text-primary mb-2">Fale com o NOG</h3>' +
        '<p class="text-sm text-muted max-w-md mb-8 leading-relaxed">Seu consultor automotivo com IA. Pergunte sobre manutenção, peças, diagnósticos ou qualquer dúvida sobre seu veículo.</p>' +
        '<div class="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-2xl">' +
          '<button type="button" class="chat-suggestion rounded-xl border border-border/60 bg-card/50 p-4 text-left transition-all duration-200 hover:border-accent/40 hover:bg-accent/5">' +
            '<p class="text-sm font-medium text-primary">Troca de óleo</p>' +
            '<p class="text-xs text-muted mt-1">Qual óleo usar e quando trocar?</p>' +
          '</button>' +
          '<button type="button" class="chat-suggestion rounded-xl border border-border/60 bg-card/50 p-4 text-left transition-all duration-200 hover:border-accent/40 hover:bg-accent/5">' +
            '<p class="text-sm font-medium text-primary">Diagnóstico</p>' +
            '<p class="text-xs text-muted mt-1">Meu carro faz um ruído estranho</p>' +
          '</button>' +
          '<button type="button" class="chat-suggestion rounded-xl border border-border/60 bg-card/50 p-4 text-left transition-all duration-200 hover:border-accent/40 hover:bg-accent/5">' +
            '<p class="text-sm font-medium text-primary">Custo estimado</p>' +
            '<p class="text-xs text-muted mt-1">Quanto custa uma revisão geral?</p>' +
          '</button>' +
          '<button type="button" class="chat-suggestion rounded-xl border border-border/60 bg-card/50 p-4 text-left transition-all duration-200 hover:border-accent/40 hover:bg-accent/5">' +
            '<p class="text-sm font-medium text-primary">Próxima manutenção</p>' +
            '<p class="text-xs text-muted mt-1">O que devo revisar em breve?</p>' +
          '</button>' +
        '</div>';
      messagesEl.appendChild(emptyStateEl);

      // Suggestion clicks
      var suggestions = emptyStateEl.querySelectorAll(".chat-suggestion");
      for (var i = 0; i < suggestions.length; i++) {
        (function (btn) {
          btn.addEventListener("click", function () {
            var text = btn.querySelector("p").textContent;
            if (textareaEl) {
              textareaEl.value = text;
              autoResize();
              updateSendBtn();
            }
            sendMessage(text);
          });
        })(suggestions[i]);
      }
    }
  }

  function hideEmptyState() {
    if (emptyStateEl && emptyStateEl.parentNode) {
      emptyStateEl.remove();
      emptyStateEl = null;
    }
  }

  // ── System message (avisos centralizados; faltava: cliques morriam em ReferenceError)
  function addSystemMessage(text) {
    if (!messagesEl) return;
    var wrap = document.createElement("div");
    wrap.className = "flex justify-center my-2";
    var bubble = document.createElement("div");
    bubble.className = "rounded-full border border-border bg-card px-4 py-1.5 text-xs text-muted";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    scrollToBottom(true);
  }

  // ── Download chat report: PDF do backend (logado) ou .txt local (visitante)
  function downloadChatReport() {
    var messages = state.messages || [];
    if (messages.length === 0) {
      addSystemMessage("Nenhuma mensagem para gerar laudo.");
      return;
    }

    var lines = [];
    lines.push("=== LAUDO DA CONVERSA - NOG AutoAssist ===");
    lines.push("Data: " + new Date().toLocaleString("pt-BR"));
    lines.push("Sessão: " + (state.activeSessionId || "Nova conversa"));
    lines.push("Veículo: " + (state.selectedVehicle || "Não informado"));
    lines.push("");
    lines.push("--- MENSAGENS ---");
    lines.push("");

    for (var i = 0; i < messages.length; i++) {
      var m = messages[i];
      var role = m.role === "user" ? "Você" : "NOG";
      var time = m.timestamp ? new Date(m.timestamp).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "";
      lines.push("[" + time + "] " + role + ":");
      lines.push(m.content || "");
      lines.push("");
    }

    lines.push("--- FIM DO LAUDO ---");
    var text = lines.join("\n");

    if (!isLoggedIn()) {
      downloadTxt(text);
      return;
    }
    addSystemMessage("Gerando PDF do laudo...");
    window.api
      .post("/api/report", { text: text })
      .then(function (data) {
        if (!data || !data.url) throw new Error("sem url");
        // Baixa via fetch autenticado (header JWT) em vez de <a href> direto,
        // que dependeria do cookie JWT — ausente em alguns fluxos de login.
        var token = null;
        try { token = localStorage.getItem("autoassist_access_token"); } catch (e) {}
        var headers = {};
        if (token) headers["Authorization"] = "Bearer " + token;
        return fetch(data.url, { headers: headers, credentials: "include" }).then(function (res) {
          if (!res.ok) throw new Error("falha no download");
          return res.blob();
        });
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "laudo-conversa-" + new Date().toISOString().slice(0, 10) + ".pdf";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
        addSystemMessage("Laudo em PDF gerado.");
      })
      .catch(function () {
        // Backend indisponível: fallback para .txt local
        downloadTxt(text);
        addSystemMessage("PDF indisponível — baixado em texto.");
      });
  }

  function downloadTxt(text) {
    var blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "laudo-conversa-" + new Date().toISOString().slice(0, 10) + ".txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    addSystemMessage("Laudo baixado com sucesso.");
  }

  // ── Conversations sidebar ──
  function renderConversations() {
    if (!conversationsList) return;
    conversationsList.innerHTML = "";

    // Merge local conversations into the list
    mergeLocalConversations();

    if (!state.conversations || state.conversations.length === 0) {
      var emptyMsg = document.createElement("div");
      emptyMsg.className = "px-4 py-8 text-center text-sm text-muted";
      emptyMsg.textContent = "Nenhuma conversa ainda";
      conversationsList.appendChild(emptyMsg);
      return;
    }

    state.conversations.forEach(function (conv) {
      var sessionId = conv.session_id || "";
      var title = conv.title || "Nova conversa";
      var preview = conv.preview || "";
      var count = conv.count || 0;
      var isActive = sessionId === state.activeSessionId;

      var item = document.createElement("div");
      item.className = "w-full px-4 py-3 border-b border-border/50 transition-colors cursor-pointer " +
        (isActive ? "bg-accent/10 border-l-2 border-l-accent" : "hover:bg-white/5");
      item.setAttribute("data-session-id", sessionId);
      item.setAttribute("data-conv-title", title);
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");

      item.innerHTML =
        '<div class="flex items-center gap-2">' +
          '<div class="flex-1 min-w-0" data-action="load">' +
            '<p class="text-sm font-medium text-primary truncate">' + escapeHTML(title) + '</p>' +
            '<p class="text-xs text-muted truncate mt-0.5">' + escapeHTML(preview) + '</p>' +
          '</div>' +
          '<div class="flex items-center gap-1 shrink-0">' +
            '<span class="text-[10px] text-muted bg-zinc-800 rounded-full px-1.5 py-0.5">' + count + '</span>' +
            '<button type="button" data-action="delete" class="relative z-10 flex items-center justify-center w-8 h-8 rounded-lg text-muted hover:text-red-400 hover:bg-red-400/10 transition-colors" aria-label="Excluir conversa">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path><line x1="10" x2="10" y1="11" y2="17"></line><line x1="14" x2="14" y1="11" y2="17"></line></svg>' +
            '</button>' +
          '</div>' +
        '</div>';

      conversationsList.appendChild(item);
    });
  }

  // Event delegation for conversations list
  function setupConversationsDelegation() {
    if (!conversationsList) return;
    conversationsList.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-action='delete']");
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        var card = btn.closest("[data-session-id]");
        if (card) {
          var sid = card.getAttribute("data-session-id");
          deleteSession(sid || null);
        }
        return;
      }

      var loadTarget = e.target.closest("[data-action='load']");
      if (!loadTarget) {
        // Check if clicked on the card itself
        var card = e.target.closest("[data-session-id]");
        if (card) loadTarget = card;
      }
      if (loadTarget) {
        var card = loadTarget.closest("[data-session-id]");
        if (card) {
          var sid = card.getAttribute("data-session-id");
          var title = card.getAttribute("data-conv-title") || "Nova conversa";
          state.activeSessionId = sid || null;
          fetchChatHistory(sid || null);
          updateSessionLabel(title);
          if (!isDesktop()) closeSidebar();
        }
      }
    });

    // Keyboard support for conversation items
    conversationsList.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        var card = e.target.closest("[data-session-id]");
        if (card) {
          e.preventDefault();
          card.click();
        }
      }
    });
  }

  function updateSessionLabel(title) {
    var label = document.getElementById("chat-session-label");
    if (label) {
      label.textContent = title || "Nova conversa";
    }
  }

  // ── Vehicle selector ──
  function populateVehicleOptions() {
    if (!vehicleSelect) return;
    while (vehicleSelect.options.length > 1) {
      vehicleSelect.remove(1);
    }
    state.vehicles.forEach(function (v) {
      var opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = vehicleLabel(v);
      vehicleSelect.appendChild(opt);
    });
  }

  // ── Textarea auto-resize ──
  function autoResize() {
    if (!textareaEl) return;
    textareaEl.style.height = "auto";
    var maxH = 128;
    textareaEl.style.height = Math.min(textareaEl.scrollHeight, maxH) + "px";
  }

  function updateSendBtn() {
    if (!sendBtn || !textareaEl) return;
    var hasText = textareaEl.value.trim().length > 0;
    sendBtn.disabled = !hasText || state.sending;
  }

  // ── Attachment handling ──
  var pendingAttachment = null;

  function handleFileSelect(e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;

    if (file.size > 8 * 1024 * 1024) {
      alert("Arquivo muito grande. Máximo 8 MB.");
      fileInput.value = "";
      return;
    }

    var reader = new FileReader();
    reader.onload = function (ev) {
      pendingAttachment = {
        name: file.name,
        type: file.type,
        size: file.size,
        data: ev.target.result,
      };
      showAttachmentPreview(file.name, file.size);
    };
    reader.readAsDataURL(file);
    fileInput.value = "";
  }

  function showAttachmentPreview(name, size) {
    var preview = document.getElementById("chat-attachment-preview");
    if (!preview) return;
    preview.className = "flex items-center gap-3 px-4 py-2 border-t border-border bg-primary/30 shrink-0";
    preview.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-accent shrink-0"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>' +
      '<span class="text-xs text-secondary truncate flex-1">' + escapeHTML(name) + ' (' + formatFileSize(size) + ')</span>' +
      '<button type="button" id="chat-remove-attachment" class="text-muted hover:text-red-400 transition-colors">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" x2="6" y1="6" y2="18"></line><line x1="6" x2="18" y1="6" y2="18"></line></svg>' +
      '</button>';

    document.getElementById("chat-remove-attachment").addEventListener("click", function () {
      pendingAttachment = null;
      preview.className = "hidden px-4 py-2 border-t border-border bg-primary/30 shrink-0";
      preview.innerHTML = "";
    });
  }

  // ── Send message ──
  function sendMessage(text) {
    if (state.sending) return;
    var message = (text || "").trim();
    if (!message && !pendingAttachment) return;

    // Ensure there is always a session_id
    if (!state.activeSessionId) {
      state.activeSessionId = generateSessionId();
    }

    state.sending = true;
    updateSendBtn();
    hideEmptyState();

    // Render user message immediately
    var userMsg = {
      role: "user",
      content: message || (pendingAttachment ? "Arquivo: " + pendingAttachment.name : ""),
      timestamp: new Date().toISOString(),
    };
    renderMessage(userMsg);
    scrollToBottom(true);

    // Track message locally
    var sid = state.activeSessionId;
    if (!state.localMessages[sid]) state.localMessages[sid] = [];
    state.localMessages[sid].push(userMsg);
    persistGuestCache();

    // Update local conversation meta
    if (!state.localConversationMeta[sid]) {
      state.localConversationMeta[sid] = {
        session_id: sid,
        title: message.slice(0, 80) || "Nova conversa",
        preview: message.slice(0, 140) || "",
        count: 0,
        updated_at: userMsg.timestamp,
      };
    } else {
      state.localConversationMeta[sid].title = message.slice(0, 80) || state.localConversationMeta[sid].title;
      state.localConversationMeta[sid].preview = message.slice(0, 140);
      state.localConversationMeta[sid].updated_at = userMsg.timestamp;
    }
    state.localConversationMeta[sid].count = state.localMessages[sid].length;

    renderConversations();

    // Build payload
    var payload = { message: message, session_id: state.activeSessionId };
    var vehicleVal = vehicleSelect ? vehicleSelect.value : "";
    if (vehicleVal) {
      payload.vehicle_id = parseInt(vehicleVal, 10);
    }
    if (pendingAttachment) {
      payload.attachment = {
        name: pendingAttachment.name,
        type: pendingAttachment.type,
        data: pendingAttachment.data,
      };
    }

    // Clear input
    textareaEl.value = "";
    autoResize();
    updateSendBtn();
    pendingAttachment = null;
    var previewEl = document.getElementById("chat-attachment-preview");
    if (previewEl) {
      previewEl.className = "hidden px-4 py-2 border-t border-border bg-primary/30 shrink-0";
      previewEl.innerHTML = "";
    }

    showTyping();

    // Send via fetch to support streaming if available
    var token = localStorage.getItem("autoassist_access_token");
    var headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = "Bearer " + token;

    var fetchOpts = {
      method: "POST",
      headers: headers,
      credentials: "include",
      body: JSON.stringify(payload),
    };

    if (!isLoggedIn()) {
      payload.guest_id = getGuestId();
      fetchOpts.headers["X-AutoAssist-Guest-Id"] = payload.guest_id;
    }

    fetch(CHAT_ENDPOINT, fetchOpts)
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (body) {
            throw new Error(body.error || "Erro ao enviar mensagem");
          });
        }
        // Check if response is SSE stream
        var ct = res.headers.get("content-type") || "";
        if (ct.indexOf("text/event-stream") !== -1) {
          var shouldFollowStream = isNearBottom();
          hideTyping();
          return handleStreamingResponse(res, shouldFollowStream);
        }
        return res.json();
      })
      .then(function (data) {
        var shouldFollow = isNearBottom();
        if (!data || data.streamed) return;
        hideTyping();

        // data.response is the AI text; data.chat has the full record
        var aiMsg = {
          role: "assistant",
          content: data.response || data.text || "",
          timestamp: (data.chat && data.chat.created_at) || new Date().toISOString(),
          videos: data.videos || [],
          links: data.links || [],
        };
        renderMessage(aiMsg);
        scrollToBottomIfNear(true, shouldFollow);

        // Track assistant message locally
        var sid = state.activeSessionId;
        if (sid) {
          if (!state.localMessages[sid]) state.localMessages[sid] = [];
          state.localMessages[sid].push(aiMsg);
          persistGuestCache();
            persistGuestCache();
          if (state.localConversationMeta[sid]) {
            state.localConversationMeta[sid].count = state.localMessages[sid].length;
            state.localConversationMeta[sid].updated_at = aiMsg.timestamp;
          }
        }

        // Update session
        if (data.chat) {
          state.latestId = data.chat.id || state.latestId;
        }

        // Guest remaining messages
        if (data.guest_messages_remaining !== undefined) {
          var remaining = data.guest_messages_remaining;
          var limit = data.guest_limit || 5;
          if (remaining <= 2 && remaining > 0) {
            renderMessage({ role: "assistant", content: "Você tem " + remaining + " mensagem" + (remaining > 1 ? "s" : "") + " restante" + (remaining > 1 ? "s" : "") + ". Crie uma conta para continuar.", timestamp: new Date().toISOString() });
            scrollToBottomIfNear(true, shouldFollow);
          } else if (remaining === 0) {
            renderMessage({ role: "assistant", content: "Você atingiu o limite de " + limit + " mensagens gratuitas. Crie uma conta ou faça login para continuar.", timestamp: new Date().toISOString() });
            scrollToBottomIfNear(true, shouldFollow);
            textareaEl.disabled = true;
            sendBtn.disabled = true;
          }
        }

        // Refresh conversations in background (merge with local)
        if (isLoggedIn()) {
          fetchConversations().then(function () {
            mergeLocalConversations();
            renderConversations();
          });
        } else {
          renderConversations();
        }
      })
      .catch(function (err) {
        var shouldFollow = isNearBottom();
        hideTyping();
        console.error("[chat] send error:", err);
        var errMsg = {
          role: "assistant",
          content: "Desculpe, ocorreu um erro ao processar sua mensagem. Tente novamente.",
          timestamp: new Date().toISOString(),
        };
        renderMessage(errMsg);
        scrollToBottomIfNear(true, shouldFollow);
      })
      .finally(function () {
        state.sending = false;
        updateSendBtn();
      });
  }

  // ── Streaming response handler ──
  function handleStreamingResponse(res, shouldFollow) {
    return new Promise(function (resolve) {
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var aiContent = "";

      // Create a streaming message element
      var streamingMsg = {
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        videos: [],
        links: [],
      };
      var msgEl = renderMessage(streamingMsg);

      function read() {
        reader.read().then(function (result) {
          if (result.done) {
            resolve({ streamed: true, response: aiContent, chat: streamingMsg });
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          var lines = buffer.split("\n");
          buffer = lines.pop() || "";

          lines.forEach(function (line) {
            if (line.indexOf("data: ") !== 0) return;
            var jsonStr = line.slice(6).trim();
            if (!jsonStr || jsonStr === "[DONE]") return;

            try {
              var chunk = JSON.parse(jsonStr);
              if (chunk.text) {
                aiContent += chunk.text;
                // Update streaming bubble
                if (msgEl) {
                  var bubble = msgEl.querySelector("div:last-child");
                  if (bubble) {
                    var contentHtml = nl2br(aiContent);
                    contentHtml = contentHtml.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
                    contentHtml = contentHtml.replace(/\*(.+?)\*/g, "<em>$1</em>");
                    // Preserve timestamp element
                    var timeEl = bubble.querySelector("div:last-child");
                    bubble.innerHTML = contentHtml;
                    if (timeEl) bubble.appendChild(timeEl);
                  }
                }
                scrollToBottomIfNear(true, shouldFollow);
              }
              if (chunk.videos) streamingMsg.videos = chunk.videos;
              if (chunk.links) streamingMsg.links = chunk.links;
              if (chunk.chat) {
                streamingMsg.timestamp = chunk.chat.created_at || streamingMsg.timestamp;
              }
            } catch (_) {}
          });

          read();
        }).catch(function () {
          resolve({ streamed: true, response: aiContent, chat: streamingMsg });
        });
      }

      read();
    });
  }

  // ── Fetch data ──
  function fetchConversations() {
    return window.api
      .get(CONVERSATIONS_ENDPOINT)
      .then(function (data) {
        state.conversations = data.conversations || [];
      })
      .catch(function (err) {
        console.error("[chat] fetch conversations error:", err);
      });
  }

  function mergeLocalConversations() {
    var existing = {};
    state.conversations.forEach(function (c) {
      existing[c.session_id] = true;
    });
    Object.keys(state.localConversationMeta).forEach(function (sid) {
      if (!existing[sid]) {
        state.conversations.unshift(state.localConversationMeta[sid]);
      } else {
        // Update count from local if backend hasn't caught up yet
        state.conversations.forEach(function (c) {
          if (c.session_id === sid && state.localConversationMeta[sid]) {
            c.count = Math.max(c.count || 0, state.localConversationMeta[sid].count || 0);
          }
        });
      }
    });
  }

  function fetchChatHistory(sessionId) {
    messagesEl.innerHTML = "";
    emptyStateEl = null;
    state.messages = [];

    // Check if we have local messages for this session
    var hasLocal = sessionId && state.localMessages[sessionId] && state.localMessages[sessionId].length > 0;

    if (hasLocal) {
      // Render local messages immediately
      state.messages = state.localMessages[sessionId].slice();
      state.messages.forEach(function (msg) {
        renderMessage(msg);
      });
      scrollToBottom(false);
      return;
    }

    // Fetch from backend
    showTyping();

    var params = [];
    if (sessionId) {
      params.push("session_id=" + encodeURIComponent(sessionId));
    }
    params.push("limit=100");

    var url = HISTORY_ENDPOINT + "?" + params.join("&");

    window.api
      .get(url)
      .then(function (data) {
        hideTyping();
        var chats = data.chats || [];
        state.messages = [];
        state.latestId = data.latest_id || 0;

        if (chats.length === 0) {
          renderEmptyState();
          return;
        }

        chats.forEach(function (chat) {
          if (chat.mensagem_usuario) {
            state.messages.push({
              role: "user",
              content: chat.mensagem_usuario,
              timestamp: chat.created_at,
            });
          }
          if (chat.resposta_ia) {
            state.messages.push({
              role: "assistant",
              content: chat.resposta_ia,
              timestamp: chat.created_at,
              videos: chat.videos || [],
              links: chat.links || [],
            });
          }
        });

        // Merge with local messages (avoid duplicates by timestamp+role)
        if (sessionId && state.localMessages[sessionId]) {
          var localMsgs = state.localMessages[sessionId];
          localMsgs.forEach(function (lm) {
            var isDupe = state.messages.some(function (m) {
              return m.role === lm.role && m.content === lm.content && m.timestamp === lm.timestamp;
            });
            if (!isDupe) {
              state.messages.push(lm);
            }
          });
          // Sort by timestamp
          state.messages.sort(function (a, b) {
            return new Date(a.timestamp) - new Date(b.timestamp);
          });
        }

        state.messages.forEach(function (msg) {
          renderMessage(msg);
        });

        scrollToBottom(false);
      })
      .catch(function (err) {
        hideTyping();
        console.error("[chat] fetch history error:", err);
        renderEmptyState();
      });
  }

  function fetchVehicles() {
    return window.api
      .get(VEICULOS_ENDPOINT)
      .then(function (data) {
        state.vehicles = data.veiculos || [];
        populateVehicleOptions();
      })
      .catch(function (err) {
        console.error("[chat] fetch vehicles error:", err);
      });
  }

  function deleteSession(sessionId) {
    if (!confirm("Excluir toda esta conversa?")) return;

    // Clean up local state
    delete state.localMessages[sessionId];
    delete state.localConversationMeta[sessionId];

    var endpoint = sessionId ? "/api/chat/session/" + sessionId : "/api/chat/session/null";
    window.api
      .delete(endpoint)
      .then(function () {
        if (state.activeSessionId === sessionId) {
          state.activeSessionId = null;
          state.messages = [];
          messagesEl.innerHTML = "";
          emptyStateEl = null;
          renderEmptyState();
          updateSessionLabel("Nova conversa");
        }
        if (isLoggedIn()) {
          fetchConversations().then(function () {
            mergeLocalConversations();
            renderConversations();
          });
        } else {
          renderConversations();
        }
      })
      .catch(function (err) {
        console.error("[chat] delete session error:", err);
        alert("Erro ao excluir conversa");
      });
  }

  // ── Event listeners ──
  function bindEvents() {
    // Event delegation for conversations list (delete + load)
    setupConversationsDelegation();

    // Textarea auto-resize + Enter to send
    textareaEl.addEventListener("input", function () {
      autoResize();
      updateSendBtn();
    });

    textareaEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(textareaEl.value);
      }
    });

    // Send button
    sendBtn.addEventListener("click", function () {
      sendMessage(textareaEl.value);
    });

    // File input
    fileInput.addEventListener("change", handleFileSelect);

    // New conversation button
    var newBtn = document.getElementById("chat-new-btn");
    if (newBtn) {
      newBtn.addEventListener("click", function () {
        var newSid = generateSessionId();
        state.activeSessionId = newSid;
        state.localMessages[newSid] = [];
        state.localConversationMeta[newSid] = {
          session_id: newSid,
          title: "Nova conversa",
          preview: "",
          count: 0,
          updated_at: new Date().toISOString(),
        };
        messagesEl.innerHTML = "";
        emptyStateEl = null;
        renderEmptyState();
        updateSessionLabel("Nova conversa");
        renderConversations();
      });
    }

    // Search conversations
    var searchInput = document.getElementById("chat-search-input");
    if (searchInput) {
      var debounceTimer = null;
      searchInput.addEventListener("input", function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          var query = searchInput.value.trim().toLowerCase();
          if (!query) {
            renderConversations();
            return;
          }
          // Merge local before searching
          mergeLocalConversations();
          // Filter locally
          var filtered = state.conversations.filter(function (c) {
            return (c.title || "").toLowerCase().indexOf(query) !== -1 ||
                   (c.preview || "").toLowerCase().indexOf(query) !== -1;
          });
          if (filtered.length === 0) {
            conversationsList.innerHTML = '<div class="px-4 py-8 text-center text-sm text-muted">Nenhum resultado</div>';
          } else {
            conversationsList.innerHTML = "";
            filtered.forEach(function (conv) {
              var item = document.createElement("div");
              item.type = "button";
              item.className = "w-full text-left px-4 py-3 border-b border-border/50 transition-colors hover:bg-white/5 cursor-pointer";
              item.setAttribute("data-session-id", conv.session_id || "");
              item.setAttribute("role", "button");
              item.setAttribute("tabindex", "0");
              item.innerHTML =
                '<p class="text-sm font-medium text-primary truncate">' + escapeHTML(conv.title || "Nova conversa") + '</p>' +
                '<p class="text-xs text-muted truncate mt-0.5">' + escapeHTML(conv.preview || "") + '</p>';
              item.addEventListener("click", function () {
                state.activeSessionId = conv.session_id || null;
                fetchChatHistory(conv.session_id);
                updateSessionLabel(conv.title);
                if (!isDesktop()) closeSidebar();
              });
              conversationsList.appendChild(item);
            });
          }
        }, 200);
      });
    }
  }

  // ── Guest ID ──
  function getGuestId() {
    var gid = localStorage.getItem("autoassist_guest_id");
    if (gid) return gid;
    gid = "g_" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    localStorage.setItem("autoassist_guest_id", gid);
    return gid;
  }

  function isLoggedIn() {
    return !!(auth && auth.isAuthenticated && auth.isAuthenticated());
  }

  // ── Guest cache (sincroniza conversa de visitante após o login) ──
  var GUEST_CACHE_KEY = "autoassist_guest_cache";

  function persistGuestCache() {
    if (isLoggedIn()) return;
    try {
      localStorage.setItem(GUEST_CACHE_KEY, JSON.stringify({
        messages: state.localMessages || {},
        meta: state.localConversationMeta || {},
      }));
    } catch (e) { /* storage cheio/indisponível: ignora */ }
  }

  function loadGuestCache() {
    var raw = null;
    try { raw = localStorage.getItem(GUEST_CACHE_KEY); } catch (e) { return false; }
    if (!raw) return false;
    try {
      var cache = JSON.parse(raw);
      state.localMessages = cache.messages || {};
      state.localConversationMeta = cache.meta || {};
      return Object.keys(state.localMessages).length > 0;
    } catch (e) { return false; }
  }

  function clearGuestCache() {
    try { localStorage.removeItem(GUEST_CACHE_KEY); } catch (e) {}
    state.localMessages = {};
    state.localConversationMeta = {};
  }

  function syncGuestCache() {
    if (!isLoggedIn()) return;
    var chats = [];
    Object.keys(state.localMessages || {}).forEach(function (sid) {
      (state.localMessages[sid] || []).forEach(function (m) {
        if (!m || !m.content) return;
        chats.push({
          session_id: sid,
          mensagem_usuario: m.role === "user" ? m.content : "",
          resposta_ia: m.role === "assistant" ? m.content : "",
          created_at: m.timestamp || new Date().toISOString(),
        });
      });
    });
    if (!chats.length) { clearGuestCache(); return; }
    window.api
      .post("/api/chat/sync_guest", { chats: chats })
      .then(function () { clearGuestCache(); })
      .catch(function () { /* tenta de novo no próximo carregamento */ });
  }

  // ── Init ──
  document.addEventListener("DOMContentLoaded", function () {
    buildUI();
    bindEvents();
    renderEmptyState();

    loadGuestCache();
    if (isLoggedIn()) syncGuestCache();

    fetchVehicles().then(function () {
      if (isLoggedIn()) {
        return fetchConversations().then(function () {
          mergeLocalConversations();
          renderConversations();
        });
      }
    }).then(function () {
      if (!state.activeSessionId) {
        renderEmptyState();
      }
    });
  });
})();
