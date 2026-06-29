(function () {
  var inputs = Array.prototype.slice.call(
    document.querySelectorAll(".allergen-search-input")
  );
  var chips = Array.prototype.slice.call(
    document.querySelectorAll(".allergen-chip")
  );
  var emptyState = document.querySelector(".allergen-empty");

  if (!inputs.length || chips.length === 0) {
    return;
  }

  function normalize(value) {
    return (value || "")
      .toString()
      .toLowerCase()
      .replace(/ё/g, "е")
      .trim();
  }

  function syncInputs(value, sourceInput) {
    inputs.forEach(function (input) {
      if (input !== sourceInput) {
        input.value = value;
      }
    });
  }

  function filterAllergens(value) {
    var query = normalize(value);
    var visibleCount = 0;

    chips.forEach(function (chip) {
      var name = normalize(chip.dataset.allergenName);
      var isVisible = query.length === 0 || name.indexOf(query) !== -1;

      chip.hidden = !isVisible;

      if (isVisible) {
        visibleCount += 1;
      }
    });

    if (emptyState) {
      emptyState.hidden = visibleCount > 0 || query.length === 0;
    }
  }

  inputs.forEach(function (input) {
    input.addEventListener("input", function () {
      syncInputs(input.value, input);
      filterAllergens(input.value);
    });
  });
})();
