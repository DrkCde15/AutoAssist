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
      <button type="button" class="notif-bell-btn" id="notifBellBtn" aria-label="Notificações">
        <i class="fas fa-bell"></i>
        <span class="notif-badge hidden" id="notifBadge">0</span>
      </button>
      <div class="notif-panel" id="notifPanel">
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
      panel.classList.toggle("is-open");
      if (panel.classList.contains("is-open")) {
        fetchNotifications();
      }
    });

    document.addEventListener("click", (e) => {
      if (!container.contains(e.target)) {
        panel.classList.remove("is-open");
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
        </div>
      `;
    }).join("");

    list.querySelectorAll(".notif-item.unread").forEach((el) => {
      el.addEventListener("click", async () => {
        const id = el.dataset.id;
        try {
          await Auth.authenticatedFetch(`/api/notifications/${id}/read`, { method: "POST" });
          el.classList.remove("unread");
          unreadCount = Math.max(0, unreadCount - 1);
          updateBadge();
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

  function init() {
    if (typeof Auth === "undefined" || !Auth.isAuthenticated()) return;
    if (document.getElementById("notif-bell-container")) {
      createBell();
      fetchUnreadCount();
      pollInterval = setInterval(fetchUnreadCount, 30000);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return { init, fetchUnreadCount };
})();
