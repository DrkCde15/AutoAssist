/**
 * AutoAssist - Configuracao central da API
 *
 * Frontend servido pelo backend (mesma aplicacao).
 *
 * Em desenvolvimento local:
 * - Se rodar em localhost:3000 (Next.js), usamos path relativo e o proxy
 *   (next.config.mjs) encaminha para o Flask.
 * - Se rodar em localhost:5000 (Flask servindo os HTMLs), tambem usamos path
 *   relativo (mesma origem).
 * - Se rodar em outra porta local (ex.: Live Server 5500), apontamos
 *   diretamente para o Flask em http://localhost:5000.
 *
 * Em producao: aponta diretamente ao servidor Flask hospedado.
 */
const CONFIG = (() => {
  const FLASK_URL_DEV = "http://localhost:5000";
  const FLASK_URL_PROD = "https://autoassist-l9lr.onrender.com";
  const API_OVERRIDE_KEY = "autoassist_api_url_override";

  const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  const isNextDev = isLocal && window.location.port === "3000";
  const isFlaskSameOrigin = isLocal && window.location.port === "5000";

  const query = new URLSearchParams(window.location.search);
  const isAllowedOverride = (value) => {
    if (!isLocal || !value) return false;
    try {
      const parsed = new URL(value, window.location.origin);
      return ["http:", "https:"].includes(parsed.protocol) &&
        ["localhost", "127.0.0.1"].includes(parsed.hostname);
    } catch {
      return false;
    }
  };

  const queryApi = (query.get("api") || "").trim();
  if (isAllowedOverride(queryApi)) {
    localStorage.setItem(API_OVERRIDE_KEY, queryApi);
  }
  const storedOverrideApi = (localStorage.getItem(API_OVERRIDE_KEY) || "").trim();
  if (storedOverrideApi && !isAllowedOverride(storedOverrideApi)) {
    localStorage.removeItem(API_OVERRIDE_KEY);
  }
  const overrideApi = isAllowedOverride(storedOverrideApi) ? storedOverrideApi : "";

  return {
    API_URL: overrideApi || (
      isLocal
        ? (isNextDev || isFlaskSameOrigin ? "" : FLASK_URL_DEV)
        : FLASK_URL_PROD
    ),
  };
})();
