(function () {
  var storageKey = "resto-theme";
  var themeToggle = document.getElementById("theme-toggle");

  if (!themeToggle) {
    return;
  }

  try {
    themeToggle.checked = window.localStorage.getItem(storageKey) === "light";
  } catch (error) {
    return;
  }

  themeToggle.addEventListener("change", function () {
    window.localStorage.setItem(storageKey, themeToggle.checked ? "light" : "dark");
  });
})();
