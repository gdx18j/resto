(function () {
  "use strict";

  var LANGUAGE_STORAGE_KEY = "cc_language";
  var LANGUAGE_COOKIE_NAME = "cc_language";
  var LANGUAGE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60;
  var supportedLanguages = {
    ru: true,
    en: true,
    tr: true,
  };

  function normalizeLanguage(value) {
    var language = String(value || "").trim().toLowerCase();
    return supportedLanguages[language] ? language : "ru";
  }

  function readStoredLanguage() {
    try {
      return window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    } catch (error) {
      return "";
    }
  }

  function persistLanguage(language) {
    var normalizedLanguage = normalizeLanguage(language);

    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, normalizedLanguage);
    } catch (error) {
      // Storage may be unavailable in private or restricted browser modes.
    }

    document.cookie = [
      LANGUAGE_COOKIE_NAME + "=" + encodeURIComponent(normalizedLanguage),
      "Path=/",
      "Max-Age=" + LANGUAGE_COOKIE_MAX_AGE,
      "SameSite=Lax",
    ].join("; ");

    return normalizedLanguage;
  }

  function applyLanguage(language, options) {
    var settings = options || {};
    var normalizedLanguage = normalizeLanguage(language);

    document.documentElement.lang = normalizedLanguage;
    document.documentElement.dataset.language = normalizedLanguage;

    if (settings.persist) {
      persistLanguage(normalizedLanguage);
    }

    return normalizedLanguage;
  }

  var serverLanguage = normalizeLanguage(
    document.documentElement.dataset.language || document.documentElement.lang
  );
  var storedLanguage = readStoredLanguage();
  var initialLanguage = normalizeLanguage(storedLanguage || serverLanguage);

  applyLanguage(initialLanguage, {
    persist: Boolean(storedLanguage && initialLanguage !== serverLanguage),
  });

  window.CaesarUiPreferences = {
    normalizeLanguage: normalizeLanguage,
    getLanguage: function () {
      return normalizeLanguage(
        document.documentElement.dataset.language || document.documentElement.lang
      );
    },
    setLanguage: function (language) {
      return applyLanguage(language, { persist: true });
    },
  };
})();
