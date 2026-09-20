/**
 * auth.js — JWT + localStorage (substitui frontend/src/lib/auth.tsx + auth-client.ts)
 */
(function () {
  "use strict";

  var TOKEN_KEY = "autoassist_access_token";
  var USER_KEY = "autoassist_user";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }

  function getStoredUser() {
    try {
      var raw = localStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function storeUser(user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function clearAuth() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  window.auth = {
    getToken: getToken,
    getUser: getStoredUser,
    isAuthenticated: function () {
      return !!getToken();
    },
    isPremium: function () {
      var u = getStoredUser();
      return u && u.is_premium;
    },
    setAuth: function (token, user) {
      setToken(token);
      storeUser(user);
    },
    clearAuth: clearAuth,
    logout: function () {
      clearAuth();
      window.location.href = "/login";
    },
    requireAuth: function () {
      if (!getToken()) {
        window.location.href = "/login?redirect=" + encodeURIComponent(window.location.pathname);
        return false;
      }
      return true;
    },
    requirePremium: function () {
      if (!getToken()) {
        window.location.href = "/login?redirect=" + encodeURIComponent(window.location.pathname);
        return false;
      }
      var u = getStoredUser();
      if (u && !u.is_premium) {
        if (window.premiumModal) {
          window.premiumModal.show();
          return false;
        }
        window.location.href = "/planos";
        return false;
      }
      return true;
    },
    // Login via API
    login: async function (email, password, turnstileToken) {
      var payload = { email: email, password: password };
      if (turnstileToken) payload.turnstile_token = turnstileToken;
      var res = await window.api.post("/api/login", payload);

      if (res.two_factor_required) {
        return { two_factor_required: true, pending_token: res.pending_token };
      }

      if (res.access_token) {
        setToken(res.access_token);
      }
      if (res.user) {
        storeUser(res.user);
      }
      return {};
    },
    // Register via API
    register: async function (data) {
      var res = await window.api.post("/api/cadastro", data);
      if (res.access_token) {
        setToken(res.access_token);
      }
      if (res.user) {
        storeUser(res.user);
      }
      return res;
    },
    // Authenticated fetch
    authFetch: async function (input, init) {
      var token = getToken();
      var headers = new Headers((init && init.headers) || {});
      if (token) {
        headers.set("Authorization", "Bearer " + token);
      }
      var opts = Object.assign({}, init || {}, { headers: headers, credentials: "include" });
      return fetch(window.API_URL + input, opts);
    },
  };
})();
