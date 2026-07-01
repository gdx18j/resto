(function () {
  'use strict';

  var root = document.querySelector('.order-history-page');
  if (!root) return;

  var searchInput = root.querySelector('[data-order-history-search]');
  var filterButtons = Array.from(root.querySelectorAll('[data-order-filter]'));
  var cards = Array.from(root.querySelectorAll('[data-order-card]'));
  var days = Array.from(root.querySelectorAll('[data-order-day]'));
  var empty = root.querySelector('[data-order-history-empty]');
  var count = root.querySelector('[data-order-visible-count]');
  var activeFilter = 'all';

  function normalize(value) {
    return String(value || '').toLocaleLowerCase('ru-RU').trim();
  }

  function applyFilters() {
    var query = normalize(searchInput ? searchInput.value : '');
    var visibleCount = 0;

    cards.forEach(function (card) {
      var matchesState = activeFilter === 'all' || card.dataset.orderState === activeFilter;
      var matchesQuery = !query || normalize(card.dataset.orderSearch).indexOf(query) !== -1;
      var visible = matchesState && matchesQuery;

      card.hidden = !visible;
      card.classList.toggle('is-hidden', !visible);
      if (visible) visibleCount += 1;
    });

    days.forEach(function (day) {
      var hasVisibleCards = !!day.querySelector('[data-order-card]:not(.is-hidden)');
      day.hidden = !hasVisibleCards;
      day.classList.toggle('is-hidden', !hasVisibleCards);
    });

    if (empty) {
      empty.hidden = visibleCount !== 0;
      empty.classList.toggle('is-hidden', visibleCount !== 0);
    }

    if (count) {
      count.textContent = query || activeFilter !== 'all'
        ? String(visibleCount)
        : String(count.dataset.orderTotalCount || visibleCount);
    }
  }

  filterButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      activeFilter = button.dataset.orderFilter || 'all';
      filterButtons.forEach(function (item) {
        item.classList.toggle('is-active', item === button);
      });
      applyFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', applyFilters);
  }

  applyFilters();
})();
