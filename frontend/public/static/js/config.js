/**
 * AutoAssist — Configuração Central da API
 *
 * Espelha as variáveis do backend:
 *   FRONTEND_URL_DEV  → http://localhost:3000/
 *   FRONTEND_URL_PROD → https://drkcde15.github.io/AutoAssist/
 *
 * Em desenvolvimento local:
 * - Se rodar em localhost:3000 (Next.js), usamos path relativo e o proxy
 *   (next.config.mjs) encaminha para o Flask.
 * - Se rodar em localhost:5000 (Flask servindo os HTMLs), também usamos path
 *   relativo (mesma origem).
 * - Se rodar em outra porta local (ex.: Live Server 5500), apontamos
 *   diretamente para o Flask em http://localhost:5000.
 *
 * Em produção: aponta diretamente ao servidor Flask hospedado.
 */
const CONFIG = (() => {
  const FLASK_URL_DEV  = "http://localhost:5000";
  const FLASK_URL_PROD = "https://autoassis.onrender.com";

  const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  const isNextDev = isLocal && window.location.port === "3000";
  const isFlaskSameOrigin = isLocal && window.location.port === "5000";

  return {
    API_URL: isLocal
      ? (isNextDev || isFlaskSameOrigin ? "" : FLASK_URL_DEV)
      : FLASK_URL_PROD,
  };
})();
