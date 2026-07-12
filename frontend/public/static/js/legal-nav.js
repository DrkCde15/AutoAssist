(function () {
  "use strict";

  function renderPublic(nav) {
    nav.innerHTML = `
      <a href="index.html">In&iacute;cio</a>
      <a href="login.html">Entrar</a>
      <a href="cadastro.html">Criar conta</a>
    `;
  }

  function renderAuthenticated(nav) {
    nav.innerHTML = `
      <a href="index.html">In&iacute;cio</a>
      <a href="chat.html">Chat</a>
      <a href="perfil.html">Perfil</a>
      <a href="#" data-aa-logout>Sair</a>
    `;
  }

  document.addEventListener("DOMContentLoaded", async () => {
    const nav = document.querySelector("[data-legal-nav]");
    if (!nav || typeof Auth === "undefined") return;

    nav.addEventListener("click", (event) => {
      const logoutLink = event.target.closest("[data-aa-logout]");
      if (!logoutLink) return;
      event.preventDefault();
      Auth.logout();
    });

    if (!Auth.isAuthenticated()) {
      renderPublic(nav);
      return;
    }

    renderAuthenticated(nav);

    try {
      const user = await Auth.syncUser({ redirectOnInvalid: false });
      if (user || Auth.isAuthenticated()) {
        renderAuthenticated(nav);
      } else {
        renderPublic(nav);
      }
    } catch {
      if (!Auth.isAuthenticated()) renderPublic(nav);
    }
  });
})();
