(function () {
  var storageKey = "resto-theme";
  var themeToggle = document.getElementById("theme-toggle");
  var themeButton = document.querySelector('label[for="theme-toggle"]');
  var reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

  if (!themeToggle) {
    return;
  }

  function persistTheme() {
    try {
      window.localStorage.setItem(storageKey, themeToggle.checked ? "light" : "dark");
    } catch (error) {
      // Local storage can be unavailable in private or restricted browser modes.
    }
  }

  function applyStoredTheme() {
    try {
      themeToggle.checked = window.localStorage.getItem(storageKey) === "light";
    } catch (error) {
      themeToggle.checked = false;
    }
  }

  function switchTheme() {
    themeToggle.checked = !themeToggle.checked;
    persistTheme();
  }

  function getTransitionOrigin(event) {
    if (typeof event.clientX === "number" && typeof event.clientY === "number") {
      return { x: event.clientX, y: event.clientY };
    }

    if (!themeButton) {
      return { x: window.innerWidth / 2, y: 0 };
    }

    var rect = themeButton.getBoundingClientRect();

    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };
  }

  function animateTheme(event) {
    var origin = getTransitionOrigin(event);
    var maxX = Math.max(origin.x, window.innerWidth - origin.x);
    var maxY = Math.max(origin.y, window.innerHeight - origin.y);
    var radius = Math.hypot(maxX, maxY);

    document.documentElement.classList.add("theme-transitioning");

    var transition = document.startViewTransition(switchTheme);

    transition.ready
      .then(function () {
        document.documentElement.animate(
          {
            clipPath: [
              "circle(0px at " + origin.x + "px " + origin.y + "px)",
              "circle(" + radius + "px at " + origin.x + "px " + origin.y + "px)",
            ],
          },
          {
            duration: 560,
            easing: "cubic-bezier(0.22, 1, 0.36, 1)",
            pseudoElement: "::view-transition-new(root)",
          }
        );
      })
      .catch(function () {});

    transition.finished.finally(function () {
      document.documentElement.classList.remove("theme-transitioning");
    });
  }

  themeToggle.addEventListener("change", function () {
    persistTheme();
  });

  if (themeButton) {
    themeButton.addEventListener("click", function (event) {
      if (!document.startViewTransition || reduceMotionQuery.matches) {
        return;
      }

      event.preventDefault();
      animateTheme(event);
    });
  }

  applyStoredTheme();
})();
