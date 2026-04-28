/**
 * AutoAssist — Módulo de Autenticação
 *
 * Responsabilidades:
 *  - Persistir e recuperar access_token / refresh_token no localStorage.
 *  - Fornecer Auth.authenticatedFetch() que adiciona o Bearer automaticamente
 *    e renova o token silenciosamente quando ele expira (401).
 *  - Expor Auth.login(), Auth.logout(), Auth.isAuthenticated().
 *  - Processar o retorno de OAuth2 (Google) via query-string na URL.
 */
const Auth = (() => {
  const KEYS = {
    ACCESS: "autoassist_access_token",
    REFRESH: "autoassist_refresh_token",
    USER: "autoassist_user",
    VEHICLES: "autoassist_veiculos_cache",
  };

  // ─── Cache de Sessão (Otimização) ──────────────────────────────────────────
  const Cache = {
    set: (key, data) => sessionStorage.setItem(key, JSON.stringify(data)),
    get: (key) => {
      try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; }
    },
    clear: () => {
      sessionStorage.removeItem(KEYS.VEHICLES);
    }
  };

  // ─── Persistência ─────────────────────────────────────────────────────────

  function saveSession(accessToken, refreshToken, user) {
    localStorage.setItem(KEYS.ACCESS, accessToken);
    if (refreshToken) localStorage.setItem(KEYS.REFRESH, refreshToken);
    if (user) localStorage.setItem(KEYS.USER, JSON.stringify(user));
  }

  function clearSession() {
    Object.values(KEYS).forEach((k) => localStorage.removeItem(k));
    Cache.clear();
  }

  function getAccessToken() {
    return localStorage.getItem(KEYS.ACCESS);
  }

  function getRefreshToken() {
    return localStorage.getItem(KEYS.REFRESH);
  }

  function getUser() {
    try {
      return JSON.parse(localStorage.getItem(KEYS.USER)) || null;
    } catch {
      return null;
    }
  }

  function isAuthenticated() {
    return !!getAccessToken();
  }

  // ─── Renovação de token ───────────────────────────────────────────────────

  async function refreshAccessToken() {
    const refreshToken = getRefreshToken();
    if (!refreshToken) throw new Error("Sem refresh token.");

    const res = await fetch(`${CONFIG.API_URL}/api/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${refreshToken}`,
      },
    });

    if (!res.ok) {
      clearSession();
      window.location.href = "login.html";
      throw new Error("Sessão expirada. Faça login novamente.");
    }

    const data = await res.json();
    localStorage.setItem(KEYS.ACCESS, data.access_token);
    return data.access_token;
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
    const url = `${CONFIG.API_URL}${endpoint}`;
    let token = getAccessToken();

    const buildHeaders = (tok, extra = {}) => ({
      ...extra,
      Authorization: `Bearer ${tok}`,
    });

    // Não sobrescrevemos Content-Type se for FormData (multipart)
    const isFormData = options.body instanceof FormData;
    const baseHeaders = isFormData
      ? buildHeaders(token, options.headers || {})
      : buildHeaders(token, { "Content-Type": "application/json", ...(options.headers || {}) });

    let res = await fetch(url, { ...options, headers: baseHeaders });

    // Tenta renovar o token se expirado
    if (res.status === 401) {
      try {
        token = await refreshAccessToken();
        const retryHeaders = isFormData
          ? buildHeaders(token, options.headers || {})
          : buildHeaders(token, { "Content-Type": "application/json", ...(options.headers || {}) });
        res = await fetch(url, { ...options, headers: retryHeaders });
      } catch {
        // refreshAccessToken já faz o redirect
        throw new Error("Sessão encerrada.");
      }
    }

    return res;
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
    }

    // Fluxo com 2FA — o chamador trata o campo `two_factor_required`
    return data;
  }

  // ─── Verificação 2FA ──────────────────────────────────────────────────────

  async function verify2FA(pendingToken, code) {
    const res = await fetch(`${CONFIG.API_URL}/api/auth/2fa/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pending_token: pendingToken, code }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Verificação 2FA falhou.");
    }

    saveSession(data.access_token, data.refresh_token, data.user);
    return data;
  }

  // ─── Logout ───────────────────────────────────────────────────────────────

  function logout() {
    clearSession();
    window.location.href = "login.html";
  }

  // ─── Callback OAuth2 (Google) ─────────────────────────────────────────────
  //
  // O backend redireciona para:
  //   /index.html?access_token=...&refresh_token=...&user=...
  //
  // Este bloco processa esses parâmetros assim que o script carrega.

  (function processOAuthCallback() {
    const params = new URLSearchParams(window.location.search);
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");
    const userRaw = params.get("user");

    if (accessToken) {
      let user = null;
      try {
        user = userRaw ? JSON.parse(userRaw) : null;
      } catch {
        user = null;
      }

      saveSession(accessToken, refreshToken, user);

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
   * @param {string} password
   * @param {Array}  veiculos - lista de objetos de veículo (opcional)
   */
  async function register(nome, email, password, veiculos = []) {
    const res = await fetch(`${CONFIG.API_URL}/api/cadastro`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome, email, password, veiculos }),
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
    const backHref = options.backHref || "chat.html";

    const styleId = "autoassist-premium-style";
    if (!document.getElementById(styleId)) {
      const style = document.createElement("style");
      style.id = styleId;
      style.textContent = `
        .autoassist-premium-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.55);
          z-index: 10000;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 20px;
        }
        .autoassist-premium-modal {
          width: 100%;
          max-width: 420px;
          background: #111827;
          color: #f9fafb;
          border-radius: 14px;
          border: 1px solid rgba(255, 255, 255, 0.12);
          box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4);
          padding: 22px;
        }
        .autoassist-premium-title {
          margin: 0 0 8px 0;
          font-size: 1.2rem;
          font-weight: 700;
        }
        .autoassist-premium-text {
          margin: 0 0 18px 0;
          color: #d1d5db;
          line-height: 1.5;
        }
        .autoassist-premium-actions {
          display: flex;
          gap: 10px;
          justify-content: flex-end;
          flex-wrap: wrap;
        }
        .autoassist-premium-btn {
          border: 0;
          border-radius: 10px;
          padding: 10px 14px;
          font-weight: 600;
          cursor: pointer;
        }
        .autoassist-premium-btn-pay {
          background: #0f766e;
          color: #ffffff;
        }
        .autoassist-premium-btn-back {
          background: #374151;
          color: #f9fafb;
        }
      `;
      document.head.appendChild(style);
    }

    const overlay = document.createElement("div");
    overlay.id = "autoassist-premium-overlay";
    overlay.className = "autoassist-premium-overlay";
    overlay.innerHTML = `
      <div class="autoassist-premium-modal" role="dialog" aria-modal="true" aria-label="Premium">
        <h2 class="autoassist-premium-title">${title}</h2>
        <p class="autoassist-premium-text">${message}</p>
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
        window.location.href = backHref;
      });
    }
  }

  function requirePremiumPage(options = {}) {
    const user = getUser();
    if (user && user.is_premium) return true;
    showPremiumPaywall(options);
    return false;
  }

  function ensurePremiumModal() {
    if (typeof document === "undefined") return;
    if (!isAuthenticated()) return;

    const user = getUser();
    if (!user || user.is_premium) return;
    if (document.getElementById("autoassist-upgrade-btn")) return;

    const styleId = "autoassist-upgrade-style";
    if (!document.getElementById(styleId)) {
      const style = document.createElement("style");
      style.id = styleId;
      style.textContent = `
        .autoassist-upgrade-btn {
          position: fixed;
          right: 18px;
          bottom: 18px;
          z-index: 9999;
          border: 0;
          border-radius: 999px;
          padding: 12px 18px;
          background: #0f766e;
          color: #ffffff;
          font-weight: 700;
          cursor: pointer;
          box-shadow: 0 8px 20px rgba(15, 118, 110, 0.28);
        }
        .autoassist-upgrade-btn:hover { filter: brightness(1.05); }
      `;
      document.head.appendChild(style);
    }

    const btn = document.createElement("button");
    btn.id = "autoassist-upgrade-btn";
    btn.className = "autoassist-upgrade-btn";
    btn.type = "button";
    btn.textContent = "Ativar Premium";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = "Abrindo checkout...";
      try {
        await openPremiumCheckout();
      } catch (err) {
        alert(err.message || "Nao foi possivel abrir o checkout premium.");
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    });

    document.body.appendChild(btn);
  }

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
    saveSession,
    showPremiumPaywall,
    closePremiumPaywall,
    requirePremiumPage,
    ensurePremiumModal,
    openPremiumCheckout,
    Cache,
    KEYS
  };
})();
