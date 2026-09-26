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
    if (window.showToast) {
      window.showToast(msg, type);
    } else if (window.components && window.components.toast) {
      window.components.toast(msg, type);
    }
  }

  // Copia texto com fallback p/ contextos sem Clipboard API (HTTP não-localhost)
  function copyTextToClipboard(text, onOk, onFallback) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(onOk, function () {
        fallbackCopy(text) ? onOk() : onFallback();
      });
      return;
    }
    fallbackCopy(text) ? onOk() : onFallback();
  }

  function fallbackCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return !!ok;
    } catch (e) {
      return false;
    }
  }

  // ── Modal ──
  var modalOverlay = null;
  var currentVehicleId = null;
  var currentMods = [];

  function createModal() {
    if (modalOverlay) return;
    modalOverlay = document.createElement("div");
    modalOverlay.id = "mod-passport-modal";
    modalOverlay.className = "hidden";
    modalOverlay.style.cssText = "position:fixed;inset:0;z-index:1200;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);padding:1rem;";
    modalOverlay.innerHTML =
      '<div style="width:100%;max-width:32rem;max-height:90vh;overflow-y:auto;border-radius:1rem;border:1px solid var(--border-color,#27272a);background:var(--card-bg,#09090b);box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border-color,#27272a);padding:1rem 1.5rem;">' +
          '<h3 style="font-size:1.125rem;font-weight:700;color:var(--text-primary,#fafafa);margin:0;">Mod Passport</h3>' +
          '<button type="button" id="mp-close" style="border:none;background:none;cursor:pointer;padding:0.375rem;border-radius:0.5rem;color:var(--text-muted,#a1a1aa);">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
          '</button>' +
        '</div>' +
        '<div id="mp-body" style="padding:1rem 1.5rem;"></div>' +
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
    modalOverlay.style.display = "flex";
    modalOverlay.classList.remove("hidden");
  }

  function closeModal() {
    if (modalOverlay) {
      modalOverlay.style.display = "none";
      modalOverlay.classList.add("hidden");
    }
  }

  // ── Render mod form ──
  function renderModForm(vehicleId, vehicleName, fipeValor, existingMods) {
    createModal();
    currentVehicleId = vehicleId;
    currentMods = (existingMods || []).slice();
    var body = document.getElementById("mp-body");
    if (!body) return;

    var pctTotal = calcPctTotal(currentMods);
    var fipeNum = parseFipe(fipeValor);
    var ajustado = fipeNum > 0 ? fipeNum * (1 + pctTotal) : 0;

    body.innerHTML =
      '<div style="margin-bottom:1rem;border-radius:0.5rem;background:rgba(91,141,239,0.05);padding:0.75rem 1rem;">' +
        '<p style="font-size:0.75rem;color:var(--text-muted,#a1a1aa);margin:0;">' + escapeHTML(vehicleName) + '</p>' +
        '<div style="display:flex;align-items:center;gap:1rem;margin-top:0.5rem;">' +
          '<div>' +
            '<p style="font-size:0.625rem;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-muted,#a1a1aa);margin:0;">FIPE Base</p>' +
            '<p style="font-size:0.875rem;font-weight:700;color:var(--text-primary,#fafafa);margin:0.25rem 0 0;">' + formatCurrency(fipeValor) + '</p>' +
          '</div>' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--text-muted,#a1a1aa);"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>' +
          '<div>' +
            '<p style="font-size:0.625rem;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-muted,#a1a1aa);margin:0;">Valor Estimado</p>' +
            '<p style="font-size:0.875rem;font-weight:700;color:var(--accent,#5b8def);margin:0.25rem 0 0;">' + (ajustado > 0 ? formatCurrency(ajustado) : "---") + '</p>' +
          '</div>' +
          '<div style="margin-left:auto;">' +
            '<span style="border-radius:0.25rem;background:rgba(91,141,239,0.1);padding:0.125rem 0.5rem;font-size:0.625rem;font-weight:500;color:var(--accent,#5b8def);">+' + (pctTotal * 100).toFixed(1) + '%</span>' +
          '</div>' +
        '</div>' +
      '</div>' +

      '<div id="mp-mods-list" style="margin-bottom:1rem;"></div>' +

      '<button type="button" id="mp-add-mod" style="width:100%;display:flex;align-items:center;justify-content:center;gap:0.5rem;border-radius:0.5rem;border:1px dashed var(--border-color,#27272a);padding:0.625rem;font-size:0.875rem;color:var(--text-muted,#a1a1aa);background:none;cursor:pointer;margin-bottom:1rem;">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14"/><path d="M5 12h14"/></svg>' +
        'Adicionar modificacao' +
      '</button>' +

      '<div style="display:flex;gap:0.5rem;">' +
        '<button type="button" id="mp-save" style="flex:1;border-radius:0.5rem;background:var(--accent,#5b8def);padding:0.625rem 1rem;font-size:0.875rem;font-weight:600;color:#fff;border:none;cursor:pointer;">' +
          'Salvar' +
        '</button>' +
        '<button type="button" id="mp-share" style="border-radius:0.5rem;border:1px solid var(--border-color,#27272a);padding:0.625rem 1rem;font-size:0.875rem;font-weight:500;color:var(--text-secondary,#a1a1aa);background:none;cursor:pointer;">' +
          'Compartilhar' +
        '</button>' +
        '<button type="button" id="mp-pdf" style="border-radius:0.5rem;border:1px solid var(--border-color,#27272a);padding:0.625rem 1rem;font-size:0.875rem;font-weight:500;color:var(--text-secondary,#a1a1aa);background:none;cursor:pointer;">' +
          'PDF' +
        '</button>' +
      '</div>' +

      '<p style="margin-top:0.75rem;font-size:0.625rem;line-height:1.5;color:var(--text-muted,#a1a1aa);">' +
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

    openModal();
  }

  function renderModsList() {
    var list = document.getElementById("mp-mods-list");
    if (!list) return;
    if (currentMods.length === 0) {
      list.innerHTML = '<p style="text-align:center;font-size:0.875rem;color:var(--text-muted,#a1a1aa);padding:1rem 0;">Nenhuma modificacao registrada.</p>';
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
        '<div style="border:1px solid var(--border-color,#27272a);border-radius:0.5rem;padding:0.75rem;margin-bottom:0.5rem;background:rgba(255,255,255,0.02);">' +
          '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;">' +
            '<select data-idx="' + i + '" data-field="categoria" class="mp-field" style="flex:1;border-radius:0.25rem;border:1px solid var(--border-color,#27272a);background:var(--card-bg,#09090b);padding:0.375rem 0.5rem;font-size:0.75rem;color:var(--text-primary,#fafafa);">' +
              catOpts +
            '</select>' +
            '<span style="font-size:0.625rem;color:var(--accent,#5b8def);font-weight:500;">+' + (pct * 100).toFixed(1) + '%</span>' +
            '<button type="button" data-idx="' + i + '" class="mp-remove" style="border:none;background:none;cursor:pointer;padding:0.25rem;color:var(--text-muted,#a1a1aa);">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
            '</button>' +
          '</div>' +
          '<input data-idx="' + i + '" data-field="descricao" class="mp-field" style="width:100%;border-radius:0.25rem;border:1px solid var(--border-color,#27272a);background:var(--card-bg,#09090b);padding:0.375rem 0.5rem;font-size:0.75rem;color:var(--text-primary,#fafafa);box-sizing:border-box;" placeholder="Descricao (ex: Turbo Kit Garrett)" value="' + escapeHTML(m.descricao || "") + '" />' +
          '<input data-idx="' + i + '" data-field="valor" type="number" class="mp-field" style="width:100%;border-radius:0.25rem;border:1px solid var(--border-color,#27272a);background:var(--card-bg,#09090b);padding:0.375rem 0.5rem;font-size:0.75rem;color:var(--text-primary,#fafafa);margin-top:0.25rem;box-sizing:border-box;" placeholder="Valor informado em R$ (opcional)" value="' + escapeHTML(m.valor || "") + '" />' +
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
          copyTextToClipboard(
            data.share_url,
            function () { toast("Link copiado para a área de transferência!", "success"); },
            function () { toast("Link gerado: " + data.share_url, "success"); }
          );
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
        if (!data.share_token) throw new Error("sem token");
        // Fetch + blob em vez de window.open (bloqueado por popup-blocker
        // quando chamado fora do gesto direto do usuário).
        return fetch("/api/public/mod-passport/" + encodeURIComponent(data.share_token) + "/pdf", {
          credentials: "include",
        }).then(function (res) {
          if (!res.ok) throw new Error("falha no download");
          return res.blob();
        });
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "mod-passport-" + vehicleId + ".pdf";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
        toast("PDF baixado com sucesso.", "success");
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
      '<style>@keyframes mp-spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}</style>' +
      '<div style="display:flex;align-items:center;justify-content:center;padding:2rem 0;">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--accent,#5b8def);animation:mp-spin 1s linear infinite;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>' +
      '</div>';
    openModal();
    document.querySelector("#mod-passport-modal h3").textContent = "Historico Mod Passport";

    window.api.get("/api/veiculos/" + vehicleId + "/modificacoes/history")
      .then(function (data) {
        var versions = data.history || data.versions || [];
        if (versions.length === 0) {
          body.innerHTML = '<p style="text-align:center;font-size:0.875rem;color:var(--text-muted,#a1a1aa);padding:2rem 0;">Nenhum historico encontrado.</p>';
          return;
        }
        var html = '<div style="display:flex;flex-direction:column;gap:0.75rem;">';
        for (var i = 0; i < versions.length; i++) {
          var v = versions[i];
          var date = v.created_at ? new Date(v.created_at).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "---";
          html +=
            '<div style="border:1px solid var(--border-color,#27272a);border-radius:0.5rem;padding:0.75rem 1rem;background:rgba(255,255,255,0.02);">' +
              '<div style="display:flex;align-items:center;justify-content:space-between;">' +
                '<span style="font-size:0.75rem;font-weight:500;color:var(--text-primary,#fafafa);">' + date + '</span>' +
                '<span style="font-size:0.625rem;color:var(--text-muted,#a1a1aa);">' + (v.qtd_modificacoes || 0) + ' mods</span>' +
              '</div>' +
              '<div style="display:flex;align-items:center;gap:0.75rem;font-size:0.75rem;margin-top:0.25rem;">' +
                '<span style="color:var(--text-muted,#a1a1aa);">FIPE: ' + formatCurrency(v.fipe_valor) + '</span>' +
                '<span style="color:var(--accent,#5b8def);font-weight:500;">Estimado: ' + formatCurrency(v.fipe_ajustada) + '</span>' +
              '</div>' +
            '</div>';
        }
        html += '</div>';
        body.innerHTML = html;
      })
      .catch(function (err) {
        body.innerHTML = '<p style="text-align:center;font-size:0.875rem;color:#ef4444;padding:2rem 0;">Erro ao carregar historico.</p>';
      });
  }

  // ── Public API ──
  window.modPassport = {
    openForm: renderModForm,
    openHistory: openHistory,
  };
})();
