(function () {
  var shell = document.querySelector(".app-shell");
  var search = document.querySelector(".search-section");
  var categoryStrip = document.querySelector(".category-strip");

  if (categoryStrip) {
    categoryStrip.scrollLeft = 0;
  }

  if (!shell || !search) {
    return;
  }

  var lastScrollY = window.scrollY;
  var scrollIntent = 0;
  var ticking = false;
  var lockUntil = 0;
  var hideDistance = 52;
  var showDistance = -18;

  function isSearchFocused() {
    return search.contains(document.activeElement);
  }

  function setSearchHidden(isHidden) {
    if (isHidden && isSearchFocused()) {
      return;
    }

    if (shell.classList.contains("search-hidden") === isHidden) {
      return;
    }

    shell.classList.toggle("search-hidden", isHidden);
    scrollIntent = 0;
    lockUntil = window.performance.now() + 280;
  }

  function updateSearchVisibility() {
    var currentScrollY = window.scrollY;
    var delta = currentScrollY - lastScrollY;
    var now = window.performance.now();

    if (currentScrollY < 90) {
      setSearchHidden(false);
    } else if (now >= lockUntil && Math.abs(delta) > 1) {
      if (Math.sign(delta) !== Math.sign(scrollIntent)) {
        scrollIntent = 0;
      }

      scrollIntent += delta;

      if (scrollIntent > hideDistance) {
        setSearchHidden(true);
      } else if (scrollIntent < showDistance) {
        setSearchHidden(false);
      }
    }

    lastScrollY = currentScrollY;
    ticking = false;
  }

  window.addEventListener(
    "scroll",
    function () {
      if (!ticking) {
        window.requestAnimationFrame(updateSearchVisibility);
        ticking = true;
      }
    },
    { passive: true }
  );

  search.addEventListener("focusin", function () {
    setSearchHidden(false);
  });
})();
