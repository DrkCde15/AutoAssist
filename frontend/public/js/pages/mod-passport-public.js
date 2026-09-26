/**
 * mod-passport-public.js — Viewer público do Mod Passport (?token=).
 * Sem login: GET /api/public/mod-passport/<token> + link p/ PDF.
 */
(function () {
  "use strict";

  function escapeHTML(str) {
    if (str === null || str === undefined) return "—";
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(String(str)));
    return div.innerHTML;
  }

  function fotoSrc(foto) {
    if (!foto) return "";
    if (foto.indexOf("data:") === 0) return foto;
    if (foto.indexOf("http://") === 0 || foto.indexOf("https://") === 0) return foto;
    if (foto.indexOf("/api/") === 0) return foto;
    var mime = "image/jpeg";
    if (foto.indexOf("iVBOR") === 0) mime = "image/png";
    else if (foto.indexOf("R0lGOD") === 0) mime = "image/gif";
    else if (foto.indexOf("UklGR") === 0) mime = "image/webp";
    else if (foto.indexOf("/9j/") === 0) mime = "image/jpeg";
    return "data:" + mime + ";base64," + foto;
  }

  function showError() {
    document.getElementById("mp-title").textContent = "Mod Passport";
    document.getElementById("mp-error").classList.remove("hidden");
  }

  document.addEventListener("DOMContentLoaded", function () {
    var token = null;
    try {
      token = new URLSearchParams(window.location.search).get("token");
    } catch (e) { token = null; }
    if (!token) { showError(); return; }

    fetch("/api/public/mod-passport/" + encodeURIComponent(token))
      .then(function (res) {
        if (!res.ok) throw new Error("not found");
        return res.json();
      })
      .then(function (data) {
        var v = data.veiculo || {};
        var title = [v.marca, v.modelo, v.ano_fabricacao].filter(Boolean).join(" ");
        document.getElementById("mp-title").textContent = title || "Mod Passport";

        var foto = fotoSrc(v.foto_base64);
        var mods = data.modificacoes || [];
        var modsHtml = mods.length
          ? mods.map(function (m) {
              var nome = escapeHTML(m.nome || m.descricao || m.item || "Modificação");
              var detalhe = escapeHTML(m.detalhe || m.valor || m.categoria || "");
              return '<li class="flex items-center justify-between gap-3 rounded-lg border border-border bg-secondary px-4 py-3">' +
                '<span class="text-sm font-medium text-primary">' + nome + "</span>" +
                (detalhe ? '<span class="text-xs text-muted">' + detalhe + "</span>" : "") +
                "</li>";
            }).join("")
          : '<li class="text-sm text-muted">Nenhuma modificação registrada.</li>';

        document.getElementById("mp-content").innerHTML =
          (foto ? '<img src="' + foto + '" alt="" class="mb-6 h-56 w-full rounded-xl object-cover border border-border" />' : "") +
          '<div class="grid gap-4 sm:grid-cols-2 mb-6">' +
            '<div class="rounded-xl border border-border bg-secondary p-5">' +
              '<p class="text-xs uppercase tracking-wider text-muted">Valor FIPE</p>' +
              '<p class="mt-1 text-xl font-bold text-primary">' + escapeHTML(data.fipe_valor) + "</p>" +
            "</div>" +
            '<div class="rounded-xl border border-accent/30 bg-accent/5 p-5">' +
              '<p class="text-xs uppercase tracking-wider text-muted">Valor estimado</p>' +
              '<p class="mt-1 text-xl font-bold text-accent">' + escapeHTML(data.valor_estimado) + "</p>" +
            "</div>" +
          "</div>" +
          '<h2 class="text-sm font-semibold text-primary mb-3">Modificações</h2>' +
          '<ul class="space-y-2">' + modsHtml + "</ul>" +
          '<p class="mt-6 text-xs text-muted">' + escapeHTML(data.aviso || "") + "</p>" +
          '<a href="/api/public/mod-passport/' + encodeURIComponent(token) + '/pdf" class="mt-4 inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover">Baixar PDF</a>';
      })
      .catch(function () { showError(); });
  });
})();
