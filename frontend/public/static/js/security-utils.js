// Utilitarios de seguranca compartilhados (escape HTML, sanitizacao).
// @ts-check

(function (global) {
  "use strict";

  /**
   * Escapa caracteres perigosos de uma string para insercao segura em HTML.
   * @param {unknown} value
   * @returns {string}
   */
  function escapeHTML(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Define o texto de um elemento de forma segura (sem interpretar HTML),
   * opcionalmente com um prefixo em negrito.
   * @param {Element} el
   * @param {string} message
   * @param {string} [prefix]
   */
  function setSafeText(el, message, prefix) {
    if (!el) return;
    el.textContent = "";
    if (prefix) {
      const strong = document.createElement("strong");
      strong.textContent = prefix;
      el.appendChild(strong);
    }
    el.appendChild(document.createTextNode(message == null ? "" : String(message)));
  }

  const api = { escapeHTML: escapeHTML, setSafeText: setSafeText };
  global.SecurityUtils = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
