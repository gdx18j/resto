(function () {
  "use strict";

  var controls = document.querySelector("[data-menu-sticky-controls]");
  var searchSelector = ".menu-search-input";
  var searchPanel = controls ? controls.querySelector(".menu-search-panel") : null;
  var categoryControls = controls ? controls.querySelector(".category-controls") : null;
  var searchInputs = controls ? controls.querySelectorAll(searchSelector) : [];
  var scroller = document.scrollingElement || document.documentElement;
  var mediaQuery = window.matchMedia ? window.matchMedia("(max-width: 619px)") : null;
  var cleanup = [];

  if (!controls || !searchPanel || !categoryControls || !scroller) {
    return;
  }

  function on(target, eventName, handler, options) {
    target.addEventListener(eventName, handler, options);
    cleanup.push(function () {
      target.removeEventListener(eventName, handler, options);
    });
  }

  function clearMode() {
    cleanup.forEach(function (dispose) {
      dispose();
    });
    cleanup = [];
    controls.classList.remove(
      "is-sticky-search-enhanced",
      "is-mobile-directional-menu",
      "is-mobile-menu-floating",
      "is-mobile-stable-menu",
      "is-search-hidden",
      "is-search-visible"
    );
    controls.style.removeProperty("--menu-search-height");
    controls.style.removeProperty("--menu-mobile-search-offset");
    controls.style.removeProperty("--menu-mobile-hidden-height");
    controls.style.removeProperty("--menu-mobile-visible-height");
    controls.style.removeProperty("--menu-mobile-placeholder-height");
    controls.style.removeProperty("--menu-mobile-search-panel-height");
    Array.prototype.forEach.call(searchInputs, function (input) {
      input.removeAttribute("tabindex");
    });
  }

  function getScrollY() {
    return window.pageYOffset
      || scroller.scrollTop
      || document.documentElement.scrollTop
      || document.body.scrollTop
      || 0;
  }

  function cssPx(element, name, fallback) {
    var value = window.getComputedStyle(element).getPropertyValue(name);
    var parsed = parseFloat(value);

    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function rootPx(name, fallback) {
    return cssPx(document.documentElement, name, fallback);
  }

  function searchHasQuery() {
    return Array.prototype.some.call(searchInputs, function (input) {
      return Boolean(input.value && input.value.trim());
    });
  }

  function hasFocusedSearch() {
    return Boolean(searchPanel.contains(document.activeElement));
  }

  function setTabIndex(enabled) {
    Array.prototype.forEach.call(searchInputs, function (input) {
      if (enabled) {
        input.removeAttribute("tabindex");
      } else {
        input.setAttribute("tabindex", "-1");
      }
    });
  }

  function setupDesktop() {
    var hiddenClass = "is-search-hidden";
    var visibleClass = "is-search-visible";
    var lastY = getScrollY();
    var ticking = false;
    var searchVisible = true;
    var lastToggleAt = 0;
    var naturalControlsTop = 0;
    var minDelta = 10;
    var hideAfterPinned = 72;
    var showDelta = 18;
    var topLock = 96;
    var toggleCooldownMs = 150;

    function headerTop() {
      return rootPx("--header-height", 68) - 1;
    }

    function syncSearchHeight() {
      controls.style.setProperty(
        "--menu-search-height",
        Math.max(0, Math.round(searchPanel.getBoundingClientRect().height)) + "px"
      );
    }

    function syncNaturalTop() {
      // offsetTop is stable for sticky elements and avoids a feedback loop where
      // getBoundingClientRect().top changes after we toggle the hidden/visible classes.
      naturalControlsTop = Math.max(0, Math.round(controls.offsetTop || 0));
    }

    function syncMeasurements() {
      syncSearchHeight();
      syncNaturalTop();
    }

    function isNearOrPastControls(y) {
      return y >= naturalControlsTop - headerTop() - 2;
    }

    function setSearchVisible(nextVisible, force) {
      nextVisible = Boolean(nextVisible || searchHasQuery() || hasFocusedSearch());

      if (!force && nextVisible === searchVisible) {
        return;
      }
      if (!force && Date.now() - lastToggleAt < toggleCooldownMs) {
        return;
      }

      syncSearchHeight();
      searchVisible = nextVisible;
      lastToggleAt = Date.now();
      controls.classList.toggle(visibleClass, searchVisible);
      controls.classList.toggle(hiddenClass, !searchVisible);
      setTabIndex(searchVisible);
    }

    function updateFromScroll() {
      var y = getScrollY();
      var delta = y - lastY;
      var distancePastControls = y - Math.max(0, naturalControlsTop - headerTop());

      ticking = false;

      if (y <= topLock || !isNearOrPastControls(y)) {
        setSearchVisible(true);
        lastY = y;
        return;
      }

      if (Math.abs(delta) < minDelta) {
        lastY = y;
        return;
      }

      if (delta > 0 && distancePastControls >= hideAfterPinned) {
        setSearchVisible(false);
      } else if (delta < 0 && (searchVisible === false || Math.abs(delta) >= showDelta)) {
        setSearchVisible(true);
      }

      lastY = y;
    }

    function requestUpdate() {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(updateFromScroll);
      }
    }

    controls.classList.add("is-sticky-search-enhanced");
    syncMeasurements();
    setSearchVisible(true, true);

    Array.prototype.forEach.call(searchInputs, function (input) {
      on(input, "focus", function () {
        setSearchVisible(true, true);
      });
      on(input, "input", function () {
        setSearchVisible(true, true);
      });
    });
    on(window, "scroll", requestUpdate, { passive: true });
    on(window, "resize", function () {
      syncMeasurements();
      lastY = getScrollY();
      requestUpdate();
    }, { passive: true });
    on(window, "pageshow", function () {
      syncMeasurements();
      lastY = getScrollY();
      requestUpdate();
    });
    requestUpdate();
  }

  function setupMobile() {
    var hiddenClass = "is-search-hidden";
    var visibleClass = "is-search-visible";
    var lastY = getScrollY();
    var ticking = false;
    var searchVisible = true;
    var lastToggleAt = 0;
    var naturalControlsTop = 0;
    var accumulatedDelta = 0;
    var lastDirection = 0;
    var minDelta = 6;
    var hideThreshold = 34;
    var showThreshold = 22;
    var topLock = 56;
    var pinnedOffset = 28;
    var toggleCooldownMs = 240;

    function headerTop() {
      return rootPx("--header-height", 68) - 1;
    }

    function syncMeasurements() {
      // Use intrinsic height. getBoundingClientRect().height becomes 0 when
      // the panel is collapsed, which would otherwise prevent reopening.
      var height = Math.max(
        0,
        Math.round(searchPanel.scrollHeight || searchPanel.getBoundingClientRect().height)
      );

      controls.style.setProperty("--menu-mobile-search-panel-height", height + "px");
      naturalControlsTop = Math.max(0, Math.round(controls.offsetTop || 0));
    }

    function isPinnedEnough(y) {
      return y >= naturalControlsTop - headerTop() + pinnedOffset;
    }

    function resetDirectionState() {
      accumulatedDelta = 0;
      lastDirection = 0;
    }

    function setSearchVisible(nextVisible, force) {
      nextVisible = Boolean(nextVisible || searchHasQuery() || hasFocusedSearch());

      if (!force && nextVisible === searchVisible) {
        return;
      }
      if (!force && Date.now() - lastToggleAt < toggleCooldownMs) {
        return;
      }

      syncMeasurements();
      searchVisible = nextVisible;
      lastToggleAt = Date.now();
      resetDirectionState();
      controls.classList.add("is-mobile-directional-menu");
      controls.classList.remove("is-mobile-stable-menu", "is-mobile-menu-floating");
      controls.classList.toggle(visibleClass, searchVisible);
      controls.classList.toggle(hiddenClass, !searchVisible);
      setTabIndex(searchVisible);
    }

    function updateFromScroll() {
      var y = getScrollY();
      var delta = y - lastY;
      var direction;

      ticking = false;

      if (y <= topLock || !isPinnedEnough(y)) {
        setSearchVisible(true);
        lastY = y;
        resetDirectionState();
        return;
      }

      if (Math.abs(delta) < minDelta) {
        lastY = y;
        return;
      }

      direction = delta > 0 ? 1 : -1;
      if (direction !== lastDirection) {
        accumulatedDelta = 0;
        lastDirection = direction;
      }
      accumulatedDelta += delta;

      if (direction > 0 && accumulatedDelta >= hideThreshold) {
        setSearchVisible(false);
      } else if (direction < 0 && Math.abs(accumulatedDelta) >= showThreshold) {
        setSearchVisible(true);
      }

      lastY = y;
    }

    function requestUpdate() {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(updateFromScroll);
      }
    }

    syncMeasurements();
    setSearchVisible(true, true);

    Array.prototype.forEach.call(searchInputs, function (input) {
      on(input, "focus", function () {
        setSearchVisible(true, true);
      });
      on(input, "input", function () {
        setSearchVisible(true, true);
      });
    });
    on(window, "scroll", requestUpdate, { passive: true });
    on(window, "resize", function () {
      syncMeasurements();
      lastY = getScrollY();
      resetDirectionState();
      requestUpdate();
    }, { passive: true });
    on(window, "orientationchange", function () {
      syncMeasurements();
      lastY = getScrollY();
      resetDirectionState();
      requestUpdate();
    }, { passive: true });
    on(window, "pageshow", function () {
      syncMeasurements();
      lastY = getScrollY();
      resetDirectionState();
      requestUpdate();
    });
    requestUpdate();
  }

  function setup() {
    clearMode();
    if (mediaQuery && mediaQuery.matches) {
      setupMobile();
    } else {
      setupDesktop();
    }
  }

  setup();
  if (mediaQuery) {
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", setup);
    } else if (typeof mediaQuery.addListener === "function") {
      mediaQuery.addListener(setup);
    }
  }
})();
