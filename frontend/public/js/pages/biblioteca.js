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

  function extractDomain(url) {
    try { return new URL(url).hostname.replace("www.", ""); } catch (_) { return ""; }
  }

  // ── SVG Icons ──
  var ICONS = {
    play: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>',
    videoIcon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"></path><rect x="2" y="6" width="14" height="12" rx="2"></rect></svg>',
    wrench: '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>',
    car: '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.5 2.8C1.4 11.3 1 12.2 1 13v3c0 .6.4 1 1 1h2"></path><circle cx="7" cy="17" r="2"></circle><path d="M9 17h6"></path><circle cx="17" cy="17" r="2"></circle></svg>',
    linkIcon: '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>',
    arrow: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"></path><path d="m12 5 7 7-7 7"></path></svg>',
    book: '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"></path></svg>',
    trash: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path><line x1="10" x2="10" y1="11" y2="17"></line><line x1="14" x2="14" y1="11" y2="17"></line></svg>',
    folder: '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"></path></svg>',
  };

  // ── Render helpers ──
  function renderSpinner() {
    return (
      '<div class="flex items-center justify-center py-16">' +
      '<div class="flex flex-col items-center gap-2.5">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="animate-spin text-accent"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>' +
      '<p class="text-xs text-muted">Carregando...</p>' +
      '</div>' +
      '</div>'
    );
  }

  function renderEmptyState(label) {
    return (
      '<div class="flex flex-col items-center justify-center py-16 text-center">' +
      '<div class="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-800/50 text-zinc-600">' +
      ICONS.folder +
      '</div>' +
      '<p class="text-sm font-medium text-secondary">' + escapeHTML(label) + '</p>' +
      '<p class="mt-1 text-xs text-muted">Converse com o NOG para gerar conteúdo.</p>' +
      '</div>'
    );
  }

  function renderError(msg) {
    return (
      '<div class="flex flex-col items-center justify-center py-16 text-center">' +
      '<div class="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-red-500/10 text-red-400">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" x2="9" y1="9" y2="15"></line><line x1="9" x2="15" y1="9" y2="15"></line></svg>' +
      '</div>' +
      '<p class="text-sm font-medium text-red-400">' + escapeHTML(msg) + '</p>' +
      '<p class="mt-1 text-xs text-muted">Verifique sua conexão e tente novamente.</p>' +
      '</div>'
    );
  }

  // ── Section Header ──
  function sectionHeader(title, count) {
    return (
      '<div class="flex items-baseline justify-between pb-2 pt-1">' +
        '<h2 class="text-xs font-semibold uppercase tracking-wider text-muted/70">' + title + '</h2>' +
        (count != null ? '<span class="text-[11px] text-muted/50">' + count + '</span>' : '') +
      '</div>' +
      '<div class="mb-3 h-px w-full bg-border/30"></div>'
    );
  }

  // ── Video Card ──
  function videoCard(video, opts) {
    opts = opts || {};
    var thumb = youtubeThumbnail(video.url);
    var title = escapeHTML(video.titulo || "Vídeo");
    var url = escapeHTML(video.url || "#");
    var showDelete = !!opts.deletable;
    var videoId = video.id || "";

    var previewInner = "";
    if (thumb) {
      previewInner =
        '<img src="' + thumb + '" alt="' + title + '" class="h-full w-full object-cover" loading="lazy" />';
    } else {
      previewInner =
        '<div class="absolute inset-0" style="background:linear-gradient(135deg,#1a1a2e,#16162a,#0f0f1a)"></div>' +
        '<div class="absolute inset-0" style="opacity:0.03;background-image:radial-gradient(circle at 1px 1px,white 1px,transparent 0);background-size:24px 24px"></div>' +
        '<div class="relative z-10 flex h-full w-full flex-col items-center justify-center gap-2">' +
          '<div class="flex h-12 w-12 items-center justify-center rounded-full" style="background:rgba(255,255,255,0.07);color:rgba(255,255,255,0.4)">' +
            ICONS.play +
          '</div>' +
          '<span class="text-xs font-medium" style="color:rgba(255,255,255,0.25)">Vídeo</span>' +
        '</div>';
    }

    var deleteBtn = "";
    if (showDelete) {
      deleteBtn =
        '<button type="button" class="delete-video-btn absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded-md opacity-0 transition-opacity duration-150 group-hover:opacity-100" style="background:rgba(0,0,0,0.5);color:rgba(255,255,255,0.5);z-index:30" data-video-id="' + videoId + '" title="Excluir">' +
          ICONS.trash +
        '</button>';
    }

    return (
      '<div class="group relative flex flex-col overflow-hidden rounded-xl" style="border:1px solid rgba(255,255,255,0.06);background:#111119;transition:all 200ms ease" onmouseenter="this.style.transform=\'translateY(-2px)\';this.style.borderColor=\'rgba(255,255,255,0.12)\';this.style.boxShadow=\'0 8px 24px rgba(0,0,0,0.3)\'" onmouseleave="this.style.transform=\'\';this.style.borderColor=\'rgba(255,255,255,0.06)\';this.style.boxShadow=\'\'">' +
        deleteBtn +
        '<a href="' + url + '" target="_blank" rel="noopener noreferrer" class="relative block w-full overflow-hidden" style="aspect-ratio:16/9;background:#0f0f1a">' +
          previewInner +
          '<div class="absolute inset-0" style="background:linear-gradient(to top,rgba(0,0,0,0.5),rgba(0,0,0,0.1) 40%,transparent)"></div>' +
          '<div class="absolute inset-0 z-20 flex items-center justify-center opacity-80 transition-opacity duration-200 group-hover:opacity-100">' +
            '<div class="flex items-center justify-center rounded-full shadow-lg transition-transform duration-200 group-hover:scale-110" style="width:48px;height:48px;background:rgba(0,0,0,0.4);color:white;backdrop-filter:blur(8px)">' +
              ICONS.play +
            '</div>' +
          '</div>' +
        '</a>' +
        '<div class="px-4 py-3" style="border-top:1px solid rgba(255,255,255,0.04)">' +
          '<h3 class="line-clamp-2 font-medium" style="font-size:14px;line-height:1.5;color:rgba(250,250,250,0.85);margin:0">' + title + '</h3>' +
          '<span class="text-xs" style="display:block;margin-top:4px;color:rgba(255,255,255,0.4)">YouTube</span>' +
        '</div>' +
      '</div>'
    );
  }

  // ── Link Card ──
  function linkCard(link) {
    var url = escapeHTML(link.url || "#");
    var title = escapeHTML(link.title || link.name || "Link");
    var domain = extractDomain(link.url);
    var tipo = link.tipo || "link";

    var iconSvg, iconBg, iconColor, badgeBg, badgeColor, tipoLabel;
    if (tipo === "veiculo") {
      iconSvg = ICONS.car;
      iconBg = "bg-blue-500/10";
      iconColor = "text-blue-400";
      badgeBg = "bg-blue-500/10";
      badgeColor = "text-blue-400";
      tipoLabel = "Veículo";
    } else if (tipo === "peca") {
      iconSvg = ICONS.wrench;
      iconBg = "bg-emerald-500/10";
      iconColor = "text-emerald-400";
      badgeBg = "bg-emerald-500/10";
      badgeColor = "text-emerald-400";
      tipoLabel = "Peça";
    } else {
      iconSvg = ICONS.linkIcon;
      iconBg = "bg-accent/10";
      iconColor = "text-accent";
      badgeBg = "bg-accent/10";
      badgeColor = "text-accent";
      tipoLabel = "Link";
    }

    return (
      '<a href="' + url + '" target="_blank" rel="noopener noreferrer" class="group flex items-center gap-3 rounded-xl border border-white/[0.06] bg-[#111119] px-3.5 py-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-white/[0.12] hover:bg-[#15151f] hover:shadow-md hover:shadow-black/15">' +
        '<div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ' + iconBg + ' ' + iconColor + '">' + iconSvg + '</div>' +
        '<div class="flex min-w-0 flex-1 flex-col gap-0.5">' +
          '<p class="text-[13px] font-medium text-primary/80 truncate transition-colors group-hover:text-primary">' + title + '</p>' +
          (domain ? '<p class="text-[11px] text-muted truncate">' + escapeHTML(domain) + '</p>' : '') +
        '</div>' +
        '<span class="shrink-0 rounded-md ' + badgeBg + ' px-2 py-0.5 text-[10px] font-medium ' + badgeColor + '">' + tipoLabel + '</span>' +
        '<div class="shrink-0 text-muted/30 transition-all duration-200 group-hover:text-muted/70 group-hover:translate-x-0.5">' + ICONS.arrow + '</div>' +
      '</a>'
    );
  }

  // ── Summary Panel ──
  function summaryPanel(totalVideos, totalLinks) {
    var total = totalVideos + totalLinks;
    return (
      '<div class="mb-8 flex flex-col gap-3 rounded-xl border border-white/[0.06] bg-[#111119] p-4 sm:flex-row sm:items-center sm:gap-5">' +
        '<div class="flex items-center gap-3">' +
          '<div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">' +
            ICONS.book +
          '</div>' +
          '<div>' +
            '<p class="text-[11px] font-medium uppercase tracking-wider text-muted/50">Biblioteca</p>' +
            '<p class="text-lg font-bold leading-tight text-primary/90">' + total + ' <span class="text-sm font-medium text-muted">itens</span></p>' +
          '</div>' +
        '</div>' +
        '<div class="hidden h-8 w-px bg-white/[0.06] sm:block"></div>' +
        '<div class="flex items-center gap-4">' +
          (totalVideos ? '<div class="flex items-center gap-2"><span class="flex h-2 w-2 items-center justify-center rounded-full bg-red-400/80"><span class="h-1 w-1 rounded-full bg-red-300"></span></span><span class="text-[13px] font-medium text-secondary/70">' + totalVideos + ' <span class="text-muted">vídeo' + (totalVideos !== 1 ? 's' : '') + '</span></span></div>' : '') +
          (totalLinks ? '<div class="flex items-center gap-2"><span class="flex h-2 w-2 items-center justify-center rounded-full bg-accent/80"><span class="h-1 w-1 rounded-full bg-accent/50"></span></span><span class="text-[13px] font-medium text-secondary/70">' + totalLinks + ' <span class="text-muted">link' + (totalLinks !== 1 ? 's' : '') + '</span></span></div>' : '') +
        '</div>' +
      '</div>'
    );
  }

  // ── Build page structure ──
  function buildPage() {
    mainEl = document.querySelector("main");
    if (!mainEl) return false;

    mainEl.innerHTML =
      '<section class="relative min-h-screen bg-primary pb-20">' +
        '<div class="mx-auto max-w-6xl px-4 pt-8 sm:px-6 sm:pt-10 lg:px-8">' +
          '<div class="mb-6">' +
            '<h1 class="text-xl font-bold tracking-tight text-primary sm:text-2xl">Biblioteca de Vídeos</h1>' +
            '<p class="mt-1 text-[13px] text-secondary/60">Vídeos e links organizados por tópico, coletados nas suas conversas com a IA.</p>' +
          '</div>' +
          '<div id="biblioteca-summary"></div>' +
          '<div id="library-section">' +
            '<div id="library-grid" class="flex flex-col gap-6"></div>' +
          '</div>' +
        '</div>' +
      '</section>';

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
        if (savedCountEl) savedCountEl.textContent = videos.length ? videos.length : "";
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
        var allVideos = [];
        var allLinks = [];

        for (var i = 0; i < library.length; i++) {
          var group = library[i];
          var vids = group.videos || [];
          var lnks = group.links || [];
          for (var j = 0; j < vids.length; j++) {
            allVideos.push(vids[j]);
          }
          for (var k = 0; k < lnks.length; k++) {
            allLinks.push(lnks[k]);
          }
        }

        var totalVideos = allVideos.length;
        var totalLinks = allLinks.length;

        // Summary
        var summaryEl = document.getElementById("biblioteca-summary");
        if (summaryEl) {
          summaryEl.innerHTML = summaryPanel(totalVideos, totalLinks);
        }

        if (libraryCountEl) libraryCountEl.textContent = (totalVideos + totalLinks) ? (totalVideos + totalLinks) : "";

        if (totalVideos + totalLinks === 0) {
          libraryGrid.innerHTML = renderEmptyState("Nenhum conteúdo encontrado nas suas conversas.");
          return;
        }

        var html = "";

        // ── Videos Section ──
        if (totalVideos) {
          html += '<div>' + sectionHeader("Vídeos", totalVideos);
          html += '<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">';
          for (var v = 0; v < allVideos.length; v++) {
            html += videoCard(allVideos[v]);
          }
          html += '</div></div>';
        }

        // ── Links Section ──
        if (totalLinks) {
          html += '<div>' + sectionHeader("Links", totalLinks);
          html += '<div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">';
          for (var l = 0; l < allLinks.length; l++) {
            html += linkCard(allLinks[l]);
          }
          html += '</div></div>';
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
      '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>';

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
        btn.innerHTML = ICONS.trash;
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
        '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>' +
        " Salvando...";
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
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"></path><path d="M12 5v14"></path></svg>' +
            " Salvar vídeo";
        }
      });
  }

  // ── Init ──
  function init() {
    if (!window.auth.requireAuth()) return;
    if (window.premiumModal && !window.premiumModal.requirePremium()) return;
    if (!buildPage()) return;

    fetchLibrary();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
