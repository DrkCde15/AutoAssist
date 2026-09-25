/**
 * perfil.js — Perfil do usuário: dados, veículos, edição e status premium
 */
(function () {
  "use strict";

  var mainEl = null;

  function toast(message, type) {
    if (window.showToast) {
      window.showToast(message, type);
    }
  }

  function escapeHTML(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str || ""));
    return div.innerHTML;
  }

  function formatDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    var day = String(d.getDate()).padStart(2, "0");
    var mon = String(d.getMonth() + 1).padStart(2, "0");
    var year = d.getFullYear();
    return day + "/" + mon + "/" + year;
  }

  function formatCurrency(val) {
    if (val === null || val === undefined) return "—";
    if (typeof val === "string") return val;
    return "R$ " + Number(val).toLocaleString("pt-BR", { minimumFractionDigits: 2 });
  }

  function fotoSrc(v) {
    // P2: prefere foto_url/storage externo; fallback foto_base64 legado.
    if (!v) return "";
    if (typeof v === "object") {
      if (v.foto_url) return v.foto_url;
      return fotoSrc(v.foto_base64);
    }
    var foto = v;
    if (!foto) return "";
    if (foto.indexOf("data:") === 0) return foto;
    // P2: URL do storage externo (absoluta) ou endpoint interno /api/...
    // NOTA: JPEG em base64 começa com "/9j/" — nunca tratar "/" genérico como URL.
    if (foto.indexOf("http://") === 0 || foto.indexOf("https://") === 0) return foto;
    if (foto.indexOf("/api/") === 0) return foto;
    var mime = "image/jpeg";
    if (foto.indexOf("iVBOR") === 0) mime = "image/png";
    else if (foto.indexOf("R0lGOD") === 0) mime = "image/gif";
    else if (foto.indexOf("UklGR") === 0) mime = "image/webp";
    else if (foto.indexOf("/9j/") === 0) mime = "image/jpeg";
    return "data:" + mime + ";base64," + foto;
  }

  function renderLoading() {
    mainEl.innerHTML =
      '<div class="min-h-screen flex items-center justify-center bg-primary pt-16">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-circle w-8 h-8 text-accent animate-spin" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>' +
      "</div>";
  }

  function renderError(msg) {
    mainEl.innerHTML =
      '<div class="min-h-screen flex flex-col items-center justify-center bg-primary pt-16 gap-4">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-alert-circle text-red-500" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" x2="12" y1="8" y2="12"></line><line x1="12" x2="12.01" y1="16" y2="16"></line></svg>' +
      '<p class="text-secondary text-sm">' + escapeHTML(msg) + "</p>" +
      '<button class="mt-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover">Tentar novamente</button>' +
      "</div>";
  }

  function badgePremium(isPremium) {
    if (isPremium) {
      return '<span class="inline-flex items-center gap-1 rounded-md bg-yellow-500/10 px-2.5 py-0.5 text-xs font-medium text-yellow-500">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-crown" aria-hidden="true"><path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"></path></svg>' +
        "Premium</span>";
    }
    return '<span class="inline-flex items-center gap-1 rounded-md bg-zinc-500/10 px-2.5 py-0.5 text-xs font-medium text-zinc-400">Gratuito</span>';
  }

  function badgeTrial(trialExpired, daysRemaining) {
    if (trialExpired) {
      return '<span class="inline-flex items-center gap-1 rounded-md bg-red-500/10 px-2.5 py-0.5 text-xs font-medium text-red-400">Trial expirado</span>';
    }
    if (daysRemaining !== null && daysRemaining !== undefined && daysRemaining > 0) {
      return '<span class="inline-flex items-center gap-1 rounded-md bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-400">Trial: ' + daysRemaining + " dias restantes</span>";
    }
    return "";
  }

  function renderProfile(user) {
    var initials = (user.nome || "U")
      .split(" ")
      .map(function (w) { return w.charAt(0); })
      .join("")
      .substring(0, 2)
      .toUpperCase();

    mainEl.innerHTML =
      '<div class="min-h-screen bg-primary pt-20 pb-12">' +
      '<div class="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">' +

      /* ── Header do perfil ── */
      '<div class="flex flex-col items-center gap-4 sm:flex-row sm:items-start">' +
        '<div class="flex h-20 w-20 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent text-2xl font-bold">' +
          escapeHTML(initials) +
        "</div>" +
        '<div class="text-center sm:text-left flex-1">' +
          '<h1 class="text-2xl font-bold text-primary">' + escapeHTML(user.nome) + "</h1>" +
          '<p class="mt-1 text-sm text-secondary">' + escapeHTML(user.email) + "</p>" +
          '<div class="mt-2 flex flex-wrap items-center justify-center sm:justify-start gap-2">' +
            badgePremium(user.is_premium) +
            badgeTrial(user.trial_expired, user.trial_days_remaining) +
          "</div>" +
          '<p class="mt-2 text-xs text-muted">Membro desde ' + formatDate(user.created_at) + "</p>" +
          '<p class="text-xs text-muted">' + (user.total_consultas || 0) + " consultas realizadas</p>" +
        "</div>" +
      "</div>" +

      /* ── Grid: Info + Editar ── */
      '<div class="mt-8 grid gap-6 sm:grid-cols-2">' +

        /* Card: Informações */
        '<div class="rounded-xl border border-border bg-secondary p-6">' +
          '<h2 class="text-sm font-semibold text-primary mb-4">Informações da conta</h2>' +
          '<dl class="space-y-3 text-sm">' +
            '<div class="flex justify-between"><dt class="text-muted">Nome</dt><dd class="text-primary font-medium">' + escapeHTML(user.nome) + "</dd></div>" +
            '<div class="flex justify-between"><dt class="text-muted">Email</dt><dd class="text-primary font-medium">' + escapeHTML(user.email) + "</dd></div>" +
            '<div class="flex justify-between"><dt class="text-muted">Status</dt><dd>' + badgePremium(user.is_premium) + "</dd></div>" +
            '<div class="flex justify-between"><dt class="text-muted">Membro desde</dt><dd class="text-primary font-medium">' + formatDate(user.created_at) + "</dd></div>" +
            '<div class="flex justify-between"><dt class="text-muted">Consultas</dt><dd class="text-primary font-medium">' + (user.total_consultas || 0) + "</dd></div>" +
          "</dl>" +
        "</div>" +

        /* Card: Editar perfil */
        '<div class="rounded-xl border border-border bg-secondary p-6">' +
          '<h2 class="text-sm font-semibold text-primary mb-4">Editar perfil</h2>' +
          '<form id="form-editar-perfil" class="space-y-4">' +
            '<div>' +
              '<label for="input-nome" class="block text-xs font-medium text-muted mb-1">Nome</label>' +
              '<input id="input-nome" type="text" value="' + escapeHTML(user.nome) + '" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />' +
            "</div>" +
            '<div>' +
              '<label for="input-email" class="block text-xs font-medium text-muted mb-1">Email</label>' +
              '<input id="input-email" type="email" value="' + escapeHTML(user.email) + '" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />' +
            "</div>" +
            '<button type="submit" id="btn-salvar-perfil" class="w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover">Salvar alterações</button>' +
          "</form>" +
        "</div>" +

      "</div>" +

      /* ── Veículos ── */
      '<div class="mt-8">' +
        '<div class="flex items-center justify-between mb-4">' +
          '<h2 class="text-lg font-semibold text-primary">Meus Veículos</h2>' +
          '<button id="btn-toggle-veiculo" class="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover">+ Adicionar veículo</button>' +
        "</div>" +

        /* Formulário de adicionar veículo (oculto) */
        '<div id="form-veiculo-wrapper" class="hidden mb-6">' +
          '<div class="rounded-xl border border-border bg-secondary p-6">' +
            '<h3 class="text-sm font-semibold text-primary mb-4">Novo veículo</h3>' +
            '<form id="form-add-veiculo" class="grid gap-4 sm:grid-cols-2">' +
              '<div>' +
                '<label for="v-tipo" class="block text-xs font-medium text-muted mb-1">Tipo</label>' +
                '<select id="v-tipo" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent">' +
                  '<option value="">Selecione</option>' +
                  '<option value="carro">Carro</option>' +
                  '<option value="moto">Moto</option>' +
                  '<option value="caminhao">Caminhão</option>' +
                  '<option value="outro">Outro</option>' +
                "</select>" +
              "</div>" +
              '<div>' +
                '<label for="v-marca" class="block text-xs font-medium text-muted mb-1">Marca</label>' +
                '<input id="v-marca" type="text" placeholder="Ex: Volkswagen" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />' +
              "</div>" +
              '<div>' +
                '<label for="v-modelo" class="block text-xs font-medium text-muted mb-1">Modelo</label>' +
                '<input id="v-modelo" type="text" placeholder="Ex: Gol" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />' +
              "</div>" +
              '<div>' +
                '<label for="v-ano" class="block text-xs font-medium text-muted mb-1">Ano fabricação</label>' +
                '<input id="v-ano" type="number" min="1900" max="2099" placeholder="2020" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />' +
              "</div>" +
              '<div>' +
                '<label for="v-ano-compra" class="block text-xs font-medium text-muted mb-1">Ano compra</label>' +
                '<input id="v-ano-compra" type="number" min="1900" max="2099" placeholder="2021" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />' +
              "</div>" +
              '<div>' +
                '<label for="v-km" class="block text-xs font-medium text-muted mb-1">Quilometragem</label>' +
                '<input id="v-km" type="number" min="0" placeholder="50000" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent" />' +
              "</div>" +
              '<div class="sm:col-span-2 flex gap-3">' +
                '<button type="submit" id="btn-salvar-veiculo" class="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover">Salvar veículo</button>' +
                '<button type="button" id="btn-cancelar-veiculo" class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-secondary transition-colors hover:bg-white/5">Cancelar</button>' +
              "</div>" +
            "</form>" +
          "</div>" +
        "</div>" +

        '<div id="veiculos-list" class="grid gap-4 sm:grid-cols-2"></div>' +
      "</div>" +

      /* ── Sair ── */
      '<div class="mt-8 text-center">' +
        '<button id="btn-logout" class="rounded-lg border border-red-500/30 px-4 py-2 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/10">Sair da conta</button>' +
      "</div>" +

      "</div></div>";
  }

  function renderVeiculos(veiculos) {
    var container = document.getElementById("veiculos-list");
    if (!container) return;

    if (!veiculos || veiculos.length === 0) {
      container.innerHTML =
        '<div class="sm:col-span-2 rounded-xl border border-dashed border-border bg-secondary p-8 text-center">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-car mx-auto text-muted mb-3" aria-hidden="true"><path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"></path><circle cx="7" cy="17" r="2"></circle><path d="M9 17h6"></path><circle cx="17" cy="17" r="2"></path></svg>' +
        '<p class="text-sm text-muted">Nenhum veículo cadastrado</p>' +
        '<p class="mt-1 text-xs text-muted">Adicione seu primeiro veículo para acompanhar manutenções e valores.</p>' +
        "</div>";
      return;
    }

    var html = "";
    for (var i = 0; i < veiculos.length; i++) {
      var v = veiculos[i];
      var tipoLabel = { carro: "Carro", moto: "Moto", caminhao: "Caminhão", outro: "Outro" }[v.tipo] || v.tipo || "—";
      var foto = fotoSrc(v);
      var iconHtml = foto
        ? '<img src="' + foto + '" alt="" class="h-10 w-10 shrink-0 rounded-lg object-cover" />'
        : '<div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-car" aria-hidden="true"><path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"></path><circle cx="7" cy="17" r="2"></circle><path d="M9 17h6"></path><circle cx="17" cy="17" r="2"></circle></svg>' +
          '</div>';
      html +=
        '<div class="rounded-xl border border-border bg-secondary p-5 transition-all duration-200 hover:border-border-hover hover:shadow-lg hover:shadow-[0_8px_30px_-4px_rgba(91,141,239,0.06)] hover:-translate-y-0.5">' +
          '<div class="flex items-start justify-between">' +
            '<div class="flex items-center gap-3">' +
              iconHtml +
              '<div>' +
                '<h3 class="text-sm font-semibold text-primary">' + escapeHTML(v.marca) + " " + escapeHTML(v.modelo) + "</h3>" +
                '<p class="text-xs text-muted">' + tipoLabel + " · " + (v.ano_fabricacao || "—") + "</p>" +
              "</div>" +
            "</div>" +
            '<div class="flex items-center gap-1">' +
              '<button class="btn-upload-foto text-muted hover:text-accent transition-colors p-1 rounded-lg" data-id="' + v.id + '" title="Alterar foto do veículo">' +
                '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-camera" aria-hidden="true"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"></path><circle cx="12" cy="13" r="3"></circle></svg>' +
              "</button>" +
              '<button class="btn-delete-veiculo text-muted hover:text-red-400 transition-colors p-1 rounded-lg hover:bg-red-500/10" data-id="' + v.id + '" title="Excluir veículo">' +
                '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash-2" aria-hidden="true"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path><line x1="10" x2="10" y1="11" y2="17"></line><line x1="14" x2="14" y1="11" y2="17"></line></svg>' +
              "</button>" +
            "</div>" +
          "</div>" +
          '<div class="mt-4 grid grid-cols-3 gap-3 text-center">' +
            '<div>' +
              '<p class="text-xs text-muted">Ano</p>' +
              '<p class="text-sm font-medium text-primary">' + (v.ano_fabricacao || "—") + "</p>" +
            "</div>" +
            '<div>' +
              '<p class="text-xs text-muted">Quilometragem</p>' +
              '<p class="text-sm font-medium text-primary">' + (v.quilometragem ? Number(v.quilometragem).toLocaleString("pt-BR") + " km" : "—") + "</p>" +
            "</div>" +
            '<div>' +
              '<p class="text-xs text-muted">Valor FIPE</p>' +
              '<p class="text-sm font-medium text-primary">' + formatCurrency(v.fipe_valor) + "</p>" +
            "</div>" +
            "</div>" +
      "</div>";
    }
    container.innerHTML = html;

    container.querySelectorAll(".btn-delete-veiculo").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = this.dataset.id;
        if (confirm("Tem certeza que deseja excluir este veículo?")) {
          deleteVeiculo(id);
        }
      });
    });

    container.querySelectorAll(".btn-upload-foto").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openFotoPicker(this.dataset.id);
      });
    });
  }

  var fotoTargetId = null;

  function openFotoPicker(id) {
    fotoTargetId = id;
    var input = document.getElementById("veiculo-foto-input");
    if (input) input.click();
  }

  function ensureFotoInput() {
    if (document.getElementById("veiculo-foto-input")) return;
    var input = document.createElement("input");
    input.type = "file";
    input.id = "veiculo-foto-input";
    input.accept = "image/png,image/jpeg,image/gif,image/webp";
    input.className = "hidden";
    document.body.appendChild(input);
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file || !fotoTargetId) return;
      if (file.size > 8 * 1024 * 1024) {
        toast("Imagem muito grande. Máximo 8 MB.", "error");
        input.value = "";
        return;
      }
      var reader = new FileReader();
      reader.onload = function (ev) {
        uploadVeiculoFoto(fotoTargetId, ev.target.result)
          .then(function () {
            toast("Foto do veículo atualizada!", "success");
            loadVeiculos();
          })
          .catch(function (err) {
            toast(err.message || "Erro ao enviar foto.", "error");
          })
          .finally(function () {
            input.value = "";
            fotoTargetId = null;
          });
      };
      reader.readAsDataURL(file);
    });
  }

  function deleteVeiculo(id) {
    window.api
      .delete("/api/veiculos/" + id)
      .then(function () {
        toast("Veículo excluído com sucesso.", "success");
        loadVeiculos();
      })
      .catch(function (err) {
        toast(err.message || "Erro ao excluir veículo.", "error");
      });
  }

  function editVeiculo(id, data) {
    return window.api.put("/api/veiculos/" + id, data);
  }

  function uploadVeiculoFoto(id, base64) {
    return window.api.post("/api/veiculos/" + id + "/foto", { foto: base64 });
  }

  function deleteAccount() {
    if (!confirm("Tem certeza que deseja excluir sua conta? Esta ação é irreversível.")) return;
    window.api.delete("/api/user").then(function () {
      window.auth.logout();
    }).catch(function (err) {
      toast(err.message || "Erro ao excluir conta.", "error");
    });
  }

  function saveUserLocation(uf) {
    return window.api.post("/api/user/location", { uf: uf || "" });
  }

  function loadVeiculos() {
    ensureFotoInput();
    window.api
      .get("/api/veiculos")
      .then(function (res) {
        renderVeiculos(res.veiculos || []);
      })
      .catch(function () {
        var container = document.getElementById("veiculos-list");
        if (container) {
          container.innerHTML =
            '<p class="sm:col-span-2 text-sm text-muted text-center py-8">Erro ao carregar veículos.</p>';
        }
      });
  }

  function handleEditarPerfil(e) {
    e.preventDefault();
    var nome = document.getElementById("input-nome");
    var email = document.getElementById("input-email");
    var btn = document.getElementById("btn-salvar-perfil");

    var payload = {
      nome: nome ? nome.value.trim() : "",
      email: email ? email.value.trim() : "",
    };

    if (!payload.nome || !payload.email) {
      toast("Preencha nome e email.", "error");
      return;
    }

    btn.disabled = true;
    btn.textContent = "Salvando...";

    window.api
      .put("/api/user", payload)
      .then(function (res) {
        toast("Perfil atualizado com sucesso!", "success");
        if (res.success) {
          var safeUser = {
            id: res.id,
            nome: res.nome,
            email: res.email,
            is_premium: res.is_premium,
            plano: res.plano,
            avatar_url: res.avatar_url,
            created_at: res.created_at
          };
          auth.setAuth(auth.getToken(), safeUser);
        }
      })
      .catch(function (err) {
        toast(err.message || "Erro ao atualizar perfil.", "error");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Salvar alterações";
      });
  }

  function handleAddVeiculo(e) {
    e.preventDefault();
    var tipo = document.getElementById("v-tipo");
    var marca = document.getElementById("v-marca");
    var modelo = document.getElementById("v-modelo");
    var ano = document.getElementById("v-ano");
    var anoCompra = document.getElementById("v-ano-compra");
    var km = document.getElementById("v-km");
    var btn = document.getElementById("btn-salvar-veiculo");

    var payload = {
      tipo: tipo ? tipo.value : "",
      marca: marca ? marca.value.trim() : "",
      modelo: modelo ? modelo.value.trim() : "",
      ano_fabricacao: ano ? (ano.value || null) : null,
      ano_compra: anoCompra ? (anoCompra.value || null) : null,
      quilometragem: km ? (km.value || null) : null,
    };

    if (!payload.marca || !payload.modelo) {
      toast("Preencha marca e modelo.", "error");
      return;
    }

    btn.disabled = true;
    btn.textContent = "Salvando...";

    window.api
      .post("/api/veiculos", payload)
      .then(function () {
        toast("Veículo adicionado com sucesso!", "success");
        e.target.reset();
        document.getElementById("form-veiculo-wrapper").classList.add("hidden");
        loadVeiculos();
      })
      .catch(function (err) {
        toast(err.message || "Erro ao adicionar veículo.", "error");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Salvar veículo";
      });
  }

  function bindEvents() {
    var formPerfil = document.getElementById("form-editar-perfil");
    if (formPerfil) formPerfil.addEventListener("submit", handleEditarPerfil);

    var formVeiculo = document.getElementById("form-add-veiculo");
    if (formVeiculo) formVeiculo.addEventListener("submit", handleAddVeiculo);

    var btnToggle = document.getElementById("btn-toggle-veiculo");
    var wrapper = document.getElementById("form-veiculo-wrapper");
    if (btnToggle && wrapper) {
      btnToggle.addEventListener("click", function () {
        wrapper.classList.toggle("hidden");
      });
    }

    var btnCancelar = document.getElementById("btn-cancelar-veiculo");
    if (btnCancelar && wrapper) {
      btnCancelar.addEventListener("click", function () {
        wrapper.classList.add("hidden");
      });
    }

    var btnLogout = document.getElementById("btn-logout");
    if (btnLogout) {
      btnLogout.addEventListener("click", function () {
        auth.logout();
      });
    }
  }

  function init() {
    if (!auth.requireAuth()) return;

    mainEl = document.querySelector("main");
    if (!mainEl) return;

    renderLoading();

    window.api
      .get("/api/user")
      .then(function (user) {
        renderProfile(user);
        bindEvents();
        ensureFotoInput();
        renderVeiculos(user.veiculos || []);
      })
      .catch(function (err) {
        if (err.status === 401 || err.status === 403) {
          auth.logout();
          return;
        }
        renderError(err.message || "Erro ao carregar perfil.");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
