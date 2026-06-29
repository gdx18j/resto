(function () {
  function getPasswordInput(button) {
    var control = button.closest(".auth-password-control");

    if (!control) {
      return null;
    }

    return control.querySelector("input");
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
        ? button.dataset.hideLabel || "Hide password"
        : button.dataset.showLabel || "Show password"
    );
  });
})();
