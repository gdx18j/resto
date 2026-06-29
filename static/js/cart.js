/**
 * Caesar & Company — Cart
 * Mobile: полноэкранная шторка снизу
 * Desktop: боковая панель справа
 */
(function () {
  'use strict';

  /* ─── State ─────────────────────────────────────────────────── */
  var cart = {
    items: {},      // { dishId: { name, price, qty } }
    persons: 1,
    payment: null,  // 'card' | 'cash'
    comment: '',
  };

  /* ─── DOM refs (resolved after DOMContentLoaded) ─────────────── */
  var els = {};

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  /* ─── Cart math ───────────────────────────────────────────────── */
  function totalItems() {
    return Object.values(cart.items).reduce(function (s, i) { return s + i.qty; }, 0);
  }

  function totalPrice() {
    return Object.values(cart.items).reduce(function (s, i) { return s + i.price * i.qty; }, 0);
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
      el.textContent = n === 1 ? '1 товар' : n + ' ' + pluralItems(n);
    });
    qsa('[data-cart-header-total]').forEach(function (el) {
      el.textContent = fmt(p);
    });

    // Mobile bar
    var bar = els.mobileBar;
    if (bar) {
      if (n > 0) {
        bar.classList.add('cart-bar--visible');
        document.body.classList.add('cart-bar-visible');
      } else {
        bar.classList.remove('cart-bar--visible');
        document.body.classList.remove('cart-bar-visible');
      }
    }

    // Desktop button
    var deskBtn = els.desktopBtn;
    if (deskBtn) {
      deskBtn.classList.toggle('cart-btn--has-items', n > 0);
    }
  }

  function pluralItems(n) {
    var mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return 'товар';
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'товара';
    return 'товаров';
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
      if (!container.querySelector('.cart-empty-msg')) {
        container.innerHTML = '<p class="cart-empty-msg">Корзина пуста — добавьте блюда из меню.</p>';
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
          '    <button class="cart-qty__btn" data-action="dec" data-id="' + id + '" aria-label="Убрать одну порцию">−</button>',
          '    <span class="cart-qty__num">' + item.qty + '</span>',
          '    <button class="cart-qty__btn" data-action="inc" data-id="' + id + '" aria-label="Добавить ещё одну порцию">+</button>',
          '  </div>',
        ].join('\n');
        container.appendChild(div);
      }
    });

    // Кнопка очистки — только когда есть товары
    var clearBtn = document.createElement('button');
    clearBtn.className = 'cart-clear-btn';
    clearBtn.setAttribute('data-cart-clear', '');
    clearBtn.textContent = 'Очистить корзину';
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

  function renderAll() {
    renderBadges();
    renderLines();
    renderSummary();
    syncPersonsUI();
    syncPaymentUI();
    syncCommentUI();
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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

  /* ─── Public API (used by dish cards) ────────────────────────── */
  function addItem(id, name, price) {
    if (cart.items[id]) {
      cart.items[id].qty += 1;
    } else {
      cart.items[id] = { name: name, price: Number(price), qty: 1 };
    }
    save();
    renderAll();
    animateAdd(id);
    showToast(name);
  }

  function changeQty(id, delta) {
    if (!cart.items[id]) return;
    cart.items[id].qty += delta;
    if (cart.items[id].qty <= 0) delete cart.items[id];
    save();
    renderAll();
  }

  function animateAdd(id) {
    var btn = qs('[data-add-btn][data-id="' + id + '"]');
    if (!btn) return;
    btn.classList.add('cart-add--flash');
    setTimeout(function () { btn.classList.remove('cart-add--flash'); }, 460);
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
      '  <span class="cart-toast__hint">Добавлено в корзину</span>',
      '</div>',
      '<button class="cart-toast__open" data-cart-open>Открыть</button>',
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

    // Add to cart (dish cards)
    var addBtn = target.closest('[data-add-btn]');
    if (addBtn) {
      addItem(addBtn.dataset.id, addBtn.dataset.name, addBtn.dataset.price);
      return;
    }

    // Quantity +/-
    var qtyBtn = target.closest('[data-action][data-id]');
    if (qtyBtn && els.panel && els.panel.contains(qtyBtn)) {
      changeQty(qtyBtn.dataset.id, qtyBtn.dataset.action === 'inc' ? 1 : -1);
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
      save(); syncPaymentUI();
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
    if (e.key === 'Escape') closePanel();
  }

  /* ─── Build "Add to cart" button on each dish card ────────────── */
  function attachDishButtons() {
    qsa('.dish-footer').forEach(function (footer) {
      var card = footer.closest('.dish-card');
      if (!card || footer.querySelector('[data-add-btn]')) return;

      var nameEl = card.querySelector('.dish-copy h2');
      var priceEl = card.querySelector('.dish-footer strong');
      if (!nameEl || !priceEl) return;

      var name = nameEl.textContent.trim();
      var priceRaw = priceEl.textContent
        .replace(/[^\d.,]/g, '')
        .replace(',', '.');
      if (!priceRaw) return;
      var price = parseFloat(priceRaw);
      var id = 'dish-' + btoa(encodeURIComponent(name)).replace(/[^a-z0-9]/gi, '').slice(0, 16);

      var btn = document.createElement('button');
      btn.className = 'cart-add-btn';
      btn.setAttribute('data-add-btn', '');
      btn.setAttribute('data-id', id);
      btn.setAttribute('data-name', name);
      btn.setAttribute('data-price', price);
      btn.setAttribute('aria-label', 'Добавить в корзину: ' + name);
      btn.innerHTML = [
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4ZM3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>',
        '<span class="cart-add-btn__label">В корзину</span>',
      ].join('');

      footer.appendChild(btn);
    });
  }

  /* ─── Inject HTML shells ──────────────────────────────────────── */
  function buildHTML() {
    // ── Cart icon for symbol sprite ──────────────────────────────
    var sprite = qs('.icon-sprite');
    if (sprite) {
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
      '  <span class="cart-bar__action">Перейти в корзину</span>',
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
      '    <h2 class="cart-panel__title">Корзина</h2>',
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
      '    <p class="cart-section__label">Количество персон</p>',
      '    <div class="cart-stepper">',
      '      <button class="cart-stepper__btn" data-persons-dec aria-label="Меньше гостей">−</button>',
      '      <span class="cart-stepper__val" data-persons-count>1</span>',
      '      <button class="cart-stepper__btn" data-persons-inc aria-label="Больше гостей">+</button>',
      '    </div>',
      '  </div>',

      '  <div class="cart-section">',
      '    <p class="cart-section__label">Способ оплаты</p>',
      '    <div class="cart-pay-row">',
      '      <button class="cart-pay-btn" data-pay="card">',
      '        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>',
      '        Картой',
      '      </button>',
      '      <button class="cart-pay-btn" data-pay="cash">',
      '        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><circle cx="12" cy="14" r="3"/><path d="M6 7V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v2"/></svg>',
      '        Наличными',
      '      </button>',
      '    </div>',
      '  </div>',

      '  <div class="cart-section">',
      '    <label class="cart-section__label" for="cart-comment">Комментарий к заказу</label>',
      '    <textarea class="cart-comment" id="cart-comment" data-cart-comment',
      '      placeholder="Аллергии, пожелания к сервировке, особые просьбы…"',
      '      rows="3"></textarea>',
      '  </div>',

      '  </div>',  /* /cart-extras */

      '</div>',

      '<div class="cart-panel__footer">',
      '  <div class="cart-total-row">',
      '    <span data-cart-items-label>0 товаров</span>',
      '    <strong data-cart-grand-total>0 ₽</strong>',
      '  </div>',
      '  <div class="cart-checkout-row">',
      '    <div class="cart-checkout-label">',
      '      <span class="cart-checkout-label__hint">К оплате</span>',
      '      <span class="cart-checkout-label__price" data-cart-checkout-total>0 ₽</span>',
      '    </div>',
      '    <button class="primary-button cart-submit-btn" disabled>Оформить заказ</button>',
      '  </div>',
      '</div>',
    ].join('\n');

    shell.appendChild(panel);
    els.panel = panel;
    els.lineList = panel.querySelector('[data-lines]');
    els.extras = panel.querySelector('[data-cart-extras]');
    els.submitBtn = panel.querySelector('.cart-submit-btn');
  }

  /* ─── Submit button state ─────────────────────────────────────── */
  function updateSubmit() {
    if (!els.submitBtn) return;
    els.submitBtn.disabled = totalItems() === 0;
  }

  var _renderAll = renderAll;
  renderAll = function () {
    _renderAll();
    updateSubmit();
  };

  /* ─── Init ────────────────────────────────────────────────────── */
  function init() {
    load();
    buildHTML();
    buildToast();
    attachDishButtons();
    renderAll();

    // Обычная делегация на document — работает везде включая iOS
    // (iOS требует cursor:pointer или onclick на промежуточных div-ах,
    //  это решено в CSS через cursor:pointer на .app-shell)
    initSwipe();
    document.addEventListener('click', handleClicks);
    document.addEventListener('input', handleInput);
    document.addEventListener('keydown', handleKeydown);

    setCartTop();
    window.addEventListener('resize', setCartTop);
    var mo = new MutationObserver(function () { attachDishButtons(); });
    var main = qs('.main-content');
    if (main) mo.observe(main, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();