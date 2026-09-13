/**
 * Day / Night theme toggle with localStorage persistence.
 * Applies data-theme on <html> before paint when possible.
 */
(function () {
  var KEY = "pla_theme";

  function preferred() {
    try {
      var saved = localStorage.getItem(KEY);
      if (saved === "day" || saved === "night") return saved;
    } catch (e) {}
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      return "night";
    }
    return "day";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch (e) {}
    var evt = new CustomEvent("pla-theme", { detail: theme });
    document.dispatchEvent(evt);
    window.dispatchEvent(evt);
  }

  window.PLATheme = {
    get: function () {
      return document.documentElement.getAttribute("data-theme") || preferred();
    },
    set: apply,
    toggle: function () {
      apply(window.PLATheme.get() === "night" ? "day" : "night");
    },
  };

  apply(preferred());
})();
