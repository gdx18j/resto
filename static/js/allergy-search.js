(function () {
  var input = document.querySelector(".allergen-search-input");
  var chips = Array.prototype.slice.call(
    document.querySelectorAll(".allergen-chip")
  );
  var emptyState = document.querySelector(".allergen-empty");

  if (!input || chips.length === 0) {
    return;
  }

  function normalize(value) {
    return (value || "")
      .toString()
      .toLowerCase()
      .replace(/ё/g, "е")
      .trim();
  }

  input.addEventListener("input", function () {
    var query = normalize(input.value);
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
  });
})();
