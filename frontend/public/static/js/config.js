/**
 * AutoAssist — Configuração Central da API
 *
 * Espelha as variáveis do backend:
 *   FRONTEND_URL_DEV  → http://localhost:3000/
 *   FRONTEND_URL_PROD → https://drkcde15.github.io/AutoAssist/
 *
 * Em desenvolvimento: todas as chamadas /api/* são interceptadas pelo
 * proxy do Next.js (next.config.mjs) e encaminhadas ao Flask na porta 5000,
 * por isso API_URL é vazio — os paths relativos funcionam naturalmente.
 *
 * Em produção: aponta diretamente ao servidor Flask hospedado.
 */
const CONFIG = (() => {
  const FLASK_URL_DEV  = "";                          // proxy Next.js cuida do roteamento
  const FLASK_URL_PROD = "https://autoassis.onrender.com";

  const isDev =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";

  return {
    API_URL: isDev ? FLASK_URL_DEV : FLASK_URL_PROD,
  };
})();

