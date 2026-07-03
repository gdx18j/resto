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
  var modalManager = window.CaesarModal || null;
  var orderModal = null;
  var orderModalBody = null;
  var orderBackdrop = null;
  var lastOrderTrigger = null;
  var translations = {
    ru: {
      orderDetails: 'Подробности заказа',
      closeOrderDetails: 'Закрыть подробности заказа',
    },
    en: {
      orderDetails: 'Order details',
      closeOrderDetails: 'Close order details',
    },
    tr: {
      orderDetails: 'Sipariş detayları',
      closeOrderDetails: 'Sipariş detaylarını kapat',
    },
  };

  function currentLanguage() {
    var language = document.documentElement.dataset.language || document.documentElement.lang || 'ru';
    return translations[language] ? language : 'ru';
  }

  function t(key) {
    var language = currentLanguage();
    return translations[language][key] || translations.ru[key] || '';
  }

  function syncModalLabels() {
    if (!orderModal) return;

    orderModal.setAttribute('aria-label', t('orderDetails'));
    Array.from(orderModal.querySelectorAll('[data-order-modal-close]')).forEach(function (button) {
      button.setAttribute('aria-label', t('closeOrderDetails'));
    });
  }

  function currentLocale() {
    return { ru: 'ru-RU', en: 'en-US', tr: 'tr-TR' }[currentLanguage()] || 'ru-RU';
  }

  function normalize(value) {
    return String(value || '').toLocaleLowerCase(currentLocale()).trim();
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

  function buildOrderModal() {
    if (!document.querySelector('[data-order-details-template]')) return;

    var shell = document.querySelector('.app-shell') || document.body;

    orderBackdrop = document.createElement('div');
    orderBackdrop.className = 'order-modal-backdrop';
    orderBackdrop.setAttribute('data-order-modal-close', '');
    orderBackdrop.setAttribute('aria-hidden', 'true');
    shell.appendChild(orderBackdrop);

    orderModal = document.createElement('div');
    orderModal.className = 'order-modal';
    orderModal.setAttribute('role', 'dialog');
    orderModal.setAttribute('aria-modal', 'true');
    orderModal.setAttribute('aria-label', t('orderDetails'));
    orderModal.setAttribute('aria-hidden', 'true');
    orderModal.innerHTML = [
      '<button class="close-button order-modal__close" data-order-modal-close aria-label="' + t('closeOrderDetails') + '">',
      '  <svg viewBox="0 0 24 24"><path d="m5 5 14 14M19 5 5 19"/></svg>',
      '</button>',
      '<div class="order-modal__body" data-order-modal-body></div>',
    ].join('\n');
    shell.appendChild(orderModal);
    orderModalBody = orderModal.querySelector('[data-order-modal-body]');
  }

  function openOrderModal(orderId, opener) {
    if (!orderModal || !orderModalBody || !orderId) return;

    var template = document.querySelector('[data-order-details-template="' + orderId + '"]');
    if (!template) return;

    lastOrderTrigger = opener || document.activeElement;
    orderModalBody.innerHTML = '';
    orderModalBody.appendChild(template.content.cloneNode(true));
    orderModal.classList.add('order-modal--open');
    orderModal.setAttribute('aria-hidden', 'false');
    orderBackdrop.classList.add('order-modal--open');

    if (modalManager) {
      modalManager.open(orderModal, {
        root: orderModal,
        container: orderModal.parentElement || document.body,
        opener: lastOrderTrigger,
        initialFocus: orderModal.querySelector('[data-order-modal-close]') || orderModal,
        exemptElements: [orderBackdrop],
        requestClose: closeOrderModal,
      });
    } else {
      document.body.style.overflow = 'hidden';
      var closeButton = orderModal.querySelector('[data-order-modal-close]');
      if (closeButton) closeButton.focus();
    }
  }

  function closeOrderModal(options) {
    if (!orderModal) return;

    var wasManaged = modalManager && modalManager.close(orderModal, options);
    orderModal.classList.remove('order-modal--open');
    orderModal.setAttribute('aria-hidden', 'true');
    orderBackdrop.classList.remove('order-modal--open');

    if (!wasManaged) {
      document.body.style.overflow = '';
      if (!options || options.restoreFocus !== false) {
        if (lastOrderTrigger && typeof lastOrderTrigger.focus === 'function') {
          lastOrderTrigger.focus();
        }
      }
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

  root.addEventListener('click', function (event) {
    if (event.target.closest('[data-repeat-order]')) return;

    if (event.target.closest('[data-order-modal-close]')) {
      closeOrderModal();
      return;
    }

    var trigger = event.target.closest('[data-order-trigger]');
    if (!trigger) return;

    openOrderModal(trigger.getAttribute('data-order-id'), trigger);
  });

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-order-modal-close]')) {
      closeOrderModal();
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && orderModal && orderModal.classList.contains('order-modal--open')) {
      closeOrderModal();
    }
  });

  window.addEventListener('cc:languagechange', syncModalLabels);

  buildOrderModal();
  syncModalLabels();
  applyFilters();
})();
