/*
  Menu responsivo compartilhado.
  Nao altera rotas nem regras de negocio; apenas controla abrir/fechar a navegacao no mobile.
*/
(function () {
  const BREAKPOINT = 860;

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
