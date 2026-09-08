/**
 * feedback.js — Página de feedback: estrelas, formulário e lista de feedbacks
 */
(function () {
  "use strict";

  var selectedStars = 0;
  var starButtons = [];
  var form = null;
  var feedbackList = null;
  var submitBtn = null;

  function toast(message, type) {
    if (window.components && window.components.toast) {
      window.components.toast(message, type);
    } else if (window.showToast) {
      window.showToast(message, type);
    }
  }

  function formatDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    var day = String(d.getDate()).padStart(2, "0");
    var mon = String(d.getMonth() + 1).padStart(2, "0");
    var year = d.getFullYear();
    return day + "/" + mon + "/" + year;
  }

  function starsHTML(count) {
    var html = "";
    for (var i = 1; i <= 5; i++) {
      var cls = i <= count ? "text-yellow-400" : "text-muted";
      html +=
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-star ' + cls + '" aria-hidden="true"><path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"></path></svg>';
    }
    return html;
  }

  function escapeHTML(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function renderFeedbacks(feedbacks) {
    if (!feedbackList) return;
    if (!feedbacks || feedbacks.length === 0) {
      feedbackList.innerHTML =
        '<p class="text-muted text-sm text-center py-8">Nenhum feedback ainda. Seja o primeiro!</p>';
      return;
    }
    var html = "";
    for (var i = 0; i < feedbacks.length; i++) {
      var fb = feedbacks[i];
      var nome = fb.nome || "Anônimo";
      var initials = nome
        .split(" ")
        .map(function (w) { return w.charAt(0); })
        .join("")
        .substring(0, 2)
        .toUpperCase();
      html +=
        '<div class="rounded-xl border border-border bg-secondary p-4 transition-all duration-200 hover:border-border-hover hover:-translate-y-0.5">' +
        '<div class="flex items-start gap-3">' +
        '<div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent text-xs font-bold">' +
        escapeHTML(initials) +
        "</div>" +
        '<div class="min-w-0 flex-1">' +
        '<div class="flex items-center gap-2 flex-wrap">' +
        '<span class="text-sm font-medium text-primary">' + escapeHTML(nome) + "</span>" +
        '<div class="flex gap-0.5">' + starsHTML(fb.estrelas || 5) + "</div>" +
        '<span class="text-xs text-muted">' + formatDate(fb.created_at) + "</span>" +
        "</div>" +
        '<p class="mt-1.5 text-sm text-secondary leading-relaxed">' + escapeHTML(fb.comentario) + "</p>" +
        "</div>" +
        "</div>" +
        "</div>";
    }
    feedbackList.innerHTML = html;
  }

  function loadFeedbacks() {
    if (!feedbackList) return;
    feedbackList.innerHTML =
      '<div class="flex items-center justify-center py-12">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-circle animate-spin text-accent" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>' +
      "</div>";

    window.api
      .get("/api/feedbacks")
      .then(function (res) {
        renderFeedbacks(res.feedbacks || []);
      })
      .catch(function () {
        feedbackList.innerHTML =
          '<p class="text-muted text-sm text-center py-8">Erro ao carregar feedbacks.</p>';
      });
  }

  function initStars(container) {
    starButtons = container.querySelectorAll("button");
    var labels = ["Péssimo", "Ruim", "Regular", "Bom", "Ótimo"];

    starButtons.forEach(function (btn, idx) {
      var val = idx + 1;

      btn.addEventListener("mouseenter", function () {
        starButtons.forEach(function (b, j) {
          var svg = b.querySelector("svg");
          if (svg) {
            svg.classList.toggle("text-yellow-400", j < val);
            svg.classList.toggle("text-muted", j >= val);
          }
        });
        btn.setAttribute("aria-label", val + " estrela" + (val > 1 ? "s" : "") + " — " + labels[idx]);
      });

      btn.addEventListener("mouseleave", function () {
        starButtons.forEach(function (b, j) {
          var svg = b.querySelector("svg");
          if (svg) {
            svg.classList.toggle("text-yellow-400", j < selectedStars);
            svg.classList.toggle("text-muted", j >= selectedStars);
          }
        });
      });

      btn.addEventListener("click", function () {
        selectedStars = val;
        starButtons.forEach(function (b, j) {
          var svg = b.querySelector("svg");
          if (svg) {
            svg.classList.toggle("text-yellow-400", j < selectedStars);
            svg.classList.toggle("text-muted", j >= selectedStars);
          }
        });
        updateSubmitState();
      });
    });
  }

  function updateSubmitState() {
    if (!form || !submitBtn) return;
    var comentario = form.querySelector("textarea");
    var hasComment = comentario && comentario.value.trim().length > 0;
    submitBtn.disabled = !(selectedStars > 0 && hasComment);
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (!form) return;

    var nome = form.querySelector('input[type="text"]');
    var email = form.querySelector('input[type="email"]');
    var comentario = form.querySelector("textarea");

    var payload = {
      nome: nome ? nome.value.trim() : "",
      email: email ? email.value.trim() : "",
      estrelas: selectedStars || 5,
      comentario: comentario ? comentario.value.trim() : "",
    };

    if (!payload.comentario) {
      toast("Por favor, escreva um comentário.", "error");
      return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-circle animate-spin" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>' +
      "Enviando...";

    window.api
      .post("/api/feedback", payload)
      .then(function () {
        toast("Feedback enviado com sucesso! Obrigado.", "success");
        form.reset();
        selectedStars = 0;
        starButtons.forEach(function (b) {
          var svg = b.querySelector("svg");
          if (svg) {
            svg.classList.remove("text-yellow-400");
            svg.classList.add("text-muted");
          }
        });
        updateSubmitState();
        loadFeedbacks();
      })
      .catch(function (err) {
        toast(err.message || "Erro ao enviar feedback. Tente novamente.", "error");
      })
      .finally(function () {
        submitBtn.disabled = false;
        submitBtn.innerHTML =
          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-send" aria-hidden="true"><path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"></path><path d="m21.854 2.147-10.94 10.939"></path></svg>' +
          "Enviar feedback";
        updateSubmitState();
      });
  }

  function init() {
    form = document.querySelector("form");
    if (!form) return;

    var starContainer = form.querySelector(".flex.gap-1");
    if (starContainer) initStars(starContainer);

    submitBtn = form.querySelector('button[type="submit"]');
    feedbackList = document.querySelector(".space-y-4");

    form.addEventListener("submit", handleSubmit);

    var comentario = form.querySelector("textarea");
    if (comentario) {
      comentario.addEventListener("input", updateSubmitState);
    }

    updateSubmitState();
    loadFeedbacks();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
