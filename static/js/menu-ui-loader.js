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
  var search = document.querySelector(".search-section");

  if (!runtimeUrl || !search) {
    return;
  }

  function closest(target, selector) {
    if (!target || typeof target.closest !== "function") {
      return null;
    }

    return target.closest(selector);
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
    var name = card
      ? card.querySelector(".dish-copy h2 .lang--" + language)
      : null;
    var fallback = card ? card.querySelector(".dish-copy h2") : null;

    return (name || fallback) ? (name || fallback).textContent.trim() : "";
  }

  function syncDishOpenLabels() {
    var language = currentLanguage();
    var prefix = translations[language] || translations.ru;

    Array.prototype.forEach.call(
      document.querySelectorAll(dishOpenSelector),
      function (button) {
        button.setAttribute("aria-label", prefix + localizedDishName(button));
      }
    );
  }

  function markBusy(element) {
    if (!element || busyElements.indexOf(element) !== -1) {
      return;
    }

    busyElements.push(element);
    element.setAttribute("aria-busy", "true");
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

      runtimeScript.addEventListener(
        "load",
        function () {
          runtimeState = "loaded";
          clearBusy();
          resolve();
        },
        { once: true }
      );

      runtimeScript.addEventListener(
        "error",
        function () {
          resetAfterFailure(runtimeScript);
          reject(new Error("Menu UI runtime failed to load."));
        },
        { once: true }
      );

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

  function ignoreLoadFailure() {
    return;
  }

  function interactionTarget(target) {
    return closest(target, searchSelector) || closest(target, dishOpenSelector);
  }


  function setupStickySearchCollapse() {
    var controls = document.querySelector(".menu-controls");
    var searchSection = controls && controls.querySelector(".search-section");
    var searchInput = controls && controls.querySelector(searchSelector);
    var scroller = document.scrollingElement || document.documentElement;
    var collapsedClass = "is-search-collapsed";
    var ticking = false;
    var defaultTabIndex;
    var lastY;
    var collapsed = false;
    var lastToggleAt = 0;
    var touchActive = false;
    var touchStartY = 0;
    var touchLastY = 0;
    var touchSettledTimer = 0;
    var TOGGLE_COOLDOWN_MS = 180;
    var DESKTOP_DELTA = 18;
    var MOBILE_GESTURE_DELTA = 34;

    if (!controls || !searchSection || !searchInput || !scroller) {
      return;
    }

    defaultTabIndex = searchInput.getAttribute("tabindex");
    lastY = getScrollY();

    function getScrollY() {
      return window.pageYOffset
        || scroller.scrollTop
        || document.documentElement.scrollTop
        || document.body.scrollTop
        || 0;
    }

    function hasQuery() {
      return Boolean(searchInput.value && searchInput.value.trim());
    }

    function isMobileViewport() {
      return Boolean(window.matchMedia && window.matchMedia("(max-width: 619px)").matches);
    }

    function collapseThreshold() {
      return isMobileViewport() ? 138 : 42;
    }

    function canToggle() {
      return Date.now() - lastToggleAt >= TOGGLE_COOLDOWN_MS;
    }

    function updateCollapseDistance() {
      var categoryRow = controls.querySelector(".category-row");
      var gap = categoryRow
        ? parseFloat(window.getComputedStyle(categoryRow).marginTop) || 0
        : 0;
      var distance = Math.max(0, Math.round(searchSection.getBoundingClientRect().height + gap));
      var fullHeight = Math.max(0, Math.round(controls.scrollHeight));
      var collapsedHeight = Math.max(
        categoryRow ? Math.round(categoryRow.getBoundingClientRect().height) : 0,
        fullHeight - distance
      );

      controls.style.setProperty("--menu-search-collapse-distance", distance + "px");
      controls.style.setProperty("--menu-controls-collapsed-height", collapsedHeight + "px");
    }

    function restoreSearchTabIndex() {
      if (defaultTabIndex === null) {
        searchInput.removeAttribute("tabindex");
      } else {
        searchInput.setAttribute("tabindex", defaultTabIndex);
      }
    }

    function setCollapsed(shouldCollapse, force) {
      shouldCollapse = Boolean(shouldCollapse && !hasQuery());

      if (!force && shouldCollapse === collapsed) {
        return;
      }

      if (!force && !canToggle()) {
        return;
      }

      collapsed = shouldCollapse;
      lastToggleAt = Date.now();

      if (shouldCollapse) {
        updateCollapseDistance();
        searchInput.setAttribute("tabindex", "-1");
        if (document.activeElement === searchInput) {
          searchInput.blur();
        }
      } else {
        restoreSearchTabIndex();
      }

      controls.classList.toggle(collapsedClass, shouldCollapse);
    }

    function updateFromScroll() {
      var y = getScrollY();
      var delta = y - lastY;

      ticking = false;

      if (touchActive) {
        touchLastY = y;
        lastY = y;
        return;
      }

      if (y <= collapseThreshold()) {
        setCollapsed(false);
        lastY = y;
        return;
      }

      if (!isMobileViewport()) {
        if (delta >= DESKTOP_DELTA) {
          setCollapsed(true);
        } else if (delta <= -DESKTOP_DELTA) {
          setCollapsed(false);
        }
      }

      lastY = y;
    }

    function requestUpdate() {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(updateFromScroll);
      }
    }

    function handleWheel(event) {
      var y = getScrollY();

      if (isMobileViewport()) {
        return;
      }

      if (y <= collapseThreshold()) {
        setCollapsed(false);
      } else if (event.deltaY > DESKTOP_DELTA) {
        setCollapsed(true);
      } else if (event.deltaY < -DESKTOP_DELTA) {
        setCollapsed(false);
      }

      lastY = y;
    }

    function handleTouchStart() {
      touchActive = true;
      touchStartY = getScrollY();
      touchLastY = touchStartY;

      if (touchSettledTimer) {
        window.clearTimeout(touchSettledTimer);
        touchSettledTimer = 0;
      }
    }

    function settleTouchGesture() {
      var y = getScrollY();
      var gestureDelta = y - touchStartY;

      touchActive = false;

      if (y <= collapseThreshold()) {
        setCollapsed(false, true);
      } else if (gestureDelta >= MOBILE_GESTURE_DELTA) {
        setCollapsed(true, true);
      } else if (gestureDelta <= -MOBILE_GESTURE_DELTA) {
        setCollapsed(false, true);
      }

      lastY = y;
      touchStartY = y;
      touchLastY = y;
    }

    function handleTouchEnd() {
      if (touchSettledTimer) {
        window.clearTimeout(touchSettledTimer);
      }

      touchSettledTimer = window.setTimeout(settleTouchGesture, 96);
    }

    window.addEventListener("scroll", requestUpdate, { passive: true });
    window.addEventListener("touchstart", handleTouchStart, { passive: true });
    window.addEventListener("touchend", handleTouchEnd, { passive: true });
    window.addEventListener("touchcancel", handleTouchEnd, { passive: true });
    window.addEventListener("resize", function () {
      updateCollapseDistance();
      lastY = getScrollY();
      requestUpdate();
    });
    window.addEventListener("wheel", handleWheel, { passive: true });
    searchInput.addEventListener("input", function () {
      setCollapsed(false, true);
      requestUpdate();
    });

    updateCollapseDistance();
    setCollapsed(false, true);
    requestUpdate();
  }

  var categoryStrip = document.querySelector(".category-strip");
  if (categoryStrip) {
    categoryStrip.scrollLeft = 0;
  }

  setupStickySearchCollapse();
  syncDishOpenLabels();
  window.addEventListener("cc:languagechange", syncDishOpenLabels);

  document.addEventListener(
    "pointerdown",
    function (event) {
      var target = interactionTarget(event.target);

      if (target && runtimeState === "idle") {
        loadRuntime(target).catch(ignoreLoadFailure);
      }
    },
    { capture: true, passive: true }
  );

  document.addEventListener(
    "focusin",
    function (event) {
      var target = interactionTarget(event.target);

      if (target && runtimeState === "idle") {
        loadRuntime(target).catch(ignoreLoadFailure);
      }
    },
    true
  );

  document.addEventListener(
    "input",
    function (event) {
      var input = closest(event.target, searchSelector);

      if (!input || runtimeState === "loaded") {
        return;
      }

      pendingInput = input;
      loadRuntime(input)
        .then(flushPendingInteraction)
        .catch(ignoreLoadFailure);
    },
    true
  );

  document.addEventListener(
    "click",
    function (event) {
      var dishOpen = closest(event.target, dishOpenSelector);

      if (!dishOpen || runtimeState === "loaded") {
        return;
      }

      event.preventDefault();
      event.stopImmediatePropagation();
      pendingDishOpen = dishOpen;

      loadRuntime(dishOpen)
        .then(flushPendingInteraction)
        .catch(ignoreLoadFailure);
    },
    true
  );
})();
