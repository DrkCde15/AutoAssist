/**
 * components.js — FAQ accordion, toast, rating stars
 */
(function () {
  "use strict";

  // ── FAQ Accordion ──
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("button[aria-expanded]").forEach(function (btn) {
      var content = btn.parentElement.querySelector(".overflow-hidden");
      var icon = btn.querySelector("svg");
      if (!content) return;

      btn.addEventListener("click", function () {
        var isOpen = btn.getAttribute("aria-expanded") === "true";

        // Close all other accordion items in the same parent section
        var section = btn.closest("section") || btn.closest("div");
        section.querySelectorAll("button[aria-expanded]").forEach(function (otherBtn) {
          if (otherBtn !== btn) {
            otherBtn.setAttribute("aria-expanded", "false");
            var otherContent = otherBtn.parentElement.querySelector(".overflow-hidden");
            if (otherContent) otherContent.style.maxHeight = "0";
            var otherIcon = otherBtn.querySelector("svg");
            if (otherIcon) otherIcon.classList.remove("rotate-180");
          }
        });

        if (isOpen) {
          btn.setAttribute("aria-expanded", "false");
          content.style.maxHeight = "0";
          if (icon) icon.classList.remove("rotate-180");
        } else {
          btn.setAttribute("aria-expanded", "true");
          content.style.maxHeight = content.scrollHeight + "px";
          if (icon) icon.classList.add("rotate-180");
        }
      });

      // Set initial state from HTML
      var initialOpen = btn.getAttribute("aria-expanded") === "true";
      if (initialOpen) {
        content.style.maxHeight = content.scrollHeight + "px";
      } else {
        content.style.maxHeight = "0";
      }
    });
  });

  // ── Toast notification (estilos 100% inline: o styles.css compilado
  // não contém as utilities dinâmicas, então classes Tailwind aqui quebravam)
  window.showToast = function (message, type) {
    type = type || "info";
    var bg = {
      info: "#3b82f6",
      success: "#16a34a",
      error: "#dc2626",
      warning: "#f59e0b",
    }[type] || "#3b82f6";
    var icons = {
      info: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
      success: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
      error: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" x2="9" y1="9" y2="15"/><line x1="9" x2="15" y1="9" y2="15"/></svg>',
      warning: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>',
    };
    var toast = document.createElement("div");
    toast.setAttribute("role", "status");
    toast.style.cssText =
      "position:fixed;bottom:1rem;right:1rem;z-index:20000;display:flex;align-items:center;gap:0.625rem;" +
      "max-width:min(92vw,24rem);padding:0.75rem 1rem;border-radius:0.5rem;border-left:4px solid rgba(255,255,255,0.35);" +
      "background:" + bg + ";color:#fff;font-size:0.875rem;font-weight:500;" +
      "box-shadow:0 10px 25px rgba(0,0,0,0.45);opacity:0;transform:translateY(0.5rem);" +
      "transition:opacity 0.3s ease,transform 0.3s ease;";
    var iconWrap = document.createElement("span");
    iconWrap.style.cssText = "flex-shrink:0;display:flex;";
    iconWrap.innerHTML = icons[type] || icons.info;
    var text = document.createElement("span");
    text.textContent = message;
    toast.appendChild(iconWrap);
    toast.appendChild(text);
    document.body.appendChild(toast);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        toast.style.opacity = "1";
        toast.style.transform = "translateY(0)";
      });
    });

    setTimeout(function () {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(0.5rem)";
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 320);
    }, 3000);
  };

  // ── Rating stars ──
  window.initRatingStars = function (container, options) {
    options = options || {};
    var initial = options.initial || 0;
    var onChange = options.onChange || function () {};
    var current = initial;

    container.innerHTML = "";
    for (var i = 1; i <= 5; i++) {
      var star = document.createElement("button");
      star.type = "button";
      star.dataset.value = i;
      star.className = "text-2xl transition-colors " + (i <= current ? "text-yellow-400" : "text-zinc-600");
      star.textContent = "★";
      star.setAttribute("aria-label", i + " estrela" + (i > 1 ? "s" : ""));

      star.addEventListener("mouseenter", function () {
        var val = parseInt(this.dataset.value);
        container.querySelectorAll("button").forEach(function (s, idx) {
          s.className = "text-2xl transition-colors " + (idx < val ? "text-yellow-400" : "text-zinc-600");
        });
      });

      star.addEventListener("mouseleave", function () {
        container.querySelectorAll("button").forEach(function (s, idx) {
          s.className = "text-2xl transition-colors " + (idx < current ? "text-yellow-400" : "text-zinc-600");
        });
      });

      star.addEventListener("click", function () {
        current = parseInt(this.dataset.value);
        onChange(current);
      });

      container.appendChild(star);
    }

    return {
      getValue: function () {
        return current;
      },
      setValue: function (val) {
        current = val;
        container.querySelectorAll("button").forEach(function (s, idx) {
          s.className = "text-2xl transition-colors " + (idx < val ? "text-yellow-400" : "text-zinc-600");
        });
      },
    };
  };

  // ── Skeleton loaders ──
  window.createSkeletonCard = function () {
    return '<div class="skeleton-card rounded-xl">' +
      '<div class="flex items-start justify-between mb-4">' +
        '<div class="flex-1">' +
          '<div class="skeleton skeleton-text mb-2" style="width:70%"></div>' +
          '<div class="skeleton skeleton-text-sm" style="width:40%"></div>' +
        '</div>' +
        '<div class="skeleton skeleton-text-sm" style="width:3rem;height:1.25rem"></div>' +
      '</div>' +
      '<div class="skeleton rounded-lg mb-4" style="height:3.5rem"></div>' +
      '<div class="grid grid-cols-3 gap-2">' +
        '<div class="skeleton rounded-lg" style="height:2.5rem"></div>' +
        '<div class="skeleton rounded-lg" style="height:2.5rem"></div>' +
        '<div class="skeleton rounded-lg" style="height:2.5rem"></div>' +
      '</div>' +
    '</div>';
  };

  window.createSkeletonStats = function () {
    return '<div class="flex flex-wrap items-center gap-6">' +
      '<div class="flex items-center gap-2"><div class="skeleton skeleton-text-sm" style="width:5rem"></div><div class="skeleton skeleton-text-sm" style="width:2rem"></div></div>' +
      '<div class="flex items-center gap-2"><div class="skeleton skeleton-text-sm" style="width:6rem"></div><div class="skeleton skeleton-text-sm" style="width:4rem"></div></div>' +
      '<div class="flex items-center gap-2"><div class="skeleton skeleton-text-sm" style="width:5rem"></div><div class="skeleton skeleton-text-sm" style="width:2rem"></div></div>' +
    '</div>';
  };
})();
