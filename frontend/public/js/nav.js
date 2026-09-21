/**
 * nav.js — Hamburger menu + mobile drawer + auth-aware navbar
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    // --- Inject drawer + frosted glass navbar styles ---
    var style = document.createElement("style");
    style.textContent = [
      /* Frosted glass navbar */
      'header {',
      '  background: rgba(12, 12, 20, 0.45) !important;',
      '  backdrop-filter: blur(16px) saturate(1.4) !important;',
      '  -webkit-backdrop-filter: blur(16px) saturate(1.4) !important;',
      '  border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;',
      '}',
      '@supports not (backdrop-filter: blur(1px)) {',
      '  header { background: rgba(12, 12, 20, 0.92) !important; }',
      '}',
      /* Drawer */
      '[data-mobile-drawer] {',
      '  background-color: var(--color-primary, #0c0c14) !important;',
      '  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;',
      '}',
      '[data-mobile-backdrop] {',
      '  transition: opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;',
      '}',
      '[data-mobile-drawer] a[data-auth-link] {',
      '  animation: drawerFadeIn 0.2s ease-out both;',
      '}',
      '@keyframes drawerFadeIn {',
      '  from { opacity: 0; transform: translateX(8px); }',
      '  to { opacity: 1; transform: translateX(0); }',
      '}',
      '[data-mobile-drawer] {',
      '  width: 85vw !important;',
      '  max-width: 18rem !important;',
      '}',
      '@media (min-width: 380px) {',
      '  [data-mobile-drawer] { width: 75vw !important; }',
      '}',
      '@media (min-width: 480px) {',
      '  [data-mobile-drawer] { width: 70vw !important; }',
      '}',
      /* Logo sizing */
      'header nav img[alt="AutoAssist"] {',
      '  height: 3rem;',
      '}',
      '@media (min-width: 768px) {',
      '  header nav img[alt="AutoAssist"] { height: 5.5rem; }',
      '}'
    ].join("\n");
    document.head.appendChild(style);

    var hamburger = document.querySelector("[data-hamburger]");
    var drawer = document.querySelector("[data-mobile-drawer]");
    if (!hamburger || !drawer) return;

    // --- Create backdrop if missing ---
    var backdrop = document.querySelector("[data-mobile-backdrop]");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.setAttribute("data-mobile-backdrop", "true");
      backdrop.className = "fixed inset-0 z-[1299] bg-black/60 backdrop-blur-sm opacity-0 pointer-events-none transition-opacity duration-300 md:hidden";
      document.body.appendChild(backdrop);
    }

    // --- Fix X button ---
    var closeBtn = drawer.querySelector("button[aria-label='Fechar menu']");
    if (closeBtn) {
      closeBtn.addEventListener("click", closeDrawer);
    }

    // --- Solid background (override any transparency) ---
    drawer.classList.remove("bg-primary/80", "bg-primary/90", "backdrop-blur-xl");
    drawer.style.backgroundColor = "";

    function openDrawer() {
      drawer.classList.add("translate-x-0");
      drawer.classList.remove("translate-x-full");
      backdrop.classList.remove("pointer-events-none", "opacity-0");
      backdrop.classList.add("pointer-events-auto", "opacity-100");
      document.body.style.overflow = "hidden";
      hamburger.setAttribute("aria-expanded", "true");
      hamburger.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    }

    function closeDrawer() {
      drawer.classList.remove("translate-x-0");
      drawer.classList.add("translate-x-full");
      backdrop.classList.add("pointer-events-none", "opacity-0");
      backdrop.classList.remove("pointer-events-auto", "opacity-100");
      document.body.style.overflow = "";
      hamburger.setAttribute("aria-expanded", "false");
      hamburger.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/></svg>';
    }

    function toggleDrawer() {
      if (drawer.classList.contains("translate-x-0")) {
        closeDrawer();
      } else {
        openDrawer();
      }
    }

    hamburger.addEventListener("click", toggleDrawer);
    backdrop.addEventListener("click", closeDrawer);

    // Close on ESC
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && drawer.classList.contains("translate-x-0")) {
        closeDrawer();
      }
    });

    // Close drawer on nav link click
    drawer.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeDrawer);
    });

    // Desktop: ensure drawer is hidden on md+
    var mql = window.matchMedia("(min-width: 768px)");
    function handleViewport(e) {
      if (e.matches) {
        closeDrawer();
        backdrop.style.display = "none";
        drawer.style.display = "none";
      } else {
        backdrop.style.display = "";
        drawer.style.display = "";
      }
    }
    mql.addEventListener("change", handleViewport);
    handleViewport(mql);

    // --- Active page indicator ---
    markActivePage(drawer);
    markActivePage(document.querySelector("header nav"));

    function markActivePage(container) {
      if (!container) return;
      var path = window.location.pathname.replace(/\/$/, "") || "/";
      container.querySelectorAll("a").forEach(function (a) {
        var href = a.getAttribute("href");
        if (!href) return;
        if (a.querySelector("img[alt='AutoAssist']")) return;
        var cleanHref = href.replace(/\/$/, "") || "/";
        if (cleanHref === path) {
          a.classList.add("bg-accent/10", "text-accent");
          a.classList.remove("text-secondary");
        }
      });
    }

    // --- Auth-aware navbar ---
    updateNavbar();

    function updateNavbar() {
      var isAuth = window.auth && window.auth.isAuthenticated();

      // Desktop nav
      var desktopNav = document.querySelector("header nav > div.hidden.md\\:flex");
      if (desktopNav) {
        toggleAuthLinks(desktopNav, isAuth);
      }

      // Mobile drawer nav links
      var drawerLinks = drawer.querySelector("div.flex.flex-col.gap-1") || drawer;
      toggleAuthLinks(drawerLinks, isAuth);

      // Hide/show footer auth section based on auth state
      var footerAuth = drawer.querySelector("div.shrink-0.border-t");
      if (footerAuth) {
        footerAuth.style.display = isAuth ? "none" : "";
      }
    }

    function toggleAuthLinks(container, isAuth) {
      var links = container.querySelectorAll("a");
      var entrarLink = null;
      var criarLink = null;

      links.forEach(function (a) {
        var href = a.getAttribute("href");
        if (href === "/login") entrarLink = a;
        if (href === "/cadastro") criarLink = a;
      });

      if (isAuth) {
        if (entrarLink) entrarLink.style.display = "none";
        if (criarLink) criarLink.style.display = "none";

        if (!container.querySelector("[data-auth-link]")) {
          var user = window.auth.getUser();
          var name = user ? (user.nome || user.name || "Perfil") : "Perfil";

          var navClass = "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors duration-150 text-secondary hover:bg-white/5 hover:text-primary";
          var iconClass = "lucide h-4 w-4";

          var links_data = [
            { href: "/dashboard", label: "Dashboard", icon: '<rect width="7" height="9" x="3" y="3" rx="1"></rect><rect width="7" height="5" x="14" y="3" rx="1"></rect><rect width="7" height="9" x="14" y="12" rx="1"></rect><rect width="7" height="5" x="3" y="16" rx="1"></rect>' },
            { href: "/anotacoes", label: "Anotações", icon: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>' },
            { href: "/eventos", label: "Eventos", icon: '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line>' },
            { href: "/maps", label: "Mapas", icon: '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle>' },
            { href: "/biblioteca", label: "Biblioteca", icon: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>' },
            { href: "/perfil", label: "Perfil", icon: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle>' }
          ];

          var refNode = entrarLink || criarLink;
          links_data.forEach(function (item) {
            var el = document.createElement("a");
            el.href = item.href;
            el.setAttribute("data-auth-link", "1");
            el.className = navClass;
            el.innerHTML = '<span class="shrink-0"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="' + iconClass + '">' + item.icon + '</svg></span>' + item.label;
            if (refNode) container.insertBefore(el, refNode);
            else container.appendChild(el);
          });

          // Separator before Sair
          var sep = document.createElement("div");
          sep.setAttribute("data-auth-link", "1");
          sep.className = "my-1 border-t border-border/50";
          container.appendChild(sep);

          // Sair link
          var sairLink = document.createElement("a");
          sairLink.href = "#";
          sairLink.setAttribute("data-auth-link", "1");
          sairLink.className = "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-red-400 transition-colors duration-150 hover:bg-red-500/10 hover:text-red-300";
          sairLink.innerHTML = '<span class="shrink-0"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide h-4 w-4"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" x2="9" y1="12" y2="12"></line></svg></span>Sair';
          sairLink.addEventListener("click", function (e) {
            e.preventDefault();
            window.auth.logout();
          });
          container.appendChild(sairLink);
        }
      } else {
        if (entrarLink) entrarLink.style.display = "";
        if (criarLink) criarLink.style.display = "";
        container.querySelectorAll("[data-auth-link]").forEach(function (el) {
          el.remove();
        });
      }
    }

    // --- Service Worker ---
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    }
  });
})();
