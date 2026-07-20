/*
 * AppSelect — componente de seleção customizado, sem dependências externas.
 * Substitui <select> nativos com um combobox acessível (role=combobox/listbox/option),
 * pesquisa interna opcional (config.searchable) com filtro por texto
 * (case/acento-insensitive), navegação por teclado, fechamento por clique
 * externo / ESC / Tab e popup 100% alinhado ao gatilho.
 *
 * Uso:
 *   <div id="meuSelect" class="app-select" data-placeholder="..." aria-label="..."></div>
 *   AppSelect.mount(el, { searchable: false, options: [...] });
 *   el.setOptions([{ value, label }, ...]);
 *   el.value            // getter/setter (mantém compatibilidade com <select>)
 *   el.disabled        // getter/setter
 *   el.addEventListener("change", cb);
 */
(function () {
  "use strict";

  function normalize(str) {
    return (str == null ? "" : String(str))
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .trim();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function mount(root, config) {
    config = config || {};
    var searchable = config.searchable !== false; // default true
    var placeholder = config.placeholder || root.dataset.placeholder || "Selecione...";
    var searchPlaceholder = config.searchPlaceholder || "Pesquisar...";
    var emptyText = config.emptyText || "Nenhum item encontrado";
    var ariaLabel = config.ariaLabel || root.getAttribute("aria-label") || "";

    var listId = "appsel-" + (root.id || Math.random().toString(36).slice(2)) + "-list";

    var searchHtml = searchable
      ? '<div class="app-select__search-wrap">' +
          '<i class="fas fa-search app-select__search-icon" aria-hidden="true"></i>' +
          '<input type="text" class="app-select__search" placeholder="' + escapeHtml(searchPlaceholder) + '" ' +
            'aria-label="' + escapeHtml(searchPlaceholder) + '" aria-autocomplete="list" ' +
            'aria-controls="' + listId + '" autocomplete="off">' +
        '</div>'
      : "";

    root.classList.add("app-select");
    if (!searchable) root.classList.add("app-select--no-search");
    root.innerHTML =
      '<button type="button" class="app-select__trigger" role="combobox" aria-haspopup="listbox" ' +
        'aria-expanded="false" aria-controls="' + listId + '" aria-label="' + escapeHtml(ariaLabel) + '">' +
        '<span class="app-select__value">' + escapeHtml(placeholder) + '</span>' +
        '<i class="fas fa-chevron-down app-select__caret" aria-hidden="true"></i>' +
      '</button>' +
      '<div class="app-select__popup" role="listbox" id="' + listId + '" aria-label="' + escapeHtml(ariaLabel) + '" hidden>' +
        searchHtml +
        '<ul class="app-select__list" tabindex="-1"></ul>' +
        '<div class="app-select__empty" hidden>' + escapeHtml(emptyText) + '</div>' +
      '</div>';

    var trigger = root.querySelector(".app-select__trigger");
    var valueEl = root.querySelector(".app-select__value");
    var popup = root.querySelector(".app-select__popup");
    var search = root.querySelector(".app-select__search");
    var list = root.querySelector(".app-select__list");
    var emptyEl = root.querySelector(".app-select__empty");

    var options = [];
    var filtered = [];
    var selectedValue = null;
    var activeIndex = -1;
    var isOpen = false;
    var isDisabled = false;
    var changeCallbacks = [];

    function findOption(value) {
      if (value == null) return null;
      var v = String(value);
      for (var i = 0; i < options.length; i++) {
        if (String(options[i].value) === v) return options[i];
      }
      return null;
    }

    function renderList() {
      list.innerHTML = "";
      if (!filtered.length) {
        emptyEl.hidden = false;
        list.hidden = true;
        return;
      }
      emptyEl.hidden = true;
      list.hidden = false;
      filtered.forEach(function (opt, i) {
        var li = document.createElement("li");
        li.className = "app-select__option";
        li.id = listId + "-opt-" + i;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(opt.value === selectedValue));
        li.dataset.value = opt.value;
        li.dataset.index = String(i);
        if (opt.value === selectedValue) li.classList.add("is-selected");
        li.textContent = opt.label;
        list.appendChild(li);
      });
    }

    function setActive(index) {
      var items = list.querySelectorAll(".app-select__option");
      if (!items.length) {
        activeIndex = -1;
        if (search) search.removeAttribute("aria-activedescendant");
        list.removeAttribute("aria-activedescendant");
        return;
      }
      activeIndex = (index + items.length) % items.length;
      items.forEach(function (el, i) {
        el.classList.toggle("is-active", i === activeIndex);
      });
      var active = items[activeIndex];
      if (active) {
        active.scrollIntoView({ block: "nearest" });
        if (search) search.setAttribute("aria-activedescendant", active.id);
        list.setAttribute("aria-activedescendant", active.id);
      }
    }

    function applyFilter(query) {
      var q = normalize(query);
      filtered = options.filter(function (o) {
        return normalize(o.label).indexOf(q) !== -1;
      });
      activeIndex = -1;
      renderList();
      if (filtered.length) setActive(0);
    }

    function syncLabel() {
      var sel = findOption(selectedValue);
      valueEl.textContent = sel ? sel.label : placeholder;
    }

    function positionPopup() {
      popup.style.visibility = "hidden";
      var rect = root.getBoundingClientRect();
      var spaceBelow = window.innerHeight - rect.bottom;
      var needed = Math.min(popup.scrollHeight || 320, 320);
      if (spaceBelow < needed && rect.top > spaceBelow) {
        popup.classList.add("app-select__popup--above");
      } else {
        popup.classList.remove("app-select__popup--above");
      }
      popup.style.visibility = "";
    }

    function open() {
      if (isDisabled || isOpen) return;
      isOpen = true;
      popup.hidden = false;
      root.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      if (search) search.value = "";
      applyFilter(search ? search.value : "");
      positionPopup();
      window.setTimeout(function () {
        if (search) search.focus();
        else list.focus();
      }, 0);
    }

    function close(returnFocus) {
      if (!isOpen) return;
      isOpen = false;
      popup.hidden = true;
      root.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
      if (search) search.removeAttribute("aria-activedescendant");
      list.removeAttribute("aria-activedescendant");
      if (returnFocus) trigger.focus();
    }

    function select(value, dispatch) {
      selectedValue = value == null ? null : String(value);
      syncLabel();
      var items = list.querySelectorAll(".app-select__option");
      items.forEach(function (el) {
        var match = el.dataset.value === selectedValue;
        el.setAttribute("aria-selected", String(match));
        el.classList.toggle("is-selected", match);
      });
      close(false);
      if (dispatch !== false) {
        for (var i = 0; i < changeCallbacks.length; i++) changeCallbacks[i](selectedValue);
        root.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function setOptions(listOpts) {
      options = (listOpts || []).map(function (o) {
        return { value: o.value == null ? "" : String(o.value), label: o.label == null ? "" : String(o.label) };
      });
      if (selectedValue === null && options.length) {
        selectedValue = options[0].value;
      }
      syncLabel();
      applyFilter(search ? search.value : "");
      setDisabled(false);
    }

    function setDisabled(val) {
      isDisabled = !!val;
      root.classList.toggle("is-disabled", isDisabled);
      trigger.disabled = isDisabled;
      if (isDisabled) close(false);
    }

    function getValue() { return selectedValue; }
    function setValue(val) {
      selectedValue = val == null ? null : String(val);
      syncLabel();
      list.querySelectorAll(".app-select__option").forEach(function (el) {
        var match = el.dataset.value === selectedValue;
        el.setAttribute("aria-selected", String(match));
        el.classList.toggle("is-selected", match);
      });
    }
    function onChange(cb) { if (typeof cb === "function") changeCallbacks.push(cb); }

    function onNav(e) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (filtered.length) setActive(activeIndex + 1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (filtered.length) setActive(activeIndex - 1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (activeIndex >= 0 && filtered[activeIndex]) select(filtered[activeIndex].value, true);
      } else if (e.key === "Escape") {
        e.preventDefault();
        close(true);
      } else if (e.key === "Tab") {
        close(false);
      }
    }

    // Eventos
    trigger.addEventListener("click", function () {
      if (isOpen) close(false); else open();
    });
    trigger.addEventListener("keydown", function (e) {
      if (isDisabled) return;
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        open();
        if (filtered.length) setActive(filtered.length - 1);
      } else if (e.key === "Escape") {
        close(false);
      } else if (e.key === "Tab") {
        close(false);
      }
    });

    if (search) {
      search.addEventListener("input", function () { applyFilter(search.value); });
      search.addEventListener("keydown", onNav);
    }
    list.addEventListener("keydown", onNav);
    list.addEventListener("click", function (e) {
      var li = e.target.closest(".app-select__option");
      if (li) select(li.dataset.value, true);
    });
    list.addEventListener("mousemove", function (e) {
      var li = e.target.closest(".app-select__option");
      if (li) setActive(Number(li.dataset.index));
    });

    document.addEventListener("click", function (e) {
      if (isOpen && !root.contains(e.target)) close(false);
    });
    window.addEventListener("resize", function () { if (isOpen) positionPopup(); });
    window.addEventListener("scroll", function () { if (isOpen) positionPopup(); }, true);

    // API + compatibilidade com <select>
    var api = {
      setOptions: setOptions,
      setDisabled: setDisabled,
      getValue: getValue,
      setValue: setValue,
      onChange: onChange,
      open: open,
      close: close,
      isOpen: function () { return isOpen; }
    };
    root._appSelect = api;
    root.setOptions = setOptions;
    root.setDisabled = setDisabled;
    root.onChange = onChange;
    Object.defineProperty(root, "value", { get: getValue, set: setValue, configurable: true });
    Object.defineProperty(root, "disabled", { get: function () { return isDisabled; }, set: setDisabled, configurable: true });

    setDisabled(true);
    valueEl.textContent = placeholder;

    return api;
  }

  window.AppSelect = { mount: mount };
})();
