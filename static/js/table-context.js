(function () {
  'use strict';

  var STORAGE_VERSION = 1;
  var DEFAULT_MAX_LOCAL_AGE_MS = 12 * 60 * 60 * 1000;
  var shell = document.querySelector('.app-shell');

  if (!shell || !window.sessionStorage) {
    return;
  }

  var restaurantSlug = shell.dataset.cartRestaurantSlug || '';
  var tableContext = shell.dataset.cartTableContext || '';
  var tableNumber = shell.dataset.cartTableNumber || '';
  var activationUrl = shell.dataset.tableContextActivationUrl || '';
  var cleanUrl = shell.dataset.tableContextCleanUrl || window.location.pathname;
  var shouldClear = shell.dataset.tableContextClear === '1';
  var orderingEnabled = shell.dataset.orderingEnabled === '1';
  var contextTtlSeconds = parseInt(shell.dataset.tableContextTtlSeconds, 10);
  var maxLocalAgeMs = Number.isFinite(contextTtlSeconds) && contextTtlSeconds >= 60
    ? contextTtlSeconds * 1000
    : DEFAULT_MAX_LOCAL_AGE_MS;
  var storageKey = restaurantSlug
    ? 'cc:table-context:v' + STORAGE_VERSION + ':' + restaurantSlug
    : '';

  if (!storageKey) {
    return;
  }

  function removeStoredContext() {
    try {
      window.sessionStorage.removeItem(storageKey);
    } catch (_) {}
  }

  function replaceVisibleUrl(url, state) {
    if (!url || !window.history || typeof window.history.replaceState !== 'function') {
      return;
    }

    try {
      window.history.replaceState(state || {}, document.title, url);
    } catch (_) {}
  }

  function readStoredContext() {
    var raw;
    var parsed;

    try {
      raw = window.sessionStorage.getItem(storageKey);
      parsed = raw ? JSON.parse(raw) : null;
    } catch (_) {
      parsed = null;
    }

    if (
      !parsed
      || parsed.version !== STORAGE_VERSION
      || parsed.restaurantSlug !== restaurantSlug
      || typeof parsed.context !== 'string'
      || !parsed.context
      || typeof parsed.activationUrl !== 'string'
      || !parsed.activationUrl
      || !Number.isFinite(parsed.savedAt)
      || Date.now() - parsed.savedAt > maxLocalAgeMs
    ) {
      removeStoredContext();
      return null;
    }

    return parsed;
  }

  if (shouldClear) {
    removeStoredContext();
    replaceVisibleUrl(cleanUrl, {});
    return;
  }

  if (orderingEnabled && tableContext && activationUrl) {
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify({
        version: STORAGE_VERSION,
        restaurantSlug: restaurantSlug,
        context: tableContext,
        tableNumber: tableNumber,
        activationUrl: activationUrl,
        savedAt: Date.now(),
      }));
    } catch (_) {}

    // После серверной проверки скрываем ограниченный контекст из адресной строки.
    // Он остаётся только в sessionStorage текущей вкладки и передаётся API явно.
    replaceVisibleUrl(cleanUrl, {
      restoTableContextStorageKey: storageKey,
    });
    return;
  }

  if (!orderingEnabled) {
    var historyState = window.history ? window.history.state : null;
    var shouldResume = Boolean(
      historyState
      && historyState.restoTableContextStorageKey === storageKey
    );

    if (!shouldResume) {
      return;
    }

    var storedContext = readStoredContext();

    if (storedContext) {
      window.location.replace(storedContext.activationUrl);
    }
  }
})();
