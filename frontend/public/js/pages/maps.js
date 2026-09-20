/**
 * maps.js — Mapa de oficinas mecânicas próximas
 */
(function () {
  "use strict";

  var BRAZIL_CENTER = [-14.235, -51.925];
  var DEFAULT_RADIUS = 10;
  var map = null;
  var markers = [];
  var allMechanics = [];
  var userPosition = null;

  function loadLeaflet(callback) {
    if (window.L) return callback();
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(link);
    var script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = callback;
    document.head.appendChild(script);
  }

  function initMap(center) {
    map = L.map("maps-container", { zoomControl: true }).setView(center, userPosition ? 12 : 5);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19
    }).addTo(map);
    if (userPosition) {
      L.circleMarker(userPosition, {
        radius: 8, color: "#5b8def", fillColor: "#5b8def", fillOpacity: 0.3, weight: 2
      }).addTo(map).bindPopup('<b class="text-sm">Sua localização</b>');
    }
  }

  function renderList(mechanics) {
    var list = document.getElementById("maps-list");
    var count = document.getElementById("maps-count");
    if (!list) return;
    count.textContent = mechanics.length + " oficina" + (mechanics.length !== 1 ? "s" : "") + " encontrada" + (mechanics.length !== 1 ? "s" : "");

    if (!mechanics.length) {
      list.innerHTML = '<div class="text-center py-8">'
        + '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="mx-auto mb-3 text-secondary/40"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"></path><circle cx="12" cy="10" r="3"></circle></svg>'
        + '<p class="text-secondary text-sm">Nenhuma oficina encontrada nesta região.</p>'
        + '<p class="text-secondary/60 text-xs mt-1">Tente aumentar o raio de busca.</p>'
        + '</div>';
      return;
    }

    list.innerHTML = mechanics.map(function (m) {
      var esp = Array.isArray(m.especialidades) ? m.especialidades.join(", ") : (m.especialidades || "");
      var dist = m.distance_km != null ? m.distance_km + " km" : "";
      var rating = m.avaliacao_media ? '<span class="text-yellow-500 text-xs">★ ' + Number(m.avaliacao_media).toFixed(1) + '</span>' : "";
      return '<div class="maps-card rounded-xl border border-border bg-secondary/30 p-4 cursor-pointer transition-all duration-200 hover:border-accent/50 hover:bg-secondary/50 hover:shadow-lg hover:shadow-[0_8px_30px_-4px_rgba(91,141,239,0.08)] hover:-translate-y-0.5" data-id="' + (m.id || "") + '" data-lat="' + (m.latitude || "") + '" data-lng="' + (m.longitude || "") + '">'
        + '<div class="flex items-start justify-between gap-2 mb-1">'
        + '<h3 class="text-sm font-semibold text-primary leading-tight">' + escapeHTML(m.nome || "Oficina") + '</h3>'
        + (m.is_verified ? '<span class="shrink-0 rounded-full bg-green-500/10 px-2 py-0.5 text-[10px] font-medium text-green-500">Verificada</span>' : '')
        + '</div>'
        + (m.endereco ? '<p class="text-xs text-secondary mb-1 flex items-center gap-1"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"></path><circle cx="12" cy="10" r="3"></circle></svg>' + escapeHTML(m.endereco) + '</p>' : '')
        + (m.telefone ? '<p class="text-xs text-secondary mb-1 flex items-center gap-1"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>' + escapeHTML(m.telefone) + '</p>' : '')
        + '<div class="flex items-center gap-2 mt-2">'
        + (dist ? '<span class="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">' + dist + '</span>' : '')
        + rating
        + (isLoggedIn() && typeof m.id === "number" ? '<button class="mech-fav-toggle ml-auto text-muted hover:text-yellow-500 transition-colors" data-mech-id="' + m.id + '" title="Favoritar">★</button>' : '')
        + '</div>'
        + (esp ? '<p class="text-[11px] text-secondary/70 mt-2 italic">' + escapeHTML(esp) + '</p>' : '')
        + '<button class="mech-profile-btn mt-2 w-full rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-secondary hover:bg-white/5 transition-colors" data-mech-id="' + m.id + '">Ver perfil</button>'
        + '</div>';
    }).join("");
  }

  function renderMarkers(mechanics) {
    if (!map) return;
    markers.forEach(function (m) { map.removeLayer(m); });
    markers = [];
    mechanics.forEach(function (m) {
      if (!m.latitude || !m.longitude) return;
      var esp = Array.isArray(m.especialidades) ? m.especialidades.join(", ") : (m.especialidades || "");
      var popup = '<div class="min-w-[180px]">'
        + '<b class="text-sm">' + escapeHTML(m.nome || "Oficina") + '</b>'
        + (m.endereco ? '<p class="text-xs text-gray-600 mt-1">' + escapeHTML(m.endereco) + '</p>' : '')
        + (m.telefone ? '<p class="text-xs text-gray-600 mt-0.5">Tel: ' + escapeHTML(m.telefone) + '</p>' : '')
        + (esp ? '<p class="text-xs text-gray-500 mt-0.5 italic">' + escapeHTML(esp) + '</p>' : '')
        + (m.avaliacao_media ? '<p class="text-xs text-yellow-600 mt-0.5">★ ' + Number(m.avaliacao_media).toFixed(1) + ' (' + (m.total_avaliacoes || 0) + ')</p>' : '')
        + '</div>';
      var marker = L.marker([m.latitude, m.longitude]).addTo(map).bindPopup(popup);
      markers.push(marker);
    });
  }

  function filterMechanics(query) {
    var q = (query || "").toLowerCase().trim();
    var filtered = allMechanics;
    if (q) {
      filtered = allMechanics.filter(function (m) {
        var nome = (m.nome || "").toLowerCase();
        var esp = Array.isArray(m.especialidades) ? m.especialidades.join(" ").toLowerCase() : ((m.especialidades || "").toLowerCase());
        var addr = (m.endereco || "").toLowerCase();
        return nome.indexOf(q) !== -1 || esp.indexOf(q) !== -1 || addr.indexOf(q) !== -1;
      });
    }
    renderList(filtered);
    renderMarkers(filtered);
  }

  async function fetchMechanics(lat, lng, radius) {
    try {
      var params = "lat=" + lat + "&lng=" + lng + "&radius=" + (radius || DEFAULT_RADIUS) + "&limit=50";
      var sort = document.getElementById("maps-sort");
      if (sort) params += "&sort_by=" + sort.value;
      var res = await window.api.get("/api/mechanics/search?" + params);
      allMechanics = res.mechanics || [];
      filterMechanics(document.getElementById("maps-search").value);
    } catch (err) {
      console.error("Erro ao buscar oficinas:", err);
      allMechanics = [];
      filterMechanics("");
      var msg = document.getElementById("maps-geo-msg");
      if (msg) {
        msg.classList.remove("hidden");
        msg.textContent = "Não foi possível buscar oficinas. Tente novamente mais tarde.";
      }
    }
  }

  function onGeoError(msg) {
    var el = document.getElementById("maps-geo-msg");
    if (el) {
      el.classList.remove("hidden");
      el.textContent = msg || "Não foi possível obter sua localização. O mapa mostra o Brasil como referência.";
    }
  }

  function init() {
    if (!window.auth || !window.auth.requireAuth()) return;
    if (window.premiumModal && !window.premiumModal.requirePremium()) return;
    loadLeaflet(function () {
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          userPosition = [pos.coords.latitude, pos.coords.longitude];
          initMap(userPosition);
          fetchMechanics(userPosition[0], userPosition[1]);
        },
        function () {
          initMap(BRAZIL_CENTER);
          onGeoError("Ative a localização para ver oficinas próximas. O mapa mostra o Brasil como referência.");
        },
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
      );

      var searchInput = document.getElementById("maps-search");
      if (searchInput) {
        var debounce = null;
        searchInput.addEventListener("input", function () {
          clearTimeout(debounce);
          debounce = setTimeout(function () { filterMechanics(searchInput.value); }, 250);
        });
      }

      var radiusSelect = document.getElementById("maps-radius");
      if (radiusSelect) {
        radiusSelect.addEventListener("change", function () {
          if (userPosition) {
            fetchMechanics(userPosition[0], userPosition[1], radiusSelect.value);
          }
        });
      }

      var sortSelect = document.getElementById("maps-sort");
      if (sortSelect) {
        sortSelect.addEventListener("change", function () {
          if (userPosition) {
            fetchMechanics(userPosition[0], userPosition[1], radiusSelect ? radiusSelect.value : DEFAULT_RADIUS);
          }
        });
      }

      document.addEventListener("click", function (e) {
        var card = e.target.closest(".maps-card");
        if (!card || !map) return;
        var lat = parseFloat(card.dataset.lat);
        var lng = parseFloat(card.dataset.lng);
        if (!isNaN(lat) && !isNaN(lng)) {
          map.setView([lat, lng], 15);
          markers.forEach(function (m) {
            var ll = m.getLatLng();
            if (Math.abs(ll.lat - lat) < 0.0001 && Math.abs(ll.lng - lng) < 0.0001) {
              m.openPopup();
            }
          });
        }

        var profileBtn = e.target.closest(".mech-profile-btn");
        if (profileBtn) {
          e.stopPropagation();
          var mechId = profileBtn.getAttribute("data-mech-id");
          if (mechId) showProfileModal(mechId);
        }

        var favBtn = e.target.closest(".mech-fav-toggle");
        if (favBtn) {
          e.stopPropagation();
          var mechId = favBtn.getAttribute("data-mech-id");
          if (mechId) {
            toggleFavorite(parseInt(mechId) || mechId, null).then(function (res) {
              favBtn.classList.toggle("text-yellow-500", !res.message || !res.message.includes("removido"));
            }).catch(function () {});
          }
        }
      });
    });
  }

  function escapeHTML(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Mechanics API functions ──
  function getMechanicProfile(id) {
    return window.api.get("/api/mechanics/" + encodeURIComponent(id));
  }

  function addMechanicReview(mechanicId, avaliacao, comentario, serviceType) {
    return window.api.post("/api/mechanics/" + mechanicId + "/reviews", {
      avaliacao: avaliacao,
      comentario: comentario || "",
      service_type: serviceType || ""
    });
  }

  function toggleFavorite(mechanicId, mechanicData) {
    if (typeof mechanicId === "number") {
      return window.api.post("/api/mechanics/" + mechanicId + "/favorite", {});
    }
    return window.api.post("/api/mechanics/" + encodeURIComponent(mechanicId) + "/favorite", mechanicData || {});
  }

  function removeFavorite(mechanicId) {
    return window.api.delete("/api/mechanics/" + mechanicId + "/favorite");
  }

  function getFavorites() {
    return window.api.get("/api/mechanics/favorites");
  }

  function createMechanic(data) {
    return window.api.post("/api/mechanics", data);
  }

  // ── Profile modal ──
  function showProfileModal(mechanicId) {
    getMechanicProfile(mechanicId).then(function (res) {
      var m = res.mechanic || res;
      var reviews = m.reviews || [];
      var esp = Array.isArray(m.especialidades) ? m.especialidades.join(", ") : (m.especialidades || "");
      var rating = m.avaliacao_media ? Number(m.avaliacao_media).toFixed(1) : "-";
      var reviewCount = m.total_avaliacoes || reviews.length;

      var html = '<div id="mech-modal" class="fixed inset-0 z-[1400] flex items-center justify-center p-4" style="display:none">'
        + '<div class="fixed inset-0 bg-black/70 backdrop-blur-sm" data-mech-close></div>'
        + '<div class="relative w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl border border-border bg-secondary p-6 shadow-2xl">'
        + '<button data-mech-close class="absolute top-4 right-4 text-muted hover:text-primary transition-colors"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>'
        + '<h2 class="text-lg font-bold text-primary mb-1">' + escapeHTML(m.nome || "Oficina") + '</h2>'
        + (m.endereco ? '<p class="text-sm text-secondary mb-3 flex items-center gap-1"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="shrink-0"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>' + escapeHTML(m.endereco) + '</p>' : '')
        + '<div class="flex items-center gap-3 mb-4">'
        + '<span class="text-yellow-500 text-sm">★ ' + rating + '</span>'
        + '<span class="text-xs text-muted">' + reviewCount + ' avaliação' + (reviewCount !== 1 ? 's' : '') + '</span>'
        + (m.telefone ? '<a href="tel:' + escapeHTML(m.telefone) + '" class="text-xs text-accent hover:underline">' + escapeHTML(m.telefone) + '</a>' : '')
        + '</div>'
        + (esp ? '<p class="text-xs text-secondary/70 italic mb-4">' + escapeHTML(esp) + '</p>' : '')
        + '<div class="flex gap-2 mb-4">'
        + '<button id="mech-fav-btn" class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-secondary hover:bg-white/5 transition-colors">★ Favoritar</button>'
        + (m.telefone ? '<a href="https://wa.me/55' + escapeHTML(m.telefone.replace(/\D/g, '')) + '" target="_blank" class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-secondary hover:bg-white/5 transition-colors">WhatsApp</a>' : '')
        + '</div>'
        + '<h3 class="text-sm font-semibold text-primary mb-3">Avaliações</h3>'
        + '<div class="space-y-3 mb-4">';

      if (reviews.length === 0) {
        html += '<p class="text-xs text-muted">Nenhuma avaliação ainda.</p>';
      } else {
        reviews.forEach(function (r) {
          var stars = "";
          for (var i = 0; i < 5; i++) stars += i < r.avaliacao ? "★" : "☆";
          html += '<div class="rounded-lg border border-border p-3">'
            + '<div class="flex items-center gap-2 mb-1">'
            + '<span class="text-yellow-500 text-xs">' + stars + '</span>'
            + '<span class="text-xs font-medium text-primary">' + escapeHTML(r.user_nome || "Anônimo") + '</span>'
            + '</div>'
            + (r.comentario ? '<p class="text-xs text-secondary">' + escapeHTML(r.comentario) + '</p>' : '')
            + '</div>';
        });
      }

      html += '</div>'
        + '<h3 class="text-sm font-semibold text-primary mb-2">Deixar avaliação</h3>'
        + '<div class="flex gap-1 mb-2" id="mech-rating-stars">'
        + '<button type="button" class="mech-star text-xl text-muted hover:text-yellow-500 transition-colors" data-val="1">☆</button>'
        + '<button type="button" class="mech-star text-xl text-muted hover:text-yellow-500 transition-colors" data-val="2">☆</button>'
        + '<button type="button" class="mech-star text-xl text-muted hover:text-yellow-500 transition-colors" data-val="3">☆</button>'
        + '<button type="button" class="mech-star text-xl text-muted hover:text-yellow-500 transition-colors" data-val="4">☆</button>'
        + '<button type="button" class="mech-star text-xl text-muted hover:text-yellow-500 transition-colors" data-val="5">☆</button>'
        + '</div>'
        + '<textarea id="mech-review-text" rows="2" placeholder="Comentário (opcional)" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-xs text-primary placeholder:text-muted focus:border-accent focus:outline-none mb-2 resize-none"></textarea>'
        + '<button id="mech-submit-review" class="rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white hover:bg-accent-hover transition-colors">Enviar avaliação</button>'
        + '</div></div>';

      var wrapper = document.createElement("div");
      wrapper.innerHTML = html;
      document.body.appendChild(wrapper.firstChild);

      var modal = document.getElementById("mech-modal");
      modal.style.display = "";

      modal.querySelectorAll("[data-mech-close]").forEach(function (el) {
        el.addEventListener("click", function () { modal.remove(); });
      });

      var selectedRating = 0;
      modal.querySelectorAll(".mech-star").forEach(function (star) {
        star.addEventListener("click", function () {
          selectedRating = parseInt(star.dataset.val);
          modal.querySelectorAll(".mech-star").forEach(function (s, i) {
            s.textContent = i < selectedRating ? "★" : "☆";
            s.classList.toggle("text-yellow-500", i < selectedRating);
            s.classList.toggle("text-muted", i >= selectedRating);
          });
        });
      });

      var favBtn = document.getElementById("mech-fav-btn");
      if (favBtn && typeof m.id === "number") {
        favBtn.addEventListener("click", function () {
          toggleFavorite(m.id, null).then(function (res) {
            favBtn.textContent = res.message && res.message.includes("removido") ? "★ Favoritar" : "★ Favoritado";
            favBtn.classList.toggle("text-accent", res.message && !res.message.includes("removido"));
          }).catch(function () {});
        });
      }

      var submitBtn = document.getElementById("mech-submit-review");
      if (submitBtn) {
        submitBtn.addEventListener("click", function () {
          if (!selectedRating) { alert("Selecione uma nota."); return; }
          var txt = document.getElementById("mech-review-text");
          submitBtn.disabled = true;
          addMechanicReview(m.id, selectedRating, txt ? txt.value : "").then(function () {
            alert("Avaliação enviada!");
            modal.remove();
          }).catch(function (err) {
            alert(err.message || "Erro ao enviar avaliação.");
            submitBtn.disabled = false;
          });
        });
      }
    }).catch(function () {});
  }

  // ── Add mechanic modal ──
  function showAddMechanicModal() {
    var html = '<div id="add-mech-modal" class="fixed inset-0 z-[1400] flex items-center justify-center p-4" style="display:none">'
      + '<div class="fixed inset-0 bg-black/70 backdrop-blur-sm" data-add-mech-close></div>'
      + '<div class="relative w-full max-w-lg rounded-2xl border border-border bg-secondary p-6 shadow-2xl">'
      + '<button data-add-mech-close class="absolute top-4 right-4 text-muted hover:text-primary transition-colors"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>'
      + '<h2 class="text-lg font-bold text-primary mb-4">Cadastrar oficina</h2>'
      + '<form id="add-mech-form" class="space-y-3">'
      + '<input type="text" name="nome" placeholder="Nome da oficina *" required class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none">'
      + '<input type="text" name="endereco" placeholder="Endereço *" required class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none">'
      + '<div class="grid grid-cols-2 gap-3">'
      + '<input type="text" name="cidade" placeholder="Cidade" class="rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none">'
      + '<input type="text" name="estado" placeholder="UF" maxlength="2" class="rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none">'
      + '</div>'
      + '<input type="tel" name="telefone" placeholder="Telefone" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none">'
      + '<input type="text" name="especialidades" placeholder="Especialidades (separar por vírgula)" class="w-full rounded-lg border border-border bg-primary px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-accent focus:outline-none">'
      + '<p class="text-xs text-muted">A localização será capturada do seu mapa atual.</p>'
      + '<button type="submit" class="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover transition-colors">Cadastrar oficina</button>'
      + '</form></div></div>';

    var wrapper = document.createElement("div");
    wrapper.innerHTML = html;
    document.body.appendChild(wrapper.firstChild);

    var modal = document.getElementById("add-mech-modal");
    modal.style.display = "";

    modal.querySelectorAll("[data-add-mech-close]").forEach(function (el) {
      el.addEventListener("click", function () { modal.remove(); });
    });

    var form = document.getElementById("add-mech-form");
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var fd = new FormData(form);
      var data = {
        nome: fd.get("nome"),
        endereco: fd.get("endereco"),
        cidade: fd.get("cidade"),
        estado: fd.get("estado"),
        telefone: fd.get("telefone"),
        especialidades: fd.get("especialidades") ? fd.get("especialidades").split(",").map(function(s){return s.trim()}).filter(Boolean) : [],
        latitude: userPosition ? userPosition[0] : 0,
        longitude: userPosition ? userPosition[1] : 0
      };
      createMechanic(data).then(function () {
        alert("Oficina cadastrada com sucesso!");
        modal.remove();
      }).catch(function (err) {
        alert(err.message || "Erro ao cadastrar oficina.");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
