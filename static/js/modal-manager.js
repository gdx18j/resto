(function () {
  "use strict";

  var FOCUSABLE_SELECTOR = [
    "a[href]",
    "area[href]",
    "button:not([disabled])",
    "input:not([disabled]):not([type='hidden'])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "iframe",
    "object",
    "embed",
    "audio[controls]",
    "video[controls]",
    "[contenteditable='true']",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  var stack = [];
  var scrollLocks = 0;
  var previousBodyOverflow = "";

  function toArray(value) {
    return Array.prototype.slice.call(value || []);
  }

  function isElement(value) {
    return value && value.nodeType === 1;
  }

  function isVisible(element) {
    var style;

    if (!isElement(element) || element.hidden) {
      return false;
    }

    style = window.getComputedStyle(element);

    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      element.getClientRects().length > 0
    );
  }

  function getFocusable(container) {
    if (!container) {
      return [];
    }

    return toArray(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(function (element) {
      return isVisible(element) && !element.closest("[inert]");
    });
  }

  function resolveElement(value, fallbackRoot) {
    if (typeof value === "function") {
      return value();
    }

    if (typeof value === "string") {
      return (fallbackRoot || document).querySelector(value);
    }

    return value || null;
  }

  function focusElement(element) {
    if (!element || typeof element.focus !== "function") {
      return false;
    }

    try {
      element.focus({ preventScroll: true });
    } catch (error) {
      element.focus();
    }

    return document.activeElement === element;
  }

  function focusInitial(instance) {
    var target = resolveElement(instance.initialFocus, instance.dialog);
    var focusable;

    if (!target || !isVisible(target)) {
      focusable = getFocusable(instance.dialog);
      target = focusable[0] || instance.dialog;
    }

    if (target === instance.dialog && !target.hasAttribute("tabindex")) {
      target.setAttribute("tabindex", "-1");
      instance.addedDialogTabindex = true;
    }

    focusElement(target);
  }

  function lockScroll() {
    if (scrollLocks === 0) {
      previousBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }

    scrollLocks += 1;
  }

  function unlockScroll() {
    scrollLocks = Math.max(0, scrollLocks - 1);

    if (scrollLocks === 0) {
      document.body.style.overflow = previousBodyOverflow;
      previousBodyOverflow = "";
    }
  }

  function directChildren(node) {
    return toArray(node ? node.children : []);
  }

  function isExempt(node, exemptElements) {
    return exemptElements.some(function (exempt) {
      return exempt && (node === exempt || node.contains(exempt) || exempt.contains(node));
    });
  }

  function setNodeInert(node, state) {
    state.push({
      node: node,
      hadAriaHidden: node.hasAttribute("aria-hidden"),
      ariaHidden: node.getAttribute("aria-hidden"),
      hadInert: node.hasAttribute("inert"),
      inert: Boolean(node.inert),
    });

    node.setAttribute("aria-hidden", "true");
    node.setAttribute("inert", "");

    try {
      node.inert = true;
    } catch (error) {
      return;
    }
  }

  function restoreNodeState(record) {
    if (record.hadAriaHidden) {
      record.node.setAttribute("aria-hidden", record.ariaHidden);
    } else {
      record.node.removeAttribute("aria-hidden");
    }

    if (record.hadInert || record.inert) {
      record.node.setAttribute("inert", "");
    } else {
      record.node.removeAttribute("inert");
    }

    try {
      record.node.inert = Boolean(record.inert);
    } catch (error) {
      return;
    }
  }

  function applyBackgroundIsolation(instance) {
    var container = instance.container;
    var exemptElements = [instance.root].concat(instance.exemptElements || []);
    var state = [];

    directChildren(container).forEach(function (node) {
      if (!isExempt(node, exemptElements)) {
        setNodeInert(node, state);
      }
    });

    instance.backgroundState = state;
  }

  function restoreBackgroundIsolation(instance) {
    instance.backgroundState.slice().reverse().forEach(restoreNodeState);
    instance.backgroundState = [];
  }

  function findInstance(target) {
    return stack.find(function (instance) {
      return instance.root === target || instance.dialog === target;
    });
  }

  function getTop() {
    return stack[stack.length - 1] || null;
  }

  function removeInstance(instance) {
    stack = stack.filter(function (candidate) {
      return candidate !== instance;
    });
  }

  function close(target, options) {
    var instance = findInstance(target);
    var shouldRestoreFocus = !options || options.restoreFocus !== false;
    var opener;

    if (!instance) {
      return false;
    }

    removeInstance(instance);
    restoreBackgroundIsolation(instance);

    if (instance.lockScroll) {
      unlockScroll();
    }

    if (instance.addedDialogTabindex) {
      instance.dialog.removeAttribute("tabindex");
    }

    if (shouldRestoreFocus) {
      opener = instance.returnFocusTo || instance.opener;

      if (opener && document.contains(opener) && isVisible(opener)) {
        focusElement(opener);
      }
    }

    return true;
  }

  function open(dialog, options) {
    var settings = options || {};
    var root = settings.root || dialog;
    var existing;
    var opener;
    var instance;

    if (!root || !dialog) {
      return null;
    }

    existing = findInstance(root);

    if (existing) {
      focusInitial(existing);
      return existing;
    }

    opener = settings.opener || document.activeElement;

    if (opener && (root === opener || root.contains(opener))) {
      opener = null;
    }

    dialog.setAttribute("role", dialog.getAttribute("role") || "dialog");
    dialog.setAttribute("aria-modal", "true");
    root.setAttribute("aria-hidden", "false");

    instance = {
      root: root,
      dialog: dialog,
      container: settings.container || root.parentElement || document.body,
      opener: opener,
      returnFocusTo: settings.returnFocusTo || opener,
      initialFocus: settings.initialFocus || null,
      exemptElements: toArray(settings.exemptElements),
      requestClose: settings.requestClose || null,
      lockScroll: settings.lockScroll !== false,
      enforceFocus: settings.enforceFocus !== false,
      backgroundState: [],
      addedDialogTabindex: false,
    };

    applyBackgroundIsolation(instance);
    stack.push(instance);

    if (instance.lockScroll) {
      lockScroll();
    }

    window.requestAnimationFrame(function () {
      if (findInstance(root)) {
        focusInitial(instance);
      }
    });

    return instance;
  }

  function handleTab(event, instance) {
    var focusable = getFocusable(instance.dialog);
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    var active = document.activeElement;

    if (!focusable.length) {
      event.preventDefault();
      event.stopImmediatePropagation();
      focusInitial(instance);
      return;
    }

    if (event.shiftKey && (active === first || !instance.dialog.contains(active))) {
      event.preventDefault();
      event.stopImmediatePropagation();
      focusElement(last);
      return;
    }

    if (!event.shiftKey && active === last) {
      event.preventDefault();
      event.stopImmediatePropagation();
      focusElement(first);
    }
  }

  function handleKeydown(event) {
    var instance = getTop();

    if (!instance) {
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();

      if (typeof instance.requestClose === "function") {
        instance.requestClose();
      } else {
        close(instance.root);
      }

      return;
    }

    if (event.key === "Tab") {
      handleTab(event, instance);
    }
  }

  function handleFocusIn(event) {
    var instance = getTop();

    if (
      !instance ||
      instance.enforceFocus === false ||
      instance.dialog.contains(event.target)
    ) {
      return;
    }

    window.requestAnimationFrame(function () {
      var current = getTop();

      if (current === instance && !instance.dialog.contains(document.activeElement)) {
        focusInitial(instance);
      }
    });
  }

  function setExpanded(openers, isOpen) {
    openers.forEach(function (opener) {
      opener.setAttribute("aria-expanded", String(isOpen));
    });
  }

  function initDeclarativeModal(root) {
    var toggleId = root.getAttribute("data-modal-toggle-id");
    var checkbox = toggleId ? document.getElementById(toggleId) : null;
    var id = root.id;
    var dialog = root.querySelector("[data-modal-dialog]") || root.querySelector("[role='dialog']") || root;
    var openers = toArray(document.querySelectorAll("[data-modal-open='" + id + "']"));
    var closers = toArray(root.querySelectorAll("[data-modal-close]"));

    if (!checkbox || !id) {
      return;
    }

    function setOpen(isOpen, opener) {
      checkbox.checked = isOpen;
      root.setAttribute("aria-hidden", String(!isOpen));
      setExpanded(openers, isOpen);

      if (isOpen) {
        open(dialog, {
          root: root,
          container: root.parentElement || document.body,
          opener: opener || document.activeElement,
          initialFocus: closers[0] || dialog,
          requestClose: function () {
            setOpen(false);
          },
        });
        return;
      }

      close(root);
    }

    openers.forEach(function (opener) {
      opener.setAttribute("aria-controls", id);
      opener.setAttribute("aria-haspopup", "dialog");
      opener.setAttribute("aria-expanded", String(checkbox.checked));

      opener.addEventListener("click", function (event) {
        event.preventDefault();
        setOpen(true, opener);
      });
    });

    closers.forEach(function (closer) {
      closer.addEventListener("click", function (event) {
        event.preventDefault();
        setOpen(false);
      });
    });

    checkbox.addEventListener("change", function () {
      setOpen(checkbox.checked);
    });

    root.setAttribute("aria-hidden", String(!checkbox.checked));

    if (checkbox.checked) {
      setOpen(true);
    }
  }

  function initDeclarativeModals() {
    toArray(document.querySelectorAll("[data-modal-toggle-id]")).forEach(initDeclarativeModal);
  }

  document.addEventListener("keydown", handleKeydown, true);
  document.addEventListener("focusin", handleFocusIn, true);

  window.CaesarModal = {
    open: open,
    close: close,
    isOpen: function (target) {
      return Boolean(findInstance(target));
    },
    hasOpen: function () {
      return stack.length > 0;
    },
    focusFirst: function (target) {
      var instance = findInstance(target);

      if (instance) {
        focusInitial(instance);
      }
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDeclarativeModals);
  } else {
    initDeclarativeModals();
  }
})();
