/**
 * biblioteca.js — Biblioteca de Vídeos
 * Fetches video library (grouped by topic) and saved videos,
 * renders cards with thumbnails, handles save/delete forms.
 */
(function () {
  "use strict";

  var LIBRARY_ENDPOINT = "/api/videos/library";
  var SAVED_ENDPOINT = "/api/videos";

  var mainEl = null;
  var savedGrid = null;
  var libraryGrid = null;
  var form = null;
  var savedSection = null;
  var librarySection = null;
  var savedCountEl = null;
  var libraryCountEl = null;

  // ── Helpers ──
  function escapeHTML(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(message, type) {
    if (window.components && window.components.toast) {
      window.components.toast(message, type);
    } else if (window.showToast) {
      window.showToast(message, type);
    }
  }

  function extractYouTubeId(url) {
    if (!url) return null;
    var match = url.match(
      /(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/
    );
    return match ? match[1] : null;
  }

  function youtubeThumbnail(url) {
    var id = extractYouTubeId(url);
    return id ? "https://img.youtube.com/vi/" + id + "/mqdefault.jpg" : null;
  }

  function formatDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    var day = String(d.getDate()).padStart(2, "0");
    var mon = String(d.getMonth() + 1).padStart(2, "0");
    var year = d.getFullYear();
    return day + "/" + mon + "/" + year;
  }

  // ── Render helpers ──
  function renderSpinner() {
    return (
      '<div class="flex items-center justify-center py-12">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-circle animate-spin text-accent" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>' +
      "</div>"
    );
  }

  function renderEmptyState(label) {
    return (
      '<div class="col-span-full flex flex-col items-center justify-center py-12 text-center">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="mb-3 text-zinc-600"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line></svg>' +
      '<p class="text-sm font-medium text-secondary">' + escapeHTML(label) + "</p>" +
      "</div>"
    );
  }

  function renderError(msg) {
    return (
      '<div class="col-span-full flex flex-col items-center justify-center py-12 text-center">' +
      '<p class="text-sm font-medium text-red-400">' + escapeHTML(msg) + "</p>" +
      '<p class="mt-1 text-xs text-muted">Verifique sua conexão e tente novamente.</p>' +
      "</div>"
    );
  }

  function videoCard(video, opts) {
    opts = opts || {};
    var thumb = youtubeThumbnail(video.url);
    var title = escapeHTML(video.titulo || "Vídeo");
    var url = escapeHTML(video.url || "#");
    var desc = escapeHTML(video.descricao || "");
    var topic = escapeHTML(video.topic || video.titulo || "");
    var showDelete = !!opts.deletable;
    var videoId = video.id || "";

    var imgHTML = "";
    if (thumb) {
      imgHTML =
        '<a href="' + url + '" target="_blank" rel="noopener noreferrer" class="relative block h-40 w-full overflow-hidden bg-zinc-800 group">' +
        '<img src="' + thumb + '" alt="' + title + '" class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" loading="lazy" />' +
        '<div class="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="currentColor" class="text-white"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>' +
        "</div>" +
        "</a>";
    } else {
      imgHTML =
        '<a href="' + url + '" target="_blank" rel="noopener noreferrer" class="flex h-40 w-full items-center justify-center bg-gradient-to-br from-zinc-800 to-zinc-900">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="text-zinc-600"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line></svg>' +
        "</a>";
    }

    var deleteBtn = "";
    if (showDelete) {
      deleteBtn =
        '<button type="button" class="delete-video-btn ml-auto flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-red-500/10 hover:text-red-400" data-video-id="' + videoId + '" title="Excluir">' +
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash-2"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path><line x1="10" x2="10" y1="11" y2="17"></line><line x1="14" x2="14" y1="11" y2="17"></line></svg>' +
        "</button>";
    }

    return (
      '<div class="group flex flex-col overflow-hidden rounded-2xl border border-border bg-card transition-all duration-200 hover:border-zinc-600 hover:shadow-lg hover:shadow-black/20">' +
      imgHTML +
      '<div class="flex flex-1 flex-col gap-1.5 p-4">' +
      '<div class="flex items-start gap-2">' +
      '<h3 class="min-w-0 flex-1 line-clamp-2 text-sm font-semibold leading-snug text-primary group-hover:text-accent transition-colors">' + title + "</h3>" +
      deleteBtn +
      "</div>" +
      (desc ? '<p class="line-clamp-2 text-xs text-muted leading-relaxed">' + desc + "</p>" : "") +
      (topic && topic !== title
        ? '<span class="mt-auto inline-flex w-fit items-center rounded-md bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">' + topic + "</span>"
        : "") +
      "</div>" +
      "</div>"
    );
  }

  // ── Build page structure ──
  function buildPage() {
    mainEl = document.querySelector("main");
    if (!mainEl) return false;

    mainEl.innerHTML =
      '<section class="relative min-h-screen overflow-hidden bg-primary pb-24">' +
      '<div class="section__wrap mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-10">' +
      // Header
      '<div class="section__header mb-8">' +
      '<h1 class="text-3xl font-bold tracking-tight text-primary sm:text-4xl">Biblioteca de Vídeos</h1>' +
      '<p class="mt-2 text-secondary">Vídeos e links organizados por tópico, coletados automaticamente nas suas conversas com a IA.</p>' +
      "</div>" +
      // Library section
      '<div id="library-section">' +
      '<div id="library-grid" class="grid gap-5 sm:grid-cols-2 lg:grid-cols-3"></div>' +
      "</div>" +
      "</div>" +
      "</section>";

    libraryGrid = document.getElementById("library-grid");
    librarySection = document.getElementById("library-section");

    return true;
  }

  // ── Fetch saved videos ──
  function fetchSaved() {
    if (!savedGrid) return;
    savedGrid.innerHTML = renderSpinner();

    window.api
      .get(SAVED_ENDPOINT)
      .then(function (res) {
        var videos = res.videos || [];
        savedCountEl.textContent = videos.length ? videos.length : "";
        if (videos.length === 0) {
          savedGrid.innerHTML = renderEmptyState("Nenhum vídeo salvo ainda.");
          return;
        }
        var html = "";
        for (var i = 0; i < videos.length; i++) {
          html += videoCard(videos[i], { deletable: true });
        }
        savedGrid.innerHTML = html;
        attachDeleteHandlers();
      })
      .catch(function (err) {
        console.error("[biblioteca] saved fetch error:", err);
        savedGrid.innerHTML = renderError(err.message || "Erro ao carregar vídeos salvos");
      });
  }

  // ── Fetch library (from chat) ──
  function fetchLibrary() {
    if (!libraryGrid) return;
    libraryGrid.innerHTML = renderSpinner();

    window.api
      .get(LIBRARY_ENDPOINT)
      .then(function (res) {
        var library = res.library || [];
        var totalCount = 0;
        var html = "";

        for (var i = 0; i < library.length; i++) {
          var group = library[i];
          var videos = group.videos || [];
          var links = group.links || [];
          totalCount += videos.length + links.length;

          // Topic header
          html +=
            '<div class="col-span-full pt-4 pb-1">' +
            '<h3 class="flex items-center gap-2 text-base font-semibold text-primary">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-accent"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"></path></svg>' +
            escapeHTML(group.topic) +
            (group.last_updated
              ? '<span class="ml-2 text-xs font-normal text-muted">· ' + formatDate(group.last_updated) + "</span>"
              : "") +
            "</h3>" +
            "</div>";

          for (var j = 0; j < videos.length; j++) {
            html += videoCard(videos[j]);
          }
          for (var k = 0; k < links.length; k++) {
            html += videoCard(links[k]);
          }
        }

        libraryCountEl.textContent = totalCount ? totalCount : "";

        if (totalCount === 0) {
          libraryGrid.innerHTML = renderEmptyState("Nenhum vídeo encontrado nas suas conversas.");
          return;
        }

        libraryGrid.innerHTML = html;
      })
      .catch(function (err) {
        console.error("[biblioteca] library fetch error:", err);
        libraryGrid.innerHTML = renderError(err.message || "Erro ao carregar biblioteca");
      });
  }

  // ── Delete handlers ──
  function attachDeleteHandlers() {
    var buttons = savedGrid.querySelectorAll(".delete-video-btn");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var videoId = btn.getAttribute("data-video-id");
        if (!videoId) return;
        deleteVideo(videoId, btn);
      });
    });
  }

  function deleteVideo(videoId, btn) {
    btn.disabled = true;
    btn.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>';

    window.api
      .delete(SAVED_ENDPOINT + "/" + videoId)
      .then(function () {
        toast("Vídeo excluído com sucesso.", "success");
        fetchSaved();
      })
      .catch(function (err) {
        console.error("[biblioteca] delete error:", err);
        toast(err.message || "Erro ao excluir vídeo.", "error");
        btn.disabled = false;
        btn.innerHTML =
          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path><line x1="10" x2="10" y1="11" y2="17"></line><line x1="14" x2="14" y1="11" y2="17"></line></svg>';
      });
  }

  // ── Save form submit ──
  function handleSubmit(e) {
    e.preventDefault();
    if (!form) return;

    var titulo = form.querySelector('input[name="titulo"]');
    var url = form.querySelector('input[name="url"]');
    var descricao = form.querySelector('input[name="descricao"]');
    var submitBtn = document.getElementById("biblioteca-submit");

    var payload = {
      titulo: titulo ? titulo.value.trim() : "",
      url: url ? url.value.trim() : "",
      descricao: descricao ? descricao.value.trim() : "",
    };

    if (!payload.titulo || !payload.url) {
      toast("Título e URL são obrigatórios.", "error");
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>' +
        "Salvando...";
    }

    window.api
      .post(SAVED_ENDPOINT, payload)
      .then(function () {
        toast("Vídeo salvo com sucesso!", "success");
        form.reset();
        fetchSaved();
      })
      .catch(function (err) {
        console.error("[biblioteca] save error:", err);
        toast(err.message || "Erro ao salvar vídeo. Tente novamente.", "error");
      })
      .finally(function () {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML =
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"></path><path d="M12 5v14"></path></svg>' +
            "Salvar vídeo";
        }
      });
  }

  // ── Init ──
  function init() {
    if (!window.auth.requireAuth()) return;
    if (!buildPage()) return;

    fetchLibrary();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
