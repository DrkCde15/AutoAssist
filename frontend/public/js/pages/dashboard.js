/**
 * dashboard.js — Página do dashboard (veículos + estatísticas gerais)
 */
(function () {
  "use strict";

  if (!window.auth || !window.api) return;
  if (!window.auth.requireAuth()) return;

  var statsBar = document.getElementById("stats-bar");
  var vehicleGrid = document.getElementById("vehicle-grid");
  var loadingEl = document.getElementById("dashboard-loading");

  function showEmpty() {
    if (loadingEl) loadingEl.classList.add("hidden");
    if (statsBar) statsBar.classList.add("hidden");
    if (vehicleGrid) {
      vehicleGrid.innerHTML =
        '<div class="col-span-full flex flex-col items-center justify-center gap-4 py-16 text-center">' +
          '<div class="rounded-full bg-accent/10 p-4">' +
            '<svg xmlns="http://www.w3.org/2000/svg" class="h-10 w-10 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M8.25 18.75a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h6m-9 0H3.375a1.125 1.125 0 0 1-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 0 0-3.213-9.193 2.056 2.056 0 0 0-1.58-.86H14.25m-2.25 0h-2.25m0 0v-.375c0-.621-.504-1.125-1.125-1.125H6.375c-.621 0-1.125.504-1.125 1.125v.375m12 0H5.25" /></svg>' +
          '</div>' +
          '<h3 class="text-lg font-semibold text-primary">Nenhum veículo encontrado</h3>' +
          '<p class="max-w-sm text-sm text-muted">Adicione seu primeiro veículo para ver o painel completo com diagnósticos, valores FIPE e previsões de manutenção.</p>' +
          '<a href="/perfil" class="mt-2 inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover">' +
            '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>' +
            'Adicionar Veículo' +
          '</a>' +
        '</div>';
    }
  }

  function formatCurrency(value) {
    if (!value || value === "Não listado na Tabela FIPE") return "Não listado";
    var num = typeof value === "string" ? parseFloat(value.replace(/[^\d,]/g, "").replace(",", ".")) : value;
    if (isNaN(num)) return String(value);
    return num.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function formatKm(km) {
    if (!km && km !== 0) return "---";
    return Number(km).toLocaleString("pt-BR") + " km";
  }

  function healthBadge(score) {
    var color, bg;
    if (score >= 80) {
      color = "text-emerald-700 dark:text-emerald-400";
      bg = "bg-emerald-100 dark:bg-emerald-900/30";
    } else if (score >= 50) {
      color = "text-amber-700 dark:text-amber-400";
      bg = "bg-amber-100 dark:bg-amber-900/30";
    } else {
      color = "text-red-700 dark:text-red-400";
      bg = "bg-red-100 dark:bg-red-900/30";
    }
    return '<span class="inline-flex items-center gap-1 rounded-md px-2.5 py-0.5 text-xs font-semibold ' + bg + ' ' + color + '">' +
      '<span class="h-1.5 w-1.5 rounded-full ' + color.replace("text-", "bg-") + '"></span>' +
      score +
    '</span>';
  }

  function renderStatsBar(vehicles) {
    if (!statsBar) return;
    var total = vehicles.length;
    var totalKm = 0;
    var totalValue = 0;
    var healthyCount = 0;
    var pendingMaint = 0;

    for (var i = 0; i < vehicles.length; i++) {
      var v = vehicles[i];
      totalKm += (v.estatisticas_extras && v.estatisticas_extras.quilometragem) || v.veiculo.quilometragem || 0;
      var score = v.estatisticas_extras ? v.estatisticas_extras.health_score : 0;
      if (score >= 80) healthyCount++;
      if (v.predicao && v.predicao.predicted_next_date) {
        var due = new Date(v.predicao.predicted_next_date);
        var now = new Date();
        if (due <= new Date(now.getTime() + 60 * 24 * 60 * 60 * 1000)) pendingMaint++;
      }
      if (v.fipe && v.fipe.Valor && v.fipe.Valor !== "Não listado na Tabela FIPE") {
        var fv = typeof v.fipe.Valor === "string" ? parseFloat(v.fipe.Valor.replace(/[^\d,]/g, "").replace(",", ".")) : v.fipe.Valor;
        if (!isNaN(fv)) totalValue += fv;
      }
    }

    statsBar.innerHTML =
      '<div class="flex flex-wrap items-center gap-6 text-sm">' +
        '<div class="flex items-center gap-2">' +
          '<span class="text-muted">Veículos:</span>' +
          '<span class="font-semibold text-primary">' + total + '</span>' +
        '</div>' +
        '<div class="flex items-center gap-2">' +
          '<span class="text-muted">Patrimônio FIPE:</span>' +
          '<span class="font-semibold text-accent">' + formatCurrency(totalValue) + '</span>' +
        '</div>' +
        '<div class="flex items-center gap-2">' +
          '<span class="text-muted">Saúde boa:</span>' +
          '<span class="font-semibold text-emerald-600 dark:text-emerald-400">' + healthyCount + '/' + total + '</span>' +
        '</div>' +
        '<div class="flex items-center gap-2">' +
          '<span class="text-muted">Manutenções próximas:</span>' +
          '<span class="font-semibold text-amber-600 dark:text-amber-400">' + pendingMaint + '</span>' +
        '</div>' +
      '</div>';
    statsBar.classList.remove("hidden");
  }

  function renderVehicleCard(item) {
    var v = item.veiculo;
    var fipe = item.fipe || {};
    var saude = item.saude || [];
    var pred = item.predicao || {};
    var stats = item.estatisticas_extras || {};

    var healthScore = stats.health_score || 0;
    var vehicleName = ((v.marca || "") + " " + (v.modelo || "")).trim();
    if (!vehicleName) vehicleName = v.tipo || "Veículo";
    var year = v.ano_fabricacao || "";

    var saudeAlert = saude.length ? saude[0] : null;
    var saudeLabel = saudeAlert ? saudeAlert.status : "";
    var saudeColor = saudeLabel === "OK" ? "text-emerald-600 dark:text-emerald-400"
      : saudeLabel === "Atenção" ? "text-amber-600 dark:text-amber-400"
      : "text-red-600 dark:text-red-400";

    var nextDate = pred.predicted_next_date;
    var nextLabel = pred.maintenance_label || "Próxima manutenção";
    var nextDateFormatted = "";
    if (nextDate) {
      var d = new Date(nextDate + "T00:00:00");
      nextDateFormatted = d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
    }

    var manutencoes = stats.manutencoes_realizadas || 0;
    var ultimaData = stats.data_ultima_manutencao || "---";

    return '<div class="group fade-in-up rounded-xl border border-border bg-card p-5 transition-all duration-200 hover:border-accent/40 hover:shadow-lg hover:shadow-[0_8px_30px_-4px_rgba(91,141,239,0.08)] hover:-translate-y-0.5">' +
      '<!-- Header -->' +
      '<div class="mb-4 flex items-start justify-between">' +
        '<div class="min-w-0 flex-1">' +
          '<h3 class="truncate text-base font-semibold text-primary">' + vehicleName + '</h3>' +
          '<p class="mt-0.5 text-xs text-muted">' + (year ? year + ' • ' : '') + formatKm(v.quilometragem) + '</p>' +
        '</div>' +
        healthBadge(healthScore) +
      '</div>' +

      '<!-- FIPE Value -->' +
      '<div class="mb-4 rounded-lg bg-accent/5 px-3 py-2.5">' +
        '<div class="flex items-center justify-between">' +
          '<span class="text-xs font-medium text-muted">Valor FIPE</span>' +
          '<span class="rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">' + (fipe.MesReferencia || "---") + '</span>' +
        '</div>' +
        '<p class="mt-1 text-lg font-bold text-accent">' + formatCurrency(fipe.Valor) + '</p>' +
        (v.fipe_ajustada ?
          '<div class="mt-1.5 flex items-center gap-2 border-t border-accent/10 pt-1.5">' +
            '<span class="text-[10px] text-muted">Estimado c/ mods:</span>' +
            '<span class="text-xs font-bold text-accent">' + formatCurrency(v.fipe_ajustada) + '</span>' +
          '</div>' : '') +
      '</div>' +

      '<!-- Next Maintenance -->' +
      (nextDate ?
        '<div class="mb-4 flex items-center gap-2 rounded-lg border border-amber-200/50 bg-amber-50/50 px-3 py-2 dark:border-amber-800/30 dark:bg-amber-900/10">' +
          '<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>' +
          '<div class="min-w-0 flex-1">' +
            '<p class="truncate text-xs font-medium text-amber-700 dark:text-amber-400">' + nextLabel + '</p>' +
            '<p class="text-[11px] text-amber-600/80 dark:text-amber-400/70">' + nextDateFormatted + '</p>' +
          '</div>' +
        '</div>' : '') +

      '<!-- Stats Grid -->' +
      '<div class="grid grid-cols-3 gap-2">' +
        '<div class="rounded-lg bg-primary/5 px-2 py-2 text-center">' +
          '<p class="text-xs text-muted">Gastos</p>' +
          '<p class="mt-0.5 text-sm font-semibold text-primary">' + manutencoes + '</p>' +
        '</div>' +
        '<div class="rounded-lg bg-primary/5 px-2 py-2 text-center">' +
          '<p class="text-xs text-muted">Última</p>' +
          '<p class="mt-0.5 text-sm font-semibold text-primary">' + (ultimaData !== "Nenhuma" ? ultimaData : "---") + '</p>' +
        '</div>' +
        '<div class="rounded-lg bg-primary/5 px-2 py-2 text-center">' +
          '<p class="text-xs text-muted">Chats</p>' +
          '<p class="mt-0.5 text-sm font-semibold text-primary">' + (stats.chats_realizados || 0) + '</p>' +
        '</div>' +
      '</div>' +

      '<!-- Action -->' +
      '<div class="mt-4 space-y-2">' +
        (window.modPassport ?
          '<div class="flex gap-2">' +
            '<button type="button" data-mp-edit="' + v.id + '" class="flex-1 flex items-center justify-center gap-1.5 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-xs font-medium text-accent transition-colors hover:bg-accent/10">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4Z"/></svg>' +
              'Mod Passport' +
            '</button>' +
            '<button type="button" data-mp-history="' + v.id + '" class="rounded-lg border border-border px-3 py-2 text-xs font-medium text-secondary transition-colors hover:border-accent/50 hover:text-primary" title="Historico">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>' +
            '</button>' +
          '</div>' : '') +
        '<a href="/perfil" class="flex w-full items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-secondary transition-colors hover:border-accent/50 hover:text-primary">' +
          'Ver detalhes' +
          '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg>' +
        '</a>' +
      '</div>' +
    '</div>';
  }

  async function loadDashboard() {
    // Show skeleton loaders while loading
    if (statsBar) {
      statsBar.innerHTML = window.createSkeletonStats ? window.createSkeletonStats() : '';
      statsBar.classList.remove("hidden");
    }
    if (vehicleGrid) {
      vehicleGrid.innerHTML = (window.createSkeletonCard ? window.createSkeletonCard() : '').repeat(3);
    }

    try {
      var data = await window.api.get("/api/dashboard");

      if (loadingEl) loadingEl.classList.add("hidden");

      if (!data || !data.length) {
        showEmpty();
        return;
      }

      renderStatsBar(data);

      if (vehicleGrid) {
        vehicleGrid.innerHTML = data.map(renderVehicleCard).join("");
        setupModPassportButtons(data);
      }
    } catch (err) {
      if (loadingEl) loadingEl.classList.add("hidden");
      if (vehicleGrid) {
        vehicleGrid.innerHTML =
          '<div class="col-span-full flex flex-col items-center justify-center gap-3 py-16 text-center">' +
            '<svg xmlns="http://www.w3.org/2000/svg" class="h-10 w-10 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" /></svg>' +
            '<p class="text-sm text-muted">Erro ao carregar dados. Tente novamente.</p>' +
            '<button onclick="location.reload()" class="mt-1 text-sm font-medium text-accent hover:underline">Recarregar</button>' +
          '</div>';
      }
    }
  }

  loadDashboard();

  function setupModPassportButtons(vehicles) {
    if (!window.modPassport || !vehicleGrid) return;

    vehicleGrid.addEventListener("click", function (e) {
      var editBtn = e.target.closest("[data-mp-edit]");
      var historyBtn = e.target.closest("[data-mp-history]");

      if (editBtn) {
        var vid = editBtn.getAttribute("data-mp-edit");
        var vData = null;
        for (var i = 0; i < vehicles.length; i++) {
          if (vehicles[i].veiculo && String(vehicles[i].veiculo.id) === String(vid)) {
            vData = vehicles[i];
            break;
          }
        }
        if (vData) {
          var v = vData.veiculo;
          var fipeObj = vData.fipe || {};
          var name = ((v.marca || "") + " " + (v.modelo || "")).trim() || v.tipo || "Veiculo";
          var mods = [];
          if (v.modificacoes) {
            mods = typeof v.modificacoes === "string" ? JSON.parse(v.modificacoes) : v.modificacoes;
          }
          var fipeRaw = fipeObj.Valor || v.fipe_valor || null;
          window.modPassport.openForm(vid, name, fipeRaw, mods);
        }
      }

      if (historyBtn) {
        var hid = historyBtn.getAttribute("data-mp-history");
        window.modPassport.openHistory(hid);
      }
    });
  }

  window.reloadDashboard = function () {
    loadDashboard();
  };
})();
