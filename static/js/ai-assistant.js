(function () {
  var REQUEST_TIMEOUT_MS = 120000;
  var LOCK_CLASS = "ai-assistant-lock";
  var TYPEWRITER_STEP_MS = 14;

  var roots = document.querySelectorAll("[data-ai-assistant]");

  Array.prototype.forEach.call(roots, initAssistant);

  function initAssistant(root) {
    var endpoint = root.dataset.endpoint;
    var storageKey = root.dataset.storageKey || "resto.aiAssistant.v3";
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
    var lastTouchY = 0;

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
        connection: "Не удалось связаться с ассистентом. Проверьте соединение."
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
        connection: "Could not reach the assistant. Check your connection."
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
        connection: "Asistana ulaşılamadı. Bağlantınızı kontrol edin."
      }
    };

    var state = readState();
    var isBusy = false;

    renderMessages();

    function getCurrentLanguage() {
      var language = document.documentElement.dataset.language || document.documentElement.lang || "ru";
      return translations[language] ? language : "ru";
    }

    function t(key) {
      var language = getCurrentLanguage();
      return translations[language][key] || translations.ru[key] || "";
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
        state = createInitialState();
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
        if (event.deltaY < 0) {
          shouldAutoScroll = false;
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

        if (currentTouchY - lastTouchY > 2) {
          shouldAutoScroll = false;
        }

        lastTouchY = currentTouchY;
      },
      { passive: true }
    );

    messagesNode.addEventListener(
      "scroll",
      function () {
        shouldAutoScroll = isMessagesNearBottom();
      },
      { passive: true }
    );

    messagesNode.addEventListener("click", function (event) {
      var cartButton = event.target.closest("[data-ai-add-to-cart]");

      if (cartButton) {
        event.preventDefault();
        event.stopPropagation();

        if (window.CaesarCart && window.CaesarCart.addItem) {
          var added = window.CaesarCart.addItem({
            id: cartButton.dataset.cartId,
            name: cartButton.dataset.name,
            price: cartButton.dataset.price,
          });

          if (added) {
            cartButton.classList.add("is-added");
            cartButton.textContent = t("added");

            window.setTimeout(function () {
              cartButton.classList.remove("is-added");
              cartButton.textContent = formatCartButtonText(cartButton.dataset.price);
            }, 1200);
          }
        }

        return;
      }

      var link = event.target.closest("[data-ai-dish-link]");

      if (link) {
        setOpen(false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (
        event.key === "Escape" &&
        panel &&
        root.classList.contains("is-open")
      ) {
        setOpen(false);
      }
    });

    window.addEventListener("cc:languagechange", function () {
      resizeInput();

      if (root.classList.contains("is-open")) {
        focusVisibleInput();
      }
    });

    function createInitialState() {
      return {
        sessionId: null,
        messages: [
          {
            role: "assistant",
            text: t("greeting"),
            dishes: [],
          },
        ],
      };
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
          messages: messages,
        };
      } catch (error) {
        return createInitialState();
      }
    }

    function writeState() {
      try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(state));
      } catch (error) {
        return;
      }
    }

    function setOpen(isOpen) {
      if (!panel || !launcher) {
        return;
      }

      window.clearTimeout(closeTimer);
      launcher.setAttribute("aria-expanded", String(isOpen));
      document.body.classList.toggle(LOCK_CLASS, isOpen);

      if (isOpen) {
        panel.hidden = false;
        root.classList.add("is-mounted");

        window.requestAnimationFrame(function () {
          root.classList.add("is-open");
          resizeInput();
          focusVisibleInput();
          scrollMessagesToBottom(true);

          window.setTimeout(resizeInput, 80);
        });
        return;
      }

      root.classList.remove("is-open");
      closeTimer = window.setTimeout(function () {
        panel.hidden = true;
        root.classList.remove("is-mounted");
      }, 260);
    }

    function renderMessages() {
      messagesNode.textContent = "";

      state.messages.forEach(function (message) {
        messagesNode.appendChild(
          createMessageNode(message.role, message.text, message.dishes)
        );
      });

      scrollMessagesToBottom(true);
    }

    function stripSimpleMarkdown(text) {
      return String(text || "")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/__([^_]+)__/g, "$1")
        .trim();
    }

    function formatCartButtonText(price) {
      return price ? t("add") + " · " + price + " ₽" : t("add");
    }

    function createMessageNode(role, text, dishes) {
      var article = document.createElement("article");
      var textNode = document.createElement("div");

      article.className = "ai-assistant__message ai-assistant__message--" + role;
      textNode.className = "ai-assistant__message-text";
      textNode.textContent = stripSimpleMarkdown(text);
      article.appendChild(textNode);

      if (role === "assistant" && dishes && dishes.length) {
        article.appendChild(createDishCardsNode(dishes));
      }

      return article;
    }

    function appendLiveAssistantMessage(text, dishes) {
      var article = document.createElement("article");
      var textNode = document.createElement("div");
      var cleanText = stripSimpleMarkdown(text);
      var index = 0;

      article.className = "ai-assistant__message ai-assistant__message--assistant";
      textNode.className = "ai-assistant__message-text";
      article.appendChild(textNode);
      messagesNode.appendChild(article);

      function tick() {
        index = Math.min(index + 2, cleanText.length);
        textNode.textContent = cleanText.slice(0, index);
        scrollMessagesToBottom();

        if (index < cleanText.length) {
          window.setTimeout(tick, TYPEWRITER_STEP_MS);
          return;
        }

        if (dishes && dishes.length) {
          article.appendChild(createDishCardsNode(dishes));
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
        var cartButton = document.createElement("button");

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
          cartButton.className = "ai-assistant__cart-button";
          cartButton.type = "button";
          cartButton.textContent = formatCartButtonText(dish.price);
          cartButton.setAttribute("data-ai-add-to-cart", "");
          cartButton.dataset.cartId = dish.cartId || ("dish-" + dish.id);
          cartButton.dataset.name = dish.name;
          cartButton.dataset.price = dish.price;
          card.appendChild(cartButton);
        }

        list.appendChild(card);
      });

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

    function addMessage(role, text, dishes) {
      var message = {
        role: role,
        text: stripSimpleMarkdown(text),
        dishes: normalizeDishes(dishes),
      };

      state.messages.push(message);
      writeState();

      if (message.role === "assistant") {
        appendLiveAssistantMessage(message.text, message.dishes);
      } else {
        messagesNode.appendChild(
          createMessageNode(message.role, message.text, message.dishes)
        );
      }

      scrollMessagesToBottom(true);
    }

    function addError(text) {
      messagesNode.appendChild(createMessageNode("error", text, []));
      scrollMessagesToBottom(true);
    }

    function isMessagesNearBottom() {
      return (
        messagesNode.scrollHeight -
        messagesNode.scrollTop -
        messagesNode.clientHeight
      ) < 72;
    }

    function scrollMessagesToBottom(force) {
      if (force) {
        shouldAutoScroll = true;
      }

      if (!shouldAutoScroll) {
        return;
      }

      window.requestAnimationFrame(function () {
        if (!shouldAutoScroll) {
          return;
        }

        messagesNode.scrollTop = messagesNode.scrollHeight;
      });
    }

    function setBusy(nextBusy) {
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

      inputs.forEach(function (input) {
        input.value = "";
      });
      resizeInput();
      addMessage("user", prompt, []);
      sendPrompt(prompt, true);
    }

    function createStreamingMessageNode() {
      var article = document.createElement("article");
      var textNode = document.createElement("div");
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

      function saveMessageWhenReady() {
        var message;

        if (isSaved || !isFinished || isTyping || queuedText) {
          return;
        }

        if (finishedDishes.length) {
          article.appendChild(createDishCardsNode(finishedDishes));
        }

        message = {
          role: "assistant",
          text: stripSimpleMarkdown(text),
          dishes: finishedDishes,
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
        scrollMessagesToBottom();
        window.setTimeout(typeNextCharacter, TYPEWRITER_STEP_MS);
      }

      return {
        node: article,
        append: function (delta) {
          text += delta;
          queuedText += delta;

          if (!isTyping) {
            typeNextCharacter();
          }
        },
        finish: function (dishes) {
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
          writeState();
          return;
        }

        if (event.type === "delta") {
          if (!liveMessage) {
            typingNode.remove();
            liveMessage = createStreamingMessageNode();
            messagesNode.appendChild(liveMessage.node);
          }

          liveMessage.append(event.text || "");
          return;
        }

        if (event.type === "done") {
          state.sessionId = event.session_id || state.sessionId;

          if (liveMessage) {
            liveMessage.finish(event.recommended_dishes || []);
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
            result.data.recommended_dishes || []
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
