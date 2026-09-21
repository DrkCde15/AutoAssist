/**
 * eventos.js — Eventos Automotivos page logic
 * Fetches events from GET /api/events/automotive, renders cards,
 * handles UF filter and "Atualizar" button.
 */
(function () {
  "use strict";

  var ENDPOINT = "/api/events/automotive";

  var CATEGORY_COLORS = {
    feira: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    encontro: "bg-green-500/15 text-green-400 border-green-500/30",
    competicao: "bg-red-500/15 text-red-400 border-red-500/30",
    exposicao: "bg-purple-500/15 text-purple-400 border-purple-500/30",
    congresso: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  };

  var UF_OPTIONS = [
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO",
  ];

  document.addEventListener("DOMContentLoaded", function () {
    if (!auth.requireAuth()) return;
    if (window.premiumModal && !window.premiumModal.requirePremium()) return;
    if (!document.getElementById("eventos-responsive-css")) {
      var eventosCss = document.createElement("style");
      eventosCss.id = "eventos-responsive-css";
      eventosCss.textContent =
        /* hover states */
        ".hover\\:border-zinc-600:hover { border-color: #3f3f46; }" +
        ".hover\\:shadow-lg { box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1); }" +
        ".hover\\:shadow-black\\/20:hover { --tw-shadow: 0 10px 15px -3px rgba(0,0,0,0.2), 0 4px 6px -4px rgba(0,0,0,0.2); box-shadow: var(--tw-shadow); }" +
        ".group:hover .group-hover\\:scale-105 { transform: scale(1.05); }" +
        ".group:hover .group-hover\\:text-accent { color: var(--color-accent); }" +
        ".hover\\:bg-accent-hover:hover { background-color: var(--color-accent-hover); }" +
        ".hover\\:bg-white\\/5:hover { background-color: rgba(255,255,255,0.05); }" +
        ".hover\\:bg-secondary:hover { background-color: var(--color-bg-secondary); }" +
        ".hover\\:text-primary:hover { color: var(--color-text-primary); }" +
        ".hover\\:border-border-hover:hover { border-color: var(--color-border-hover); }" +
        /* disabled states */
        ".disabled\\:opacity-50:disabled { opacity: 0.5; }" +
        ".disabled\\:cursor-not-allowed:disabled { cursor: not-allowed; }" +
        /* gradients */
        ".bg-zinc-800 { background-color: #27272a; }" +
        ".from-zinc-800 { --tw-gradient-from: #27272a; --tw-gradient-stops: var(--tw-gradient-from), var(--tw-gradient-to, rgba(39,39,42,0)); }" +
        ".to-zinc-900 { --tw-gradient-to: #18181b; }" +
        ".bg-gradient-to-br { background-image: linear-gradient(to bottom right, var(--tw-gradient-from), var(--tw-gradient-to)); }" +
        /* transitions */
        ".transition-all { transition-property: all; transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1); transition-duration: 200ms; }" +
        ".transition-transform { transition-property: transform; transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1); transition-duration: 300ms; }" +
        ".duration-200 { transition-duration: 200ms; }" +
        ".duration-300 { transition-duration: 300ms; }" +
        /* semantic colors — missing from compiled CSS */
        ".bg-primary { background-color: var(--color-bg-primary); }" +
        ".bg-card { background-color: var(--color-bg-card); }" +
        ".bg-secondary { background-color: var(--color-bg-secondary); }" +
        ".text-primary { color: var(--color-text-primary); }" +
        ".text-secondary { color: var(--color-text-secondary); }" +
        ".text-muted { color: var(--color-text-muted); }" +
        ".text-accent { color: var(--color-accent); }" +
        /* dropdown max-height */
        ".max-h-64 { max-height: 16rem; }" +
        /* spacing used by cards */
        ".mb-8 { margin-bottom: 2rem; }" +
        ".py-20 { padding-top: 5rem; padding-bottom: 5rem; }" +
        ".py-16 { padding-top: 4rem; padding-bottom: 4rem; }";
      document.head.appendChild(eventosCss);
    }

    var section = document.querySelector("main section");
    if (!section) return;

    var wrap = section.querySelector(".section__wrap");
    if (!wrap) return;

    var header = wrap.querySelector(".section__header");
    var filterBar = header ? header.nextElementSibling : null;

    if (!filterBar) {
      var allDivs = wrap.querySelectorAll(":scope > div");
      filterBar = allDivs.length > 0 ? allDivs[0] : null;
    }

    var countEl = null;
    var ufDropdownBtn = null;
    var refreshBtn = null;

    if (filterBar) {
      countEl = filterBar.querySelector("p");
      var btnGroup = filterBar.querySelector(".flex.items-center.gap-3");
      if (btnGroup) {
        ufDropdownBtn = btnGroup.querySelector('[role="combobox"]');
        refreshBtn = btnGroup.querySelector("button:last-child");
      }
    }

    if (!ufDropdownBtn) {
      ufDropdownBtn = section.querySelector('[role="combobox"]');
    }
    if (!refreshBtn) {
      var allBtns = section.querySelectorAll("button");
      for (var i = 0; i < allBtns.length; i++) {
        if (allBtns[i].textContent.indexOf("Atualizar") !== -1) {
          refreshBtn = allBtns[i];
          break;
        }
      }
    }

    var grid = document.createElement("div");
    grid.className = "grid gap-5 sm:grid-cols-2 lg:grid-cols-3";
    wrap.appendChild(grid);

    var selectedUF = "";
    var loading = false;
    var initialLoad = true;
    var events = [];
    var errorMessage = null;

    // ── UF Dropdown ──
    var dropdownWrap = ufDropdownBtn
      ? ufDropdownBtn.closest(".relative") || ufDropdownBtn.parentElement
      : null;
    var dropdownPanel = null;
    var dropdownOpen = false;

    function buildDropdown() {
      if (!dropdownWrap) return;
      dropdownWrap.style.position = "relative";

      dropdownPanel = document.createElement("div");
      dropdownPanel.className =
        "absolute left-0 top-full z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-border bg-primary shadow-xl";
      dropdownPanel.style.display = "none";
      dropdownPanel.setAttribute("role", "listbox");
      dropdownPanel.setAttribute("aria-label", "Filtrar por UF");

      var allOpt = document.createElement("div");
      allOpt.className =
        "cursor-pointer px-3 py-2 text-sm transition-colors hover:bg-white/5 " +
        (selectedUF === "" ? "text-accent font-medium" : "text-secondary");
      allOpt.textContent = "Todas as UFs";
      allOpt.setAttribute("role", "option");
      allOpt.addEventListener("click", function () {
        selectUF("");
      });
      dropdownPanel.appendChild(allOpt);

      UF_OPTIONS.forEach(function (uf) {
        var opt = document.createElement("div");
        opt.className =
          "cursor-pointer px-3 py-2 text-sm transition-colors hover:bg-white/5 " +
          (selectedUF === uf ? "text-accent font-medium" : "text-secondary");
        opt.textContent = uf;
        opt.setAttribute("role", "option");
        opt.setAttribute("data-uf", uf);
        opt.addEventListener("click", function () {
          selectUF(uf);
        });
        dropdownPanel.appendChild(opt);
      });

      dropdownWrap.appendChild(dropdownPanel);
    }

    function selectUF(uf) {
      selectedUF = uf;
      var label = ufDropdownBtn.querySelector("span");
      if (label) {
        label.textContent = uf || "Todas as UFs";
        label.classList.toggle("text-muted", !uf);
        label.classList.toggle("text-primary", !!uf);
      }
      closeDropdown();
      fetchEvents();
    }

    function openDropdown() {
      if (!dropdownPanel) return;
      dropdownPanel.style.display = "block";
      dropdownOpen = true;
      ufDropdownBtn.setAttribute("aria-expanded", "true");
      var chevron = ufDropdownBtn.querySelector("svg");
      if (chevron) chevron.style.transform = "rotate(180deg)";
      highlightCurrentOption();
    }

    function closeDropdown() {
      if (!dropdownPanel) return;
      dropdownPanel.style.display = "none";
      dropdownOpen = false;
      ufDropdownBtn.setAttribute("aria-expanded", "false");
      var chevron = ufDropdownBtn.querySelector("svg");
      if (chevron) chevron.style.transform = "";
    }

    function highlightCurrentOption() {
      if (!dropdownPanel) return;
      var opts = dropdownPanel.querySelectorAll("[role='option']");
      opts.forEach(function (opt) {
        var isAll = !opt.getAttribute("data-uf") && selectedUF === "";
        var isMatch = opt.getAttribute("data-uf") === selectedUF;
        opt.className =
          "cursor-pointer px-3 py-2 text-sm transition-colors hover:bg-white/5 " +
          (isAll || isMatch ? "text-accent font-medium" : "text-secondary");
      });
    }

    if (ufDropdownBtn) {
      ufDropdownBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (dropdownOpen) {
          closeDropdown();
        } else {
          openDropdown();
        }
      });
    }

    document.addEventListener("click", function (e) {
      if (dropdownOpen && dropdownPanel && !dropdownPanel.contains(e.target) && ufDropdownBtn && !ufDropdownBtn.contains(e.target)) {
        closeDropdown();
      }
    });

    // ── Refresh button ──
    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        if (!loading) fetchEvents(true);
      });
    }

    // ── Helpers ──
    function setLoadingState(isLoading) {
      loading = isLoading;
      if (refreshBtn) {
        refreshBtn.disabled = isLoading;
        refreshBtn.classList.toggle("disabled:opacity-50", isLoading);
        refreshBtn.classList.toggle("disabled:cursor-not-allowed", isLoading);
        var svg = refreshBtn.querySelector("svg");
        if (svg) {
          svg.classList.toggle("animate-spin", isLoading);
        }
      }
    }

    function setCount(n) {
      if (!countEl) return;
      countEl.textContent = n + " evento" + (n !== 1 ? "s" : "") + " encontrado" + (n !== 1 ? "s" : "");
    }

    function renderEmpty() {
      grid.innerHTML = "";
      var msg = document.createElement("div");
      msg.className = "col-span-full flex flex-col items-center justify-center py-16 text-center";
      msg.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="mb-4 text-zinc-600"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line></svg>' +
        '<p class="text-lg font-medium text-secondary">Nenhum evento encontrado</p>' +
        '<p class="mt-1 text-sm text-muted">Tente filtrar por outro estado ou clique em Atualizar.</p>';
      grid.appendChild(msg);
    }

    function showEventModal(ev) {
      var existing = document.getElementById("eventos-modal");
      if (existing) existing.remove();

      var cat = (ev.categoria || ev.categoria_label || "").toLowerCase();
      var catClass = CATEGORY_COLORS[cat] || "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
      var catLabel = ev.categoria_label || ev.categoria || "Evento";

      var dateStr = ev.data_inicio || "";
      if (ev.data_fim && ev.data_fim !== ev.data_inicio) {
        dateStr += " — " + ev.data_fim;
      }

      var location = "";
      if (ev.cidade) location = ev.cidade;
      if (ev.uf) location += location ? " · " + ev.uf : ev.uf;

      var imgHTML = "";
      if (ev.image_url) {
        imgHTML =
          '<img src="' + escapeAttr(ev.image_url) + '" alt="' + escapeAttr(ev.titulo || "") + '" style="width:100%;max-height:240px;object-fit:cover;border-radius:0.75rem 0.75rem 0 0;" loading="lazy" />';
      }

      var html =
        '<div id="eventos-modal" style="position:fixed;inset:0;z-index:1400;display:flex;align-items:center;justify-content:center;padding:1rem;">' +
          '<div data-ev-close style="position:absolute;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);"></div>' +
          '<div style="position:relative;z-index:1;width:100%;max-width:32rem;max-height:90vh;overflow-y:auto;border-radius:1rem;background:#111119;border:1px solid rgba(255,255,255,0.08);box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);">' +
            imgHTML +
            '<div style="padding:1.5rem;">' +
              '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem;flex-wrap:wrap;">' +
                '<span class="inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-medium ' + catClass + '">' + escapeHTML(catLabel) + '</span>' +
                (ev.fonte ? '<span style="margin-left:auto;font-size:0.75rem;color:#a1a1aa;">' + escapeHTML(ev.fonte) + '</span>' : '') +
              '</div>' +
              '<h2 style="font-size:1.25rem;font-weight:600;color:#f4f4f5;line-height:1.4;margin-bottom:1rem;">' + escapeHTML(ev.titulo || "Evento automotivo") + '</h2>' +
              (dateStr
                ? '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;font-size:0.875rem;color:#a1a1aa;">' +
                  '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;color:#71717a;"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line></svg>' +
                  escapeHTML(dateStr) +
                  '</div>'
                : '') +
              (location
                ? '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;font-size:0.875rem;color:#a1a1aa;">' +
                  '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;color:#71717a;"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"></path><circle cx="12" cy="10" r="3"></circle></svg>' +
                  escapeHTML(location) +
                  '</div>'
                : '') +
              (ev.descricao
                ? '<p style="font-size:0.875rem;color:#a1a1aa;line-height:1.6;margin-bottom:1.25rem;white-space:pre-wrap;">' + escapeHTML(ev.descricao) + '</p>'
                : '') +
              '<div style="display:flex;gap:0.75rem;flex-wrap:wrap;">' +
                (ev.event_url || ev.url
                  ? '<a href="' + escapeAttr(ev.event_url || ev.url) + '" target="_blank" rel="noopener noreferrer" style="display:inline-flex;align-items:center;gap:0.5rem;border-radius:9999px;background:var(--color-accent,#6366f1);padding:0.625rem 1.25rem;font-size:0.875rem;font-weight:600;color:#fff;text-decoration:none;transition:background 0.15s;">' +
                    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" x2="21" y1="14" y2="3"></line></svg>' +
                    'Abrir site do evento</a>'
                  : '') +
                '<button data-ev-close style="display:inline-flex;align-items:center;gap:0.5rem;border-radius:9999px;border:1px solid rgba(255,255,255,0.1);background:transparent;padding:0.625rem 1.25rem;font-size:0.875rem;font-weight:500;color:#a1a1aa;cursor:pointer;transition:background 0.15s;">Fechar</button>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>';

      document.body.insertAdjacentHTML("beforeend", html);

      var modal = document.getElementById("eventos-modal");
      modal.querySelectorAll("[data-ev-close]").forEach(function (el) {
        el.addEventListener("click", function () { modal.remove(); });
      });
      modal.addEventListener("click", function (e) {
        if (e.target === modal || e.target.getAttribute("data-ev-close") !== null) return;
        if (e.target === modal.firstElementChild) modal.remove();
      });
      document.addEventListener("keydown", function handler(e) {
        if (e.key === "Escape") {
          var m = document.getElementById("eventos-modal");
          if (m) m.remove();
          document.removeEventListener("keydown", handler);
        }
      });
    }

    function renderEvents(eventList) {
      grid.innerHTML = "";
      if (!eventList || eventList.length === 0) {
        renderEmpty();
        return;
      }

      eventList.forEach(function (ev) {
        var card = document.createElement("button");
        card.type = "button";
        card.className =
          "group flex flex-col overflow-hidden rounded-2xl border border-border bg-card transition-all duration-200 hover:border-zinc-600 hover:shadow-lg hover:shadow-black/20 text-left";
        card.addEventListener("click", function () { showEventModal(ev); });

        var cat = (ev.categoria || ev.categoria_label || "").toLowerCase();
        var catClass = CATEGORY_COLORS[cat] || "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
        var catLabel = ev.categoria_label || ev.categoria || "Evento";

        var dateStr = ev.data_inicio || "";
        if (ev.data_fim && ev.data_fim !== ev.data_inicio) {
          dateStr += " — " + ev.data_fim;
        }

        var location = "";
        if (ev.cidade) location = ev.cidade;
        if (ev.uf) location += location ? " · " + ev.uf : ev.uf;

        var imgHTML = "";
        if (ev.image_url) {
          imgHTML =
            '<div class="relative h-44 w-full overflow-hidden bg-zinc-800">' +
            '<img src="' + escapeAttr(ev.image_url) + '" alt="' + escapeAttr(ev.titulo || "") + '" class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" loading="lazy" />' +
            '</div>';
        } else {
          imgHTML =
            '<div class="flex h-44 w-full items-center justify-center bg-gradient-to-br from-zinc-800 to-zinc-900">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="text-zinc-600"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line></svg>' +
            '</div>';
        }

        card.innerHTML =
          imgHTML +
          '<div class="flex flex-1 flex-col gap-2 p-4">' +
            '<div class="flex items-center gap-2">' +
              '<span class="inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-medium ' + catClass + '">' + escapeHTML(catLabel) + '</span>' +
              (ev.fonte ? '<span class="ml-auto text-xs text-muted">' + escapeHTML(ev.fonte) + '</span>' : '') +
            '</div>' +
            '<h3 class="line-clamp-2 text-base font-semibold leading-snug text-primary group-hover:text-accent transition-colors">' + escapeHTML(ev.titulo || "Evento automotivo") + '</h3>' +
            '<div class="mt-auto flex flex-col gap-1 text-sm text-secondary">' +
              (dateStr
                ? '<span class="flex items-center gap-1.5">' +
                  '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-muted"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line></svg>' +
                  escapeHTML(dateStr) +
                  '</span>'
                : '') +
              (location
                ? '<span class="flex items-center gap-1.5">' +
                  '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-muted"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"></path><circle cx="12" cy="10" r="3"></circle></svg>' +
                  escapeHTML(location) +
                  '</span>'
                : '') +
            '</div>' +
          '</div>';

        grid.appendChild(card);
      });
    }

    function renderLoading() {
      grid.innerHTML = "";
      var loader = document.createElement("div");
      loader.className = "col-span-full flex items-center justify-center py-20";
      loader.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="animate-spin text-accent"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>';
      grid.appendChild(loader);
    }

    function showError(msg) {
      grid.innerHTML = "";
      var err = document.createElement("div");
      err.className = "col-span-full flex flex-col items-center justify-center py-16 text-center";
      err.innerHTML =
        '<p class="text-lg font-medium text-red-400">' + escapeHTML(msg) + '</p>' +
        '<p class="mt-1 text-sm text-muted">Verifique sua conexão e tente novamente.</p>' +
        '<button class="mt-4 inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg>' +
          'Tentar novamente' +
        '</button>';
      grid.appendChild(err);
      err.querySelector("button").addEventListener("click", function () { fetchEvents(true); });
    }

    function escapeHTML(str) {
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function escapeAttr(str) {
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    // ── Fetch ──
    function fetchEvents(force) {
      setLoadingState(true);
      errorMessage = null;

      if (initialLoad) {
        countEl.textContent = "Carregando eventos...";
        renderLoading();
      }

      var params = [];
      if (selectedUF) params.push("uf=" + encodeURIComponent(selectedUF));
      if (force) params.push("force=1");

      var url = ENDPOINT + (params.length ? "?" + params.join("&") : "");

      window.api
        .get(url)
        .then(function (data) {
          events = data.events || [];
          initialLoad = false;
          setCount(events.length);
          renderEvents(events);
        })
        .catch(function (err) {
          console.error("[eventos] fetch error:", err);
          events = [];
          initialLoad = false;
          errorMessage = err.message || "Erro ao carregar eventos";
          setCount(0);
          showError(errorMessage);
        })
        .finally(function () {
          setLoadingState(false);
        });
    }

    window.__eventosRetry = function () {
      fetchEvents(true);
    };

    // ── Init ──
    buildDropdown();
    fetchEvents();
  });
})();
