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
      "is-search-hidden",
      "is-search-visible"
    );
    controls.style.removeProperty("--menu-search-height");
    controls.style.removeProperty("--menu-mobile-search-offset");
    controls.style.removeProperty("--menu-mobile-hidden-height");
    controls.style.removeProperty("--menu-mobile-visible-height");
    controls.style.removeProperty("--menu-mobile-placeholder-height");
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

  function controlVar(name) {
    var parsed = parseFloat(controls.style.getPropertyValue(name));

    return Number.isFinite(parsed) ? parsed : 0;
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
    var pinnedAtY = null;
    var minDelta = 14;
    var pinnedHideDistance = 54;
    var topLock = 96;
    var toggleCooldownMs = 150;

    function stickyTop() {
      var headerHeight = rootPx("--header-height", 68);
      var searchHeight = controlVar("--menu-search-height");
      var searchGap = controlVar("--menu-search-gap");

      return searchVisible
        ? headerHeight + searchHeight + searchGap - 1
        : headerHeight - 1;
    }

    function syncSearchHeight() {
      controls.style.setProperty(
        "--menu-search-height",
        Math.max(0, Math.round(searchPanel.getBoundingClientRect().height)) + "px"
      );
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

    function isControlsPinned() {
      return controls.getBoundingClientRect().top <= stickyTop() + 2;
    }

    function updateFromScroll() {
      var y = getScrollY();
      var delta = y - lastY;

      ticking = false;

      if (y <= topLock) {
        pinnedAtY = null;
        setSearchVisible(true);
        lastY = y;
        return;
      }

      if (Math.abs(delta) < minDelta) {
        lastY = y;
        return;
      }

      if (!isControlsPinned()) {
        pinnedAtY = null;
        setSearchVisible(true);
        lastY = y;
        return;
      }

      if (pinnedAtY === null) {
        pinnedAtY = y;
      } else if (delta > 0 && y - pinnedAtY >= pinnedHideDistance) {
        setSearchVisible(false);
      } else if (delta < 0) {
        pinnedAtY = y;
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
    syncSearchHeight();
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
      syncSearchHeight();
      lastY = getScrollY();
      pinnedAtY = null;
      requestUpdate();
    }, { passive: true });
    requestUpdate();
  }

  function setupMobile() {
    var placeholder = document.createElement("div");
    var hiddenClass = "is-search-hidden";
    var visibleClass = "is-search-visible";
    var lastY = getScrollY();
    var ticking = false;
    var floating = false;
    var searchVisible = true;
    var downDistance = 0;
    var minDelta = 8;
    var hideDistance = 34;
    var releaseDistance = 24;
    var topLock = 88;

    placeholder.className = "menu-controls-placeholder";
    placeholder.hidden = true;
    controls.insertAdjacentElement("afterend", placeholder);
    cleanup.push(function () {
      placeholder.remove();
    });

    var flowBottomMargin = cssPx(controls, "margin-bottom", 0);

    function headerTop() {
      return rootPx("--header-height", 68) - 1;
    }

    function measure() {
      var controlsStyle = window.getComputedStyle(controls);
      var searchStyle = window.getComputedStyle(searchPanel);
      var paddingY = cssPx(controls, "padding-top", 0) + cssPx(controls, "padding-bottom", 0);
      var searchOffset = Math.max(
        0,
        Math.round(searchPanel.getBoundingClientRect().height + cssPx(searchPanel, "margin-bottom", 0))
      );
      var hiddenHeight = Math.max(
        0,
        Math.round(categoryControls.getBoundingClientRect().height + paddingY)
      );
      var visibleHeight = Math.max(hiddenHeight, hiddenHeight + searchOffset);

      if (controlsStyle.display === "none") {
        return;
      }

      if (!floating) {
        flowBottomMargin = cssPx(controls, "margin-bottom", flowBottomMargin);
      }
      controls.style.setProperty("--menu-mobile-search-offset", searchOffset + "px");
      controls.style.setProperty("--menu-mobile-hidden-height", hiddenHeight + "px");
      controls.style.setProperty("--menu-mobile-visible-height", visibleHeight + "px");
      controls.style.setProperty("--menu-mobile-placeholder-height", Math.round(visibleHeight + flowBottomMargin) + "px");
      placeholder.style.height = "var(--menu-mobile-placeholder-height)";
    }

    function anchorTop() {
      return floating
        ? placeholder.getBoundingClientRect().top
        : controls.getBoundingClientRect().top;
    }

    function setSearchVisible(nextVisible, force) {
      nextVisible = Boolean(nextVisible || searchHasQuery() || hasFocusedSearch());

      if (!force && nextVisible === searchVisible) {
        return;
      }

      searchVisible = nextVisible;
      controls.classList.toggle(visibleClass, searchVisible);
      controls.classList.toggle(hiddenClass, !searchVisible);
      setTabIndex(searchVisible);
    }

    function setFloating(nextFloating) {
      if (nextFloating === floating) {
        return;
      }

      floating = nextFloating;
      if (floating) {
        measure();
        placeholder.hidden = false;
        controls.classList.add("is-mobile-menu-floating");
      } else {
        placeholder.hidden = true;
        controls.classList.remove("is-mobile-menu-floating");
        setSearchVisible(true, true);
        downDistance = 0;
      }
    }

    function updateFromScroll() {
      var y = getScrollY();
      var delta = y - lastY;

      ticking = false;
      measure();

      if (y <= topLock) {
        setFloating(false);
        lastY = y;
        return;
      }

      if (floating) {
        if (anchorTop() > headerTop() + releaseDistance) {
          setFloating(false);
        }
      } else if (anchorTop() <= headerTop()) {
        setFloating(true);
      }

      if (floating && Math.abs(delta) >= minDelta) {
        if (delta > 0) {
          downDistance += delta;
          if (downDistance >= hideDistance) {
            setSearchVisible(false);
          }
        } else {
          downDistance = 0;
          setSearchVisible(true);
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

    controls.classList.add("is-mobile-directional-menu", visibleClass);
    measure();

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
      measure();
      lastY = getScrollY();
      requestUpdate();
    }, { passive: true });
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
