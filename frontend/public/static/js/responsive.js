/*
  Menu responsivo compartilhado.
  Nao altera rotas nem regras de negocio; apenas controla abrir/fechar a navegacao no mobile.
*/
(function () {
  const BREAKPOINT = 860;
  const NAV_TOOLTIP_SELECTOR = [
    ".nav-links .nav-link",
    ".nav-links .nav-btn",
    ".header-nav .nav-link",
    ".header-nav .nav-btn",
    ".nav-bell-btn",
    "#btnReport",
  ].join(", ");

  const NAV_TOOLTIPS_BY_PATH = {
    "dashboard.html": "Premium: acompanhe a saúde do veículo em tempo real, receba alertas inteligentes e evite prejuízos antes que eles aconteçam.",
    "chat.html": "Converse com a IA para diagnosticar problemas, analisar arquivos e manter todo o histórico salvo para consultas futuras.",
    "maintenance_history.html": "Premium: Tenha controle total das manutenções, despesas e revisões para valorizar seu veículo e reduzir gastos desnecessários.",
    "library.html": "Premium: salve diagnósticos, recomendações e conteúdos importantes em uma biblioteca exclusiva, acessível sempre que precisar.",
  };

  const NAV_TOOLTIPS_BY_LABEL = {
    dashboard: NAV_TOOLTIPS_BY_PATH["dashboard.html"],
    chat: NAV_TOOLTIPS_BY_PATH["chat.html"],
    anotacoes: NAV_TOOLTIPS_BY_PATH["maintenance_history.html"],
    biblioteca: NAV_TOOLTIPS_BY_PATH["library.html"],
  };

  function normalizeLabel(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  function getLinkPath(item) {
    const href = item.getAttribute("href") || "";
    if (!href || href.startsWith("#")) return "";

    try {
      return new URL(href, window.location.href).pathname.split("/").pop().toLowerCase();
    } catch (error) {
      return href.split("#")[0].split("?")[0].split("/").pop().toLowerCase();
    }
  }

  function getTooltipById(item) {
    if (item.id === "btnNotifications") return "Ver alertas e lembretes de manutenção.";
    if (item.id === "btnReport") return "Exportar a última análise em PDF.";
    if (item.id === "logout" || item.id === "btnLogout") return NAV_TOOLTIPS_BY_LABEL.sair;
    return "";
  }

  function getTooltipForItem(item) {
    const byId = getTooltipById(item);
    if (byId) return byId;

    const label = normalizeLabel(item.textContent);
    if (NAV_TOOLTIPS_BY_LABEL[label]) return NAV_TOOLTIPS_BY_LABEL[label];

    const path = getLinkPath(item);
    return NAV_TOOLTIPS_BY_PATH[path] || "";
  }

  function findNavTooltipItems(root) {
    const items = [];
    if (root.matches && root.matches(NAV_TOOLTIP_SELECTOR)) items.push(root);
    if (root.querySelectorAll) {
      root.querySelectorAll(NAV_TOOLTIP_SELECTOR).forEach((item) => items.push(item));
    }
    return items;
  }

  function applyNavTooltips(root) {
    findNavTooltipItems(root).forEach((item) => {
      if (item.closest(".notification-panel") || item.dataset.navTooltip) return;

      const tooltip = getTooltipForItem(item);
      if (tooltip) item.dataset.navTooltip = tooltip;
    });
  }

  function observeNavTooltipChanges() {
    if (!("MutationObserver" in window)) return;

    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === Node.ELEMENT_NODE) applyNavTooltips(node);
        });
      });
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  function createToggle(nav) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "aa-menu-toggle";
    button.setAttribute("aria-label", "Abrir menu de navegacao");
    button.setAttribute("aria-expanded", "false");

    if (!nav.id) {
      nav.id = "aa-menu-" + Math.random().toString(36).slice(2, 8);
    }
    button.setAttribute("aria-controls", nav.id);

    button.innerHTML = "<span></span><span></span><span></span>";
    return button;
  }

  function closeMenu(nav, button) {
    nav.classList.remove("aa-menu-open");
    button.classList.remove("aa-menu-open");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", "Abrir menu de navegacao");
    document.body.classList.remove("aa-menu-lock");
  }

  function openMenu(nav, button) {
    nav.classList.add("aa-menu-open");
    button.classList.add("aa-menu-open");
    button.setAttribute("aria-expanded", "true");
    button.setAttribute("aria-label", "Fechar menu de navegacao");
    document.body.classList.add("aa-menu-lock");
  }

  function setupNavbar(navbar) {
    const container = navbar.querySelector(".nav-container");
    const nav = navbar.querySelector(".nav-links");
    if (!container || !nav || container.querySelector(".aa-menu-toggle")) return;

    const button = createToggle(nav);
    container.insertBefore(button, nav);
    document.body.classList.add("aa-mobile-menu-ready");

    button.addEventListener("click", function () {
      if (nav.classList.contains("aa-menu-open")) {
        closeMenu(nav, button);
      } else {
        openMenu(nav, button);
      }
    });

    nav.addEventListener("click", function (event) {
      const target = event.target.closest("a, button");
      if (!target || target.id === "btnNotifications") return;
      closeMenu(nav, button);
    });

    document.addEventListener("click", function (event) {
      if (!nav.classList.contains("aa-menu-open")) return;
      if (navbar.contains(event.target)) return;
      closeMenu(nav, button);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu(nav, button);
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > BREAKPOINT) closeMenu(nav, button);
    });
  }

  function setupChatHeader(header) {
    const right = header.querySelector(".header-right");
    const nav = header.querySelector(".header-nav");
    if (!right || !nav || right.querySelector(".aa-menu-toggle")) return;

    const button = createToggle(nav);
    right.insertBefore(button, nav);
    document.body.classList.add("aa-mobile-menu-ready", "aa-chat-layout");

    button.addEventListener("click", function () {
      if (nav.classList.contains("aa-menu-open")) {
        closeMenu(nav, button);
      } else {
        openMenu(nav, button);
      }
    });

    nav.addEventListener("click", function (event) {
      if (event.target.closest("a, button")) closeMenu(nav, button);
    });

    document.addEventListener("click", function (event) {
      if (!nav.classList.contains("aa-menu-open")) return;
      if (header.contains(event.target)) return;
      closeMenu(nav, button);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu(nav, button);
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > BREAKPOINT) closeMenu(nav, button);
    });
  }

  function initResponsiveMenus() {
    applyNavTooltips(document);
    observeNavTooltipChanges();

    document.querySelectorAll(".navbar").forEach(setupNavbar);
    document.querySelectorAll("header").forEach(function (header) {
      if (header.querySelector(".header-nav")) setupChatHeader(header);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initResponsiveMenus);
  } else {
    initResponsiveMenus();
  }
})();
