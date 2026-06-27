(function () {
  var shell = document.querySelector(".app-shell");
  var search = document.querySelector(".search-section");
  var categoryStrip = document.querySelector(".category-strip");

  if (!shell || !search) {
    return;
  }

  if (categoryStrip) {
    categoryStrip.scrollLeft = 0;
  }

  var lastScrollY = window.scrollY;
  var ticking = false;
  var threshold = 8;

  function updateSearchVisibility() {
    var currentScrollY = window.scrollY;
    var delta = currentScrollY - lastScrollY;

    if (currentScrollY < 80) {
      shell.classList.remove("search-hidden");
    } else if (delta > threshold) {
      shell.classList.add("search-hidden");
    } else if (delta < -1) {
      shell.classList.remove("search-hidden");
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
})();
