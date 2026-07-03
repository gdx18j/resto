(function () {
  "use strict";

  function getPasswordInput(button) {
    var control = button.closest(".auth-password-control");

    if (!control) {
      return null;
    }

    return control.querySelector("input");
  }

  function getCurrentLanguage() {
    var language = document.documentElement.dataset.language || document.documentElement.lang || "ru";

    return ["ru", "en", "tr"].indexOf(language) === -1 ? "ru" : language;
  }

  function localizedDatasetValue(button, name) {
    var language = getCurrentLanguage();
    var key = name + language.charAt(0).toUpperCase() + language.slice(1);

    return button.dataset[key] || button.dataset[name] || "";
  }

  function syncButtonLabel(button) {
    var input = getPasswordInput(button);
    var isVisible;

    if (!input) {
      return;
    }

    isVisible = input.type !== "password";
    button.classList.toggle("is-visible", isVisible);
    button.setAttribute(
      "aria-label",
      isVisible
        ? localizedDatasetValue(button, "hideLabel") || "Hide password"
        : localizedDatasetValue(button, "showLabel") || "Show password"
    );
  }

  function syncAllButtons() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-password-toggle]"),
      syncButtonLabel
    );
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-password-toggle]");
    var input;

    if (!button) {
      return;
    }

    input = getPasswordInput(button);

    if (!input) {
      return;
    }

    input.type = input.type === "password" ? "text" : "password";
    syncButtonLabel(button);
  });

  window.addEventListener("cc:languagechange", syncAllButtons);
  syncAllButtons();
})();
