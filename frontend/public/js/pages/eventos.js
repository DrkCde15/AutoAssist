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
    grid.className =
      "grid gap-5 sm:grid-cols-2 lg:grid-cols-3";
    wrap.appendChild(grid);

    var selectedUF = "";
    var loading = false;

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

    // ── Fetch events ──
    function setLoading(isLoading) {
      loading = isLoading;
      if (refreshBtn) {
        refreshBtn.disabled = isLoading;
        refreshBtn.classList.toggle("disabled:opacity-50", isLoading);
        refreshBtn.classList.toggle("disabled:cursor-not-allowed", isLoading);
        var svg = refreshBtn.querySelector("svg");
        if (svg) {
          if (isLoading) {
            svg.classList.add("animate-spin");
          } else {
            svg.classList.remove("animate-spin");
          }
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

    function renderEvents(events) {
      grid.innerHTML = "";
      if (!events || events.length === 0) {
        renderEmpty();
        return;
      }

      events.forEach(function (ev) {
        var card = document.createElement("a");
        var url = ev.event_url || ev.url || "#";
        card.href = url;
        card.target = "_blank";
        card.rel = "noopener noreferrer";
        card.className =
          "group flex flex-col overflow-hidden rounded-2xl border border-border bg-card transition-all duration-200 hover:border-zinc-600 hover:shadow-lg hover:shadow-black/20";

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
        '<p class="mt-1 text-sm text-muted">Verifique sua conexão e tente novamente.</p>';
      grid.appendChild(err);
    }

    // ── Helpers ──
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
      setLoading(true);
      renderLoading();

      var params = [];
      if (selectedUF) params.push("uf=" + encodeURIComponent(selectedUF));
      if (force) params.push("force=1");

      var url = ENDPOINT + (params.length ? "?" + params.join("&") : "");

      window.api
        .get(url)
        .then(function (data) {
          var events = data.events || [];
          setCount(events.length);
          renderEvents(events);
        })
        .catch(function (err) {
          console.error("[eventos] fetch error:", err);
          setCount(0);
          showError(err.message || "Erro ao carregar eventos");
        })
        .finally(function () {
          setLoading(false);
        });
    }

    // ── Init ──
    buildDropdown();
    fetchEvents();
  });
})();
