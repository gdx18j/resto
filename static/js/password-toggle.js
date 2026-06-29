(function () {
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

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-password-toggle]");

    if (!button) {
      return;
    }

    var input = getPasswordInput(button);

    if (!input) {
      return;
    }

    var shouldShow = input.type === "password";
    input.type = shouldShow ? "text" : "password";
    button.classList.toggle("is-visible", shouldShow);
    button.setAttribute(
      "aria-label",
      shouldShow
        ? localizedDatasetValue(button, "hideLabel") || "Hide password"
        : localizedDatasetValue(button, "showLabel") || "Show password"
    );
  });
})();
