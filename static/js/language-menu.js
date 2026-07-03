(function () {
  "use strict";

  var preferences = window.CaesarUiPreferences || null;
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
  var reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

  if (!languageMenu || !languageInputs.length) {
    return;
  }

  var summary = languageMenu.querySelector("summary");
  var closingClass = "language-menu--closing";

  if (!summary) {
    return;
  }

  function normalizeLanguage(value) {
    if (preferences && typeof preferences.normalizeLanguage === "function") {
      return preferences.normalizeLanguage(value);
    }

    return supportedLanguages[value] ? value : "ru";
  }

  function readLanguage() {
    if (preferences && typeof preferences.getLanguage === "function") {
      return preferences.getLanguage();
    }

    try {
      return normalizeLanguage(window.localStorage.getItem(storageKey));
    } catch (error) {
      return normalizeLanguage(document.documentElement.lang);
    }
  }

  function saveLanguage(language) {
    if (preferences && typeof preferences.setLanguage === "function") {
      return preferences.setLanguage(language);
    }

    try {
      window.localStorage.setItem(storageKey, language);
    } catch (error) {
      // Storage may be unavailable in private or restricted browser modes.
    }

    document.cookie = "cc_language=" + encodeURIComponent(language)
      + "; Path=/; Max-Age=31536000; SameSite=Lax";

    return language;
  }

  function localizedAttributeValue(element, attributeName, language) {
    return element.getAttribute("data-" + attributeName + "-" + language)
      || element.getAttribute("data-" + attributeName + "-ru")
      || "";
  }

  function applyLocalizedAttributes(language) {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-i18n-aria-label]"),
      function (element) {
        var value = localizedAttributeValue(element, "aria-label", language);

        if (value) {
          element.setAttribute("aria-label", value);
        }
      }
    );

    Array.prototype.forEach.call(
      document.querySelectorAll("[data-i18n-title]"),
      function (element) {
        var value = localizedAttributeValue(element, "title", language);

        if (value) {
          element.setAttribute("title", value);
        }
      }
    );

    Array.prototype.forEach.call(
      document.querySelectorAll("[data-i18n-placeholder]"),
      function (element) {
        var value = localizedAttributeValue(element, "placeholder", language);

        if (value) {
          element.setAttribute("placeholder", value);
        }
      }
    );
  }

  function closeLanguageMenu() {
    if (!languageMenu.open) {
      return;
    }

    if (reduceMotionQuery.matches) {
      languageMenu.open = false;
      languageMenu.classList.remove(closingClass);
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

    if (shouldSave) {
      normalizedLanguage = saveLanguage(normalizedLanguage);
    } else {
      document.documentElement.dataset.language = normalizedLanguage;
      document.documentElement.lang = normalizedLanguage;
    }

    if (matchingInput) {
      matchingInput.checked = true;
    }

    applyLocalizedAttributes(normalizedLanguage);

    if (shouldSave) {
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
