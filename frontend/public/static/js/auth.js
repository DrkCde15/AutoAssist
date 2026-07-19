/**
 * AutoAssist — Módulo de Autenticação
 *
 * Responsabilidades:
 *  - Usar cookies HttpOnly como sessao principal e aceitar tokens legados.
 *  - Fornecer Auth.authenticatedFetch() que envia CSRF/cookies automaticamente
 *    e renova a sessao silenciosamente quando ela expira (401).
 *  - Expor Auth.login(), Auth.logout(), Auth.isAuthenticated().
 *  - Processar o retorno de OAuth2 (Google) sem expor tokens na URL.
 */
const Auth = (() => {
  const KEYS = {
    ACCESS: "autoassist_access_token",
    REFRESH: "autoassist_refresh_token",
    USER: "autoassist_user",
    VEHICLES: "autoassist_veiculos_cache",
    USER_SYNC: "autoassist_user_sync_cache",
  };

  // ─── Cache de Sessão (Otimização) ──────────────────────────────────────────
  const Cache = {
    set: (key, data) => sessionStorage.setItem(key, JSON.stringify(data)),
    get: (key) => {
      try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; }
    },
    remove: (key) => sessionStorage.removeItem(key),
    clear: () => {
      sessionStorage.removeItem(KEYS.VEHICLES);
      sessionStorage.removeItem(KEYS.USER_SYNC);
    }
  };
  const USER_SYNC_TTL_MS = 30000;
  let refreshPromise = null;
  let invalidSessionHandled = false;

  // ─── Erro de rede / backend indisponível ──────────────────────────────────
  class AuthNetworkError extends Error {
    constructor(message) {
      super(message || "Erro de conexao com o servidor.");
      this.name = "AuthNetworkError";
      this.isNetworkError = true;
    }
  }

  function isNetworkError(err) {
    return !!(err && (err.isNetworkError || err.name === "AuthNetworkError"));
  }

  // ─── Banner de "serviço inicializando" ────────────────────────────────────
  function showBackendBanner(message) {
    if (typeof document === "undefined") return;
    const root = document.body || document.documentElement;
    if (!root) return;
    let el = document.getElementById("autoassist-backend-banner");
    if (!el) {
      el = document.createElement("div");
      el.id = "autoassist-backend-banner";
      el.setAttribute("role", "status");
      el.style.cssText =
        "position:fixed;top:0;left:0;right:0;z-index:10001;" +
        "background:linear-gradient(135deg,#f59e0b,#b45309);color:#1a1206;" +
        "font:600 13px/1.4 Inter,system-ui,sans-serif;text-align:center;" +
        "padding:10px 16px;box-shadow:0 4px 18px rgba(0,0,0,.35);";
      root.appendChild(el);
    }
    el.textContent = message || "Servico inicializando, aguarde alguns instantes...";
    el.style.display = "block";
    ensureRecovery();
  }

  let _recoveryTimer = null;

  function hideBackendBanner() {
    const el = document.getElementById("autoassist-backend-banner");
    if (el) el.style.display = "none";
    if (_recoveryTimer) {
      clearInterval(_recoveryTimer);
      _recoveryTimer = null;
    }
  }

  // Quando o backend está em cold start, sonda /health e recarrega a página
  // automaticamente assim que o serviço voltar, evitando que o usuário fique
  // preso em uma tela que "não funciona".
  function ensureRecovery() {
    if (_recoveryTimer) return;
    _recoveryTimer = setInterval(async () => {
      try {
        const res = await fetch(`${CONFIG.API_URL}/health`, { credentials: "include" });
        if (res) {
          clearInterval(_recoveryTimer);
          _recoveryTimer = null;
          hideBackendBanner();
          window.location.reload();
        }
      } catch {
        // Ainda indisponível: continua sondando.
      }
    }, 5000);
  }

  // ─── Persistência ─────────────────────────────────────────────────────────

  function saveSession(accessToken, refreshToken, user, options = {}) {
    invalidSessionHandled = false;
    if (accessToken) localStorage.setItem(KEYS.ACCESS, accessToken);
    if (refreshToken) localStorage.setItem(KEYS.REFRESH, refreshToken);
    if (user) {
      localStorage.setItem(KEYS.USER, JSON.stringify(user));
      Cache.set(KEYS.USER_SYNC, { ts: Date.now(), data: user });
    }
  }

  function clearSession() {
    console.warn("[Auth] clearSession() chamado");
    Object.values(KEYS).forEach((k) => localStorage.removeItem(k));
    Cache.clear();
  }

  async function syncGuestHistory() {
    try {
      const guestHistoryKeys = [
        "autoassist_guest_chat_history_cache_v1",
        "autoassist_guest_chat_history",
      ];
      const items = [];

      guestHistoryKeys.forEach((key) => {
        const cached = localStorage.getItem(key);
        if (!cached) return;
        try {
          const parsed = JSON.parse(cached);
          const parsedItems = Array.isArray(parsed)
            ? parsed
            : (Array.isArray(parsed?.items) ? parsed.items : []);
          parsedItems.forEach((item) => items.push(item));
        } catch {
          // Cache antigo ou corrompido: ignora sem apagar para nao perder historico.
        }
      });

      if (!items.length) return;

      const res = await authenticatedFetch("/api/chat/sync_guest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chats: items }),
        redirectOnInvalid: false,
      });

      if (res.ok) {
        guestHistoryKeys.forEach((key) => localStorage.removeItem(key));
      }
    } catch (e) {
      console.warn("Falha ao sincronizar histórico do visitante:", e);
    }
  }

  function redirectToLogin() {
    if (typeof window === "undefined") return;
    const currentPage = (window.location.pathname.split("/").pop() || "").toLowerCase();
    if (currentPage !== "login.html") {
      window.location.href = "login.html";
    }
  }

  function handleInvalidSession({ redirect = true } = {}) {
    if (!redirect) {
      clearSession();
      return;
    }
    if (!invalidSessionHandled) {
      invalidSessionHandled = true;
      clearSession();
      redirectToLogin();
    }
  }

  function getAccessToken() {
    return localStorage.getItem(KEYS.ACCESS);
  }

  function getRefreshToken() {
    return localStorage.getItem(KEYS.REFRESH);
  }

  function getCookie(name) {
    const encoded = `${encodeURIComponent(name)}=`;
    return document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(encoded))
      ?.slice(encoded.length) || "";
  }

  function getCsrfToken(endpoint = "") {
    return getCookie(endpoint === "/api/refresh" ? "csrf_refresh_token" : "csrf_access_token");
  }

  function getUser() {
    try {
      return JSON.parse(localStorage.getItem(KEYS.USER)) || null;
    } catch {
      return null;
    }
  }

  function isAuthenticated() {
    // Apenas o token JWT (localStorage) ou o cookie CSRF definido pelo backend
    // (HttpOnly + SameSite) sao fontes de verdade. A flag COOKIE_SESSION em
    // localStorage e totalmente controlavel pelo cliente e nao prova autenticacao.
    return !!getAccessToken() || !!getCookie("csrf_access_token") || !!getCookie("csrf_refresh_token");
  }

  function escapeHTML(value) {
    if (typeof SecurityUtils !== "undefined" && SecurityUtils.escapeHTML) {
      return SecurityUtils.escapeHTML(value);
    }
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Sincroniza os dados do usuário com o banco de dados.
   * Útil para atualizar o status Premium sem precisar de re-login.
   */
  async function syncUser({ redirectOnInvalid = false, force = false } = {}) {
    if (!isAuthenticated()) return null;
    if (!force) {
      const cached = Cache.get(KEYS.USER_SYNC);
      if (cached && cached.data && Date.now() - cached.ts < USER_SYNC_TTL_MS) {
        return cached.data;
      }
    }
    try {
      let token = getAccessToken();
      const buildUserHeaders = (tok) => tok ? { Authorization: `Bearer ${tok}` } : {};
      let res = await fetch(`${CONFIG.API_URL}/api/user`, {
        credentials: "include",
        headers: buildUserHeaders(token)
      });

      if (res.status === 401) {
        try {
          token = await refreshAccessToken({ redirectOnFailure: redirectOnInvalid });
          res = await fetch(`${CONFIG.API_URL}/api/user`, {
            credentials: "include",
            headers: buildUserHeaders(token)
          });
        } catch {
          return null;
        }
      }

      if (res.status === 401 || res.status === 404) {
        handleInvalidSession({ redirect: redirectOnInvalid });
        return null;
      }

      if (res.ok) {
        const data = await res.json();
        // Atualiza o localStorage com os dados frescos do banco
        localStorage.setItem(KEYS.USER, JSON.stringify(data));
        Cache.set(KEYS.USER_SYNC, { ts: Date.now(), data });
        hideBackendBanner();
        await syncGuestHistory();
        return data;
      }
    } catch (e) {
      if (isNetworkError(e)) {
        showBackendBanner();
        throw e;
      }
      console.warn("Falha ao sincronizar usuário:", e);
    }
    return getUser();
  }

  // ─── Renovação de token ───────────────────────────────────────────────────

  async function refreshAccessToken({ redirectOnFailure = true } = {}) {
    const refreshToken = getRefreshToken();
    if (!refreshToken && !getCookie("csrf_refresh_token")) {
      handleInvalidSession({ redirect: redirectOnFailure });
      throw new Error("Sem refresh token.");
    }

    const doRefresh = async (attempt = 1) => {
      const headers = { "Content-Type": "application/json" };
      if (refreshToken) headers.Authorization = `Bearer ${refreshToken}`;
      const csrfToken = getCsrfToken("/api/refresh");
      if (csrfToken) headers["X-CSRF-TOKEN"] = csrfToken;

      let res;
      try {
        res = await fetch(`${CONFIG.API_URL}/api/refresh`, {
          method: "POST",
          credentials: "include",
          headers,
        });
      } catch (netErr) {
        if (attempt <= 2) {
          const delay = Math.min(1000 * Math.pow(2, attempt - 1) + Math.random() * 500, 3000);
          await new Promise((r) => setTimeout(r, delay));
          return doRefresh(attempt + 1);
        }
        throw new AuthNetworkError(netErr && netErr.message ? netErr.message : "Erro de conexao com o servidor.");
      }

      if (!res.ok) {
        if (res.status >= 500 && attempt <= 2) {
          const delay = Math.min(1000 * Math.pow(2, attempt - 1) + Math.random() * 500, 3000);
          await new Promise((r) => setTimeout(r, delay));
          return doRefresh(attempt + 1);
        }
        throw new Error("refresh_failed");
      }

      const data = await res.json();
      if (refreshToken && data.access_token) {
        localStorage.setItem(KEYS.ACCESS, data.access_token);
      }
      invalidSessionHandled = false;
      return data.access_token;
    };

    if (!refreshPromise) {
      refreshPromise = doRefresh().finally(() => {
        refreshPromise = null;
      });
    }

    try {
      return await refreshPromise;
    } catch (err) {
      if (isNetworkError(err)) throw err;
      handleInvalidSession({ redirect: redirectOnFailure });
      throw new Error("Sessao expirada. Faca login novamente.");
    }
  }

  // ─── Fetch autenticado ────────────────────────────────────────────────────

  /**
   * Wrapper de fetch que:
   *  1. Injeta o Bearer token automaticamente.
   *  2. Se receber 401, tenta renovar o token uma vez e repete a requisição.
   *  3. Se ainda receber 401 após renovação, faz logout e redireciona.
   *
   * @param {string} endpoint - Caminho relativo da API, ex: "/api/user"
   * @param {RequestInit} options - Opções do fetch (method, body, headers…)
   */
  async function authenticatedFetch(endpoint, options = {}) {
    const { redirectOnInvalid = true, ...fetchOptions } = options;
    const url = `${CONFIG.API_URL}${endpoint}`;
    const method = (fetchOptions.method || "GET").toUpperCase();
    let token = getAccessToken();

    const buildHeaders = (tok, extra = {}) => {
      const headers = { ...extra };
      if (tok) headers.Authorization = `Bearer ${tok}`;
      const csrfToken = getCsrfToken(endpoint);
      if (csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) {
        headers["X-CSRF-TOKEN"] = csrfToken;
      }
      return headers;
    };

    // Não sobrescrevemos Content-Type se for FormData (multipart)
    const isFormData = fetchOptions.body instanceof FormData;
    const baseHeaders = isFormData
      ? buildHeaders(token, fetchOptions.headers || {})
      : buildHeaders(token, { "Content-Type": "application/json", ...(fetchOptions.headers || {}) });

    let res;
    try {
      res = await fetch(url, { ...fetchOptions, credentials: "include", headers: baseHeaders });
    } catch (netErr) {
      // Falha de rede (ex.: backend em cold start no Render) — NÃO desloga o usuário.
      showBackendBanner();
      throw new AuthNetworkError(netErr && netErr.message ? netErr.message : "Erro de conexao com o servidor.");
    }
    hideBackendBanner();

    // Tenta renovar o token se expirado
    if (res.status === 401) {
      try {
        token = await refreshAccessToken({ redirectOnFailure: redirectOnInvalid });
        const retryHeaders = isFormData
          ? buildHeaders(token, fetchOptions.headers || {})
          : buildHeaders(token, { "Content-Type": "application/json", ...(fetchOptions.headers || {}) });
        res = await fetch(url, { ...fetchOptions, credentials: "include", headers: retryHeaders });
      } catch (refreshErr) {
        if (!redirectOnInvalid) return res;
        throw refreshErr;
      }

      if (res.status === 401 || (res.status === 404 && endpoint === "/api/user")) {
        handleInvalidSession({ redirect: redirectOnInvalid });
        if (!redirectOnInvalid) return res;
        throw new Error("Sessao encerrada.");
      }
    }

    if (res.status === 200 && endpoint === "/api/user" && method === "GET") {
      const data = await res.clone().json();
      localStorage.setItem(KEYS.USER, JSON.stringify(data));
      Cache.set(KEYS.USER_SYNC, { ts: Date.now(), data });
    } else if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      Cache.remove(KEYS.USER_SYNC);
    }

    hideBackendBanner();
    return res;
  }

  async function publicFetch(endpoint, options = {}) {
    const fetchOptions = { ...options };
    delete fetchOptions.redirectOnInvalid;
    const isFormData = fetchOptions.body instanceof FormData;
    const headers = isFormData
      ? { ...(fetchOptions.headers || {}) }
      : { "Content-Type": "application/json", ...(fetchOptions.headers || {}) };

    return fetch(`${CONFIG.API_URL}${endpoint}`, {
      ...fetchOptions,
      credentials: "include",
      headers,
    });
  }

  async function optionalFetch(endpoint, options = {}) {
    if (!isAuthenticated()) {
      return publicFetch(endpoint, options);
    }

    const res = await authenticatedFetch(endpoint, {
      ...options,
      redirectOnInvalid: false,
    });

    if (res.status !== 401 && res.status !== 422) {
      return res;
    }

    return publicFetch(endpoint, options);
  }

  // ─── Login ────────────────────────────────────────────────────────────────

  /**
   * Envia credenciais para /api/login.
   * Salva a sessão e retorna os dados do backend.
   * Lança um Error com a mensagem de erro do servidor em caso de falha.
   */
  async function login(email, password) {
    const res = await fetch(`${CONFIG.API_URL}/api/login`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Erro ao fazer login.");
    }

    // Fluxo normal (sem 2FA)
    if (data.access_token) {
      saveSession(data.access_token, data.refresh_token, data.user);
      await syncGuestHistory();
    }

    // Fluxo com 2FA — o chamador trata o campo `two_factor_required`
    return data;
  }

  // ─── Verificação 2FA ──────────────────────────────────────────────────────

  async function verify2FA(pendingToken, code) {
    const res = await fetch(`${CONFIG.API_URL}/api/auth/2fa/verify`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pending_token: pendingToken, code }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Verificação 2FA falhou.");
    }

    saveSession(data.access_token, data.refresh_token, data.user);
    await syncGuestHistory();
    return data;
  }

  // ─── Logout ───────────────────────────────────────────────────────────────

  function logout() {
    const csrfToken = getCsrfToken();
    const headers = csrfToken ? { "X-CSRF-TOKEN": csrfToken } : {};
    fetch(`${CONFIG.API_URL}/api/logout`, {
      method: "POST",
      credentials: "include",
      headers,
    }).finally(() => {
      clearSession();
      window.location.href = "login.html";
    });
  }

  // ─── Callback OAuth2 (Google) ─────────────────────────────────────────────
  //
  // O backend novo redireciona para /index.html?oauth=success.
  //
  // Este bloco processa esses parâmetros assim que o script carrega.

  (async function processOAuthCallback() {
    const params = new URLSearchParams(window.location.search);
    const oauthSuccess = params.get("oauth") === "success";
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");
    const userRaw = params.get("user");

    if (oauthSuccess) {
      window.history.replaceState({}, document.title, window.location.pathname);
      const userData = await syncUser({ redirectOnInvalid: false, force: true });
      if (userData) {
        try {
          const token = await refreshAccessToken({ redirectOnFailure: false });
          if (token) localStorage.setItem(KEYS.ACCESS, token);
        } catch {}
      }
      return;
    }

    if (accessToken) {
      let user = null;
      try {
        user = userRaw ? JSON.parse(userRaw) : null;
      } catch {
        user = null;
      }

      saveSession(accessToken, refreshToken, user);
      await syncGuestHistory();

      // Remove os tokens da URL por segurança
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, document.title, cleanUrl);
    }
  })();

  // ─── Registro ─────────────────────────────────────────────────────────────

  /**
   * Cria uma nova conta de usuário.
   * @param {string} nome
   * @param {string} email
   * @param {string} confirmEmail
   * @param {string} password
   * @param {string} confirmPassword
   * @param {Array}  veiculos - lista de objetos de veículo (opcional)
   */
  async function register(nome, email, confirmEmail, password, confirmPassword, veiculos = []) {
    const res = await fetch(`${CONFIG.API_URL}/api/cadastro`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nome,
        email,
        confirm_email: confirmEmail,
        password,
        confirm_password: confirmPassword,
        veiculos,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Erro ao criar conta.");
    }

    return data;
  }

  // ─── Esqueci minha senha ──────────────────────────────────────────────────

  /**
   * Solicita o envio de e-mail para redefinição de senha.
   * @param {string} email
   */
  async function forgotPassword(email) {
    const res = await fetch(`${CONFIG.API_URL}/api/auth/forgot-password`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Erro ao solicitar redefinição de senha.");
    }

    return data;
  }

  // ─── Redefinir senha ──────────────────────────────────────────────────────

  /**
   * Redefine a senha usando o token recebido por e-mail.
   * @param {string} token
   * @param {string} newPassword
   */
  async function resetPassword(token, newPassword) {
    const res = await fetch(`${CONFIG.API_URL}/api/auth/reset-password`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password: newPassword }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Erro ao redefinir senha.");
    }

    return data;
  }

  // ─── API Pública ──────────────────────────────────────────────────────────

  async function openPremiumCheckout() {
    const res = await authenticatedFetch("/api/pay/preference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || "Nao foi possivel iniciar o checkout premium.");
    }

    const checkoutUrl =
      data.checkout_url ||
      (data.data && data.data.checkout_url) ||
      data.init_point ||
      "";

    if (!checkoutUrl) {
      throw new Error("Checkout premium nao configurado.");
    }

    window.location.href = checkoutUrl;
  }

  function closePremiumPaywall() {
    const overlay = document.getElementById("autoassist-premium-overlay");
    if (overlay) overlay.remove();
  }

  function showPremiumPaywall(options = {}) {
    if (typeof document === "undefined") return;
    if (document.getElementById("autoassist-premium-overlay")) return;

    const title = options.title || "Recurso Premium";
    const message =
      options.message ||
      "Este recurso esta disponivel apenas para usuarios Premium.";
    const showBackButton = options.showBackButton !== false;
    const backHref = options.backHref || "index.html";

    const styleId = "autoassist-premium-style";
    if (!document.getElementById(styleId)) {
      const style = document.createElement("style");
      style.id = styleId;
      style.textContent = `
        .autoassist-premium-overlay {
          position: fixed;
          inset: 0;
          background:
            radial-gradient(circle at top right, rgba(16, 185, 129, 0.18), transparent 45%),
            rgba(2, 6, 23, 0.78);
          backdrop-filter: blur(5px);
          z-index: 10000;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 20px;
        }
        .autoassist-premium-modal {
          width: 100%;
          max-width: 460px;
          background: linear-gradient(180deg, #0f172a 0%, #0b1224 100%);
          color: #f8fafc;
          border-radius: 18px;
          border: 1px solid rgba(148, 163, 184, 0.28);
          box-shadow:
            0 26px 64px rgba(2, 6, 23, 0.52),
            inset 0 1px 0 rgba(255, 255, 255, 0.08);
          padding: 24px;
          transform: translateY(6px);
          animation: premium-pop 0.25s ease-out forwards;
        }
        @keyframes premium-pop {
          to { transform: translateY(0); }
        }
        .autoassist-premium-badge {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
          padding: 6px 12px;
          border-radius: 999px;
          background: rgba(16, 185, 129, 0.16);
          border: 1px solid rgba(16, 185, 129, 0.35);
          color: #6ee7b7;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.3px;
        }
        .autoassist-premium-title {
          margin: 0 0 10px 0;
          font-size: 1.42rem;
          font-weight: 700;
          letter-spacing: -0.3px;
        }
        .autoassist-premium-text {
          margin: 0 0 20px 0;
          color: #cbd5e1;
          line-height: 1.62;
        }
        .autoassist-premium-actions {
          display: flex;
          gap: 12px;
          justify-content: space-between;
        }
        .autoassist-premium-btn {
          border: 0;
          border-radius: 12px;
          padding: 11px 15px;
          font-weight: 600;
          cursor: pointer;
          min-width: 120px;
          transition: transform 0.15s ease, filter 0.15s ease, box-shadow 0.15s ease;
        }
        .autoassist-premium-btn:hover {
          transform: translateY(-1px);
          filter: brightness(1.03);
        }
        .autoassist-premium-btn-pay {
          background: linear-gradient(135deg, #059669, #0f766e);
          color: #ffffff;
          box-shadow: 0 10px 22px rgba(5, 150, 105, 0.28);
        }
        .autoassist-premium-btn-back {
          background: rgba(51, 65, 85, 0.58);
          color: #e2e8f0;
          border: 1px solid rgba(148, 163, 184, 0.32);
        }
      `;
      document.head.appendChild(style);
    }

    const overlay = document.createElement("div");
    overlay.id = "autoassist-premium-overlay";
    overlay.className = "autoassist-premium-overlay";
    overlay.innerHTML = `
      <div class="autoassist-premium-modal" role="dialog" aria-modal="true" aria-label="Premium">
        <div class="autoassist-premium-badge">Plano Premium</div>
        <h2 class="autoassist-premium-title">${escapeHTML(title)}</h2>
        <p class="autoassist-premium-text">${escapeHTML(message)}</p>
        <div class="autoassist-premium-actions">
          ${showBackButton ? '<button type="button" class="autoassist-premium-btn autoassist-premium-btn-back" id="autoassist-premium-back">Voltar</button>' : ""}
          <button type="button" class="autoassist-premium-btn autoassist-premium-btn-pay" id="autoassist-premium-pay">Pagar</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    const payBtn = document.getElementById("autoassist-premium-pay");
    const backBtn = document.getElementById("autoassist-premium-back");
    if (payBtn) {
      payBtn.addEventListener("click", async () => {
        payBtn.disabled = true;
        const original = payBtn.textContent;
        payBtn.textContent = "Abrindo checkout...";
        try {
          await openPremiumCheckout();
        } catch (err) {
          alert(err.message || "Nao foi possivel abrir o checkout premium.");
          payBtn.disabled = false;
          payBtn.textContent = original;
        }
      });
    }

    if (backBtn) {
      backBtn.addEventListener("click", () => {
        closePremiumPaywall();
      });
    }
  }

  function requirePremiumPage(options = {}) {
    const user = getUser();
    if (user && user.is_premium) return true;
    showPremiumPaywall(options);
    return false;
  }

  function bindPremiumLinkGuards() {
    if (typeof document === "undefined") return;
    if (document.body?.dataset?.premiumGuardBound === "1") return;
    document.body.dataset.premiumGuardBound = "1";

    const premiumPaths = new Set([
      "dashboard.html",
      "library.html",
      "maintenance_history.html",
    ]);

    document.addEventListener("click", (event) => {
      const anchor = event.target.closest("a");
      if (!anchor) return;

      const hrefRaw = (anchor.getAttribute("href") || "").trim();
      if (!hrefRaw || hrefRaw.startsWith("#") || hrefRaw.startsWith("javascript:")) return;

      let targetPath = "";
      try {
        const hrefUrl = new URL(hrefRaw, window.location.href);
        targetPath = (hrefUrl.pathname.split("/").pop() || "").toLowerCase();
      } catch {
        return;
      }

      if (!premiumPaths.has(targetPath)) return;
      if (!isAuthenticated()) return;

      const user = getUser();
      if (user && user.is_premium) return;

      event.preventDefault();
      showPremiumPaywall({
        title: "Recurso Premium",
        message: "Para acessar esta pagina, ative o plano Premium.",
        backHref: "index.html",
      });
    });
  }

  function ensurePremiumModal() {
    // Mantido para compatibilidade com paginas que chamam este metodo.
    // O CTA flutuante foi removido; agora usamos apenas modal contextual.
    const oldBtn = document.getElementById("autoassist-upgrade-btn");
    if (oldBtn) oldBtn.remove();
  }

  // Ativa o guard global para cliques em links premium.
  bindPremiumLinkGuards();

  return {
    isAuthenticated,
    login,
    logout,
    register,
    verify2FA,
    forgotPassword,
    resetPassword,
    getUser,
    getAccessToken,
    authenticatedFetch,
    optionalFetch,
    publicFetch,
    saveSession,
    syncUser,
    showPremiumPaywall,
    closePremiumPaywall,
    requirePremiumPage,
    bindPremiumLinkGuards,
    ensurePremiumModal,
    openPremiumCheckout,
    showBackendBanner,
    hideBackendBanner,
    isNetworkError,
    Cache,
    KEYS
  };
})();

// Sincronização automática ao carregar o script (se autenticado)
const autoassistCurrentPage = (window.location.pathname.split("/").pop() || "").toLowerCase();
const autoassistPublicPages = new Set([
  "",
  "index.html",
  "login.html",
  "cadastro.html",
  "esqueci-senha.html",
  "redefinir-senha.html",
]);
if (Auth.isAuthenticated() && !autoassistPublicPages.has(autoassistCurrentPage)) {
  Auth.syncUser().catch(() => {});
}
