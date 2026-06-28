(function () {
  var shell = document.querySelector(".app-shell");
  var search = document.querySelector(".search-section");
  var categoryStrip = document.querySelector(".category-strip");
  var searchInputs = Array.prototype.slice.call(
    document.querySelectorAll(".menu-search-input")
  );
  var dishCards = Array.prototype.slice.call(
    document.querySelectorAll(".dish-card")
  );
  var menuSections = Array.prototype.slice.call(
    document.querySelectorAll(".menu-section")
  );
  var emptyState = document.querySelector(".menu-search-empty");
  var searchStatus = document.querySelector(".menu-search-count");
  var clearButton = document.querySelector(".search-clear-button");
  var categoryLinks = Array.prototype.slice.call(
    document.querySelectorAll(".category-chip")
  );

  if (!shell || !search) {
    return;
  }

  if (categoryStrip) {
    categoryStrip.scrollLeft = 0;
  }

  var lastScrollY = window.scrollY;
  var ticking = false;
  var threshold = 8;
  var activeQuery = "";
  var totalDishes = dishCards.length;

  function updateSearchVisibility() {
    var currentScrollY = window.scrollY;
    var delta = currentScrollY - lastScrollY;
    var activeElement = document.activeElement;
    var isSearchActive =
      activeElement && activeElement.classList.contains("menu-search-input");

    if (activeQuery || isSearchActive || currentScrollY < 80) {
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

  function normalize(value) {
    return (value || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/ё/g, "е")
      .replace(/ı/g, "i")
      .trim();
  }

  function tokenize(value) {
    return normalize(value)
      .split(/\s+/)
      .filter(Boolean);
  }

  function syncInputs(value, sourceInput) {
    searchInputs.forEach(function (input) {
      if (input !== sourceInput) {
        input.value = value;
      }
    });
  }

  function setCategoryVisibility(section, isVisible) {
    if (!section.id) {
      return;
    }

    categoryLinks.forEach(function (link) {
      if (link.getAttribute("href") === "#" + section.id) {
        link.hidden = !isVisible;
      }
    });
  }

  function getMatchType(card, tokens) {
    if (tokens.length === 0) {
      return "all";
    }

    var name = normalize(card.dataset.searchName);
    var ingredients = normalize(card.dataset.searchIngredients);
    var combined = normalize(card.dataset.searchText);
    var matchesName = tokens.every(function (token) {
      return name.indexOf(token) !== -1;
    });
    var matchesIngredients = tokens.every(function (token) {
      return ingredients.indexOf(token) !== -1;
    });
    var matchesCombined = tokens.every(function (token) {
      return combined.indexOf(token) !== -1;
    });

    if (matchesName) {
      return "name";
    }

    if (matchesIngredients) {
      return "ingredients";
    }

    if (matchesCombined) {
      return "mixed";
    }

    return "";
  }

  function dishWord(count) {
    var absCount = Math.abs(count);
    var mod100 = absCount % 100;
    var mod10 = absCount % 10;

    if (mod100 >= 11 && mod100 <= 14) {
      return "блюд";
    }

    if (mod10 === 1) {
      return "блюдо";
    }

    if (mod10 >= 2 && mod10 <= 4) {
      return "блюда";
    }

    return "блюд";
  }

  function updateSearchStatus(query, visibleTotal) {
    if (searchStatus) {
      if (!query) {
        searchStatus.textContent = "";
      } else {
        searchStatus.textContent = "Найдено " + visibleTotal + " " + dishWord(visibleTotal);
      }
    }

    if (clearButton) {
      clearButton.hidden = !query;
    }
  }

  function filterMenu(query) {
    var normalizedQuery = normalize(query);
    var tokens = tokenize(query);
    var visibleTotal = 0;

    activeQuery = normalizedQuery;

    dishCards.forEach(function (card) {
      var matchType = getMatchType(card, tokens);
      var isVisible = normalizedQuery.length === 0 || Boolean(matchType);

      card.hidden = !isVisible;
      card.dataset.matchType = matchType || "";

      if (isVisible) {
        visibleTotal += 1;
      }
    });

    menuSections.forEach(function (section) {
      var visibleCards = Array.prototype.slice
        .call(section.querySelectorAll(".dish-card"))
        .filter(function (card) {
          return !card.hidden;
        });
      var isVisible = visibleCards.length > 0;
      var count = section.querySelector(".section-count");

      section.hidden = !isVisible;
      setCategoryVisibility(section, isVisible);

      if (count) {
        count.textContent = visibleCards.length;
      }
    });

    if (emptyState) {
      emptyState.hidden = visibleTotal > 0 || normalizedQuery.length === 0;
    }

    updateSearchStatus(normalizedQuery, visibleTotal);
  }

  function setSearchQuery(value) {
    searchInputs.forEach(function (input) {
      input.value = value;
    });

    filterMenu(value);
    shell.classList.remove("search-hidden");
  }

  searchInputs.forEach(function (input) {
    input.addEventListener("input", function () {
      syncInputs(input.value, input);
      filterMenu(input.value);
    });

    input.addEventListener("focus", function () {
      shell.classList.remove("search-hidden");
    });
  });

  if (clearButton) {
    clearButton.addEventListener("click", function () {
      setSearchQuery("");

      var visibleInput = searchInputs.find(function (input) {
        return window.getComputedStyle(input).display !== "none";
      });

      if (visibleInput) {
        visibleInput.focus();
      }
    });
  }

  updateSearchStatus("", totalDishes);
})();
