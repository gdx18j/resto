(function () {
  "use strict";

  var controls = document.querySelector("[data-menu-sticky-controls]");
  var searchSelector = ".menu-search-input";
  var searchPanel = controls ? controls.querySelector(".menu-search-panel") : null;
  var categoryControls = controls ? controls.querySelector(".category-controls") : null;
  var searchInputs = controls ? controls.querySelectorAll(searchSelector) : [];
  var scroller = document.scrollingElement || document.documentElement;
  var compactQuery = window.matchMedia ? window.matchMedia("(max-width: 959px)") : null;
  var cleanup = [];
  var compactPlaceholder = null;

  if (!controls || !searchPanel || !categoryControls || !scroller) {
    return;
  }

  function on(target, eventName, handler, options) {
    target.addEventListener(eventName, handler, options);
    cleanup.push(function () {
      target.removeEventListener(eventName, handler, options);
    });
  }

  function removeCompactPlaceholder() {
    if (compactPlaceholder && compactPlaceholder.parentNode) {
      compactPlaceholder.parentNode.removeChild(compactPlaceholder);
    }
    compactPlaceholder = null;
  }

  function clearMode() {
    cleanup.forEach(function (dispose) {
      dispose();
    });
    cleanup = [];
    controls.classList.remove(
      "is-sticky-search-enhanced",
      "is-compact-sticky",
      "is-search-hidden",
      "is-search-visible"
    );
    controls.style.removeProperty("--menu-search-height");
    controls.style.removeProperty("--menu-compact-left");
    controls.style.removeProperty("--menu-compact-width");
    controls.style.removeProperty("--menu-compact-search-height");
    controls.style.removeProperty("--menu-compact-full-height");
    removeCompactPlaceholder();
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

  function setupCompact() {
    var hiddenClass = "is-search-hidden";
    var visibleClass = "is-search-visible";
    var lastY = getScrollY();
    var ticking = false;
    var isFixed = false;
    var searchVisible = true;
    var lastToggleAt = 0;
    var naturalControlsTop = 0;
    var stickyAt = 0;
    var releaseAt = 0;
    var fullOuterHeight = 0;
    var accumulatedDelta = 0;
    var lastDirection = 0;
    var minDelta = 8;
    var hideThreshold = 46;
    var showThreshold = 30;
    var toggleCooldownMs = 170;
    var releaseHysteresis = 12;

    function headerTop() {
      return rootPx("--header-height", 68) - 1;
    }

    function ensurePlaceholder() {
      if (!compactPlaceholder || !compactPlaceholder.isConnected) {
        compactPlaceholder = document.createElement("div");
        compactPlaceholder.className = "menu-controls-placeholder";
        compactPlaceholder.dataset.menuControlsPlaceholder = "";
        compactPlaceholder.hidden = true;
        controls.insertAdjacentElement("afterend", compactPlaceholder);
      }

      return compactPlaceholder;
    }

    function resetDirectionState() {
      accumulatedDelta = 0;
      lastDirection = 0;
    }

    function outerHeightFor(element, rect) {
      var styles = window.getComputedStyle(element);
      var marginBottom = parseFloat(styles.marginBottom) || 0;

      return Math.max(0, Math.round(rect.height + marginBottom));
    }

    function searchPanelHeight() {
      return Math.max(
        0,
        Math.round(searchPanel.scrollHeight || searchPanel.getBoundingClientRect().height)
      );
    }

    function syncCompactGeometry() {
      var placeholder = ensurePlaceholder();
      var anchor = isFixed && !placeholder.hidden ? placeholder : controls;
      var rect = anchor.getBoundingClientRect();
      var measuredHeight = isFixed && fullOuterHeight
        ? fullOuterHeight
        : outerHeightFor(controls, controls.getBoundingClientRect());
      var searchHeight = searchPanelHeight();

      naturalControlsTop = Math.max(0, Math.round(rect.top + getScrollY()));
      stickyAt = Math.max(0, naturalControlsTop - headerTop());
      releaseAt = Math.max(0, stickyAt - releaseHysteresis);
      fullOuterHeight = measuredHeight;

      controls.style.setProperty("--menu-compact-left", Math.round(rect.left) + "px");
      controls.style.setProperty("--menu-compact-width", Math.round(rect.width) + "px");
      controls.style.setProperty("--menu-compact-search-height", searchHeight + "px");
      controls.style.setProperty("--menu-compact-full-height", measuredHeight + "px");
      placeholder.style.height = measuredHeight + "px";
    }

    function showPlaceholder() {
      var placeholder = ensurePlaceholder();

      placeholder.hidden = false;
      placeholder.style.height = fullOuterHeight + "px";
    }

    function hidePlaceholder() {
      if (!compactPlaceholder) {
        return;
      }

      compactPlaceholder.hidden = true;
      compactPlaceholder.style.removeProperty("height");
    }

    function setSearchVisible(nextVisible, force) {
      if (!isFixed) {
        nextVisible = true;
      }
      nextVisible = Boolean(nextVisible || searchHasQuery() || hasFocusedSearch());

      if (!force && nextVisible === searchVisible) {
        return;
      }
      if (!force && Date.now() - lastToggleAt < toggleCooldownMs) {
        return;
      }

      searchVisible = nextVisible;
      lastToggleAt = Date.now();
      resetDirectionState();
      controls.classList.toggle(visibleClass, searchVisible);
      controls.classList.toggle(hiddenClass, !searchVisible);
      setTabIndex(searchVisible);
    }

    function fixControls() {
      if (isFixed) {
        return;
      }

      syncCompactGeometry();
      showPlaceholder();
      controls.classList.add("is-compact-sticky");
      isFixed = true;
      setSearchVisible(true, true);
      syncCompactGeometry();
    }

    function releaseControls() {
      if (!isFixed) {
        return;
      }

      isFixed = false;
      controls.classList.remove("is-compact-sticky", hiddenClass);
      controls.classList.add(visibleClass);
      controls.style.removeProperty("--menu-compact-left");
      controls.style.removeProperty("--menu-compact-width");
      hidePlaceholder();
      searchVisible = true;
      resetDirectionState();
      setTabIndex(true);
      syncCompactGeometry();
    }

    function updateFromScroll() {
      var y = getScrollY();
      var delta = y - lastY;
      var direction;

      ticking = false;

      if (!isFixed) {
        syncCompactGeometry();
      }

      if (!isFixed && y >= stickyAt) {
        fixControls();
      } else if (isFixed && y <= releaseAt) {
        releaseControls();
        lastY = y;
        return;
      }

      if (!isFixed) {
        setSearchVisible(true);
        lastY = y;
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

    ensurePlaceholder();
    controls.classList.add(visibleClass);
    syncCompactGeometry();
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
      syncCompactGeometry();
      if (isFixed) {
        showPlaceholder();
      }
      lastY = getScrollY();
      resetDirectionState();
      requestUpdate();
    }, { passive: true });
    on(window, "orientationchange", function () {
      syncCompactGeometry();
      if (isFixed) {
        showPlaceholder();
      }
      lastY = getScrollY();
      resetDirectionState();
      requestUpdate();
    }, { passive: true });
    on(window, "pageshow", function () {
      syncCompactGeometry();
      lastY = getScrollY();
      resetDirectionState();
      requestUpdate();
    });
    requestUpdate();
  }

  function setup() {
    clearMode();
    if (compactQuery && compactQuery.matches) {
      setupCompact();
    } else {
      setupDesktop();
    }
  }

  setup();
  if (compactQuery) {
    if (typeof compactQuery.addEventListener === "function") {
      compactQuery.addEventListener("change", setup);
    } else if (typeof compactQuery.addListener === "function") {
      compactQuery.addListener(setup);
    }
  }
})();
