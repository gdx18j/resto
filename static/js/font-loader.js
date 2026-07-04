(function () {
  "use strict";

  var script =
    document.currentScript ||
    document.querySelector("script[data-font-stylesheet-url]");
  var stylesheetUrl = script ? script.dataset.fontStylesheetUrl : "";
  var loadedSelector = "link[data-resto-font-stylesheet]";

  if (!stylesheetUrl || document.querySelector(loadedSelector)) {
    return;
  }

  function loadFontStylesheet() {
    if (document.querySelector(loadedSelector)) {
      return;
    }

    var stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = stylesheetUrl;
    stylesheet.dataset.restoFontStylesheet = "";
    stylesheet.fetchPriority = "low";
    document.head.appendChild(stylesheet);
  }

  function scheduleAfterFirstPaint() {
    if (navigator.connection && navigator.connection.saveData) {
      return;
    }

    var afterPaint = function () {
      if ("requestIdleCallback" in window) {
        window.requestIdleCallback(loadFontStylesheet, { timeout: 1500 });
        return;
      }
      window.setTimeout(loadFontStylesheet, 0);
    };

    if ("requestAnimationFrame" in window) {
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(afterPaint);
      });
      return;
    }

    window.setTimeout(afterPaint, 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleAfterFirstPaint, { once: true });
  } else {
    scheduleAfterFirstPaint();
  }
})();
