/**
 * notifications.js — Notification bell, dropdown, unread count, push subscription
 */
(function () {
  "use strict";

  var POLL_INTERVAL = 60000;
  var pollTimer = null;
  var notifPanel = null;
  var notifBell = null;
  var notifBadge = null;
  var panelOpen = false;

  // ── CSS ──
  function injectStyles() {
    if (document.getElementById("notif-css")) return;
    var s = document.createElement("style");
    s.id = "notif-css";
    s.textContent =
      ".notif-bell{position:relative;cursor:pointer;display:flex;align-items:center;justify-content:center;width:2.25rem;height:2.25rem;border-radius:0.5rem;transition:background-color 0.15s}" +
      ".notif-bell:hover{background-color:rgba(255,255,255,0.05)}" +
      ".notif-badge{position:absolute;top:4px;right:4px;min-width:16px;height:16px;padding:0 4px;border-radius:9999px;background-color:var(--color-accent,#3b82f6);color:#fff;font-size:10px;font-weight:600;display:flex;align-items:center;justify-content:center;line-height:1}" +
      ".notif-panel{position:absolute;top:100%;right:0;margin-top:0.5rem;width:380px;max-height:480px;overflow-y:auto;border-radius:0.75rem;border:1px solid var(--color-border,#1e1e2e);background-color:var(--color-bg-primary,#0c0c14);box-shadow:0 20px 40px rgba(0,0,0,0.5);z-index:1200;display:none}" +
      ".notif-panel.open{display:block}" +
      ".notif-item{display:flex;gap:0.75rem;padding:0.75rem 1rem;border-bottom:1px solid var(--color-border,#1e1e2e);cursor:pointer;transition:background-color 0.15s}" +
      ".notif-item:hover{background-color:rgba(255,255,255,0.03)}" +
      ".notif-item.unread{background-color:rgba(59,130,246,0.05)}" +
      ".notif-item:last-child{border-bottom:none}" +
      ".notif-empty{padding:2rem;text-align:center;color:var(--color-text-muted,#666);font-size:0.875rem}" +
      "@media(max-width:640px){.notif-panel{width:calc(100vw - 2rem);right:-0.5rem}}";
    document.head.appendChild(s);
  }

  // ── Build bell + panel ──
  function build() {
    injectStyles();

    var desktopNav = document.querySelector("header nav > div.hidden.md\\:flex");
    if (!desktopNav) return;

    // Bell button
    notifBell = document.createElement("div");
    notifBell.className = "notif-bell";
    notifBell.setAttribute("role", "button");
    notifBell.setAttribute("aria-label", "Notificações");
    notifBell.setAttribute("tabindex", "0");
    notifBell.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-secondary"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>';

    // Badge
    notifBadge = document.createElement("span");
    notifBadge.className = "notif-badge";
    notifBadge.style.display = "none";
    notifBadge.textContent = "0";
    notifBell.appendChild(notifBadge);

    // Panel
    notifPanel = document.createElement("div");
    notifPanel.className = "notif-panel";
    notifPanel.innerHTML = '<div class="notif-empty">Carregando notificações...</div>';
    notifBell.appendChild(notifPanel);

    // Insert bell before the first auth link or at the end
    var refNode = desktopNav.querySelector("a[href='/login']") || desktopNav.lastElementChild;
    desktopNav.insertBefore(notifBell, refNode);

    // Toggle panel
    notifBell.addEventListener("click", function (e) {
      e.stopPropagation();
      if (panelOpen) {
        closePanel();
      } else {
        openPanel();
      }
    });

    // Close on outside click
    document.addEventListener("click", function (e) {
      if (panelOpen && notifPanel && !notifPanel.contains(e.target) && notifBell && !notifBell.contains(e.target)) {
        closePanel();
      }
    });

    // Close on ESC
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && panelOpen) closePanel();
    });
  }

  function openPanel() {
    if (!notifPanel) return;
    notifPanel.classList.add("open");
    panelOpen = true;
    loadNotifications();
  }

  function closePanel() {
    if (!notifPanel) return;
    notifPanel.classList.remove("open");
    panelOpen = false;
  }

  // ── Fetch unread count ──
  function fetchUnreadCount() {
    if (!window.auth || !window.auth.isAuthenticated()) return;
    window.api
      .get("/api/notifications/unread-count")
      .then(function (d) {
        var count = d.count || 0;
        if (notifBadge) {
          notifBadge.textContent = count > 99 ? "99+" : String(count);
          notifBadge.style.display = count > 0 ? "flex" : "none";
        }
      })
      .catch(function () {});
  }

  // ── Load notifications into panel ──
  function loadNotifications() {
    if (!notifPanel) return;
    notifPanel.innerHTML = '<div class="notif-empty">Carregando...</div>';

    window.api
      .get("/api/notifications")
      .then(function (data) {
        var notifs = data || [];
        if (notifs.length === 0) {
          notifPanel.innerHTML =
            '<div class="notif-empty">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="mx-auto mb-2 text-zinc-600"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>' +
              'Nenhuma notificação' +
            '</div>';
          return;
        }

        var html = '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.75rem 1rem;border-bottom:1px solid var(--color-border,#1e1e2e)">' +
          '<span style="font-size:0.875rem;font-weight:600;color:var(--color-text-primary)">Notificações</span>' +
          '<button id="notif-mark-all" style="font-size:0.75rem;color:var(--color-accent);background:none;border:none;cursor:pointer">Marcar todas como lidas</button>' +
        '</div>';

        notifs.forEach(function (n) {
          var unread = !n.is_read;
          var icon = getNotifIcon(n.type);
          var time = formatTime(n.created_at);
          html +=
            '<div class="notif-item' + (unread ? ' unread' : '') + '" data-notif-id="' + n.id + '" data-action="' + escapeAttr(n.action_url || '') + '">' +
              '<div style="shrink-0;width:2rem;height:2rem;border-radius:0.5rem;display:flex;align-items:center;justify-content:center;background-color:rgba(255,255,255,0.05)">' + icon + '</div>' +
              '<div style="flex:1;min-width:0">' +
                '<p style="font-size:0.875rem;font-weight:' + (unread ? '600' : '400') + ';color:var(--color-text-primary);margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHTML(n.title) + '</p>' +
                (n.body ? '<p style="font-size:0.75rem;color:var(--color-text-muted);margin:0.125rem 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHTML(n.body) + '</p>' : '') +
                '<p style="font-size:0.6875rem;color:var(--color-text-muted);margin:0.25rem 0 0">' + time + '</p>' +
              '</div>' +
              '<button data-notif-delete="' + n.id + '" style="shrink:0;background:none;border:none;color:var(--color-text-muted);cursor:pointer;padding:0.25rem;border-radius:0.25rem;transition:color 0.15s" title="Excluir" onclick="event.stopPropagation()">' +
                '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>' +
              '</button>' +
            '</div>';
        });

        notifPanel.innerHTML = html;

        // Mark all as read
        var markAllBtn = notifPanel.querySelector("#notif-mark-all");
        if (markAllBtn) {
          markAllBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            markAllRead();
          });
        }

        // Click on notification
        notifPanel.querySelectorAll(".notif-item").forEach(function (item) {
          item.addEventListener("click", function () {
            var id = item.getAttribute("data-notif-id");
            var url = item.getAttribute("data-action");
            if (id) markAsRead(id);
            if (url) window.location.href = url;
            closePanel();
          });
        });

        // Delete notification buttons
        notifPanel.querySelectorAll("[data-notif-delete]").forEach(function (btn) {
          btn.addEventListener("click", function (e) {
            e.stopPropagation();
            var id = btn.getAttribute("data-notif-delete");
            if (id) deleteNotification(id);
          });
        });
      })
      .catch(function () {
        notifPanel.innerHTML = '<div class="notif-empty">Erro ao carregar notificações</div>';
      });
  }

  function getNotifIcon(type) {
    var icons = {
      info: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-blue-400"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
      warning: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-amber-400"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>',
      fipe: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-green-400"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
      ativo: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-purple-400"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
    };
    return icons[type] || icons.info;
  }

  function formatTime(dateStr) {
    if (!dateStr) return "";
    var d = new Date(dateStr);
    var now = new Date();
    var diff = (now - d) / 1000;
    if (diff < 60) return "Agora";
    if (diff < 3600) return Math.floor(diff / 60) + " min atrás";
    if (diff < 86400) return Math.floor(diff / 3600) + "h atrás";
    if (diff < 604800) return Math.floor(diff / 86400) + "d atrás";
    return d.toLocaleDateString("pt-BR");
  }

  function escapeHTML(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function escapeAttr(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ── API calls ──
  function markAsRead(id) {
    window.api.post("/api/notifications/" + id + "/read").then(function () {
      fetchUnreadCount();
      var item = notifPanel ? notifPanel.querySelector('[data-notif-id="' + id + '"]') : null;
      if (item) item.classList.remove("unread");
    }).catch(function () {});
  }

  function markAllRead() {
    window.api.post("/api/notifications/read-all").then(function () {
      fetchUnreadCount();
      if (notifPanel) notifPanel.querySelectorAll(".unread").forEach(function (el) {
        el.classList.remove("unread");
      });
    }).catch(function () {});
  }

  function deleteNotification(id) {
    window.api.delete("/api/notifications/" + id).then(function () {
      var item = notifPanel ? notifPanel.querySelector('[data-notif-id="' + id + '"]') : null;
      if (item) item.remove();
      fetchUnreadCount();
    }).catch(function () {});
  }

  function unsubscribePush(endpoint) {
    return window.api.post("/api/push/unsubscribe", endpoint ? { endpoint: endpoint } : {});
  }

  // ── Push subscription ──
  function initPush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    if (!window.auth || !window.auth.isAuthenticated()) return;

    navigator.serviceWorker.ready.then(function (reg) {
      return reg.pushManager.getSubscription();
    }).then(function (sub) {
      if (sub) return;
      return window.api.get("/api/push/vapid-public-key").then(function (d) {
        var key = d.public_key;
        if (!key) return;
        var applicationServerKey = urlBase64ToUint8Array(key);
        return navigator.serviceWorker.ready.then(function (reg) {
          return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: applicationServerKey });
        });
      }).then(function (sub) {
        if (!sub) return;
        var p = sub.toJSON();
        return window.api.post("/api/push/subscribe", {
          endpoint: p.endpoint,
          p256dh: btoa(String.fromCharCode.apply(null, new Uint8Array(p.keys.p256dh))),
          auth: btoa(String.fromCharCode.apply(null, new Uint8Array(p.keys.auth)))
        });
      }).catch(function () {});
    }).catch(function () {});
  }

  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var rawData = atob(base64);
    var arr = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; i++) {
      arr[i] = rawData.charCodeAt(i);
    }
    return arr;
  }

  // ── Init ──
  function init() {
    if (!window.auth || !window.auth.isAuthenticated()) return;
    build();
    fetchUnreadCount();
    initPush();
    pollTimer = setInterval(fetchUnreadCount, POLL_INTERVAL);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
