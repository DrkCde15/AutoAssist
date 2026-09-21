(function () {
  "use strict";

  var MODAL_ID = "premium-paywall-modal";

  var MODAL_HTML =
    '<div id="' + MODAL_ID + '" class="fixed inset-0 z-[1400] flex items-center justify-center p-4" style="display:none">' +
      '<div class="fixed inset-0 bg-black/70 backdrop-blur-sm" data-premium-close></div>' +
      '<div class="relative w-full max-w-md rounded-2xl border border-border bg-secondary p-8 shadow-2xl text-center">' +
        '<button data-premium-close class="absolute top-4 right-4 text-muted hover:text-primary transition-colors" aria-label="Fechar">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
        '</button>' +
        '<div class="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-accent/10">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-accent"><path d="M15.914 4a1.5 1.5 0 0 0-2.474-1.561l-9 9A1.5 1.5 0 0 0 5.5 14h4.002a.5.5 0 0 1 .471.666L8.086 20a1.5 1.5 0 0 0 2.475 1.56l9-9A1.5 1.5 0 0 0 18.5 10h-3.997a.5.5 0 0 1-.472-.667z"/></svg>' +
        '</div>' +
        '<h2 class="text-xl font-bold text-primary mb-2">Recurso Premium</h2>' +
        '<p class="text-sm text-secondary mb-6 leading-relaxed">Este recurso esta disponivel apenas para assinantes Premium. Assine e tenha acesso ilimitado a todas as funcionalidades.</p>' +
        '<div class="flex flex-col gap-3">' +
          '<button id="premium-modal-checkout-btn" class="inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-all duration-200 bg-accent text-white border border-accent hover:bg-accent-hover hover:shadow-glow px-5 py-2.5 text-sm w-full cursor-pointer">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15.914 4a1.5 1.5 0 0 0-2.474-1.561l-9 9A1.5 1.5 0 0 0 5.5 14h4.002a.5.5 0 0 1 .471.666L8.086 20a1.5 1.5 0 0 0 2.475 1.56l9-9A1.5 1.5 0 0 0 18.5 10h-3.997a.5.5 0 0 1-.472-.667z"/></svg>' +
            'Assinar Premium' +
          '</button>' +
          '<a href="/planos" class="inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-all duration-200 bg-transparent text-primary border border-border hover:bg-secondary hover:border-border-hover px-5 py-2.5 text-sm w-full">' +
            'Ver planos' +
          '</a>' +
        '</div>' +
      '</div>' +
    '</div>';

  function injectModal() {
    if (document.getElementById(MODAL_ID)) return;
    var wrapper = document.createElement("div");
    wrapper.innerHTML = MODAL_HTML;
    document.body.appendChild(wrapper.firstChild);

    var modal = document.getElementById(MODAL_ID);
    var closeEls = modal.querySelectorAll("[data-premium-close]");
    closeEls.forEach(function (el) {
      el.addEventListener("click", function () {
        window.premiumModal.hide();
      });
    });

    modal.addEventListener("click", function (e) {
      if (e.target === modal || e.target === modal.firstElementChild) {
        window.premiumModal.hide();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && modal.style.display !== "none") {
        window.premiumModal.hide();
      }
    });

    var checkoutBtn = document.getElementById("premium-modal-checkout-btn");
    if (checkoutBtn) {
      checkoutBtn.addEventListener("click", function () {
        if (window.auth && !window.auth.isAuthenticated()) {
          window.location.href = "/login?redirect=" + encodeURIComponent(window.location.pathname);
          return;
        }
        if (window.payment && window.payment.goToCheckout) {
          checkoutBtn.disabled = true;
          checkoutBtn.textContent = "Redirecionando...";
          window.payment.goToCheckout().catch(function (err) {
            checkoutBtn.disabled = false;
            checkoutBtn.textContent = "Assinar Premium";
            alert(err.message || "Erro ao iniciar pagamento.");
          });
        } else {
          window.location.href = "/planos";
        }
      });
    }
  }

  function waitForPayment(cb) {
    if (window.payment) return cb();
    var tries = 0;
    var iv = setInterval(function () {
      tries++;
      if (window.payment || tries > 50) {
        clearInterval(iv);
        cb();
      }
    }, 100);
  }

  window.premiumModal = {
    show: function () {
      injectModal();
      var modal = document.getElementById(MODAL_ID);
      if (modal) {
        modal.style.display = "";
        document.body.style.overflow = "hidden";
        var checkoutBtn = document.getElementById("premium-modal-checkout-btn");
        if (checkoutBtn) {
          checkoutBtn.disabled = false;
          checkoutBtn.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15.914 4a1.5 1.5 0 0 0-2.474-1.561l-9 9A1.5 1.5 0 0 0 5.5 14h4.002a.5.5 0 0 1 .471.666L8.086 20a1.5 1.5 0 0 0 2.475 1.56l9-9A1.5 1.5 0 0 0 18.5 10h-3.997a.5.5 0 0 1-.472-.667z"/></svg>' +
            "Assinar Premium";
        }
      }
    },
    hide: function () {
      var modal = document.getElementById(MODAL_ID);
      if (modal) {
        modal.style.display = "none";
        document.body.style.overflow = "";
      }
    },
    requirePremium: function () {
      if (window.auth && window.auth.isAuthenticated() && !window.auth.isPremium()) {
        this.show();
        return false;
      }
      return true;
    },
  };

  injectModal();
})();
