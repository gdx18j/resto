(function () {
  var REQUEST_TIMEOUT_MS = 120000;
  var LOCK_CLASS = "ai-assistant-lock";
  var TYPEWRITER_STEP_MS = 14;
  var modalManager = window.CaesarModal || null;

  var roots = document.querySelectorAll("[data-ai-assistant]");

  Array.prototype.forEach.call(roots, initAssistant);

  function initAssistant(root) {
    var endpoint = root.dataset.endpoint;
    var historyEndpoint = root.dataset.historyEndpoint || "";
    var isAccountBound = root.dataset.accountBound === "1";
    var shell = document.querySelector(".app-shell");
    var restaurantSlug = shell ? shell.dataset.cartRestaurantSlug || "" : "";
    var tableToken = shell ? shell.dataset.cartTableToken || "" : "";
    var contextStorageKey = "global";

    if (tableToken) {
      contextStorageKey = "table:" + tableToken;
    } else if (restaurantSlug) {
      contextStorageKey = "restaurant:" + restaurantSlug;
    }

    var storageKey = (root.dataset.storageKey || "resto.aiAssistant.v3") + ":" + contextStorageKey;
    var launcher = root.querySelector("[data-ai-open]");
    var backdrop = root.querySelector("[data-ai-backdrop]");
    var panel = root.querySelector("[data-ai-panel]");
    var closeButton = root.querySelector("[data-ai-close]");
    var resetButton = root.querySelector("[data-ai-reset]");
    var form = root.querySelector("[data-ai-form]");
    var inputs = Array.prototype.slice.call(root.querySelectorAll("[data-ai-input]"));
    var sendButton = root.querySelector("[data-ai-send]");
    var messagesNode = root.querySelector("[data-ai-messages]");
    var csrfInput = form ? form.querySelector("[name=csrfmiddlewaretoken]") : null;
    var closeTimer = null;
    var shouldAutoScroll = true;
    var userPausedAutoScroll = false;
    var lastTouchY = 0;
    var lastScrollTop = 0;
    var pausedScrollTop = 0;
    var isRestoringPausedScroll = false;
    var userScrollIntentUntil = 0;

    if (!endpoint || !form || !inputs.length || !sendButton || !messagesNode) {
      return;
    }

    var translations = {
      ru: {
        greeting: "Здравствуйте! Я помогу разобраться в меню, подобрать блюдо, проверить ингредиенты и аллергены.",
        added: "Добавлено",
        add: "Добавить",
        openDish: "Открыть блюдо в меню",
        typing: "Ассистент отвечает",
        noResponse: "Я не получил текст ответа.",
        requestFailed: "Не удалось получить ответ. Попробуйте еще раз.",
        timeout: "Ответ занимает слишком много времени. Попробуйте еще раз.",
        connection: "Не удалось связаться с ассистентом. Проверьте соединение.",
        today: "Сегодня",
        yesterday: "Вчера"
      },
      en: {
        greeting: "Hi! I can help you explore the menu, choose a dish, and check ingredients or allergens.",
        added: "Added",
        add: "Add",
        openDish: "Open this dish in the menu",
        typing: "Assistant is replying",
        noResponse: "I did not receive a text response.",
        requestFailed: "Could not get a response. Please try again.",
        timeout: "The response is taking too long. Please try again.",
        connection: "Could not reach the assistant. Check your connection.",
        today: "Today",
        yesterday: "Yesterday"
      },
      tr: {
        greeting: "Merhaba! Menüyü keşfetmenize, yemek seçmenize, içerikleri ve alerjenleri kontrol etmenize yardımcı olurum.",
        added: "Eklendi",
        add: "Ekle",
        openDish: "Menüde bu yemeği aç",
        typing: "Asistan yanıtlıyor",
        noResponse: "Yanıt metni alınamadı.",
        requestFailed: "Yanıt alınamadı. Lütfen tekrar deneyin.",
        timeout: "Yanıt çok uzun sürüyor. Lütfen tekrar deneyin.",
        connection: "Asistana ulaşılamadı. Bağlantınızı kontrol edin.",
        today: "Bugün",
        yesterday: "Dün"
      }
    };

    var state = readState();
    var isBusy = false;
    var hasUserInteracted = false;

    renderMessages();
    hydrateServerHistory();

    function getCurrentLanguage() {
      var language = document.documentElement.dataset.language || document.documentElement.lang || "ru";
      return translations[language] ? language : "ru";
    }

    function t(key) {
      var language = getCurrentLanguage();
      return translations[language][key] || translations.ru[key] || "";
    }

    function getCurrentLocale() {
      var language = getCurrentLanguage();
      var locales = {
        ru: "ru-RU",
        en: "en-US",
        tr: "tr-TR",
      };

      return locales[language] || locales.ru;
    }

    function normalizeTimestamp(value) {
      var date;

      if (typeof value !== "string" || !value) {
        return null;
      }

      date = new Date(value);

      if (Number.isNaN(date.getTime())) {
        return null;
      }

      return date.toISOString();
    }

    function parseMessageDate(value) {
      var date = value ? new Date(value) : null;

      if (!date || Number.isNaN(date.getTime())) {
        return null;
      }

      return date;
    }

    function getLocalDateKey(value) {
      var date = parseMessageDate(value);

      if (!date) {
        return "";
      }

      return [
        date.getFullYear(),
        String(date.getMonth() + 1).padStart(2, "0"),
        String(date.getDate()).padStart(2, "0"),
      ].join("-");
    }

    function isSameLocalDay(left, right) {
      return (
        left &&
        right &&
        left.getFullYear() === right.getFullYear() &&
        left.getMonth() === right.getMonth() &&
        left.getDate() === right.getDate()
      );
    }

    function formatDateLabel(value) {
      var date = parseMessageDate(value);
      var today = new Date();
      var yesterday = new Date();
      var options;

      if (!date) {
        return "";
      }

      yesterday.setDate(today.getDate() - 1);

      if (isSameLocalDay(date, today)) {
        return t("today");
      }

      if (isSameLocalDay(date, yesterday)) {
        return t("yesterday");
      }

      options = {
        day: "numeric",
        month: "long",
      };

      if (date.getFullYear() !== today.getFullYear()) {
        options.year = "numeric";
      }

      return new Intl.DateTimeFormat(getCurrentLocale(), options).format(date);
    }

    function formatMessageTime(value) {
      var date = parseMessageDate(value);

      if (!date) {
        return "";
      }

      return new Intl.DateTimeFormat(
        getCurrentLocale(),
        {
          hour: "2-digit",
          minute: "2-digit",
        }
      ).format(date);
    }

    function getVisibleInput() {
      return inputs.find(function (candidate) {
        return window.getComputedStyle(candidate).display !== "none";
      }) || inputs[0];
    }

    function focusVisibleInput() {
      var visibleInput = getVisibleInput();

      if (visibleInput) {
        visibleInput.focus();
      }
    }

    function syncInputs(value, sourceInput) {
      inputs.forEach(function (candidate) {
        if (candidate !== sourceInput) {
          candidate.value = value;
        }
      });
    }

    if (launcher && panel) {
      launcher.addEventListener("click", function () {
        setOpen(!root.classList.contains("is-open"));
      });
    }

    if (backdrop) {
      backdrop.addEventListener("click", function () {
        setOpen(false);
      });
    }

    if (closeButton && panel) {
      closeButton.addEventListener("click", function () {
        setOpen(false);
      });
    }

    if (resetButton) {
      resetButton.addEventListener("click", function () {
        hasUserInteracted = true;
        state = createInitialState();
        state.isNewChat = true;
        writeState();
        renderMessages();
        resizeInput();
        focusVisibleInput();
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      sendCurrentPrompt();
    });

    inputs.forEach(function (input) {
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          sendCurrentPrompt();
        }
      });

      input.addEventListener("input", function () {
        syncInputs(input.value, input);
        resizeInput();
      });
    });

    messagesNode.addEventListener(
      "wheel",
      function (event) {
        markUserScrollIntent();

        if (event.deltaY < 0) {
          pauseAutoScroll();
        }
      },
      { passive: true }
    );

    messagesNode.addEventListener(
      "touchstart",
      function (event) {
        if (event.touches && event.touches.length) {
          lastTouchY = event.touches[0].clientY;
        }
      },
      { passive: true }
    );

    messagesNode.addEventListener(
      "touchmove",
      function (event) {
        var currentTouchY;

        if (!event.touches || !event.touches.length) {
          return;
        }

        currentTouchY = event.touches[0].clientY;
        markUserScrollIntent();

        if (currentTouchY - lastTouchY > 2) {
          pauseAutoScroll();
        }

        lastTouchY = currentTouchY;
      },
      { passive: true }
    );

    messagesNode.addEventListener(
      "scroll",
      function () {
        var isScrollingUp = messagesNode.scrollTop < lastScrollTop - 1;

        if (isRestoringPausedScroll) {
          lastScrollTop = messagesNode.scrollTop;
          isRestoringPausedScroll = false;
          return;
        }

        if (isBusy && isScrollingUp) {
          pauseAutoScroll();
        }

        lastScrollTop = messagesNode.scrollTop;

        if (userPausedAutoScroll) {
          if (isMessagesAtBottom()) {
            userPausedAutoScroll = false;
            shouldAutoScroll = true;
          } else {
            shouldAutoScroll = false;
            if (hasRecentUserScrollIntent() || isScrollingUp) {
              pausedScrollTop = messagesNode.scrollTop;
            }
          }
          return;
        }

        shouldAutoScroll = isMessagesNearBottom();

        if (isMessagesAtBottom()) {
          userPausedAutoScroll = false;
        }
      },
      { passive: true }
    );

    messagesNode.addEventListener("click", function (event) {
      var link = event.target.closest("[data-ai-dish-link]");

      if (link) {
        setOpen(false);
      }
    });

    messagesNode.addEventListener(
      "pointerdown",
      function () {
        markUserScrollIntent();
      },
      { passive: true }
    );

    document.addEventListener("keydown", function (event) {
      if (
        !modalManager &&
        event.key === "Escape" &&
        panel &&
        root.classList.contains("is-open")
      ) {
        setOpen(false);
      }
    });

    window.addEventListener("cc:languagechange", function () {
      syncInitialGreetingLanguage();
      renderMessages();
      resizeInput();

      if (root.classList.contains("is-open")) {
        focusVisibleInput();
      }
    });

    function createInitialState() {
      return {
        sessionId: null,
        greetingLanguage: getCurrentLanguage(),
        isNewChat: false,
        messages: [
          {
            role: "assistant",
            text: t("greeting"),
            isGreeting: true,
            dishes: [],
          },
        ],
      };
    }

    function isInitialGreetingState() {
      return (
        state &&
        !state.sessionId &&
        Array.isArray(state.messages) &&
        state.messages.length === 1 &&
        state.messages[0].role === "assistant" &&
        (!state.messages[0].dishes || !state.messages[0].dishes.length)
      );
    }

    function syncInitialGreetingLanguage() {
      var language = getCurrentLanguage();

      if (!isInitialGreetingState()) {
        return;
      }

      if (state.greetingLanguage === language) {
        return;
      }

      state.greetingLanguage = language;
      state.messages[0].text = t("greeting");
      state.messages[0].isGreeting = true;
      writeState();
      renderMessages();
    }

    function normalizeDishes(dishes) {
      if (!Array.isArray(dishes)) {
        return [];
      }

      return dishes
        .filter(function (dish) {
          return dish && typeof dish.name === "string" && typeof dish.url === "string";
        })
        .slice(0, 3)
        .map(function (dish) {
          return {
            id: dish.id || "",
            cartId: dish.cartId || dish.cart_id || dish.id || "",
            name: dish.name,
            description: typeof dish.description === "string" ? dish.description : "",
            price: typeof dish.price === "string" ? dish.price : "",
            imageUrl: dish.imageUrl || dish.image_url || "",
            url: dish.url,
            category: typeof dish.category === "string" ? dish.category : "",
          };
        });
    }

    function normalizeMessages(messages) {
      if (!Array.isArray(messages)) {
        return null;
      }

      var normalized = messages
        .filter(function (message) {
          return (
            message &&
            (message.role === "assistant" || message.role === "user") &&
            typeof message.text === "string" &&
            message.text.trim()
          );
        })
        .map(function (message) {
          return {
            role: message.role,
            text: message.text.trim(),
            dishes: normalizeDishes(message.dishes),
            createdAt: normalizeTimestamp(message.createdAt || message.created_at),
          };
        });

      return normalized.length ? normalized : null;
    }

    function readState() {
      try {
        var raw = window.sessionStorage.getItem(storageKey);

        if (!raw) {
          return createInitialState();
        }

        var parsed = JSON.parse(raw);
        var messages = normalizeMessages(parsed && parsed.messages);

        if (!messages) {
          return createInitialState();
        }

        return {
          sessionId: parsed.sessionId || null,
          greetingLanguage: parsed.greetingLanguage || null,
          isNewChat: Boolean(parsed.isNewChat),
          messages: messages,
        };
      } catch (error) {
        return createInitialState();
      }
    }

    function hydrateServerHistory() {
      var url;

      if (!historyEndpoint || !isAccountBound || state.isNewChat) {
        return;
      }

      url = new URL(historyEndpoint, window.location.href);
      url.searchParams.set("language", getCurrentLanguage());

      if (restaurantSlug) {
        url.searchParams.set("restaurant_slug", restaurantSlug);
      }

      if (tableToken) {
        url.searchParams.set("table_token", tableToken);
      }

      if (state.sessionId) {
        url.searchParams.set("session_id", state.sessionId);
      }

      window.fetch(url.toString(), {
        method: "GET",
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
      })
        .then(function (response) {
          if (!response.ok) {
            return null;
          }

          return response.json().catch(function () {
            return null;
          });
        })
        .then(function (data) {
          var messages;

          if (!data || hasUserInteracted) {
            return;
          }

          messages = normalizeMessages(data.messages);

          if (!messages) {
            return;
          }

          state = {
            sessionId: data.session_id || null,
            greetingLanguage: getCurrentLanguage(),
            isNewChat: false,
            messages: messages,
          };
          writeState();
          renderMessages();
        })
        .catch(function () {
          return;
        });
    }

    function writeState() {
      try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(state));
      } catch (error) {
        return;
      }
    }

    function getCartExemptElements() {
      var elements = Array.prototype.slice.call(document.querySelectorAll("[data-cart-open]"));
      var cartPanel = document.querySelector(".cart-panel");
      var cartBackdrop = document.querySelector(".cart-panel__backdrop");

      if (cartPanel) {
        elements.push(cartPanel);
      }

      if (cartBackdrop) {
        elements.push(cartBackdrop);
      }

      return elements;
    }

    function closeCartBeforeAssistantOpen() {
      if (
        window.CaesarCart &&
        typeof window.CaesarCart.close === "function" &&
        window.CaesarCart.isOpen &&
        window.CaesarCart.isOpen()
      ) {
        window.CaesarCart.close({ restoreFocus: false });
      }
    }

    function setOpen(isOpen, options) {
      if (!panel || !launcher) {
        return;
      }

      window.clearTimeout(closeTimer);
      launcher.setAttribute("aria-expanded", String(isOpen));
      document.body.classList.toggle(LOCK_CLASS, isOpen);

      if (isOpen) {
        closeCartBeforeAssistantOpen();
        syncInitialGreetingLanguage();
        panel.hidden = false;
        root.classList.add("is-mounted");

        window.requestAnimationFrame(function () {
          root.classList.add("is-open");
          resizeInput();

          if (modalManager) {
            modalManager.open(panel, {
              root: root,
              container: root.parentElement || document.body,
              opener: launcher,
              returnFocusTo: launcher,
              initialFocus: getVisibleInput,
              exemptElements: getCartExemptElements(),
              requestClose: function () {
                setOpen(false);
              },
            });
          } else {
            focusVisibleInput();
          }

          scrollMessagesToBottom(true);

          window.setTimeout(resizeInput, 80);
        });
        return;
      }

      if (modalManager) {
        modalManager.close(root, options);
      }

      root.classList.remove("is-open");
      closeTimer = window.setTimeout(function () {
        panel.hidden = true;
        root.classList.remove("is-mounted");
      }, 260);
    }

    window.CaesarAiAssistant = window.CaesarAiAssistant || {};
    window.CaesarAiAssistant.open = function () {
      setOpen(true);
      return true;
    };
    window.CaesarAiAssistant.close = function (options) {
      if (!root.classList.contains("is-open")) {
        return false;
      }

      setOpen(false, options);
      return true;
    };
    window.CaesarAiAssistant.isOpen = function () {
      return root.classList.contains("is-open");
    };

    function renderMessages() {
      var previousMessage = null;

      messagesNode.textContent = "";

      state.messages.forEach(function (message) {
        appendDateDividerForMessage(message, previousMessage);
        messagesNode.appendChild(
          createMessageNode(
            message.role,
            message.text,
            message.dishes,
            message.createdAt
          )
        );
        previousMessage = message;
      });

      scrollMessagesToBottom(true);
    }

    function createDateDividerNode(createdAt) {
      var divider = document.createElement("div");
      var time = document.createElement("time");

      divider.className = "ai-assistant__date-divider";
      time.dateTime = createdAt;
      time.textContent = formatDateLabel(createdAt);
      divider.appendChild(time);

      return divider;
    }

    function appendDateDividerForMessage(message, previousMessage) {
      var dateKey = getLocalDateKey(message && message.createdAt);
      var previousDateKey = getLocalDateKey(previousMessage && previousMessage.createdAt);

      if (!dateKey || dateKey === previousDateKey) {
        return;
      }

      messagesNode.appendChild(createDateDividerNode(message.createdAt));
    }

    function stripSimpleMarkdown(text) {
      return String(text || "")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/__([^_]+)__/g, "$1")
        .trim();
    }

    function createMessageTimeNode(createdAt) {
      var timeText = formatMessageTime(createdAt);
      var timeNode;

      if (!timeText) {
        return null;
      }

      timeNode = document.createElement("time");
      timeNode.className = "ai-assistant__message-time";
      timeNode.dateTime = createdAt;
      timeNode.textContent = timeText;

      return timeNode;
    }

    function createCartIconNode() {
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      var use = document.createElementNS("http://www.w3.org/2000/svg", "use");

      svg.setAttribute("class", "dish-price-button__icon");
      svg.setAttribute("aria-hidden", "true");
      use.setAttribute("href", "#i-cart");
      svg.appendChild(use);

      return svg;
    }

    function refreshCartControlsSoon() {
      window.requestAnimationFrame(function () {
        if (window.CaesarCart && window.CaesarCart.refreshControls) {
          window.CaesarCart.refreshControls();
        }
      });
    }

    function createMessageNode(role, text, dishes, createdAt) {
      var article = document.createElement("article");
      var textNode = document.createElement("div");
      var timeNode = createMessageTimeNode(createdAt);

      article.className = "ai-assistant__message ai-assistant__message--" + role;
      textNode.className = "ai-assistant__message-text";
      textNode.textContent = stripSimpleMarkdown(text);
      article.appendChild(textNode);

      if (timeNode) {
        article.appendChild(timeNode);
      }

      if (role === "assistant" && dishes && dishes.length) {
        article.appendChild(createDishCardsNode(dishes));
      }

      return article;
    }

    function appendLiveAssistantMessage(text, dishes, createdAt) {
      var article = document.createElement("article");
      var textNode = document.createElement("div");
      var timeNode = createMessageTimeNode(createdAt);
      var cleanText = stripSimpleMarkdown(text);
      var index = 0;

      article.className = "ai-assistant__message ai-assistant__message--assistant";
      textNode.className = "ai-assistant__message-text";
      article.appendChild(textNode);

      if (timeNode) {
        article.appendChild(timeNode);
      }

      messagesNode.appendChild(article);

      function tick() {
        index = Math.min(index + 2, cleanText.length);
        textNode.textContent = cleanText.slice(0, index);
        preservePausedScrollPosition();
        scrollMessagesToBottom();

        if (index < cleanText.length) {
          window.setTimeout(tick, TYPEWRITER_STEP_MS);
          return;
        }

        if (dishes && dishes.length) {
          article.appendChild(createDishCardsNode(dishes));
          preservePausedScrollPosition();
          scrollMessagesToBottom();
        }
      }

      tick();
    }

    function createDishCardsNode(dishes) {
      var list = document.createElement("div");

      list.className = "ai-assistant__dish-list";

      dishes.forEach(function (dish) {
        var card = document.createElement("article");
        var link = document.createElement("a");
        var media = document.createElement("span");
        var body = document.createElement("span");
        var title = document.createElement("strong");
        var meta = document.createElement("span");
        var description = document.createElement("span");
        var cartControl = document.createElement("div");
        var addButton = document.createElement("button");
        var price = document.createElement("strong");
        var stepper = document.createElement("div");
        var decreaseButton = document.createElement("button");
        var count = document.createElement("span");
        var increaseButton = document.createElement("button");
        var cartId = dish.cartId || ("dish-" + dish.id);

        card.className = "ai-assistant__dish-card-wrap";
        link.className = "ai-assistant__dish-card";
        link.href = dish.url;
        link.setAttribute("data-ai-dish-link", "");

        media.className = "ai-assistant__dish-media";

        if (dish.imageUrl) {
          var image = document.createElement("img");
          image.src = dish.imageUrl;
          image.alt = "";
          image.loading = "lazy";
          media.appendChild(image);
        } else {
          media.textContent = dish.name.charAt(0);
        }

        body.className = "ai-assistant__dish-body";
        title.textContent = dish.name;

        meta.className = "ai-assistant__dish-meta";
        meta.textContent = [dish.category, dish.price ? dish.price + " ₽" : ""]
          .filter(Boolean)
          .join(" · ");

        description.className = "ai-assistant__dish-description";
        description.textContent = dish.description || t("openDish");

        body.appendChild(title);

        if (meta.textContent) {
          body.appendChild(meta);
        }

        body.appendChild(description);
        link.appendChild(media);
        link.appendChild(body);
        card.appendChild(link);

        if (dish.price) {
          cartControl.className = "dish-cart-control ai-assistant__dish-cart-control";
          cartControl.dataset.id = cartId;
          cartControl.dataset.name = dish.name;
          cartControl.dataset.nameRu = dish.name;
          cartControl.dataset.nameEn = dish.name;
          cartControl.dataset.nameTr = dish.name;
          cartControl.dataset.price = dish.price;
          cartControl.setAttribute("data-dish-cart-control", "");

          addButton.className = "dish-price-button ai-assistant__dish-price-button";
          addButton.type = "button";
          addButton.setAttribute("data-add-btn", "");
          addButton.dataset.id = cartId;
          addButton.dataset.name = dish.name;
          addButton.dataset.nameRu = dish.name;
          addButton.dataset.nameEn = dish.name;
          addButton.dataset.nameTr = dish.name;
          addButton.dataset.price = dish.price;
          addButton.setAttribute("aria-label", t("add") + ": " + dish.name);
          price.textContent = dish.price + " ₽";
          addButton.appendChild(createCartIconNode());
          addButton.appendChild(price);

          stepper.className = "dish-qty-stepper ai-assistant__dish-qty-stepper";
          stepper.setAttribute("data-dish-qty-stepper", "");
          stepper.hidden = true;

          decreaseButton.className = "dish-qty-stepper__btn";
          decreaseButton.type = "button";
          decreaseButton.textContent = "−";
          decreaseButton.dataset.dishQtyAction = "dec";
          decreaseButton.dataset.id = cartId;
          decreaseButton.setAttribute("aria-label", "Уменьшить количество");

          count.className = "dish-qty-stepper__count";
          count.setAttribute("data-dish-qty-count", "");
          count.setAttribute("aria-live", "polite");
          count.textContent = "0";

          increaseButton.className = "dish-qty-stepper__btn";
          increaseButton.type = "button";
          increaseButton.textContent = "+";
          increaseButton.dataset.dishQtyAction = "inc";
          increaseButton.dataset.id = cartId;
          increaseButton.setAttribute("aria-label", "Увеличить количество");

          stepper.appendChild(decreaseButton);
          stepper.appendChild(count);
          stepper.appendChild(increaseButton);
          cartControl.appendChild(addButton);
          cartControl.appendChild(stepper);
          card.appendChild(cartControl);
        }

        list.appendChild(card);
      });

      refreshCartControlsSoon();
      return list;
    }

    function createTypingNode() {
      var article = document.createElement("article");
      var dots = document.createElement("span");

      article.className = "ai-assistant__message ai-assistant__message--assistant";
      dots.className = "ai-assistant__typing";
      dots.setAttribute("aria-label", t("typing"));

      for (var index = 0; index < 3; index += 1) {
        dots.appendChild(document.createElement("span"));
      }

      article.appendChild(dots);
      return article;
    }

    function addMessage(role, text, dishes, createdAt) {
      var previousMessage = state.messages[state.messages.length - 1] || null;
      var message = {
        role: role,
        text: stripSimpleMarkdown(text),
        dishes: normalizeDishes(dishes),
        createdAt: normalizeTimestamp(createdAt) || new Date().toISOString(),
      };

      state.messages.push(message);
      writeState();

      appendDateDividerForMessage(message, previousMessage);

      if (message.role === "assistant") {
        appendLiveAssistantMessage(message.text, message.dishes, message.createdAt);
      } else {
        messagesNode.appendChild(
          createMessageNode(
            message.role,
            message.text,
            message.dishes,
            message.createdAt
          )
        );
      }

      scrollMessagesToBottom(true);
    }

    function addError(text) {
      var message = {
        createdAt: new Date().toISOString(),
      };
      var previousMessage = state.messages[state.messages.length - 1] || null;

      appendDateDividerForMessage(message, previousMessage);
      messagesNode.appendChild(
        createMessageNode("error", text, [], message.createdAt)
      );
      scrollMessagesToBottom(true);
    }

    function pauseAutoScroll() {
      shouldAutoScroll = false;

      if (isBusy) {
        userPausedAutoScroll = true;
        pausedScrollTop = messagesNode.scrollTop;
      }
    }

    function markUserScrollIntent() {
      userScrollIntentUntil = Date.now() + 300;
    }

    function hasRecentUserScrollIntent() {
      return Date.now() <= userScrollIntentUntil;
    }

    function preservePausedScrollPosition() {
      if (!userPausedAutoScroll) {
        return;
      }

      window.requestAnimationFrame(function () {
        if (!userPausedAutoScroll) {
          return;
        }

        isRestoringPausedScroll = true;
        messagesNode.scrollTop = pausedScrollTop;
        lastScrollTop = messagesNode.scrollTop;
      });
    }

    function getDistanceFromMessagesBottom() {
      return (
        messagesNode.scrollHeight -
        messagesNode.scrollTop -
        messagesNode.clientHeight
      );
    }

    function isMessagesAtBottom() {
      return getDistanceFromMessagesBottom() <= 1;
    }

    function isMessagesNearBottom(threshold) {
      return getDistanceFromMessagesBottom() < (threshold === undefined ? 72 : threshold);
    }

    function scrollMessagesToBottom(force) {
      if (force && !isBusy) {
        userPausedAutoScroll = false;
        isRestoringPausedScroll = false;
      }

      if (userPausedAutoScroll) {
        preservePausedScrollPosition();
        return;
      }

      if (force) {
        shouldAutoScroll = true;
      }

      if (!shouldAutoScroll) {
        return;
      }

      window.requestAnimationFrame(function () {
        if (!shouldAutoScroll || userPausedAutoScroll) {
          return;
        }

        messagesNode.scrollTop = messagesNode.scrollHeight;
        lastScrollTop = messagesNode.scrollTop;
      });
    }

    function setBusy(nextBusy) {
      if (nextBusy) {
        userPausedAutoScroll = false;
        isRestoringPausedScroll = false;
      } else if (isMessagesAtBottom()) {
        userPausedAutoScroll = false;
        isRestoringPausedScroll = false;
      }

      isBusy = nextBusy;
      inputs.forEach(function (input) {
        input.disabled = nextBusy;
      });
      sendButton.disabled = nextBusy;
      messagesNode.setAttribute("aria-busy", String(nextBusy));

      if (resetButton) {
        resetButton.disabled = nextBusy;
      }
    }

    function resizeInput() {
      inputs.forEach(function (input) {
        if (input.offsetParent === null) {
          return;
        }

        input.style.height = "auto";
        input.style.height = Math.min(Math.max(input.scrollHeight, 56), 124) + "px";
      });
    }

    function sendCurrentPrompt() {
      var activeInput = getVisibleInput();
      var prompt = activeInput ? activeInput.value.trim() : "";

      if (!prompt || isBusy) {
        return;
      }

      hasUserInteracted = true;
      userPausedAutoScroll = false;
      isRestoringPausedScroll = false;
      shouldAutoScroll = true;
      inputs.forEach(function (input) {
        input.value = "";
      });
      resizeInput();
      addMessage("user", prompt, []);
      sendPrompt(prompt, true);
    }

    function updateLatestUserMessageTimestamp(createdAt) {
      var normalized = normalizeTimestamp(createdAt);
      var index;

      if (!normalized) {
        return;
      }

      for (index = state.messages.length - 1; index >= 0; index -= 1) {
        if (state.messages[index].role === "user") {
          state.messages[index].createdAt = normalized;
          writeState();
          return;
        }
      }
    }

    function createStreamingMessageNode(createdAt) {
      var article = document.createElement("article");
      var textNode = document.createElement("div");
      var messageCreatedAt = normalizeTimestamp(createdAt) || new Date().toISOString();
      var timeNode = createMessageTimeNode(messageCreatedAt);
      var text = "";
      var displayedText = "";
      var queuedText = "";
      var isTyping = false;
      var isFinished = false;
      var finishedDishes = [];
      var isSaved = false;

      article.className = "ai-assistant__message ai-assistant__message--assistant";
      textNode.className = "ai-assistant__message-text";
      article.appendChild(textNode);

      if (timeNode) {
        article.appendChild(timeNode);
      }

      function setMessageCreatedAt(value) {
        var normalized = normalizeTimestamp(value);

        if (!normalized || !timeNode) {
          return;
        }

        messageCreatedAt = normalized;
        timeNode.dateTime = normalized;
        timeNode.textContent = formatMessageTime(normalized);
      }

      function saveMessageWhenReady() {
        var message;

        if (isSaved || !isFinished || isTyping || queuedText) {
          return;
        }

        if (finishedDishes.length) {
          article.appendChild(createDishCardsNode(finishedDishes));
          preservePausedScrollPosition();
        }

        message = {
          role: "assistant",
          text: stripSimpleMarkdown(text),
          dishes: finishedDishes,
          createdAt: messageCreatedAt,
        };

        state.messages.push(message);
        writeState();
        scrollMessagesToBottom();
        isSaved = true;
      }

      function typeNextCharacter() {
        if (!queuedText) {
          isTyping = false;
          saveMessageWhenReady();
          return;
        }

        isTyping = true;
        displayedText += queuedText.charAt(0);
        queuedText = queuedText.slice(1);
        textNode.textContent = stripSimpleMarkdown(displayedText);
        preservePausedScrollPosition();
        scrollMessagesToBottom();
        window.setTimeout(typeNextCharacter, TYPEWRITER_STEP_MS);
      }

      return {
        node: article,
        createdAt: messageCreatedAt,
        append: function (delta) {
          text += delta;
          queuedText += delta;

          if (!isTyping) {
            typeNextCharacter();
          }
        },
        finish: function (dishes, createdAt) {
          setMessageCreatedAt(createdAt);
          isFinished = true;
          finishedDishes = normalizeDishes(dishes);
          saveMessageWhenReady();
        },
      };
    }

    function parseStreamLine(line) {
      if (!line.trim()) {
        return null;
      }

      try {
        return JSON.parse(line);
      } catch (error) {
        return null;
      }
    }

    function readStreamingResponse(response, typingNode) {
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var liveMessage = null;

      function handleEvent(event) {
        if (!event || !event.type) {
          return;
        }

        if (event.type === "session") {
          state.sessionId = event.session_id || state.sessionId;
          state.isNewChat = false;
          updateLatestUserMessageTimestamp(event.user_message_created_at);
          writeState();
          return;
        }

        if (event.type === "delta") {
          if (!liveMessage) {
            typingNode.remove();
            liveMessage = createStreamingMessageNode();
            appendDateDividerForMessage(
              {
                createdAt: liveMessage.createdAt,
              },
              state.messages[state.messages.length - 1] || null
            );
            messagesNode.appendChild(liveMessage.node);
          }

          liveMessage.append(event.text || "");
          return;
        }

        if (event.type === "done") {
          state.sessionId = event.session_id || state.sessionId;
          state.isNewChat = false;

          if (liveMessage) {
            liveMessage.finish(event.recommended_dishes || [], event.created_at);
          } else {
            typingNode.remove();
          }

          writeState();
          return;
        }

        if (event.type === "error") {
          typingNode.remove();
          addError(event.error || t("requestFailed"));
        }
      }

      function pump() {
        return reader.read().then(function (result) {
          var lines;

          if (result.done) {
            if (buffer) {
              handleEvent(parseStreamLine(buffer));
            }

            if (!liveMessage) {
              typingNode.remove();
            }

            return;
          }

          buffer += decoder.decode(result.value, { stream: true });
          lines = buffer.split("\n");
          buffer = lines.pop() || "";

          lines.forEach(function (line) {
            handleEvent(parseStreamLine(line));
          });

          return pump();
        });
      }

      return pump();
    }

    function sendPrompt(prompt, canRetryWithoutSession) {
      var typingNode = createTypingNode();
      var payload = {
        prompt: prompt,
        language: getCurrentLanguage(),
      };
      var controller = window.AbortController ? new AbortController() : null;
      var timeout = window.setTimeout(function () {
        if (controller) {
          controller.abort();
        }
      }, REQUEST_TIMEOUT_MS);

      if (restaurantSlug) {
        payload.restaurant_slug = restaurantSlug;
      }

      if (tableToken) {
        payload.table_token = tableToken;
      }

      if (state.sessionId) {
        payload.session_id = state.sessionId;
      }

      setBusy(true);
      messagesNode.appendChild(typingNode);
      scrollMessagesToBottom(true);

      return window.fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/x-ndjson",
          "X-AI-Stream": "1",
          "X-CSRFToken": csrfInput ? csrfInput.value : "",
          "X-Requested-With": "XMLHttpRequest",
        },
        signal: controller ? controller.signal : undefined,
        body: JSON.stringify(payload),
      })
        .then(function (response) {
          var contentType = response.headers.get("Content-Type") || "";

          if (
            response.ok &&
            response.body &&
            contentType.indexOf("application/x-ndjson") !== -1
          ) {
            return readStreamingResponse(response, typingNode).then(function () {
              return null;
            });
          }

          return response.json()
            .catch(function () {
              return {};
            })
            .then(function (data) {
              return {
                ok: response.ok,
                status: response.status,
                data: data,
              };
            });
        })
        .then(function (result) {
          if (!result) {
            return;
          }

          typingNode.remove();

          if (
            result.status === 404 &&
            state.sessionId &&
            canRetryWithoutSession
          ) {
            state.sessionId = null;
            writeState();
            return sendPrompt(prompt, false);
          }

          state.sessionId = result.data.session_id || state.sessionId;
          state.isNewChat = false;
          updateLatestUserMessageTimestamp(result.data.user_message_created_at);
          writeState();

          if (!result.ok) {
            addError(
              result.data.error ||
              t("requestFailed")
            );
            return;
          }

          addMessage(
            "assistant",
            result.data.answer || t("noResponse"),
            result.data.recommended_dishes || [],
            result.data.created_at
          );
        })
        .catch(function (error) {
          typingNode.remove();

          if (error && error.name === "AbortError") {
            addError(t("timeout"));
            return;
          }

          addError(t("connection"));
        })
        .finally(function () {
          window.clearTimeout(timeout);
          setBusy(false);
          resizeInput();
          focusVisibleInput();
        });
    }
  }
})();
