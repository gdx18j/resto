(function () {
  "use strict";

  var loaderScript = document.currentScript;
  var runtimeUrl = loaderScript ? loaderScript.dataset.menuUiScriptUrl || "" : "";
  var searchSelector = ".menu-search-input";
  var dishOpenSelector = "[data-dish-open]";
  var runtimeState = "idle";
  var runtimePromise = null;
  var pendingInput = null;
  var pendingDishOpen = null;
  var busyElements = [];
  var translations = {
    ru: "Открыть описание: ",
    en: "Open details: ",
    tr: "Detayları aç: ",
  };

  if (!runtimeUrl || !document.querySelector(".search-section")) {
    return;
  }

  function closest(target, selector) {
    return target && typeof target.closest === "function"
      ? target.closest(selector)
      : null;
  }

  function currentLanguage() {
    var language = document.documentElement.dataset.language
      || document.documentElement.lang
      || "ru";

    return translations[language] ? language : "ru";
  }

  function localizedDishName(button) {
    var card = closest(button, "[data-dish-card]");
    var language = currentLanguage();
    var name = card ? card.querySelector(".dish-copy h2 .lang--" + language) : null;
    var fallback = card ? card.querySelector(".dish-copy h2") : null;
    var element = name || fallback;

    return element ? element.textContent.trim() : "";
  }

  function syncDishOpenLabels() {
    var prefix = translations[currentLanguage()] || translations.ru;

    Array.prototype.forEach.call(
      document.querySelectorAll(dishOpenSelector),
      function (button) {
        button.setAttribute("aria-label", prefix + localizedDishName(button));
      }
    );
  }

  function markBusy(element) {
    if (element && busyElements.indexOf(element) === -1) {
      busyElements.push(element);
      element.setAttribute("aria-busy", "true");
    }
  }

  function clearBusy() {
    busyElements.forEach(function (element) {
      if (element && element.isConnected) {
        element.removeAttribute("aria-busy");
      }
    });
    busyElements = [];
  }

  function resetAfterFailure(runtimeScript) {
    if (runtimeScript) {
      runtimeScript.remove();
    }
    runtimeState = "idle";
    runtimePromise = null;
    pendingInput = null;
    pendingDishOpen = null;
    clearBusy();
  }

  function loadRuntime(trigger) {
    var existingRuntime;

    markBusy(trigger);

    if (runtimeState === "loaded") {
      clearBusy();
      return Promise.resolve();
    }

    if (runtimePromise) {
      return runtimePromise;
    }

    existingRuntime = document.querySelector("script[data-menu-ui-runtime]");
    if (existingRuntime) {
      runtimeState = "loaded";
      clearBusy();
      return Promise.resolve();
    }

    runtimeState = "loading";
    runtimePromise = new Promise(function (resolve, reject) {
      var runtimeScript = document.createElement("script");

      runtimeScript.src = runtimeUrl;
      runtimeScript.async = true;
      runtimeScript.dataset.menuUiRuntime = "";

      runtimeScript.addEventListener("load", function () {
        runtimeState = "loaded";
        clearBusy();
        resolve();
      }, { once: true });

      runtimeScript.addEventListener("error", function () {
        resetAfterFailure(runtimeScript);
        reject(new Error("Menu UI runtime failed to load."));
      }, { once: true });

      document.head.appendChild(runtimeScript);
    });

    return runtimePromise;
  }

  function flushPendingInteraction() {
    var input = pendingInput;
    var dishOpen = pendingDishOpen;

    pendingInput = null;
    pendingDishOpen = null;

    if (input && input.isConnected) {
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    if (dishOpen && dishOpen.isConnected) {
      dishOpen.click();
    }
  }

  function ignoreLoadFailure() {}

  function interactionTarget(target) {
    return closest(target, searchSelector) || closest(target, dishOpenSelector);
  }

  function setupSeasonalCarouselDots() {
    var carousels = document.querySelectorAll(".seasonal-menu");

    Array.prototype.forEach.call(carousels, function (carousel) {
      var track = carousel.querySelector("[data-seasonal-track]");
      var dotsRoot = carousel.querySelector("[data-seasonal-dots]");
      var cards = track
        ? Array.prototype.slice.call(track.querySelectorAll("[data-seasonal-card]"))
        : [];
      var maxDots = 4;
      var dotCount = Math.min(maxDots, cards.length);
      var ticking = false;
      var activeDot = -1;
      var dots = [];

      if (!track || !dotsRoot || cards.length <= 1) {
        if (dotsRoot) {
          dotsRoot.hidden = true;
        }
        return;
      }

      function cardIndexForDot(dotIndex) {
        if (dotCount <= 1) {
          return 0;
        }

        return Math.round(dotIndex * (cards.length - 1) / (dotCount - 1));
      }

      function dotIndexForCard(cardIndex) {
        if (cards.length <= 1 || dotCount <= 1) {
          return 0;
        }

        return Math.round(cardIndex * (dotCount - 1) / (cards.length - 1));
      }

      function closestCardIndex() {
        var trackRect = track.getBoundingClientRect();
        var targetLeft = trackRect.left;
        var closestIndex = 0;
        var closestDistance = Infinity;

        cards.forEach(function (card, index) {
          var distance = Math.abs(card.getBoundingClientRect().left - targetLeft);

          if (distance < closestDistance) {
            closestDistance = distance;
            closestIndex = index;
          }
        });

        return closestIndex;
      }

      function setActiveDot(nextDot) {
        if (nextDot === activeDot) {
          return;
        }

        activeDot = nextDot;
        dots.forEach(function (dot, index) {
          var isActive = index === activeDot;

          dot.classList.toggle("is-active", isActive);
          dot.setAttribute("aria-current", isActive ? "true" : "false");
        });
      }

      function update() {
        ticking = false;
        setActiveDot(dotIndexForCard(closestCardIndex()));
      }

      function requestUpdate() {
        if (!ticking) {
          ticking = true;
          window.requestAnimationFrame(update);
        }
      }

      dotsRoot.textContent = "";
      dotsRoot.hidden = false;
      dotsRoot.setAttribute("role", "tablist");

      for (var index = 0; index < dotCount; index += 1) {
        var dot = document.createElement("button");
        var targetIndex = cardIndexForDot(index);

        dot.className = "seasonal-menu__dot";
        dot.type = "button";
        dot.setAttribute("role", "tab");
        dot.setAttribute("aria-label", String(targetIndex + 1));
        dot.addEventListener("click", function (card) {
          return function () {
            card.scrollIntoView({
              behavior: "smooth",
              block: "nearest",
              inline: "start",
            });
          };
        }(cards[targetIndex]));
        dotsRoot.appendChild(dot);
        dots.push(dot);
      }

      track.addEventListener("scroll", requestUpdate, { passive: true });
      window.addEventListener("resize", requestUpdate, { passive: true });
      requestUpdate();
    });
  }

  var categoryStrip = document.querySelector(".category-strip");
  if (categoryStrip) {
    categoryStrip.scrollLeft = 0;
  }

  setupSeasonalCarouselDots();
  syncDishOpenLabels();
  window.addEventListener("cc:languagechange", syncDishOpenLabels);

  document.addEventListener("pointerdown", function (event) {
    var target = interactionTarget(event.target);

    if (target && runtimeState === "idle") {
      loadRuntime(target).catch(ignoreLoadFailure);
    }
  }, { capture: true, passive: true });

  document.addEventListener("focusin", function (event) {
    var target = interactionTarget(event.target);

    if (target && runtimeState === "idle") {
      loadRuntime(target).catch(ignoreLoadFailure);
    }
  }, true);

  document.addEventListener("input", function (event) {
    var input = closest(event.target, searchSelector);

    if (!input || runtimeState === "loaded") {
      return;
    }

    pendingInput = input;
    loadRuntime(input).then(flushPendingInteraction).catch(ignoreLoadFailure);
  }, true);

  document.addEventListener("click", function (event) {
    var dishOpen = closest(event.target, dishOpenSelector);

    if (!dishOpen || runtimeState === "loaded") {
      return;
    }

    event.preventDefault();
    event.stopImmediatePropagation();
    pendingDishOpen = dishOpen;
    loadRuntime(dishOpen).then(flushPendingInteraction).catch(ignoreLoadFailure);
  }, true);
})();
