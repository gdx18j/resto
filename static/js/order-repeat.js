(function () {
  'use strict';

  var TABLE_CONTEXT_STORAGE_VERSION = 1;
  var PENDING_REPEAT_VERSION = 1;
  var TABLE_CONTEXT_MAX_AGE_MS = 12 * 60 * 60 * 1000;
  var PENDING_REPEAT_MAX_AGE_MS = 5 * 60 * 1000;
  var RECENT_ORDER_STORAGE_KEY = 'cc_recent_order:v2';

  var messages = {
    ru: {
      unavailable: 'Сейчас этот заказ нельзя повторить.',
      scanQr: 'Чтобы повторить заказ, сначала откройте меню по QR-коду текущего стола.',
      invalidContext: 'Сохранённый контекст стола устарел. Отсканируйте QR-код ещё раз.',
      preparing: 'Открываем меню текущего стола…',
      storageFailed: 'Не удалось подготовить повтор заказа. Обновите страницу и попробуйте ещё раз.',
      confirmTable: 'Повторить заказ для стола {table}?',
      confirmUnknownTable: 'Повторить заказ для текущего открытого стола?',
    },
    en: {
      unavailable: 'This order cannot be repeated right now.',
      scanQr: 'To repeat the order, first open the menu using the QR code of your current table.',
      invalidContext: 'The saved table context has expired. Scan the QR code again.',
      preparing: 'Opening the menu for your current table…',
      storageFailed: 'Could not prepare the repeated order. Refresh the page and try again.',
      confirmTable: 'Repeat the order for table {table}?',
      confirmUnknownTable: 'Repeat the order for the currently opened table?',
    },
    tr: {
      unavailable: 'Bu sipariş şu anda tekrarlanamaz.',
      scanQr: 'Siparişi tekrarlamak için önce mevcut masanın QR koduyla menüyü açın.',
      invalidContext: 'Kaydedilen masa bağlamının süresi doldu. QR kodunu yeniden tarayın.',
      preparing: 'Mevcut masanın menüsü açılıyor…',
      storageFailed: 'Sipariş tekrarı hazırlanamadı. Sayfayı yenileyip tekrar deneyin.',
      confirmTable: '{table} numaralı masa için sipariş tekrarlansın mı?',
      confirmUnknownTable: 'Sipariş mevcut açık masa için tekrarlansın mı?',
    },
  };

  function currentLanguage() {
    var language = document.documentElement.dataset.language || document.documentElement.lang || 'ru';
    return messages[language] ? language : 'ru';
  }

  function t(key, values) {
    var text = messages[currentLanguage()][key] || messages.ru[key] || '';

    Object.keys(values || {}).forEach(function (name) {
      text = text.replace('{' + name + '}', String(values[name]));
    });

    return text;
  }

  function statusElement() {
    return document.querySelector('[data-repeat-order-status]');
  }

  function showStatus(message, isError) {
    var element = statusElement();

    if (!element) {
      window.alert(message);
      return;
    }

    element.textContent = message;
    element.hidden = false;
    element.classList.toggle('is-error', Boolean(isError));
    element.classList.toggle('is-info', !isError);
    element.scrollIntoView({
      block: 'nearest',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    });
  }

  function parseJson(value, fallback) {
    try {
      return JSON.parse(value || '');
    } catch (_) {
      return fallback;
    }
  }

  function tableContextStorageKey(restaurantSlug) {
    return 'cc:table-context:v' + TABLE_CONTEXT_STORAGE_VERSION + ':' + restaurantSlug;
  }

  function pendingRepeatStorageKey(restaurantSlug) {
    return 'cc:pending-repeat:v' + PENDING_REPEAT_VERSION + ':' + restaurantSlug;
  }

  function readStoredTableContext(restaurantSlug) {
    var storageKey = tableContextStorageKey(restaurantSlug);
    var stored;

    try {
      stored = parseJson(window.sessionStorage.getItem(storageKey), null);
    } catch (_) {
      return null;
    }

    if (
      !stored
      || stored.version !== TABLE_CONTEXT_STORAGE_VERSION
      || stored.restaurantSlug !== restaurantSlug
      || typeof stored.context !== 'string'
      || !stored.context
      || typeof stored.activationUrl !== 'string'
      || !stored.activationUrl
      || !Number.isFinite(stored.savedAt)
      || Date.now() - stored.savedAt > TABLE_CONTEXT_MAX_AGE_MS
    ) {
      try { window.sessionStorage.removeItem(storageKey); } catch (_) {}
      return null;
    }

    return stored;
  }

  function clearCreatedOrderStorage() {
    var receipt = document.querySelector('[data-confirmed-order-id]');

    if (!receipt) return;

    var orderId = String(receipt.getAttribute('data-confirmed-order-id') || '');
    var recentOrder;
    var legacyRecentOrder = false;

    try {
      recentOrder = parseJson(window.sessionStorage.getItem(RECENT_ORDER_STORAGE_KEY), null);

      if (!recentOrder) {
        recentOrder = parseJson(window.sessionStorage.getItem('cc_recent_order'), null);
        legacyRecentOrder = Boolean(recentOrder);
      }
    } catch (_) {
      recentOrder = null;
    }

    if (!recentOrder || String(recentOrder.id || '') !== orderId) {
      return;
    }

    try {
      if (legacyRecentOrder) {
        window.sessionStorage.removeItem('cc_cart');
        window.sessionStorage.removeItem('cc_cart_recovery_snapshot');
        window.sessionStorage.removeItem('cc_order_idempotency');
        window.sessionStorage.removeItem('cc_recent_order');
        return;
      }

      [
        recentOrder.cartStorageKey,
        recentOrder.idempotencyStorageKey,
        recentOrder.recoveryStorageKey,
      ].forEach(function (storageKey) {
        if (storageKey) window.sessionStorage.removeItem(storageKey);
      });
      window.sessionStorage.removeItem(RECENT_ORDER_STORAGE_KEY);
    } catch (_) {}
  }

  function repeatItems(button) {
    var repeatResult = parseJson(button.getAttribute('data-repeat-result'), null);

    if (repeatResult) {
      return {
        items: [].concat(repeatResult.available || [], repeatResult.changed || []),
        result: repeatResult,
      };
    }

    return {
      items: parseJson(button.getAttribute('data-items'), []),
      result: null,
    };
  }

  function prepareRepeat(button) {
    var restaurantSlug = String(button.dataset.repeatRestaurantSlug || '').trim();
    var orderMode = String(button.dataset.repeatOrderMode || '').trim();
    var originalTableNumber = String(button.dataset.repeatTableNumber || '').trim();
    var guestsCount = Math.max(1, Math.min(20, parseInt(button.dataset.repeatGuestsCount, 10) || 1));
    var repeat = repeatItems(button);

    if (orderMode !== 'table' || !restaurantSlug || !repeat.items.length) {
      showStatus(t('unavailable'), true);
      return;
    }

    var storedContext = readStoredTableContext(restaurantSlug);

    if (!storedContext) {
      showStatus(t('scanQr'), true);
      return;
    }

    var currentTableNumber = String(storedContext.tableNumber || '').trim();
    var confirmationMessage = currentTableNumber
      ? t('confirmTable', { table: currentTableNumber })
      : t('confirmUnknownTable');

    if (!window.confirm(confirmationMessage)) {
      return;
    }

    var pendingPayload = {
      version: PENDING_REPEAT_VERSION,
      restaurantSlug: restaurantSlug,
      expectedContext: storedContext.context,
      originalTableNumber: originalTableNumber,
      targetTableNumber: currentTableNumber,
      guestsCount: guestsCount,
      items: repeat.items,
      repeatResult: repeat.result,
      savedAt: Date.now(),
    };

    try {
      window.sessionStorage.setItem(
        pendingRepeatStorageKey(restaurantSlug),
        JSON.stringify(pendingPayload)
      );
    } catch (_) {
      showStatus(t('storageFailed'), true);
      return;
    }

    showStatus(t('preparing'), false);
    window.location.assign(storedContext.activationUrl);
  }

  clearCreatedOrderStorage();

  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-repeat-order]');

    if (!button) return;

    event.preventDefault();
    event.stopPropagation();
    prepareRepeat(button);
  });

  window.addEventListener('cc:languagechange', function () {
    var element = statusElement();
    if (element) element.hidden = true;
  });

  // Export only for isolated browser-state tests.
  window.RestoOrderRepeat = {
    readStoredTableContext: readStoredTableContext,
    pendingRepeatStorageKey: pendingRepeatStorageKey,
    pendingRepeatMaxAgeMs: PENDING_REPEAT_MAX_AGE_MS,
  };
})();
