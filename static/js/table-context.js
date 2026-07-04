(function () {
  'use strict';

  var STORAGE_VERSION = 1;
  var DEFAULT_MAX_LOCAL_AGE_MS = 12 * 60 * 60 * 1000;
  var LAST_CONTEXT_KEY = 'cc:table-context:last:v' + STORAGE_VERSION;
  var shell = document.querySelector('.app-shell');

  if (!shell) {
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
  var storageKey = tableContextStorageKey(restaurantSlug);

  function tableContextStorageKey(slug) {
    return slug
      ? 'cc:table-context:v' + STORAGE_VERSION + ':' + slug
      : '';
  }

  function safeSessionStorage() {
    try {
      var storage = window.sessionStorage;
      var probeKey = '__cc_table_context_probe__';
      storage.setItem(probeKey, '1');
      storage.removeItem(probeKey);
      return storage;
    } catch (_) {
      return null;
    }
  }

  function safeLocalStorage() {
    try {
      var storage = window.localStorage;
      var probeKey = '__cc_table_context_probe__';
      storage.setItem(probeKey, '1');
      storage.removeItem(probeKey);
      return storage;
    } catch (_) {
      return null;
    }
  }

  function storageBackends() {
    var storages = [];
    var session = safeSessionStorage();
    var local = safeLocalStorage();

    if (session) storages.push(session);
    if (local) storages.push(local);

    return storages;
  }

  function parseJson(raw) {
    try {
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function removeStoredContext(key) {
    var targetKey = key || storageKey || readLastContextKey();

    storageBackends().forEach(function (storage) {
      try {
        if (targetKey) storage.removeItem(targetKey);
        storage.removeItem(LAST_CONTEXT_KEY);
      } catch (_) {}
    });
  }

  function writeLastContextKey(key, slug) {
    if (!key || !slug) {
      return;
    }

    var payload = JSON.stringify({
      version: STORAGE_VERSION,
      storageKey: key,
      restaurantSlug: slug,
      savedAt: Date.now(),
    });

    storageBackends().forEach(function (storage) {
      try {
        storage.setItem(LAST_CONTEXT_KEY, payload);
      } catch (_) {}
    });
  }

  function readLastContextKey() {
    var result = '';

    storageBackends().some(function (storage) {
      var parsed = parseJson(storage.getItem(LAST_CONTEXT_KEY));

      if (
        parsed
        && parsed.version === STORAGE_VERSION
        && typeof parsed.storageKey === 'string'
        && parsed.storageKey
        && Number.isFinite(parsed.savedAt)
        && Date.now() - parsed.savedAt <= maxLocalAgeMs
      ) {
        result = parsed.storageKey;
        return true;
      }

      return false;
    });

    return result;
  }

  function isValidStoredContext(parsed, expectedRestaurantSlug) {
    return Boolean(
      parsed
      && parsed.version === STORAGE_VERSION
      && (!expectedRestaurantSlug || parsed.restaurantSlug === expectedRestaurantSlug)
      && typeof parsed.restaurantSlug === 'string'
      && parsed.restaurantSlug
      && typeof parsed.context === 'string'
      && parsed.context
      && typeof parsed.activationUrl === 'string'
      && parsed.activationUrl
      && Number.isFinite(parsed.savedAt)
      && Date.now() - parsed.savedAt <= maxLocalAgeMs
    );
  }

  function readStoredContext() {
    var key = storageKey || readLastContextKey();
    var expectedRestaurantSlug = restaurantSlug || '';
    var storages = storageBackends();
    var parsed = null;

    if (!key) {
      return null;
    }

    storages.some(function (storage) {
      try {
        parsed = parseJson(storage.getItem(key));
      } catch (_) {
        parsed = null;
      }

      return isValidStoredContext(parsed, expectedRestaurantSlug);
    });

    if (!isValidStoredContext(parsed, expectedRestaurantSlug)) {
      removeStoredContext(key);
      return null;
    }

    return parsed;
  }

  function samePathAndQuery(leftUrl, rightUrl) {
    var left;
    var right;

    try {
      left = new URL(leftUrl, window.location.origin);
      right = new URL(rightUrl, window.location.origin);
    } catch (_) {
      return false;
    }

    return left.origin === window.location.origin
      && right.origin === window.location.origin
      && left.pathname === right.pathname
      && left.search === right.search;
  }

  function rewriteMenuLinks(storedContext) {
    var target = storedContext && storedContext.activationUrl;
    var catalog = cleanUrl || storedContext.catalogUrl || '/';

    if (!target) {
      return;
    }

    Array.prototype.forEach.call(document.querySelectorAll('a[href]'), function (link) {
      var href = link.getAttribute('href') || '';

      if (
        link.dataset.tableContextMenuLink === '1'
        || samePathAndQuery(href, catalog)
        || samePathAndQuery(href, '/')
      ) {
        link.setAttribute('href', target);
        link.dataset.tableContextMenuLink = '1';
      }
    });
  }

  function applyStoredContext(storedContext) {
    if (!storedContext) {
      return;
    }

    shell.dataset.cartRestaurantSlug = shell.dataset.cartRestaurantSlug || storedContext.restaurantSlug || '';
    shell.dataset.cartTableContext = shell.dataset.cartTableContext || storedContext.context || '';
    shell.dataset.cartTableNumber = shell.dataset.cartTableNumber || storedContext.tableNumber || '';
    shell.dataset.tableContextActivationUrl = shell.dataset.tableContextActivationUrl || storedContext.activationUrl || '';
    shell.dataset.tableContextCleanUrl = shell.dataset.tableContextCleanUrl || storedContext.catalogUrl || cleanUrl || '';
    rewriteMenuLinks(storedContext);
  }

  if (shouldClear) {
    removeStoredContext();
    return;
  }

  if (tableContext && activationUrl) {
    storageKey = storageKey || tableContextStorageKey(restaurantSlug);

    if (storageKey) {
      var payload = JSON.stringify({
        version: STORAGE_VERSION,
        restaurantSlug: restaurantSlug,
        context: tableContext,
        tableNumber: tableNumber,
        activationUrl: activationUrl,
        catalogUrl: cleanUrl,
        savedAt: Date.now(),
      });

      storageBackends().forEach(function (storage) {
        try {
          storage.setItem(storageKey, payload);
        } catch (_) {}
      });
      writeLastContextKey(storageKey, restaurantSlug);
    }

    applyStoredContext({
      version: STORAGE_VERSION,
      restaurantSlug: restaurantSlug,
      context: tableContext,
      tableNumber: tableNumber,
      activationUrl: activationUrl,
      catalogUrl: cleanUrl,
      savedAt: Date.now(),
    });

    if (orderingEnabled && window.history && typeof window.history.replaceState === 'function') {
      try {
        window.history.replaceState({
          restoTableContextStorageKey: storageKey,
        }, document.title, window.location.href);
      } catch (_) {}
    }
    return;
  }

  if (!orderingEnabled) {
    var historyState = window.history ? window.history.state : null;
    var shouldResume = Boolean(
      historyState
      && historyState.restoTableContextStorageKey
    );
    var storedContext = readStoredContext();

    if (shouldResume && storedContext) {
      applyStoredContext(storedContext);
      window.location.replace(storedContext.activationUrl);
    }
  }
})();
