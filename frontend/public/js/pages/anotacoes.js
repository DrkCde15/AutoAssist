/**
 * anotacoes.js — Histórico de manutenção (Anotações) page logic.
 * Fetches records from GET /api/maintenance/history, vehicle list from
 * GET /api/veiculos, renders cards with summary, handles add/delete.
 */
(function () {
  "use strict";

  var HISTORY_ENDPOINT = "/api/maintenance/history";
  var VEICULOS_ENDPOINT = "/api/veiculos";

  var vehicles = [];
  var selectedVehicleId = "";
  var records = [];
  var summary = null;
  var loading = false;
  var initialLoad = true;

  document.addEventListener("DOMContentLoaded", function () {
    if (!auth.requireAuth()) return;
    if (window.premiumModal && !window.premiumModal.requirePremium()) return;

    // Inject missing CSS
    if (!document.getElementById("anotacoes-responsive-css")) {
      var css = document.createElement("style");
      css.id = "anotacoes-responsive-css";
      css.textContent =
        ".bg-primary { background-color: var(--color-bg-primary); }" +
        ".bg-card { background-color: var(--color-bg-card); }" +
        ".bg-secondary { background-color: var(--color-bg-secondary); }" +
        ".text-primary { color: var(--color-text-primary); }" +
        ".text-secondary { color: var(--color-text-secondary); }" +
        ".text-muted { color: var(--color-text-muted); }" +
        ".hover\\:bg-white\\/5:hover { background-color: rgba(255,255,255,0.05); }" +
        ".hover\\:bg-secondary:hover { background-color: var(--color-bg-secondary); }" +
        ".hover\\:text-primary:hover { color: var(--color-text-primary); }" +
        ".hover\\:border-zinc-600:hover { border-color: #3f3f46; }" +
        ".hover\\:border-border-hover:hover { border-color: var(--color-border-hover); }" +
        ".hover\\:-translate-y-0\\.5:hover { transform: translateY(-0.125rem); }" +
        ".disabled\\:opacity-50:disabled { opacity: 0.5; }" +
        ".disabled\\:cursor-not-allowed:disabled { cursor: not-allowed; }" +
        ".focus\\:border-accent:focus { border-color: var(--color-accent); }" +
        ".focus\\:ring-1:focus { box-shadow: 0 0 0 1px var(--color-accent); }" +
        ".focus\\:ring-2:focus { box-shadow: 0 0 0 2px var(--color-accent); }" +
        ".focus\\:ring-accent\\/50:focus { box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-accent) 50%, transparent); }" +
        ".focus\\:outline-none:focus { outline: 2px solid transparent; outline-offset: 2px; }" +
        ".whitespace-nowrap { white-space: nowrap; }" +
        ".text-\\[11px\\] { font-size: 11px; line-height: 1rem; }" +
        ".transition-transform { transition-property: transform; transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1); transition-duration: 200ms; }" +
        ".anotacoes-section__header { text-align: left; margin-bottom: 0; }";
      document.head.appendChild(css);
    }

    var section = document.querySelector("main section");
    if (!section) return;

    var wrap = section.querySelector(".section__wrap");
    if (!wrap) return;

    var header = wrap.querySelector(".section__header");
    var filterBar = header ? header.nextElementSibling : null;

    var countEl = null;
    var vehicleSelect = null;
    var addBtn = null;
    var refreshBtn = null;

    if (filterBar) {
      countEl = filterBar.querySelector("p");
      var btnGroup = filterBar.querySelector(".flex.items-center.gap-3");
      if (btnGroup) {
        vehicleSelect = btnGroup.querySelector("select");
        var buttons = btnGroup.querySelectorAll("button");
        for (var i = 0; i < buttons.length; i++) {
          if (buttons[i].textContent.indexOf("Atualizar") !== -1) {
            refreshBtn = buttons[i];
          }
        }
      }
    }

    var grid = document.createElement("div");
    grid.className = "space-y-3";
    wrap.appendChild(grid);

    // ── Helpers ──
    function escapeHTML(str) {
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function formatCurrency(value) {
      if (value == null) return "R$ 0,00";
      return "R$ " + Number(value).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function formatDate(dateStr) {
      if (!dateStr) return "";
      var parts = String(dateStr).split("-");
      if (parts.length === 3) return parts[2] + "/" + parts[1] + "/" + parts[0];
      return dateStr;
    }

    function formatKm(km) {
      if (km == null) return "";
      return Number(km).toLocaleString("pt-BR") + " km";
    }

    // ── Loading / Error / Empty states ──
    function renderLoading() {
      grid.innerHTML = "";
      var loader = document.createElement("div");
      loader.className = "flex items-center justify-center py-12";
      loader.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="animate-spin text-accent"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>';
      grid.appendChild(loader);
    }

    function renderEmpty() {
      grid.innerHTML = "";
      var msg = document.createElement("div");
      msg.className = "flex flex-col items-center justify-center py-12 text-center";
      msg.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="mb-4 text-zinc-600"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>' +
        '<p class="text-lg font-medium text-secondary">Nenhuma anotação registrada</p>' +
        '<p class="mt-1 text-sm text-muted">Clique em "Nova anotação" para adicionar seu primeiro registro de manutenção.</p>';
      grid.appendChild(msg);
    }

    function showError(msg) {
      grid.innerHTML = "";
      var err = document.createElement("div");
      err.className = "flex flex-col items-center justify-center py-12 text-center";
      err.innerHTML =
        '<p class="text-lg font-medium text-red-400">' + escapeHTML(msg) + '</p>' +
        '<p class="mt-1 text-sm text-muted">Verifique sua conexão e tente novamente.</p>' +
        '<button class="mt-4 inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover" onclick="window.__anotacoesRetry()">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg>' +
          'Tentar novamente' +
        '</button>';
      grid.appendChild(err);
    }

    // ── Summary card ──
    function renderSummary() {
      var existing = wrap.querySelector(".anotacoes-summary");
      if (existing) existing.remove();

      if (!summary) return;

      var card = document.createElement("div");
      card.className = "anotacoes-summary rounded-xl border border-border bg-card p-4 mb-4";
      card.innerHTML =
        '<div class="flex flex-wrap items-center gap-6">' +
          '<div>' +
            '<p class="text-sm text-muted">Total gasto</p>' +
            '<p class="text-2xl font-bold text-primary">' + formatCurrency(summary.total_gastos) + '</p>' +
          '</div>' +
          '<div>' +
            '<p class="text-sm text-muted">Registros</p>' +
            '<p class="text-2xl font-bold text-primary">' + (summary.quantidade_registros || 0) + '</p>' +
          '</div>' +
          (summary.gastos_por_tipo && summary.gastos_por_tipo.length
            ? '<div class="flex-1 min-w-[200px]">' +
                '<p class="text-sm text-muted mb-2">Por tipo</p>' +
                '<div class="flex flex-wrap gap-2">' +
                  summary.gastos_por_tipo.map(function (item) {
                    return '<span class="inline-flex items-center rounded-md border border-border px-2.5 py-0.5 text-xs font-medium text-secondary">' +
                      escapeHTML(item.tipo) + ': ' + formatCurrency(item.valor) +
                    '</span>';
                  }).join("") +
                '</div>' +
              '</div>'
            : '') +
        '</div>';

      if (header) {
        header.parentNode.insertBefore(card, header.nextSibling);
      } else {
        wrap.insertBefore(card, wrap.firstChild);
      }
    }

    // ── Records list ──
    function renderRecords() {
      grid.innerHTML = "";
      if (!records || records.length === 0) {
        renderEmpty();
        return;
      }

      records.forEach(function (rec) {
        var vehicleName = "";
        if (rec.vehicle_marca || rec.vehicle_modelo) {
          vehicleName = ((rec.vehicle_marca || "") + " " + (rec.vehicle_modelo || "")).trim();
        }

        var row = document.createElement("div");
        row.className = "flex items-start justify-between gap-4 rounded-xl border border-border bg-card p-4 transition-all duration-200 hover:border-zinc-600 hover:-translate-y-0.5";

        var left = document.createElement("div");
        left.className = "flex-1 min-w-0";

        var desc = document.createElement("p");
        desc.className = "text-sm font-medium text-primary truncate";
        desc.textContent = rec.description || rec.maintenance_label || "Sem descrição";
        left.appendChild(desc);

        var meta = document.createElement("div");
        meta.className = "mt-1.5 flex flex-wrap items-center gap-3 text-xs text-muted";

        if (rec.service_date) {
          var dateSpan = document.createElement("span");
          dateSpan.className = "flex items-center gap-1";
          dateSpan.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line></svg>' +
            escapeHTML(formatDate(rec.service_date));
          meta.appendChild(dateSpan);
        }

        if (rec.service_km != null) {
          var kmSpan = document.createElement("span");
          kmSpan.className = "flex items-center gap-1";
          kmSpan.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>' +
            escapeHTML(formatKm(rec.service_km));
          meta.appendChild(kmSpan);
        }

        if (vehicleName) {
          var vehicleSpan = document.createElement("span");
          vehicleSpan.className = "flex items-center gap-1";
          vehicleSpan.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0"><path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"></path><circle cx="7" cy="17" r="2"></circle><path d="M9 17h6"></path><circle cx="17" cy="17" r="2"></circle></svg>' +
            escapeHTML(vehicleName);
          meta.appendChild(vehicleSpan);
        }

        if (rec.maintenance_label && rec.maintenance_label !== rec.description) {
          var labelSpan = document.createElement("span");
          labelSpan.className = "inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-secondary";
          labelSpan.textContent = rec.maintenance_label;
          meta.appendChild(labelSpan);
        }

        left.appendChild(meta);

        var right = document.createElement("div");
        right.className = "flex flex-col items-end gap-2 shrink-0";

        if (rec.cost != null && rec.cost > 0) {
          var costEl = document.createElement("p");
          costEl.className = "text-sm font-semibold text-primary whitespace-nowrap";
          costEl.textContent = formatCurrency(rec.cost);
          right.appendChild(costEl);
        }

        var delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "text-xs text-red-400 hover:text-red-300 transition-colors";
        delBtn.textContent = "Excluir";
        delBtn.setAttribute("data-delete-id", rec.id);
        delBtn.addEventListener("click", function () {
          handleDelete(rec.id, rec.description || "este registro");
        });
        right.appendChild(delBtn);

        row.appendChild(left);
        row.appendChild(right);
        grid.appendChild(row);
      });
    }

    // ── Vehicle selector ──
    function buildVehicleSelect() {
      if (vehicleSelect) return;
      vehicleSelect = document.createElement("select");
      vehicleSelect.className = "rounded-lg border border-border bg-card px-3 py-1.5 text-sm text-primary focus:outline-none focus:ring-2 focus:ring-accent/50";
      var firstOpt = document.createElement("option");
      firstOpt.value = "";
      firstOpt.textContent = "Todos os veículos";
      vehicleSelect.appendChild(firstOpt);

      if (filterBar) {
        var btnGroup = filterBar.querySelector(".flex.items-center.gap-3");
        if (btnGroup) {
          btnGroup.insertBefore(vehicleSelect, btnGroup.firstChild);
        }
      }

      vehicleSelect.addEventListener("change", function () {
        selectedVehicleId = vehicleSelect.value;
        fetchHistory();
      });
    }

    function populateVehicleOptions() {
      if (!vehicleSelect) return;
      while (vehicleSelect.options.length > 1) {
        vehicleSelect.remove(1);
      }
      vehicles.forEach(function (v) {
        var opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = ((v.marca || "") + " " + (v.modelo || "")).trim() || "Veículo " + v.id;
        vehicleSelect.appendChild(opt);
      });
    }

    // ── Add button ──
    function buildAddButton() {
      addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover whitespace-nowrap";
      addBtn.textContent = "Nova anotação";
      addBtn.addEventListener("click", function () {
        openAddForm();
      });

      if (header) {
        header.appendChild(addBtn);
      }
    }

    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        if (!loading) fetchHistory();
      });
    }

    buildVehicleSelect();
    buildAddButton();

    // ── Fetch data ──
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
      countEl.textContent = n + " registro" + (n !== 1 ? "s" : "");
    }

    function fetchVehicles() {
      return window.api
        .get(VEICULOS_ENDPOINT)
        .then(function (data) {
          vehicles = data.veiculos || [];
          populateVehicleOptions();
        })
        .catch(function (err) {
          console.error("[anotacoes] fetch vehicles error:", err);
        });
    }

    function fetchHistory() {
      setLoadingState(true);

      if (initialLoad) {
        countEl.textContent = "Carregando...";
        renderLoading();
      }

      var params = [];
      if (selectedVehicleId) params.push("veiculo_id=" + encodeURIComponent(selectedVehicleId));

      var url = HISTORY_ENDPOINT + (params.length ? "?" + params.join("&") : "");

      window.api
        .get(url)
        .then(function (data) {
          records = data.historico || [];
          summary = data.resumo || null;
          initialLoad = false;
          setCount(data.total || records.length);
          renderSummary();
          renderRecords();
        })
        .catch(function (err) {
          console.error("[anotacoes] fetch history error:", err);
          records = [];
          summary = null;
          initialLoad = false;
          setCount(0);
          showError(err.message || "Erro ao carregar histórico");
        })
        .finally(function () {
          setLoadingState(false);
        });
    }

    window.__anotacoesRetry = function () {
      fetchHistory();
    };

    // ── Delete ──
    function handleDelete(id, label) {
      if (!window.confirm('Excluir "' + label + '"?')) return;

      var rowEl = grid.querySelector('[data-delete-id="' + id + '"]');
      if (rowEl) rowEl.disabled = true;

      window.api
        .delete(HISTORY_ENDPOINT + "/" + id)
        .then(function () {
          records = records.filter(function (r) { return r.id !== id; });
          setCount(records.length);
          renderRecords();
          fetchHistory();
        })
        .catch(function (err) {
          console.error("[anotacoes] delete error:", err);
          alert(err.message || "Erro ao excluir registro");
        });
    }

    // ── Add form modal ──
    function openAddForm() {
      var existing = document.getElementById("anotacoes-modal");
      if (existing) existing.remove();

      var modal = document.createElement("div");
      modal.id = "anotacoes-modal";
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      modal.setAttribute("aria-labelledby", "anotacoes-modal-title");
      modal.className = "fixed inset-0 z-[1200] flex items-center justify-center p-4";
      modal.innerHTML =
        '<div class="fixed inset-0 bg-black/60" data-close-modal></div>' +
        '<div class="relative w-full max-w-lg rounded-2xl border border-border bg-primary p-6 shadow-2xl" style="max-height:calc(100vh - 32px);overflow-y:auto">' +
          '<h3 id="anotacoes-modal-title" class="text-lg font-semibold text-primary mb-4">Nova anotação</h3>' +
          '<form id="anotacoes-form" class="space-y-4">' +
            '<div>' +
              '<label class="block text-sm font-medium text-secondary mb-1.5" for="anotacao-desc">Descrição *</label>' +
              '<textarea id="anotacao-desc" rows="3" class="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-primary placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50" placeholder="Ex: Troca de óleo, revisão 50.000 km..." required></textarea>' +
            '</div>' +
            '<div>' +
              '<label class="block text-sm font-medium text-secondary mb-1.5" for="anotacao-veiculo">Veículo</label>' +
              '<select id="anotacao-veiculo" class="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-primary focus:outline-none focus:ring-2 focus:ring-accent/50">' +
                '<option value="">Nenhum (opcional)</option>' +
              '</select>' +
            '</div>' +
            '<div class="flex items-center justify-end gap-3 pt-2">' +
              '<button type="button" class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-secondary hover:bg-white/5 transition-colors" data-close-modal>Cancelar</button>' +
              '<button type="submit" id="anotacao-submit" class="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover">Salvar</button>' +
            '</div>' +
          '</form>' +
        '</div>';

      document.body.appendChild(modal);

      // Populate vehicle options
      var modalSelect = modal.querySelector("#anotacao-veiculo");
      vehicles.forEach(function (v) {
        var opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = ((v.marca || "") + " " + (v.modelo || "")).trim() || "Veículo " + v.id;
        modalSelect.appendChild(opt);
      });

      if (selectedVehicleId) {
        modalSelect.value = selectedVehicleId;
      }

      // Close handlers
      modal.querySelectorAll("[data-close-modal]").forEach(function (el) {
        el.addEventListener("click", function (e) {
          if (e.target === el || el.hasAttribute("data-close-modal")) {
            modal.remove();
          }
        });
      });

      // Escape key closes modal
      function onKeyDown(e) {
        if (e.key === "Escape") {
          modal.remove();
          document.removeEventListener("keydown", onKeyDown);
        }
      }
      document.addEventListener("keydown", onKeyDown);

      // Trap focus inside modal
      modal.addEventListener("keydown", function (e) {
        if (e.key !== "Tab") return;
        var focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (focusable.length === 0) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      });

      // Form submit
      var form = modal.querySelector("#anotacoes-form");
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        handleSubmit(form, modal);
      });

      // Focus first field
      var descInput = modal.querySelector("#anotacao-desc");
      if (descInput) descInput.focus();
    }

    function handleSubmit(form, modal) {
      var descInput = form.querySelector("#anotacao-desc");
      var veiculoInput = form.querySelector("#anotacao-veiculo");
      var submitBtn = form.querySelector("#anotacao-submit");

      var descricao = (descInput.value || "").trim();
      if (!descricao) {
        descInput.focus();
        return;
      }

      var payload = { descricao: descricao };
      if (veiculoInput.value) {
        payload.veiculo_id = parseInt(veiculoInput.value, 10);
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "Salvando...";

      window.api
        .post(HISTORY_ENDPOINT, payload)
        .then(function () {
          modal.remove();
          fetchHistory();
        })
        .catch(function (err) {
          console.error("[anotacoes] add error:", err);
          alert(err.message || "Erro ao salvar anotação");
          submitBtn.disabled = false;
          submitBtn.textContent = "Salvar";
        });
    }

    // ── Init ──
    fetchVehicles().then(function () {
      fetchHistory();
    });
  });
})();
