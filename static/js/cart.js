/**
 * Caesar & Company — Cart
 * Mobile: полноэкранная шторка снизу
 * Desktop: боковая панель справа
 */
(function () {
  'use strict';

  /* ─── State ─────────────────────────────────────────────────── */
  var cart = {
    items: {},      // { dishId: { name, price, qty, modifiers } }
    persons: 1,
    payment: null,  // 'card' | 'cash'
    comment: '',
  };

  /* ─── DOM refs (resolved after DOMContentLoaded) ─────────────── */
  var els = {};
  var cartApi = {
    quoteUrl: '',
    createUrl: '',
    quoteTimer: null,
    quotePending: false,
    submitting: false,
    noteTimer: null,
  };

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  var translations = {
    ru: {
      itemOne: 'товар',
      itemFew: 'товара',
      itemMany: 'товаров',
      empty: 'Корзина пуста — добавьте блюда из меню.',
      clear: 'Очистить корзину',
      added: 'Добавлено в корзину',
      open: 'Открыть',
      addToCart: 'Добавить в корзину: ',
      increaseItem: 'Добавить еще: ',
      decreaseItem: 'Убрать одно: ',
      commentPlaceholder: 'Аллергии, пожелания к сервировке, особые просьбы…',
      selectPayment: 'Выберите способ оплаты.',
      orderCreated: 'Заказ создан',
      orderFailed: 'Не удалось оформить заказ. Попробуйте еще раз.',
      cartSyncFailed: 'Не удалось обновить корзину. Проверьте позиции.',
    },
    en: {
      itemOne: 'item',
      itemFew: 'items',
      itemMany: 'items',
      empty: 'Your cart is empty — add dishes from the menu.',
      clear: 'Clear cart',
      added: 'Added to cart',
      open: 'Open',
      addToCart: 'Add to cart: ',
      increaseItem: 'Add one more: ',
      decreaseItem: 'Remove one: ',
      commentPlaceholder: 'Allergies, serving wishes, special requests…',
      selectPayment: 'Choose a payment method.',
      orderCreated: 'Order created',
      orderFailed: 'Could not place the order. Please try again.',
      cartSyncFailed: 'Could not update the cart. Check the items.',
    },
    tr: {
      itemOne: 'ürün',
      itemFew: 'ürün',
      itemMany: 'ürün',
      empty: 'Sepet boş — menüden yemek ekleyin.',
      clear: 'Sepeti temizle',
      added: 'Sepete eklendi',
      open: 'Aç',
      addToCart: 'Sepete ekle: ',
      increaseItem: 'Bir tane daha ekle: ',
      decreaseItem: 'Bir tane çıkar: ',
      commentPlaceholder: 'Alerjiler, servis istekleri, özel notlar…',
      selectPayment: 'Ödeme yöntemini seçin.',
      orderCreated: 'Sipariş oluşturuldu',
      orderFailed: 'Sipariş verilemedi. Lütfen tekrar deneyin.',
      cartSyncFailed: 'Sepet güncellenemedi. Ürünleri kontrol edin.',
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

  function localizedDatasetName(element) {
    var language = currentLanguage();
    var key = 'name' + language.charAt(0).toUpperCase() + language.slice(1);

    return element.dataset[key] || element.dataset.name || '';
  }

  function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');

    if (parts.length === 2) {
      return parts.pop().split(';').shift();
    }

    return '';
  }

  function withLanguage(url) {
    if (!url) return '';
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'language=' + encodeURIComponent(currentLanguage());
  }

  function normalizeDishId(id, item) {
    var raw = item && item.dishId ? item.dishId : id;
    var match = String(raw || '').match(/(\d+)$/);
    return match ? match[1] : '';
  }

  /* ─── Cart math ───────────────────────────────────────────────── */
  function totalItems() {
    return Object.values(cart.items).reduce(function (s, i) { return s + i.qty; }, 0);
  }

  function totalPrice() {
    return Object.values(cart.items).reduce(function (s, i) {
      return s + (Number(i.price) || 0) * i.qty;
    }, 0);
  }

  function fmt(n) {
    var rounded = Math.round(n * 100) / 100;
    return rounded % 1 === 0
      ? rounded.toLocaleString('ru-RU') + ' ₽'
      : rounded.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₽';
  }

  /* ─── Persist to sessionStorage ──────────────────────────────── */
  function save() {
    try { sessionStorage.setItem('cc_cart', JSON.stringify(cart)); } catch (_) {}
  }

  function load() {
    try {
      var raw = sessionStorage.getItem('cc_cart');
      if (raw) {
        var stored = JSON.parse(raw);
        if (stored && stored.items) Object.assign(cart, stored);
      }
    } catch (_) {}

    Object.keys(cart.items).forEach(function (id) {
      var item = cart.items[id];

      if (!item || !item.qty) {
        delete cart.items[id];
        return;
      }

      item.qty = Math.max(1, Math.min(99, parseInt(item.qty, 10) || 1));
      item.price = Number(item.price) || 0;
      item.name = String(item.name || '');
      item.note = String(item.note || '');
      item.modifiers = Array.isArray(item.modifiers) ? item.modifiers : [];
      item.dishId = normalizeDishId(id, item);

      if (!item.dishId) {
        delete cart.items[id];
      }
    });

    save();
  }

  /* ─── UI update helpers ───────────────────────────────────────── */
  function renderBadges() {
    var n = totalItems();
    var p = totalPrice();

    qsa('[data-cart-count]').forEach(function (el) {
      el.textContent = n;
      el.hidden = n === 0;
    });
    qsa('[data-cart-total-mini]').forEach(function (el) {
      el.textContent = fmt(p);
    });
    // Шапка панели — счётчик и сумма
    qsa('[data-cart-header-count]').forEach(function (el) {
      el.textContent = n + ' ' + pluralItems(n);
    });
    qsa('[data-cart-header-total]').forEach(function (el) {
      el.textContent = fmt(p);
    });

    // Mobile bar
    var bar = els.mobileBar;
    var suppressMobileBar = !!qs('.auth-page');
    if (bar) {
      if (n > 0 && !suppressMobileBar) {
        bar.classList.add('cart-bar--visible');
        document.body.classList.add('cart-bar-visible');
      } else {
        bar.classList.remove('cart-bar--visible');
        document.body.classList.remove('cart-bar-visible');
      }
    }
    document.body.classList.toggle('cart-bar-suppressed', suppressMobileBar);

    // Desktop button
    var deskBtn = els.desktopBtn;
    if (deskBtn) {
      deskBtn.classList.toggle('cart-btn--has-items', n > 0);
    }
  }

  function pluralItems(n) {
    if (currentLanguage() !== 'ru') {
      return n === 1 ? t('itemOne') : t('itemMany');
    }

    var mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return t('itemOne');
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return t('itemFew');
    return t('itemMany');
  }

  function renderLines() {
    var container = els.lineList;
    if (!container) return;

    var items = Object.entries(cart.items);

    // Всегда удаляем кнопку очистки — пересоздадим ниже если нужно
    var existingClear = document.querySelector('.cart-clear-btn');
    if (existingClear) existingClear.remove();

    if (items.length === 0) {
      // Удаляем все строки товаров
      qsa('.cart-line', container).forEach(function (row) { row.remove(); });
      // Показываем сообщение если его ещё нет
      var emptyMessage = container.querySelector('.cart-empty-msg');
      if (!emptyMessage) {
        container.innerHTML = '<p class="cart-empty-msg">' + escHtml(t('empty')) + '</p>';
      } else {
        emptyMessage.textContent = t('empty');
      }
      if (els.extras) els.extras.hidden = true;
      return;
    }

    // Есть товары — убираем сообщение о пустой корзине
    var emptyMsg = container.querySelector('.cart-empty-msg');
    if (emptyMsg) emptyMsg.remove();

    if (els.extras) els.extras.hidden = false;

    // Удаляем строки которых больше нет
    qsa('.cart-line', container).forEach(function (row) {
      if (!cart.items[row.dataset.id]) row.remove();
    });

    // Обновляем существующие / добавляем новые
    items.forEach(function (entry) {
      var id = entry[0], item = entry[1];
      var existing = container.querySelector('.cart-line[data-id="' + id + '"]');
      if (existing) {
        existing.querySelector('.cart-line__price').textContent = fmt(item.price * item.qty);
        existing.querySelector('.cart-qty__num').textContent = item.qty;
      } else {
        var div = document.createElement('div');
        div.className = 'cart-line';
        div.dataset.id = id;
        div.innerHTML = [
          '  <span class="cart-line__name">' + escHtml(item.name) + '</span>',
          '  <span class="cart-line__price">' + fmt(item.price * item.qty) + '</span>',
          '  <div class="cart-qty">',
          '    <button class="cart-qty__btn" data-action="dec" data-id="' + id + '" aria-label="Remove one portion">−</button>',
          '    <span class="cart-qty__num">' + item.qty + '</span>',
          '    <button class="cart-qty__btn" data-action="inc" data-id="' + id + '" aria-label="Add one more portion">+</button>',
          '  </div>',
        ].join('\n');
        container.appendChild(div);
      }
    });

    // Кнопка очистки — только когда есть товары
    var clearBtn = document.createElement('button');
    clearBtn.className = 'cart-clear-btn';
    clearBtn.setAttribute('data-cart-clear', '');
    clearBtn.textContent = t('clear');
    container.parentNode.appendChild(clearBtn);
  }

  function renderSummary() {
    var price = totalPrice();
    var n = totalItems();
    qsa('[data-cart-grand-total]').forEach(function (el) {
      el.textContent = fmt(price);
    });
    qsa('[data-cart-checkout-total]').forEach(function (el) {
      el.textContent = fmt(price);
    });
    qsa('[data-cart-items-label]').forEach(function (el) {
      el.textContent = n + ' ' + pluralItems(n);
    });
  }

  function syncDishControls() {
    qsa('[data-dish-cart-control]').forEach(function (control) {
      var id = control.dataset.id;
      var item = id ? cart.items[id] : null;
      var qty = item ? item.qty : 0;
      var addBtn = control.querySelector('[data-add-btn]');
      var stepper = control.querySelector('[data-dish-qty-stepper]');
      var count = control.querySelector('[data-dish-qty-count]');
      var name = localizedDatasetName(control);
      var isActive = qty > 0;

      control.classList.toggle('dish-cart-control--active', isActive);

      if (addBtn) {
        addBtn.hidden = isActive;
        addBtn.setAttribute('aria-label', t('addToCart') + name);
      }

      if (stepper) {
        stepper.hidden = !isActive;
      }

      if (count) {
        count.textContent = qty;
      }

      qsa('[data-dish-qty-action]', control).forEach(function (btn) {
        var key = btn.dataset.dishQtyAction === 'inc' ? 'increaseItem' : 'decreaseItem';
        btn.setAttribute('aria-label', t(key) + name);
      });
    });
  }

  function renderAll() {
    renderBadges();
    renderLines();
    renderSummary();
    syncDishControls();
    syncPersonsUI();
    syncPaymentUI();
    syncCommentUI();
    syncLocalizedText();
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function readCartApi() {
    var shell = qs('.app-shell');

    cartApi.quoteUrl = shell ? shell.dataset.cartQuoteUrl || '' : '';
    cartApi.createUrl = shell ? shell.dataset.cartCreateUrl || '' : '';
  }

  function cartPayload() {
    return {
      items: Object.entries(cart.items).map(function (entry) {
        var id = entry[0];
        var item = entry[1];

        return {
          id: id,
          dish_id: item.dishId || normalizeDishId(id, item),
          quantity: item.qty,
          note: item.note || '',
          modifiers: Array.isArray(item.modifiers) ? item.modifiers : [],
        };
      }),
      guests_count: cart.persons,
      payment_method: cart.payment,
      comment: cart.comment,
    };
  }

  function createIdempotencyKey() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }

    return [
      'cc',
      Date.now().toString(36),
      Math.random().toString(36).slice(2),
      Math.random().toString(36).slice(2),
    ].join(':');
  }

  function idempotencyFingerprint(payload) {
    return JSON.stringify(payload);
  }

  function idempotencyKeyForPayload(payload) {
    var fingerprint = idempotencyFingerprint(payload);
    var storageKey = 'cc_order_idempotency';
    var stored = null;

    try {
      stored = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    } catch (_) {
      stored = null;
    }

    if (stored && stored.fingerprint === fingerprint && stored.key) {
      return stored.key;
    }

    stored = {
      key: createIdempotencyKey(),
      fingerprint: fingerprint,
    };

    try {
      sessionStorage.setItem(storageKey, JSON.stringify(stored));
    } catch (_) {}

    return stored.key;
  }

  function cartItemsKey() {
    return JSON.stringify(cartPayload().items);
  }

  function cartHeaders() {
    return {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken'),
      'X-Language': currentLanguage(),
      'X-Requested-With': 'XMLHttpRequest',
    };
  }

  function parseCartResponse(response) {
    return response.json()
      .catch(function () { return {}; })
      .then(function (data) {
        if (!response.ok || data.ok === false) {
          var error = new Error(data.error || t('orderFailed'));
          error.code = data.code || '';
          throw error;
        }

        return data;
      });
  }

  function applyQuote(data) {
    var serverItems = Array.isArray(data.items) ? data.items : [];
    var nextItems = {};

    serverItems.forEach(function (serverItem) {
      var id = serverItem.id || ('dish-' + serverItem.dish_id);
      var existing = cart.items[id] || cart.items[String(serverItem.dish_id)] || {};

      nextItems[id] = {
        name: serverItem.name || existing.name || '',
        price: Number(serverItem.unit_price) || 0,
        qty: Number(serverItem.quantity) || existing.qty || 1,
        dishId: serverItem.dish_id,
        note: existing.note || serverItem.note || '',
        modifiers: Array.isArray(existing.modifiers) ? existing.modifiers : [],
      };
    });

    cart.items = nextItems;
    save();
    renderAll();
  }

  function requestQuote() {
    var requestKey = cartItemsKey();

    if (!cartApi.quoteUrl || totalItems() === 0) {
      return Promise.resolve(null);
    }

    cartApi.quotePending = true;
    updateSubmit();

    return fetch(withLanguage(cartApi.quoteUrl), {
      method: 'POST',
      headers: cartHeaders(),
      credentials: 'same-origin',
      body: JSON.stringify(cartPayload()),
    })
      .then(parseCartResponse)
      .then(function (data) {
        if (cartItemsKey() === requestKey) {
          applyQuote(data);
        } else {
          scheduleQuote();
        }

        return data;
      })
      .catch(function (error) {
        showCartNote(error.message || t('cartSyncFailed'), 'error');
        throw error;
      })
      .finally(function () {
        cartApi.quotePending = false;
        renderAll();
      });
  }

  function scheduleQuote() {
    clearTimeout(cartApi.quoteTimer);

    if (totalItems() === 0) {
      cartApi.quotePending = false;
      return;
    }

    cartApi.quoteTimer = setTimeout(function () {
      requestQuote().catch(function () {});
    }, 120);
  }

  function showCartNote(message, kind) {
    if (!els.note) return;

    clearTimeout(cartApi.noteTimer);
    els.note.hidden = false;
    els.note.textContent = message;
    els.note.classList.toggle('cart-submit-note--success', kind === 'success');
    els.note.classList.toggle('cart-submit-note--error', kind === 'error');

    if (kind === 'success') {
      cartApi.noteTimer = setTimeout(function () {
        els.note.hidden = true;
      }, 4200);
    }
  }

  function clearCartNote() {
    if (!els.note) return;

    clearTimeout(cartApi.noteTimer);
    els.note.hidden = true;
    els.note.textContent = '';
    els.note.classList.remove('cart-submit-note--success', 'cart-submit-note--error');
  }

  /* ─── Persons / payment / comment sync ───────────────────────── */
  function syncPersonsUI() {
    qsa('[data-persons-count]').forEach(function (el) {
      el.textContent = cart.persons;
    });
  }

  function syncPaymentUI() {
    qsa('[data-pay]').forEach(function (btn) {
      btn.classList.toggle('is-selected', btn.dataset.pay === cart.payment);
    });
  }

  function syncCommentUI() {
    qsa('[data-cart-comment]').forEach(function (el) {
      if (el.value !== cart.comment) el.value = cart.comment;
    });
  }

  function syncLocalizedText() {
    qsa('[data-cart-comment]').forEach(function (el) {
      el.setAttribute('placeholder', t('commentPlaceholder'));
    });
    qsa('[data-cart-toast-hint]').forEach(function (el) {
      el.textContent = t('added');
    });
    qsa('[data-cart-toast-open]').forEach(function (el) {
      el.textContent = t('open');
    });
    qsa('[data-add-btn]').forEach(function (btn) {
      var name = localizedDatasetName(btn);
      btn.setAttribute('aria-label', t('addToCart') + name);
    });
    qsa('[data-dish-qty-action]').forEach(function (btn) {
      var control = btn.closest('[data-dish-cart-control]');
      var name = control ? localizedDatasetName(control) : '';
      var key = btn.dataset.dishQtyAction === 'inc' ? 'increaseItem' : 'decreaseItem';
      btn.setAttribute('aria-label', t(key) + name);
    });
  }

  /* ─── Public API (used by dish cards) ────────────────────────── */
  function addItem(id, name, price, sourceControl) {
    if (cart.items[id]) {
      cart.items[id].qty += 1;
    } else {
      cart.items[id] = {
        name: name,
        price: Number(price) || 0,
        qty: 1,
        dishId: normalizeDishId(id, null),
        note: '',
        modifiers: [],
      };
    }
    clearCartNote();
    save();
    renderAll();
    scheduleQuote();
    animateAdd(id, sourceControl);
    showToast(name);
  }

  window.CaesarCart = window.CaesarCart || {};
  window.CaesarCart.addItem = function (item) {
    if (!item || !item.id || !item.name) {
      return false;
    }

    addItem(String(item.id), String(item.name), Number(item.price) || 0, item.sourceControl || null);
    return true;
  };

  window.CaesarCart.refreshControls = function () {
    renderAll();
  };

  window.CaesarCart.removeItem = function (id) {
    if (!id || !cart.items[String(id)]) {
      return false;
    }

    delete cart.items[String(id)];
    clearCartNote();
    save();
    renderAll();
    scheduleQuote();
    return true;
  };

  window.CaesarCart.repeatOrder = function (items) {
    if (!Array.isArray(items) || items.length === 0) {
      return false;
    }

    items.forEach(function (item, index) {
      var dishId = item.dish_id || item.dishId || '';
      var id = item.id || (dishId ? 'dish-' + dishId : 'repeat-' + index);
      var qty = Math.max(1, Math.min(99, parseInt(item.qty || item.quantity || 1, 10) || 1));
      var existing = cart.items[id];

      if (existing) {
        existing.qty = Math.min(99, existing.qty + qty);
      } else {
        cart.items[id] = {
          name: String(item.name || ''),
          price: Number(item.price || item.unit_price) || 0,
          qty: qty,
          dishId: dishId,
          note: String(item.note || ''),
          modifiers: Array.isArray(item.modifiers) ? item.modifiers : [],
        };
      }
    });

    clearCartNote();
    save();
    renderAll();
    scheduleQuote();
    openPanel();
    return true;
  };

  function changeQty(id, delta, sourceControl) {
    if (!cart.items[id]) return;
    cart.items[id].qty += delta;
    if (cart.items[id].qty <= 0) delete cart.items[id];
    clearCartNote();
    save();
    renderAll();
    scheduleQuote();
    animateCardFrame(sourceControl);
  }

  function submitOrder() {
    if (cartApi.submitting || totalItems() === 0) {
      return;
    }

    if (!cart.payment) {
      showCartNote(t('selectPayment'), 'error');
      updateSubmit();
      return;
    }

    if (!cartApi.createUrl) {
      showCartNote(t('orderFailed'), 'error');
      return;
    }

    cartApi.submitting = true;
    clearCartNote();
    renderAll();

    requestQuote()
      .then(function () {
        var payload = cartPayload();
        var idempotencyKey = idempotencyKeyForPayload(payload);
        var headers = cartHeaders();

        headers['Idempotency-Key'] = idempotencyKey;
        payload.idempotency_key = idempotencyKey;

        return fetch(withLanguage(cartApi.createUrl), {
          method: 'POST',
          headers: headers,
          credentials: 'same-origin',
          body: JSON.stringify(payload),
        });
      })
      .then(parseCartResponse)
      .then(function (data) {
        var order = data.order || {};
        var confirmationUrl = data.confirmation_url || order.confirmation_url || '';

        cart.items = {};
        cart.persons = 1;
        cart.payment = null;
        cart.comment = '';
        save();
        renderAll();

        if (confirmationUrl) {
          window.location.href = confirmationUrl;
          return;
        }

        showCartNote(t('orderCreated') + (order.id ? ' #' + order.id : ''), 'success');
      })
      .catch(function (error) {
        showCartNote(error.message || t('orderFailed'), 'error');
      })
      .finally(function () {
        cartApi.submitting = false;
        renderAll();
      });
  }

  function restartAddAnimation(target) {
    if (!target) {
      return;
    }

    target.classList.remove('cart-add--flash');
    target.offsetWidth;
    target.classList.add('cart-add--flash');
    setTimeout(function () { target.classList.remove('cart-add--flash'); }, 240);
  }

  function restartFrameAnimation(target) {
    if (!target) {
      return;
    }

    target.classList.remove('cart-frame--pulse');
    target.offsetWidth;
    target.classList.add('cart-frame--pulse');
    setTimeout(function () { target.classList.remove('cart-frame--pulse'); }, 260);
  }

  function animateCardFrame(sourceControl) {
    var card;

    if (!sourceControl) {
      return;
    }

    if (sourceControl.closest('.dish-detail')) {
      restartAddAnimation(sourceControl.closest('[data-dish-cart-control]') || sourceControl);
      return;
    }

    card = sourceControl.closest(
      '.dish-card, .ai-assistant__dish-card'
    );
    restartFrameAnimation(card);
  }

  function animateAdd(id, sourceControl) {
    var control = sourceControl || null;
    var btn;

    if (control && !control.matches('[data-dish-cart-control]')) {
      control = control.closest('[data-dish-cart-control]');
    }

    if (control) {
      restartAddAnimation(control);
      return;
    }

    btn = qs('[data-add-btn][data-id="' + id + '"]');
    restartAddAnimation(btn);
  }

  /* ─── Desktop toast ───────────────────────────────────────────── */
  var toastTimer = null;

  function buildToast() {
    if (isMobile()) return;
    var shell = qs('.app-shell') || document.body;
    var toast = document.createElement('div');
    toast.className = 'cart-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.innerHTML = [
      '<div class="cart-toast__icon">',
      '  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4ZM3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>',
      '</div>',
      '<div class="cart-toast__body">',
      '  <span class="cart-toast__name" data-toast-name></span>',
      '  <span class="cart-toast__hint" data-cart-toast-hint>' + escHtml(t('added')) + '</span>',
      '</div>',
      '<button class="cart-toast__open" data-cart-open data-cart-toast-open>' + escHtml(t('open')) + '</button>',
      '<button class="cart-toast__close" data-toast-close aria-label="Закрыть">✕</button>',
    ].join('\n');
    shell.appendChild(toast);
    els.toast = toast;

    toast.querySelector('[data-toast-close]').addEventListener('click', function () {
      hideToast();
    });
  }

  function showToast(name) {
    if (isMobile() || !els.toast) return;
    if (els.panel && els.panel.classList.contains('cart-panel--open')) return; // панель уже открыта
    var nameEl = els.toast.querySelector('[data-toast-name]');
    if (nameEl) nameEl.textContent = name;
    els.toast.classList.add('cart-toast--visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 3500);
  }

  function hideToast() {
    if (!els.toast) return;
    els.toast.classList.remove('cart-toast--visible');
    clearTimeout(toastTimer);
  }


  function isMobile() { return window.innerWidth < 768; }

  function setCartTop() {
    if (isMobile()) return;
    var header = qs('.site-header');
    var top = header ? header.getBoundingClientRect().bottom : 60;
    document.documentElement.style.setProperty('--cart-top', top + 'px');
  }

  function openPanel() {
    var panel = els.panel;
    if (!panel) return;
    setCartTop();
    hideToast();
    panel.classList.add('cart-panel--open');
    if (els.backdrop) els.backdrop.classList.add('cart-panel--open');
    if (isMobile()) {
      document.body.style.overflow = 'hidden';
    } else {
      var shell = qs('.app-shell');
      if (shell) shell.classList.add('cart-is-open');
    }
    setTimeout(function () {
      var f = qs('button, [tabindex="0"]', panel);
      if (f) f.focus();
    }, 80);
  }

  function closePanel() {
    var panel = els.panel;
    if (!panel) return;
    panel.classList.remove('cart-panel--open');
    if (els.backdrop) els.backdrop.classList.remove('cart-panel--open');
    document.body.style.overflow = '';
    var shell = qs('.app-shell');
    if (shell) shell.classList.remove('cart-is-open');
  }

  function openOrderModal(orderId) {
    if (!els.orderModal || !els.orderModalBody || !orderId) {
      return;
    }

    var template = qs('[data-order-details-template="' + orderId + '"]');
    if (!template) {
      return;
    }

    els.orderModalBody.innerHTML = '';
    els.orderModalBody.appendChild(template.content.cloneNode(true));
    els.orderModal.classList.add('order-modal--open');
    if (els.orderBackdrop) els.orderBackdrop.classList.add('order-modal--open');
    document.body.style.overflow = 'hidden';

    setTimeout(function () {
      var closeBtn = qs('[data-order-modal-close]', els.orderModal);
      if (closeBtn) closeBtn.focus();
    }, 60);
  }

  function closeOrderModal() {
    if (!els.orderModal) {
      return;
    }

    els.orderModal.classList.remove('order-modal--open');
    if (els.orderBackdrop) els.orderBackdrop.classList.remove('order-modal--open');
    if (!els.panel || !els.panel.classList.contains('cart-panel--open')) {
      document.body.style.overflow = '';
    }
  }

  function parseRepeatItems(raw) {
    try {
      var items = JSON.parse(raw || '[]');
      return Array.isArray(items) ? items : [];
    } catch (_) {
      return [];
    }
  }


  /* ─── Swipe-to-close на мобиле ───────────────────────────────── */
  function initSwipe() {
    var panel = els.panel;
    if (!panel) return;

    var startY = 0;
    var currentY = 0;
    var isDragging = false;
    var THRESHOLD = 100; // px вниз чтобы закрыть

    panel.addEventListener('touchstart', function (e) {
      // Свайп работает только если скролл body вверху (нет прокрутки контента)
      var body = panel.querySelector('.cart-panel__body');
      if (body && body.scrollTop > 0) return;
      startY = e.touches[0].clientY;
      isDragging = true;
      panel.style.transition = 'none';
    }, { passive: true });

    panel.addEventListener('touchmove', function (e) {
      if (!isDragging) return;
      currentY = e.touches[0].clientY;
      var delta = currentY - startY;
      if (delta < 0) { delta = 0; } // нельзя тянуть вверх
      panel.style.transform = 'translateY(' + delta + 'px)';
    }, { passive: true });

    panel.addEventListener('touchend', function () {
      if (!isDragging) return;
      isDragging = false;
      var delta = currentY - startY;
      // Восстанавливаем transition
      panel.style.transition = '';
      if (delta > THRESHOLD) {
        closePanel();
        panel.style.transform = '';
      } else {
        panel.style.transform = '';
      }
    });
  }

  /* ─── Event delegation ───────────────────────────────────────── */
  function closeLanguageMenu() {
    var menu = document.querySelector('.language-menu');
    if (!menu || !menu.open) return;
    menu.classList.add('language-menu--closing');
    setTimeout(function () {
      menu.open = false;
      menu.classList.remove('language-menu--closing');
    }, 170);
  }

  function handleClicks(e) {
    var target = e.target;

    if (target.closest('[data-order-modal-close]')) {
      closeOrderModal();
      return;
    }

    var repeatBtn = target.closest('[data-repeat-order]');
    if (repeatBtn) {
      e.preventDefault();
      e.stopPropagation();
      if (window.CaesarCart.repeatOrder(parseRepeatItems(repeatBtn.getAttribute('data-items')))) {
        closeOrderModal();
      }
      return;
    }

    var orderTrigger = target.closest('[data-order-trigger]');
    if (orderTrigger) {
      openOrderModal(orderTrigger.getAttribute('data-order-id'));
      return;
    }

    // Закрываем языковое меню при клике вне него
    var langMenu = document.querySelector('.language-menu');
    if (langMenu && langMenu.open && !langMenu.contains(target)) {
      closeLanguageMenu();
    }

    // Игнорируем клики на state-control лейблах (theme, waiter, profile, lang)
    // чтобы не закрывать корзину при смене темы и т.п.
    var stateLabel = target.closest('label[for]');
    if (stateLabel) {
      var forId = stateLabel.getAttribute('for');
      var ctrl = document.getElementById(forId);
      if (ctrl && ctrl.classList.contains('state-control')) {
        // Это системный лейбл — не трогаем корзину
        return;
      }
    }

    // Dish card quantity +/-
    var dishQtyBtn = target.closest('[data-dish-qty-action][data-id]');
    if (dishQtyBtn) {
      changeQty(
        dishQtyBtn.dataset.id,
        dishQtyBtn.dataset.dishQtyAction === 'inc' ? 1 : -1,
        dishQtyBtn.closest('[data-dish-cart-control]') || dishQtyBtn
      );
      return;
    }

    // Add to cart (dish cards)
    var addBtn = target.closest('[data-add-btn]');
    if (addBtn) {
      addItem(
        addBtn.dataset.id,
        localizedDatasetName(addBtn),
        addBtn.dataset.price,
        addBtn.closest('[data-dish-cart-control]') || addBtn
      );
      return;
    }

    // Quantity +/-
    var qtyBtn = target.closest('[data-action][data-id]');
    if (qtyBtn && els.panel && els.panel.contains(qtyBtn)) {
      changeQty(qtyBtn.dataset.id, qtyBtn.dataset.action === 'inc' ? 1 : -1);
      return;
    }

    // Submit order
    if (target.closest('.cart-submit-btn')) {
      submitOrder();
      return;
    }

    // Toggle panel
    if (target.closest('[data-cart-open]')) {
      var isOpen = els.panel && els.panel.classList.contains('cart-panel--open');
      if (isOpen) closePanel(); else openPanel();
      return;
    }

    // Очистить корзину
    if (target.closest('[data-cart-clear]')) {
      cart.items = {};
      clearCartNote();
      save();
      var clearBtn = document.querySelector('.cart-clear-btn');
      if (clearBtn) clearBtn.remove();
      renderAll();
      return;
    }

    // Close panel
    if (target.closest('[data-cart-close]')) {
      closePanel();
      return;
    }

    // Клик вне корзины закрывает её только на десктопе
    // Проверяем через composedPath чтобы не поймать тот же клик что открыл панель
    if (!isMobile() && els.panel && els.panel.classList.contains('cart-panel--open')) {
      var path = e.composedPath ? e.composedPath() : [];
      var clickedInsidePanel = els.panel.contains(target) || path.indexOf(els.panel) !== -1;
      var clickedCartBtn = path.some(function(el) {
        return el && el.hasAttribute && el.hasAttribute('data-cart-open');
      });
      if (!clickedInsidePanel && !clickedCartBtn) {
        closePanel();
        return;
      }
    }

    // Persons
    if (target.closest('[data-persons-dec]')) {
      cart.persons = Math.max(1, cart.persons - 1);
      save(); syncPersonsUI();
      return;
    }
    if (target.closest('[data-persons-inc]')) {
      cart.persons = Math.min(20, cart.persons + 1);
      save(); syncPersonsUI();
      return;
    }

    // Payment
    var payBtn = target.closest('[data-pay]');
    if (payBtn) {
      cart.payment = payBtn.dataset.pay;
      clearCartNote();
      save(); syncPaymentUI(); updateSubmit();
      return;
    }
  }

  function handleInput(e) {
    if (e.target.matches('[data-cart-comment]')) {
      cart.comment = e.target.value;
      save();
    }
  }

  function handleKeydown(e) {
    var orderTrigger = e.target.closest('[data-order-trigger]');

    if (e.key === 'Escape') {
      if (els.orderModal && els.orderModal.classList.contains('order-modal--open')) {
        closeOrderModal();
      } else {
        closePanel();
      }
      return;
    }

    if (orderTrigger && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      openOrderModal(orderTrigger.getAttribute('data-order-id'));
    }
  }

  /* ─── Prepare price buttons on dish cards ─────────────────────── */
  function attachDishButtons() {
    qsa('.dish-card').forEach(function (card) {
      var btn = card.querySelector('[data-add-btn]');
      var nameEl = card.querySelector('.dish-copy h2');
      var priceEl = card.querySelector('.dish-footer strong');

      if (!btn || !nameEl || !priceEl || btn.dataset.cartReady === '1') return;

      var name = localizedDatasetName(btn) || nameEl.textContent.trim();
      var priceRaw = priceEl.textContent
        .replace(/[^\d.,]/g, '')
        .replace(',', '.');
      if (!priceRaw) return;
      var price = parseFloat(priceRaw);
      var id = card.id || 'dish-' + btoa(encodeURIComponent(name)).replace(/[^a-z0-9]/gi, '').slice(0, 16);

      btn.setAttribute('data-add-btn', '');
      btn.setAttribute('data-id', id);
      if (!btn.dataset.name) {
        btn.setAttribute('data-name', name);
      }
      btn.setAttribute('data-price', price);
      btn.setAttribute('aria-label', t('addToCart') + name);
      btn.dataset.cartReady = '1';
    });
  }

  /* ─── Inject HTML shells ──────────────────────────────────────── */
  function buildHTML() {
    // ── Cart icon for symbol sprite ──────────────────────────────
    var sprite = qs('.icon-sprite');
    if (sprite && !document.getElementById('i-cart')) {
      var sym = document.createElementNS('http://www.w3.org/2000/svg', 'symbol');
      sym.setAttribute('id', 'i-cart');
      sym.setAttribute('viewBox', '0 0 24 24');
      sym.innerHTML = '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4ZM3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>';
      sprite.appendChild(sym);
    }

    // ── Desktop header button ────────────────────────────────────
    var headerActions = qs('.header-actions');
    if (headerActions) {
      var deskWrap = document.createElement('div');
      deskWrap.className = 'cart-desktop-wrap';
      deskWrap.innerHTML = [
        '<button class="icon-button cart-btn" data-cart-open aria-label="Корзина">',
        '  <svg><use href="#i-cart"/></svg>',
        '  <span class="cart-btn__badge" data-cart-count hidden>0</span>',
        '</button>',
      ].join('');
      headerActions.insertBefore(deskWrap, headerActions.firstChild);
      els.desktopBtn = deskWrap.querySelector('.cart-btn');
    }

    // ── Mobile bottom bar ────────────────────────────────────────
    var bar = document.createElement('div');
    bar.className = 'cart-bar';
    bar.innerHTML = [
      '<button class="cart-bar__inner" data-cart-open aria-label="Открыть корзину">',
      '  <span class="cart-bar__icon">',
      '    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4ZM3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>',
      '    <span class="cart-bar__count" data-cart-count hidden>0</span>',
      '  </span>',
      '  <span class="cart-bar__sep"></span>',
      '  <span class="cart-bar__price" data-cart-total-mini>0 ₽</span>',
      '  <span class="cart-bar__action">',
      '    <span class="lang lang--ru">Перейти в корзину</span>',
      '    <span class="lang lang--en">Open cart</span>',
      '    <span class="lang lang--tr">Sepeti aç</span>',
      '  </span>',
      '  <span class="cart-bar__arrow">›</span>',
      '</button>',
    ].join('');
    var shell = qs('.app-shell') || document.body;
    shell.appendChild(bar);
    els.mobileBar = bar;

    // ── Backdrop (мобиле не нужен при full-screen, но оставляем для десктопа) ──
    var backdrop = document.createElement('div');
    backdrop.className = 'cart-panel__backdrop';
    backdrop.setAttribute('data-cart-close', '');
    backdrop.setAttribute('aria-hidden', 'true');
    shell.appendChild(backdrop);
    els.backdrop = backdrop;

    // ── Cart panel ───────────────────────────────────────────────
    var panel = document.createElement('div');
    panel.className = 'cart-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', 'Корзина');
    panel.innerHTML = [
      // ── Шапка в стиле Lovin: счётчик + итог + кнопка закрытия
      '<div class="cart-panel__header">',
      '  <div class="cart-panel__header-meta">',
      '    <h2 class="cart-panel__title">',
      '      <span class="lang lang--ru">Корзина</span>',
      '      <span class="lang lang--en">Cart</span>',
      '      <span class="lang lang--tr">Sepet</span>',
      '    </h2>',
      '    <span class="cart-panel__header-count" data-cart-header-count></span>',
      '  </div>',
      '  <div class="cart-panel__header-right">',
      '    <span class="cart-panel__header-total" data-cart-header-total></span>',
      '    <button class="close-button" data-cart-close aria-label="Закрыть корзину">',
      '      <svg viewBox="0 0 24 24"><path d="m5 5 14 14M19 5 5 19"/></svg>',
      '    </button>',
      '  </div>',
      '</div>',

      '<div class="cart-panel__body">',

      '  <div class="cart-lines" data-lines></div>',

      '  <div class="cart-extras" data-cart-extras hidden>',

      '  <div class="cart-section">',
      '    <p class="cart-section__label">',
      '      <span class="lang lang--ru">Количество персон</span>',
      '      <span class="lang lang--en">Number of guests</span>',
      '      <span class="lang lang--tr">Kişi sayısı</span>',
      '    </p>',
      '    <div class="cart-stepper">',
      '      <button class="cart-stepper__btn" data-persons-dec aria-label="Меньше гостей">−</button>',
      '      <span class="cart-stepper__val" data-persons-count>1</span>',
      '      <button class="cart-stepper__btn" data-persons-inc aria-label="Больше гостей">+</button>',
      '    </div>',
      '  </div>',

      '  <div class="cart-section">',
      '    <p class="cart-section__label">',
      '      <span class="lang lang--ru">Способ оплаты</span>',
      '      <span class="lang lang--en">Payment method</span>',
      '      <span class="lang lang--tr">Ödeme yöntemi</span>',
      '    </p>',
      '    <div class="cart-pay-row">',
      '      <button class="cart-pay-btn" data-pay="card">',
      '        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>',
      '        <span class="lang lang--ru">Картой</span>',
      '        <span class="lang lang--en">Card</span>',
      '        <span class="lang lang--tr">Kart</span>',
      '      </button>',
      '      <button class="cart-pay-btn" data-pay="online">',
      '        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 18h4M9 6h6"/></svg>',
      '        <span class="lang lang--ru">Онлайн</span>',
      '        <span class="lang lang--en">Online</span>',
      '        <span class="lang lang--tr">Online</span>',
      '      </button>',
      '      <button class="cart-pay-btn" data-pay="cash">',
      '        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><circle cx="12" cy="14" r="3"/><path d="M6 7V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v2"/></svg>',
      '        <span class="lang lang--ru">Наличными</span>',
      '        <span class="lang lang--en">Cash</span>',
      '        <span class="lang lang--tr">Nakit</span>',
      '      </button>',
      '    </div>',
      '  </div>',

      '  <div class="cart-section">',
      '    <label class="cart-section__label" for="cart-comment">',
      '      <span class="lang lang--ru">Комментарий к заказу</span>',
      '      <span class="lang lang--en">Order comment</span>',
      '      <span class="lang lang--tr">Sipariş notu</span>',
      '    </label>',
      '    <textarea class="cart-comment" id="cart-comment" data-cart-comment',
      '      placeholder="' + escHtml(t('commentPlaceholder')) + '"',
      '      rows="3"></textarea>',
      '  </div>',

      '  </div>',  /* /cart-extras */

      '</div>',

      '<div class="cart-panel__footer">',
      '  <div class="cart-total-row">',
      '    <span data-cart-items-label>0 ' + escHtml(pluralItems(0)) + '</span>',
      '    <strong data-cart-grand-total>0 ₽</strong>',
      '  </div>',
      '  <div class="cart-checkout-row">',
      '    <div class="cart-checkout-label">',
      '      <span class="cart-checkout-label__hint">',
      '        <span class="lang lang--ru">К оплате</span>',
      '        <span class="lang lang--en">Total</span>',
      '        <span class="lang lang--tr">Toplam</span>',
      '      </span>',
      '      <span class="cart-checkout-label__price" data-cart-checkout-total>0 ₽</span>',
      '    </div>',
      '    <button class="primary-button cart-submit-btn" disabled>',
      '      <span class="lang lang--ru">Оформить заказ</span>',
      '      <span class="lang lang--en">Place order</span>',
      '      <span class="lang lang--tr">Sipariş ver</span>',
      '    </button>',
      '  </div>',
      '  <div class="cart-submit-note" data-cart-note role="status" aria-live="polite" hidden></div>',
      '</div>',
    ].join('\n');

    shell.appendChild(panel);
    els.panel = panel;
    els.lineList = panel.querySelector('[data-lines]');
    els.extras = panel.querySelector('[data-cart-extras]');
    els.submitBtn = panel.querySelector('.cart-submit-btn');
    els.note = panel.querySelector('[data-cart-note]');

    if (qs('[data-order-details-template]')) {
      var orderBackdrop = document.createElement('div');
      orderBackdrop.className = 'order-modal-backdrop';
      orderBackdrop.setAttribute('data-order-modal-close', '');
      orderBackdrop.setAttribute('aria-hidden', 'true');
      shell.appendChild(orderBackdrop);
      els.orderBackdrop = orderBackdrop;

      var orderModal = document.createElement('div');
      orderModal.className = 'order-modal';
      orderModal.setAttribute('role', 'dialog');
      orderModal.setAttribute('aria-modal', 'true');
      orderModal.setAttribute('aria-label', 'Order details');
      orderModal.innerHTML = [
        '<button class="close-button order-modal__close" data-order-modal-close aria-label="Close order details">',
        '  <svg viewBox="0 0 24 24"><path d="m5 5 14 14M19 5 5 19"/></svg>',
        '</button>',
        '<div class="order-modal__body" data-order-modal-body></div>',
      ].join('\n');
      shell.appendChild(orderModal);
      els.orderModal = orderModal;
      els.orderModalBody = orderModal.querySelector('[data-order-modal-body]');
    }
  }

  /* ─── Submit button state ─────────────────────────────────────── */
  function updateSubmit() {
    if (!els.submitBtn) return;
    var needsPayment = totalItems() > 0 && !cart.payment;
    els.submitBtn.disabled = totalItems() === 0
      || cartApi.quotePending
      || cartApi.submitting
      || !cartApi.createUrl;
    els.submitBtn.setAttribute('aria-busy', cartApi.submitting ? 'true' : 'false');
    els.submitBtn.title = needsPayment ? t('selectPayment') : '';
  }

  var _renderAll = renderAll;
  renderAll = function () {
    _renderAll();
    updateSubmit();
  };

  /* ─── Init ────────────────────────────────────────────────────── */
  function init() {
    load();
    readCartApi();
    buildHTML();
    buildToast();
    attachDishButtons();
    renderAll();
    scheduleQuote();

    // Обычная делегация на document — работает везде включая iOS
    // (iOS требует cursor:pointer или onclick на промежуточных div-ах,
    //  это решено в CSS через cursor:pointer на .app-shell)
    initSwipe();
    document.addEventListener('click', handleClicks);
    document.addEventListener('input', handleInput);
    document.addEventListener('keydown', handleKeydown);

    setCartTop();
    window.addEventListener('resize', setCartTop);
    window.addEventListener('cc:languagechange', renderAll);
    window.addEventListener('pageshow', function (event) {
      if (!event.persisted) {
        return;
      }

      cartApi.submitting = false;
      load();
      renderAll();
    });
    document.addEventListener('cc:dishdetailopen', function () {
      attachDishButtons();
      syncDishControls();
      syncLocalizedText();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
