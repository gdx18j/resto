(function () {
  var languageMenu = document.querySelector(".language-menu");

  if (!languageMenu) {
    return;
  }

  var summary = languageMenu.querySelector("summary");
  var closingClass = "language-menu--closing";

  if (!summary) {
    return;
  }

  summary.addEventListener("click", function (event) {
    if (!languageMenu.open) {
      return;
    }

    event.preventDefault();
    languageMenu.classList.add(closingClass);

    window.setTimeout(function () {
      languageMenu.open = false;
      languageMenu.classList.remove(closingClass);
    }, 170);
  });
})();
