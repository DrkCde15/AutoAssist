(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.auth || !window.auth.requireAuth()) return;
  });
})();
