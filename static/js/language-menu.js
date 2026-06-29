(function () {
  var storageKey = "cc_language";
  var supportedLanguages = {
    ru: true,
    en: true,
    tr: true,
  };
  var languageMenu = document.querySelector(".language-menu");
  var languageInputs = Array.prototype.slice.call(
    document.querySelectorAll('input[name="language"]')
  );

  if (!languageMenu || !languageInputs.length) {
    return;
  }

  var summary = languageMenu.querySelector("summary");
  var closingClass = "language-menu--closing";

  if (!summary) {
    return;
  }

  function normalizeLanguage(value) {
    return supportedLanguages[value] ? value : "ru";
  }

  function readLanguage() {
    try {
      return normalizeLanguage(window.localStorage.getItem(storageKey));
    } catch (error) {
      return "ru";
    }
  }

  function saveLanguage(language) {
    try {
      window.localStorage.setItem(storageKey, language);
    } catch (error) {
      return;
    }
  }

  function closeLanguageMenu() {
    if (!languageMenu.open) {
      return;
    }

    languageMenu.classList.add(closingClass);

    window.setTimeout(function () {
      languageMenu.open = false;
      languageMenu.classList.remove(closingClass);
    }, 170);
  }

  function applyLanguage(language, shouldSave) {
    var normalizedLanguage = normalizeLanguage(language);
    var matchingInput = document.getElementById("lang-" + normalizedLanguage);

    document.documentElement.dataset.language = normalizedLanguage;
    document.documentElement.lang = normalizedLanguage;

    if (matchingInput) {
      matchingInput.checked = true;
    }

    if (shouldSave) {
      saveLanguage(normalizedLanguage);
      window.dispatchEvent(
        new CustomEvent("cc:languagechange", {
          detail: {
            language: normalizedLanguage,
          },
        })
      );
    }
  }

  applyLanguage(readLanguage(), false);

  languageInputs.forEach(function (input) {
    input.addEventListener("change", function () {
      if (!input.checked) {
        return;
      }

      applyLanguage(input.id.replace("lang-", ""), true);
      closeLanguageMenu();
    });
  });

  languageMenu.addEventListener("click", function (event) {
    var label = event.target.closest(".language-popover label[for]");
    var input;

    if (!label) {
      return;
    }

    input = document.getElementById(label.getAttribute("for"));

    if (!input || input.name !== "language") {
      return;
    }

    event.preventDefault();
    input.checked = true;
    applyLanguage(input.id.replace("lang-", ""), true);
    closeLanguageMenu();
  });

  summary.addEventListener("click", function (event) {
    if (!languageMenu.open) {
      return;
    }

    event.preventDefault();
    closeLanguageMenu();
  });
})();
