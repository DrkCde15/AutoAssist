/**
 * planos-checkout.js — Lógica do botão "Assinar Premium" na página de planos.
 * Lida com autenticação e redirecionamento para checkout Cakto.
 */
(function () {
  "use strict";

  var btn = document.getElementById("premiumCheckoutBtn");
  if (!btn) return;

  var loginUrl = "/login?redirect=" + encodeURIComponent("/planos");

  function setup() {
    if (!window.payment || !window.auth) return;

    btn.addEventListener("click", function () {
      if (!window.auth.isAuthenticated()) {
        window.location.href = loginUrl;
        return;
      }
      btn.disabled = true;
      btn.textContent = "Redirecionando...";
      window.payment.goToCheckout().catch(function (err) {
        btn.disabled = false;
        btn.textContent = "Assinar Premium";
        alert(err.message || "Erro ao iniciar pagamento.");
      });
    });
  }

  // Try immediately, then retry until payment + auth load
  setup();
  var tries = 0;
  var iv = setInterval(function () {
    tries++;
    if (window.payment && window.auth) {
      clearInterval(iv);
      setup();
    }
    if (tries > 50) {
      clearInterval(iv);
      btn.addEventListener("click", function () {
        window.location.href = loginUrl;
      });
    }
  }, 100);
})();
