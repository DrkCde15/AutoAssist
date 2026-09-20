(function () {
  "use strict";

  var B2B_PLANS = {
    trial:   { label: "Trial gratuito", amount: 0,   requests: 100 },
    pro_1k:  { label: "Pro 1k",         amount: 99,  requests: 1000 },
    pro_5k:  { label: "Pro 5k",         amount: 399, requests: 5000 },
    pro_20k: { label: "Pro 20k",        amount: 999, requests: 20000 },
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (!window.auth || !window.auth.requireAuth()) return;

    var form = document.querySelector("form");
    if (!form) return;

    var nameInput = form.querySelector('input[type="text"]');
    var planBtn = form.querySelector('[role="combobox"]');
    var submitBtn = form.querySelector('button[type="submit"], button:not([type])');
    var planSpan = planBtn ? planBtn.querySelector("span") : null;

    var selectedPlan = "trial";
    var dropdownOpen = false;
    var dropdown = null;

    function createDropdown() {
      if (dropdown) { dropdown.remove(); dropdown = null; }
      dropdown = document.createElement("div");
      dropdown.className = "absolute z-50 mt-1 w-full rounded-xl border border-border bg-primary shadow-xl max-h-60 overflow-y-auto";
      Object.keys(B2B_PLANS).forEach(function (key) {
        var p = B2B_PLANS[key];
        var item = document.createElement("div");
        item.className = "flex items-center justify-between px-3 py-2.5 text-sm cursor-pointer transition-colors hover:bg-white/5" + (key === selectedPlan ? " text-accent" : " text-primary");
        var price = p.amount === 0 ? "Gratis" : "R$ " + p.amount + "/mes";
        item.innerHTML = '<span>' + p.label + '</span><span class="text-xs text-muted">' + price + "</span>";
        item.addEventListener("click", function () {
          selectedPlan = key;
          if (planSpan) planSpan.textContent = p.label;
          closeDropdown();
          updateSubmitButton();
        });
        dropdown.appendChild(item);
      });
      planBtn.parentElement.appendChild(dropdown);
    }

    function openDropdown() {
      createDropdown();
      dropdownOpen = true;
      if (planBtn) planBtn.setAttribute("aria-expanded", "true");
    }

    function closeDropdown() {
      if (dropdown) { dropdown.remove(); dropdown = null; }
      dropdownOpen = false;
      if (planBtn) planBtn.setAttribute("aria-expanded", "false");
    }

    function updateSubmitButton() {
      if (!submitBtn) return;
      var p = B2B_PLANS[selectedPlan];
      if (p && p.amount > 0) {
        submitBtn.textContent = "Assinar " + p.label + " - R$ " + p.amount;
      } else {
        submitBtn.textContent = "Criar API Key";
      }
    }

    if (planBtn) {
      planBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (dropdownOpen) closeDropdown();
        else openDropdown();
      });
    }

    document.addEventListener("click", function (e) {
      if (dropdownOpen && dropdown && !dropdown.contains(e.target) && !planBtn.contains(e.target)) {
        closeDropdown();
      }
    });

    if (!planSpan) {
      var span = planBtn ? planBtn.querySelector("span") : null;
      if (span) planSpan = span;
    }

    updateSubmitButton();

    if (!form.hasAttribute("data-b2b-bound")) {
      form.setAttribute("data-b2b-bound", "true");
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!window.payment) {
          alert("Modulo de pagamento nao carregado.");
          return;
        }

        var nome = nameInput ? nameInput.value.trim() : "";
        var p = B2B_PLANS[selectedPlan];

        if (!p) {
          alert("Selecione um plano.");
          return;
        }

        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = "Processando...";
        }

        if (p.amount === 0) {
          window.payment.b2bCreateKey(selectedPlan, nome)
            .then(function (res) {
              var data = res.data || res;
              if (data.api_key) {
                alert("API Key criada!\n\nChave: " + data.api_key);
              }
              if (submitBtn) {
                submitBtn.disabled = false;
                updateSubmitButton();
              }
            })
            .catch(function (err) {
              alert(err.message || "Erro ao criar API key.");
              if (submitBtn) {
                submitBtn.disabled = false;
                updateSubmitButton();
              }
            });
        } else {
          window.payment.goToB2bCheckout(selectedPlan, nome)
            .catch(function (err) {
              alert(err.message || "Erro ao iniciar checkout.");
              if (submitBtn) {
                submitBtn.disabled = false;
                updateSubmitButton();
              }
            });
        }
      });
    }
  });
})();
