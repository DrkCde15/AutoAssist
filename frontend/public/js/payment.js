(function () {
  "use strict";

  var api = window.api;

  function requireAuth() {
    return !!(window.auth && window.auth.isAuthenticated());
  }

  function redirect(url) {
    if (url) window.location.href = url;
  }

  var payment = {
    createPreference: function (opts) {
      if (!requireAuth()) return Promise.reject(new Error("Auth required"));
      return api.post("/api/pay/preference", opts || {});
    },

    confirmPayment: function () {
      if (!requireAuth()) return Promise.reject(new Error("Auth required"));
      return api.post("/api/pay/confirm", {});
    },

    listMethods: function () {
      if (!requireAuth()) return Promise.reject(new Error("Auth required"));
      return api.get("/pagamentos/metodos");
    },

    checkout: function (method, opts) {
      if (!requireAuth()) return Promise.reject(new Error("Auth required"));
      var url = method
        ? "/pagamentos/checkout/" + encodeURIComponent(method)
        : "/pagamentos/checkout";
      return api.post(url, opts || {});
    },

    checkoutPix: function (opts) {
      return this.checkout("pix", opts);
    },

    checkoutBoleto: function (opts) {
      return this.checkout("boleto", opts);
    },

    checkoutCartaoCredito: function (opts) {
      return this.checkout("cartao_credito", opts);
    },

    checkoutPicPay: function (opts) {
      return this.checkout("picpay", opts);
    },

    checkoutApplePay: function (opts) {
      return this.checkout("apple_pay", opts);
    },

    checkoutGooglePay: function (opts) {
      return this.checkout("google_pay", opts);
    },

    b2bCheckout: function (plan, nome) {
      if (!requireAuth()) return Promise.reject(new Error("Auth required"));
      return api.post("/api/b2b/self-serve/checkout", {
        plan: plan || "trial",
        nome: nome || "",
      });
    },

    b2bCreateKey: function (plan, nome) {
      if (!requireAuth()) return Promise.reject(new Error("Auth required"));
      return api.post("/api/b2b/self-serve/keys", {
        plan: plan || "trial",
        nome: nome || "",
      });
    },

    goToCheckout: function (method, opts) {
      var self = this;
      var fn = method ? self.checkout.bind(self, method) : self.createPreference.bind(self);
      return fn(opts || {}).then(function (res) {
        var data = res.data || res;
        var url = data.checkout_url;
        if (url) redirect(url);
        return data;
      });
    },

    goToB2bCheckout: function (plan, nome) {
      return this.b2bCheckout(plan, nome).then(function (res) {
        var data = res.data || res;
        var url = data.checkout_url;
        if (url) redirect(url);
        return data;
      });
    },
  };

  window.payment = payment;
})();
