(function () {
  "use strict";

  var loaderScript = document.currentScript;
  var runtimeUrl = loaderScript ? loaderScript.dataset.aiScriptUrl || "" : "";
  var rootSelector = "[data-ai-assistant]";
  var launcherSelector = "[data-ai-open]";
  var runtimeState = "idle";
  var runtimePromise = null;
  var pendingLauncher = null;
  var pendingOpenRequested = false;

  if (!runtimeUrl || !document.querySelector(rootSelector)) {
    return;
  }

  function findLauncher(target) {
    var launcher;

    if (!target || typeof target.closest !== "function") {
      return null;
    }

    launcher = target.closest(launcherSelector);

    if (!launcher || !launcher.closest(rootSelector)) {
      return null;
    }

    return launcher;
  }

  function setLoading(isLoading) {
    var roots = document.querySelectorAll(rootSelector);

    Array.prototype.forEach.call(roots, function (root) {
      var launcher = root.querySelector(launcherSelector);

      root.toggleAttribute("aria-busy", isLoading);

      if (launcher) {
        launcher.toggleAttribute("aria-busy", isLoading);
      }
    });
  }

  function loadRuntime() {
    if (runtimeState === "loaded") {
      return Promise.resolve();
    }

    if (runtimePromise) {
      return runtimePromise;
    }

    runtimeState = "loading";
    setLoading(true);

    runtimePromise = new Promise(function (resolve, reject) {
      var runtimeScript = document.createElement("script");

      runtimeScript.src = runtimeUrl;
      runtimeScript.async = true;
      runtimeScript.dataset.aiAssistantRuntime = "";

      runtimeScript.addEventListener(
        "load",
        function () {
          runtimeState = "loaded";
          setLoading(false);
          resolve();
        },
        { once: true }
      );

      runtimeScript.addEventListener(
        "error",
        function () {
          runtimeScript.remove();
          runtimePromise = null;
          runtimeState = "idle";
          pendingLauncher = null;
          pendingOpenRequested = false;
          setLoading(false);
          reject(new Error("AI assistant runtime failed to load."));
        },
        { once: true }
      );

      document.head.appendChild(runtimeScript);
    });

    return runtimePromise;
  }

  function flushPendingToggle() {
    var launcher = pendingLauncher;
    var shouldOpen = pendingOpenRequested;

    pendingLauncher = null;
    pendingOpenRequested = false;

    if (launcher && shouldOpen && launcher.isConnected) {
      launcher.click();
    }
  }

  function ignoreLoadFailure() {
    return;
  }

  document.addEventListener(
    "pointerdown",
    function (event) {
      if (runtimeState === "idle" && findLauncher(event.target)) {
        loadRuntime().catch(ignoreLoadFailure);
      }
    },
    { capture: true, passive: true }
  );

  document.addEventListener(
    "click",
    function (event) {
      var launcher = findLauncher(event.target);

      if (!launcher || runtimeState === "loaded") {
        return;
      }

      event.preventDefault();
      event.stopImmediatePropagation();

      pendingLauncher = launcher;
      pendingOpenRequested = true;

      loadRuntime()
        .then(flushPendingToggle)
        .catch(ignoreLoadFailure);
    },
    true
  );
})();
