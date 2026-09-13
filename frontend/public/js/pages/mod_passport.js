/**
 * mod_passport.js — Gerencia Mod Passport no dashboard
 *
 * Endpoints:
 *   POST /api/veiculos/:id/modificacoes       — salva mods
 *   GET  /api/veiculos/:id/modificacoes/history — historico
 *   POST /api/veiculos/:id/mod-passport/share   — gera link publico
 *   GET  /api/public/mod-passport/:token        — visualizacao publica
 *   GET  /api/public/mod-passport/:token/pdf    — export PDF
 */
(function () {
  "use strict";

  var CATEGORIAS = [
    { value: "motor", label: "Motor" },
    { value: "turbo", label: "Turbo / Aspirador" },
    { value: "suspensao", label: "Suspensao" },
    { value: "freios", label: "Freios" },
    { value: "rodas", label: "Rodas / Aros" },
    { value: "pneus", label: "Pneus" },
    { value: "escapamento", label: "Escapamento" },
    { value: "eletronica", label: "Eletronica" },
    { value: "som", label: "Som" },
    { value: "estetica", label: "Estetica" },
    { value: "interna", label: "Interior" },
    { value: "outros", label: "Outros" },
  ];

  var MOD_PCT = {
    motor: 0.04, turbo: 0.05, suspensao: 0.02, freios: 0.02,
    rodas: 0.015, pneus: 0.01, escapamento: 0.015, eletronica: 0.02,
    som: 0.005, estetica: 0.005, interna: 0.01, outros: 0.01,
  };

  function escapeHTML(s) {
    if (!s) return "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function formatCurrency(v) {
    if (!v) return "---";
    var num = typeof v === "string" ? parseFloat(v.replace(/[^\d,]/g, "").replace(",", ".")) : v;
    if (isNaN(num)) return String(v);
    return num.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function toast(msg, type) {
    if (window.components && window.components.toast) window.components.toast(msg, type);
  }

  // ── Modal ──
  var modalOverlay = null;
  var currentVehicleId = null;
  var currentMods = [];

  function createModal() {
    if (modalOverlay) return;
    modalOverlay = document.createElement("div");
    modalOverlay.id = "mod-passport-modal";
    modalOverlay.className = "fixed inset-0 z-[1200] hidden items-center justify-center bg-black/60 backdrop-blur-sm p-4";
    modalOverlay.innerHTML =
      '<div class="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl border border-border bg-card shadow-2xl">' +
        '<div class="flex items-center justify-between border-b border-border px-6 py-4">' +
          '<h3 class="text-lg font-bold text-primary">Mod Passport</h3>' +
          '<button type="button" id="mp-close" class="rounded-lg p-1.5 text-muted hover:text-primary hover:bg-white/5 transition-colors">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
          '</button>' +
        '</div>' +
        '<div id="mp-body" class="px-6 py-4"></div>' +
      '</div>';
    document.body.appendChild(modalOverlay);

    modalOverlay.addEventListener("click", function (e) {
      if (e.target === modalOverlay) closeModal();
    });
    document.getElementById("mp-close").addEventListener("click", closeModal);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !modalOverlay.classList.contains("hidden")) closeModal();
    });
  }

  function openModal() {
    createModal();
    modalOverlay.classList.remove("hidden");
    modalOverlay.classList.add("flex");
  }

  function closeModal() {
    if (modalOverlay) {
      modalOverlay.classList.add("hidden");
      modalOverlay.classList.remove("flex");
    }
  }

  // ── Render mod form ──
  function renderModForm(vehicleId, vehicleName, fipeValor, existingMods) {
    currentVehicleId = vehicleId;
    currentMods = (existingMods || []).slice();
    var body = document.getElementById("mp-body");
    if (!body) return;

    var pctTotal = calcPctTotal(currentMods);
    var fipeNum = parseFipe(fipeValor);
    var ajustado = fipeNum > 0 ? fipeNum * (1 + pctTotal) : 0;

    body.innerHTML =
      '<div class="mb-4 rounded-lg bg-accent/5 px-4 py-3">' +
        '<p class="text-xs text-muted">' + escapeHTML(vehicleName) + '</p>' +
        '<div class="mt-2 flex items-center gap-4">' +
          '<div>' +
            '<p class="text-[10px] uppercase tracking-wide text-muted">FIPE Base</p>' +
            '<p class="text-sm font-bold text-primary">' + formatCurrency(fipeValor) + '</p>' +
          '</div>' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-muted"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>' +
          '<div>' +
            '<p class="text-[10px] uppercase tracking-wide text-muted">Valor Estimado</p>' +
            '<p class="text-sm font-bold text-accent">' + (ajustado > 0 ? formatCurrency(ajustado) : "---") + '</p>' +
          '</div>' +
          '<div class="ml-auto">' +
            '<span class="rounded bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">+' + (pctTotal * 100).toFixed(1) + '%</span>' +
          '</div>' +
        '</div>' +
      '</div>' +

      '<div id="mp-mods-list" class="space-y-2 mb-4"></div>' +

      '<button type="button" id="mp-add-mod" class="mb-4 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border px-3 py-2.5 text-sm text-muted transition-colors hover:border-accent hover:text-accent">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14"/><path d="M5 12h14"/></svg>' +
        'Adicionar modificacao' +
      '</button>' +

      '<div class="flex gap-2">' +
        '<button type="button" id="mp-save" class="flex-1 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed">' +
          'Salvar' +
        '</button>' +
        '<button type="button" id="mp-share" class="rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-secondary transition-colors hover:border-accent hover:text-primary">' +
          'Compartilhar' +
        '</button>' +
        '<button type="button" id="mp-pdf" class="rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-secondary transition-colors hover:border-accent hover:text-primary">' +
          'PDF' +
        '</button>' +
      '</div>' +

      '<p class="mt-3 text-[10px] leading-relaxed text-muted">' +
        'Valor estimado com base na Tabela FIPE e precos de anuncios reais, ajustado por modificacoes documentadas. ' +
        'Nao e avaliacao oficial e nao substitui pericia para venda, seguro ou financiamento.' +
      '</p>';

    renderModsList();

    document.getElementById("mp-add-mod").addEventListener("click", function () {
      currentMods.push({ categoria: "outros", descricao: "", valor: "" });
      renderModsList();
    });

    document.getElementById("mp-save").addEventListener("click", function () {
      saveMods(vehicleId);
    });

    document.getElementById("mp-share").addEventListener("click", function () {
      sharePassport(vehicleId);
    });

    document.getElementById("mp-pdf").addEventListener("click", function () {
      exportPDF(vehicleId);
    });
  }

  function renderModsList() {
    var list = document.getElementById("mp-mods-list");
    if (!list) return;
    if (currentMods.length === 0) {
      list.innerHTML = '<p class="text-center text-sm text-muted py-4">Nenhuma modificacao registrada.</p>';
      return;
    }
    var html = "";
    for (var i = 0; i < currentMods.length; i++) {
      var m = currentMods[i];
      var catOpts = "";
      for (var c = 0; c < CATEGORIAS.length; c++) {
        var sel = CATEGORIAS[c].value === m.categoria ? " selected" : "";
        catOpts += '<option value="' + CATEGORIAS[c].value + '"' + sel + '>' + CATEGORIAS[c].label + '</option>';
      }
      var pct = MOD_PCT[m.categoria] || MOD_PCT.outros;
      html +=
        '<div class="rounded-lg border border-border bg-primary/5 p-3">' +
          '<div class="flex items-center gap-2 mb-2">' +
            '<select data-idx="' + i + '" data-field="categoria" class="mp-field flex-1 rounded-md border border-border bg-card px-2 py-1.5 text-xs text-primary">' +
              catOpts +
            '</select>' +
            '<span class="text-[10px] text-accent font-medium">+' + (pct * 100).toFixed(1) + '%</span>' +
            '<button type="button" data-idx="' + i + '" class="mp-remove rounded p-1 text-muted hover:text-red-400 transition-colors">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
            '</button>' +
          '</div>' +
          '<input data-idx="' + i + '" data-field="descricao" class="mp-field w-full rounded-md border border-border bg-card px-2 py-1.5 text-xs text-primary placeholder:text-muted" placeholder="Descricao (ex: Turbo Kit Garrett)" value="' + escapeHTML(m.descricao || "") + '" />' +
          '<input data-idx="' + i + '" data-field="valor" type="number" class="mp-field mt-1 w-full rounded-md border border-border bg-card px-2 py-1.5 text-xs text-primary placeholder:text-muted" placeholder="Valor informado em R$ (opcional)" value="' + escapeHTML(m.valor || "") + '" />' +
        '</div>';
    }
    list.innerHTML = html;

    list.querySelectorAll(".mp-field").forEach(function (el) {
      el.addEventListener("change", function () {
        var idx = parseInt(el.getAttribute("data-idx"));
        var field = el.getAttribute("data-field");
        currentMods[idx][field] = el.value;
        if (field === "categoria") renderModsList();
      });
    });

    list.querySelectorAll(".mp-remove").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(btn.getAttribute("data-idx"));
        currentMods.splice(idx, 1);
        renderModsList();
      });
    });
  }

  function calcPctTotal(mods) {
    var pct = 0;
    for (var i = 0; i < mods.length; i++) {
      var cat = (mods[i].categoria || "outros").toLowerCase();
      pct += MOD_PCT[cat] || MOD_PCT.outros;
    }
    return Math.min(pct, 0.12);
  }

  function parseFipe(v) {
    if (!v) return 0;
    if (typeof v === "number") return v;
    var n = parseFloat(String(v).replace(/[^\d,]/g, "").replace(",", "."));
    return isNaN(n) ? 0 : n;
  }

  // ── API calls ──
  function saveMods(vehicleId) {
    var btn = document.getElementById("mp-save");
    if (btn) { btn.disabled = true; btn.textContent = "Salvando..."; }

    window.api.post("/api/veiculos/" + vehicleId + "/modificacoes", { modificacoes: currentMods })
      .then(function (data) {
        toast("Mod Passport salvo com sucesso!", "success");
        closeModal();
        if (typeof window.reloadDashboard === "function") window.reloadDashboard();
      })
      .catch(function (err) {
        toast(err.message || "Erro ao salvar. Verifique se voce tem assinatura Premium.", "error");
      })
      .finally(function () {
        if (btn) { btn.disabled = false; btn.textContent = "Salvar"; }
      });
  }

  function sharePassport(vehicleId) {
    var btn = document.getElementById("mp-share");
    if (btn) { btn.disabled = true; btn.textContent = "Gerando..."; }

    window.api.post("/api/veiculos/" + vehicleId + "/mod-passport/share")
      .then(function (data) {
        if (data.share_url) {
          navigator.clipboard.writeText(data.share_url).then(function () {
            toast("Link copiado para a area de transferencia!", "success");
          }).catch(function () {
            toast("Link gerado: " + data.share_url, "success");
          });
        }
      })
      .catch(function (err) {
        toast(err.message || "Erro ao gerar link.", "error");
      })
      .finally(function () {
        if (btn) { btn.disabled = false; btn.textContent = "Compartilhar"; }
      });
  }

  function exportPDF(vehicleId) {
    var btn = document.getElementById("mp-pdf");
    if (btn) { btn.disabled = true; btn.textContent = "Gerando..."; }

    window.api.post("/api/veiculos/" + vehicleId + "/mod-passport/share")
      .then(function (data) {
        if (data.share_token) {
          window.open("/api/public/mod-passport/" + data.share_token + "/pdf", "_blank");
        }
      })
      .catch(function (err) {
        toast(err.message || "Erro ao gerar PDF.", "error");
      })
      .finally(function () {
        if (btn) { btn.disabled = false; btn.textContent = "PDF"; }
      });
  }

  // ── History modal ──
  function openHistory(vehicleId) {
    createModal();
    var body = document.getElementById("mp-body");
    if (!body) return;
    body.innerHTML =
      '<div class="flex items-center justify-center py-8">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="animate-spin text-accent"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>' +
      '</div>';
    openModal();
    document.querySelector("#mod-passport-modal h3").textContent = "Historico Mod Passport";

    window.api.get("/api/veiculos/" + vehicleId + "/modificacoes/history")
      .then(function (data) {
        var versions = data.versions || [];
        if (versions.length === 0) {
          body.innerHTML = '<p class="text-center text-sm text-muted py-8">Nenhum historico encontrado.</p>';
          return;
        }
        var html = '<div class="space-y-3">';
        for (var i = 0; i < versions.length; i++) {
          var v = versions[i];
          var date = v.created_at ? new Date(v.created_at).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "---";
          html +=
            '<div class="rounded-lg border border-border bg-primary/5 px-4 py-3">' +
              '<div class="flex items-center justify-between">' +
                '<span class="text-xs font-medium text-primary">' + date + '</span>' +
                '<span class="text-[10px] text-muted">' + (v.qtd_modificacoes || 0) + ' mods</span>' +
              '</div>' +
              '<div class="mt-1 flex items-center gap-3 text-xs">' +
                '<span class="text-muted">FIPE: ' + formatCurrency(v.fipe_valor) + '</span>' +
                '<span class="text-accent font-medium">Estimado: ' + formatCurrency(v.fipe_ajustada) + '</span>' +
              '</div>' +
            '</div>';
        }
        html += '</div>';
        body.innerHTML = html;
      })
      .catch(function (err) {
        body.innerHTML = '<p class="text-center text-sm text-red-400 py-8">Erro ao carregar historico.</p>';
      });
  }

  // ── Public API ──
  window.modPassport = {
    openForm: renderModForm,
    openHistory: openHistory,
  };
})();
