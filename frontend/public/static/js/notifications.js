const Notifications = (() => {
  let unreadCount = 0;
  let pollInterval = null;

  function escapeHTML(str) {
    if (!str) return "";
    return str.toString()
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function timeAgo(dateStr) {
    if (!dateStr) return "";
    const now = Date.now();
    const then = new Date(dateStr).getTime();
    const diff = Math.floor((now - then) / 1000);
    if (diff < 60) return "agora";
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    const days = Math.floor(diff / 86400);
    if (days < 7) return `${days}d`;
    return new Date(dateStr).toLocaleDateString("pt-BR");
  }

  function createBell() {
    const container = document.getElementById("notif-bell-container");
    if (!container) return;

    const bell = document.createElement("div");
    bell.style.cssText = "position:relative;display:inline-flex;align-items:center;";

    bell.innerHTML = `
      <button type="button" class="nav-bell-btn notif-bell-btn" id="notifBellBtn" aria-label="Notificações">
        <i class="fas fa-bell"></i>
        <span class="notif-badge hidden" id="notifBadge">0</span>
      </button>
      <div class="notification-panel notif-panel" id="notifPanel">
        <div class="notif-panel-header">
          <span class="notif-panel-title">Notificações</span>
          <div class="notif-panel-actions">
            <button type="button" class="notif-btn-mark-read" id="notifMarkAllRead">Marcar todas como lidas</button>
          </div>
        </div>
        <div class="notif-list" id="notifList">
          <div class="notif-empty">Nenhuma notificação</div>
        </div>
      </div>
    `;

    container.appendChild(bell);

    const btn = document.getElementById("notifBellBtn");
    const panel = document.getElementById("notifPanel");
    const badge = document.getElementById("notifBadge");
    const list = document.getElementById("notifList");
    const markAllBtn = document.getElementById("notifMarkAllRead");

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const shouldOpen = !panel.classList.contains("is-open");
      panel.classList.toggle("is-open", shouldOpen);
      panel.classList.toggle("open", shouldOpen);
      if (shouldOpen) {
        fetchNotifications();
      }
    });

    document.addEventListener("click", (e) => {
      if (!container.contains(e.target)) {
        panel.classList.remove("is-open");
        panel.classList.remove("open");
      }
    });

    markAllBtn.addEventListener("click", async () => {
      try {
        await Auth.authenticatedFetch("/api/notifications/read-all", { method: "POST" });
        unreadCount = 0;
        updateBadge();
        document.querySelectorAll(".notif-item.unread").forEach((el) => el.classList.remove("unread"));
        markAllBtn.style.display = "none";
      } catch {}
    });

    return { panel, badge, list };
  }

  async function fetchNotifications() {
    try {
      const res = await Auth.authenticatedFetch("/api/notifications", { redirectOnInvalid: false });
      if (!res.ok) return;
      const data = await res.json();
      renderList(data);
    } catch {}
  }

  function renderList(notifs) {
    const list = document.getElementById("notifList");
    const markAllBtn = document.getElementById("notifMarkAllRead");
    if (!list) return;

    if (!notifs || notifs.length === 0) {
      list.innerHTML = '<div class="notif-empty">Nenhuma notificação</div>';
      if (markAllBtn) markAllBtn.style.display = "none";
      return;
    }

    if (markAllBtn) markAllBtn.style.display = unreadCount > 0 ? "" : "none";

    list.innerHTML = notifs.map((n) => {
      const iconMap = { info: "fa-info-circle", warning: "fa-exclamation-triangle", success: "fa-check-circle", error: "fa-times-circle" };
      const icon = iconMap[n.type] || "fa-bell";
      return `
        <div class="notif-item ${n.is_read ? "" : "unread"}" data-id="${n.id}">
          <div class="notif-icon ${n.type || "info"}"><i class="fas ${icon}"></i></div>
          <div class="notif-item-content">
            <div class="notif-item-title">${escapeHTML(n.title)}</div>
            ${n.body ? `<div class="notif-item-body">${escapeHTML(n.body)}</div>` : ""}
            <div class="notif-item-time">${timeAgo(n.created_at)}</div>
          </div>
          <button class="notif-delete-btn" data-id="${n.id}" title="Excluir notificação"><i class="fas fa-trash"></i></button>
        </div>
      `;
    }).join("");

    list.querySelectorAll(".notif-item.unread").forEach((el) => {
      el.addEventListener("click", async (e) => {
        if (e.target.closest(".notif-delete-btn")) return;
        const id = el.dataset.id;
        try {
          await Auth.authenticatedFetch(`/api/notifications/${id}/read`, { method: "POST" });
          el.classList.remove("unread");
          unreadCount = Math.max(0, unreadCount - 1);
          updateBadge();
        } catch {}
      });
    });

    list.querySelectorAll(".notif-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = btn.dataset.id;
        try {
          const res = await Auth.authenticatedFetch(`/api/notifications/${id}`, { method: "DELETE" });
          if (res.ok) {
            const item = btn.closest(".notif-item");
            if (item.classList.contains("unread")) {
              unreadCount = Math.max(0, unreadCount - 1);
            }
            item.remove();
            updateBadge();
            if (!list.querySelector(".notif-item")) {
              list.innerHTML = '<div class="notif-empty">Nenhuma notificação</div>';
              const markAllBtn = document.getElementById("notifMarkAllRead");
              if (markAllBtn) markAllBtn.style.display = "none";
            }
          }
        } catch {}
      });
    });
  }

  async function fetchUnreadCount() {
    try {
      const res = await Auth.authenticatedFetch("/api/notifications/unread-count", { redirectOnInvalid: false });
      if (!res.ok) return;
      const data = await res.json();
      unreadCount = data.count || 0;
      updateBadge();
    } catch {}
  }

  function updateBadge() {
    const badge = document.getElementById("notifBadge");
    if (!badge) return;
    if (unreadCount > 0) {
      badge.textContent = unreadCount > 99 ? "99+" : unreadCount;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  }

  /* ── Push Notification Subscription ── */

  function urlBase64ToUint8Array(base64) {
    const padding = "=".repeat((4 - (base64.length % 4)) % 4);
    const raw = atob(base64.replace(/-/g, "+").replace(/_/g, "/") + padding);
    return Uint8Array.from(raw.split("").map((c) => c.charCodeAt(0)));
  }

  async function getVapidPublicKey() {
    try {
      const res = await Auth.authenticatedFetch("/api/push/vapid-public-key", { redirectOnInvalid: false });
      if (!res.ok) return null;
      const data = await res.json();
      return data.publicKey || null;
    } catch {
      return null;
    }
  }

  async function subscribeToPush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;

    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (subscription) return subscription;

    const publicKey = await getVapidPublicKey();
    if (!publicKey) return;

    try {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
      await Auth.authenticatedFetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(subscription.toJSON()),
        redirectOnInvalid: false,
      });
    } catch {}
  }

  async function unsubscribeFromPush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      if (!subscription) return;
      await subscription.unsubscribe();
      await Auth.authenticatedFetch("/api/push/unsubscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: subscription.endpoint }),
        redirectOnInvalid: false,
      });
    } catch {}
  }

  async function requestPushPermission() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      await subscribeToPush();
      return;
    }
    if (Notification.permission === "denied") return;
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      await subscribeToPush();
    }
  }

  /* ── Init ── */

  function init() {
    if (typeof Auth === "undefined" || !Auth.isAuthenticated()) return;
    if (document.getElementById("notif-bell-container")) {
      createBell();
      fetchUnreadCount();
      pollInterval = setInterval(fetchUnreadCount, 30000);
      requestPushPermission();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return { init, fetchUnreadCount, requestPushPermission, subscribeToPush, unsubscribeFromPush };
})();
