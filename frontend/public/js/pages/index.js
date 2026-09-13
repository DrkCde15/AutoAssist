(function() {
  var elDiag = document.getElementById("stat-diagnosticos");
  var elVeic = document.getElementById("stat-veiculos");
  var elUsers = document.getElementById("stat-usuarios");
  if (!elDiag && !elVeic && !elUsers) return;

  fetch("/api/public/stats")
    .then(function(r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function(d) {
      console.log("[stats]", d);
      if (d.diagnosticos != null && elDiag) elDiag.textContent = d.diagnosticos.toLocaleString("pt-BR");
      if (d.veiculos != null && elVeic) elVeic.textContent = d.veiculos.toLocaleString("pt-BR");
      if (d.usuarios != null && elUsers) elUsers.textContent = d.usuarios.toLocaleString("pt-BR");
    })
    .catch(function(e) {
      console.warn("[stats] Erro ao buscar estatísticas:", e);
    });
})();
