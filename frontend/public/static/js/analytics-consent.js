(function () {
  "use strict";

  const CONSENT_KEY = "autoassist_analytics_consent";
  const ANONYMOUS_ID_KEY = "autoassist_analytics_id";
  const ACCEPTED = "accepted";
  const DECLINED = "declined";
  const BLOCKED_KEYS = new Set([
    "authorization",
    "cookie",
    "password",
    "senha",
    "token",
    "refresh_token",
    "access_token",
    "jwt",
    "secret",
    "email",
    "telefone",
    "phone",
    "cpf",
    "cnpj",
    "placa",
    "license_plate",
    "message",
    "mensagem",
    "prompt",
    "content",
    "imagem",
    "image",
    "photo",
    "foto",
    "audio",
    "voice",
  ]);

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return "";
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      // Storage can be disabled by the browser; analytics remains optional.
    }
  }

  function getApiBase() {
    return (typeof CONFIG !== "undefined" && CONFIG.API_URL) || "";
  }

  function generateId() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return `aa-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }

  function getAnonymousId() {
    let id = storageGet(ANONYMOUS_ID_KEY);
    if (!id) {
      id = generateId();
      storageSet(ANONYMOUS_ID_KEY, id);
    }
    return id;
  }

  function isPlainValue(value) {
    return value === null || ["string", "number", "boolean"].includes(typeof value);
  }

  function cleanValue(value) {
    if (typeof value === "string") return value.trim().slice(0, 240);
    return value;
  }

  function sanitizeMetadata(metadata) {
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return {};

    const clean = {};
    Object.entries(metadata).forEach(([rawKey, rawValue]) => {
      const key = String(rawKey || "").trim().slice(0, 80);
      if (!key || BLOCKED_KEYS.has(key.toLowerCase())) return;

      if (isPlainValue(rawValue)) {
        clean[key] = cleanValue(rawValue);
        return;
      }

      if (Array.isArray(rawValue)) {
        clean[key] = rawValue
          .filter(isPlainValue)
          .slice(0, 10)
          .map(cleanValue);
      }
    });

    return clean;
  }

  function hasConsent() {
    return storageGet(CONSENT_KEY) === ACCEPTED;
  }

  async function track(eventType, metadata) {
    if (!hasConsent()) return false;

    const safeEventType = String(eventType || "").trim().slice(0, 80);
    if (!/^[a-zA-Z0-9_.:-]{1,80}$/.test(safeEventType)) return false;

    const payload = {
      event_type: safeEventType,
      path: window.location.pathname,
      anonymous_id: getAnonymousId(),
      metadata: sanitizeMetadata({
        page_title: document.title,
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        ...metadata,
      }),
    };

    try {
      await fetch(`${getApiBase()}/api/analytics/events`, {
        method: "POST",
        credentials: "include",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      return true;
    } catch {
      return false;
    }
  }

  function injectBannerStyles() {
    if (document.getElementById("aa-analytics-style")) return;
    const style = document.createElement("style");
    style.id = "aa-analytics-style";
    style.textContent = `
      .aa-consent {
        position: fixed;
        left: 16px;
        right: 16px;
        bottom: 16px;
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        max-width: 980px;
        margin: 0 auto;
        padding: 14px 16px;
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-radius: 8px;
        background: rgba(9, 9, 11, 0.94);
        box-shadow: 0 18px 44px rgba(0, 0, 0, 0.4);
        color: #fafafa;
        font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif;
        backdrop-filter: blur(18px);
      }
      .aa-consent__text {
        min-width: 0;
        font-size: 13px;
        line-height: 1.5;
        color: #d4d4d8;
      }
      .aa-consent__text strong {
        display: block;
        margin-bottom: 2px;
        color: #ffffff;
        font-size: 14px;
      }
      .aa-consent__text a {
        color: #93c5fd;
        text-decoration: none;
      }
      .aa-consent__actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
      }
      .aa-consent__button {
        height: 36px;
        padding: 0 14px;
        border-radius: 8px;
        border: 1px solid rgba(148, 163, 184, 0.3);
        background: transparent;
        color: #e4e4e7;
        font: inherit;
        font-size: 13px;
        font-weight: 700;
        cursor: pointer;
      }
      .aa-consent__button--accept {
        border-color: #2563eb;
        background: #2563eb;
        color: white;
      }
      @media (max-width: 720px) {
        .aa-consent {
          align-items: stretch;
          flex-direction: column;
        }
        .aa-consent__actions {
          justify-content: flex-end;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function removeBanner() {
    document.getElementById("aa-analytics-consent")?.remove();
  }

  function showConsentBanner() {
    if (storageGet(CONSENT_KEY) || document.getElementById("aa-analytics-consent")) return;
    injectBannerStyles();

    const banner = document.createElement("div");
    banner.id = "aa-analytics-consent";
    banner.className = "aa-consent";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-live", "polite");
    banner.innerHTML = `
      <div class="aa-consent__text">
        <strong>Cookies e analytics</strong>
        Usamos eventos anonimizados para entender uso do AutoAssist e melhorar o produto. Veja a <a href="privacidade.html">Pol&iacute;tica de Privacidade</a>.
      </div>
      <div class="aa-consent__actions">
        <button type="button" class="aa-consent__button" data-aa-consent="decline">Recusar</button>
        <button type="button" class="aa-consent__button aa-consent__button--accept" data-aa-consent="accept">Aceitar</button>
      </div>
    `;

    banner.addEventListener("click", (event) => {
      const action = event.target?.getAttribute("data-aa-consent");
      if (!action) return;
      storageSet(CONSENT_KEY, action === "accept" ? ACCEPTED : DECLINED);
      removeBanner();
      if (action === "accept") track("page_view");
    });

    document.body.appendChild(banner);
  }

  window.AutoAssistAnalytics = {
    track,
    consent: {
      hasConsent,
      accept() {
        storageSet(CONSENT_KEY, ACCEPTED);
        removeBanner();
        track("page_view");
      },
      decline() {
        storageSet(CONSENT_KEY, DECLINED);
        removeBanner();
      },
      reset() {
        storageSet(CONSENT_KEY, "");
        showConsentBanner();
      },
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    if (hasConsent()) {
      track("page_view");
      return;
    }
    showConsentBanner();
  });
})();
