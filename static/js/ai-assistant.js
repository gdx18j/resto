(function () {
  var REQUEST_TIMEOUT_MS = 45000;
  var LOCK_CLASS = "ai-assistant-lock";

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
    var input = root.querySelector("[data-ai-input]");
    var sendButton = root.querySelector("[data-ai-send]");
    var messagesNode = root.querySelector("[data-ai-messages]");
    var csrfInput = form ? form.querySelector("[name=csrfmiddlewaretoken]") : null;
    var closeTimer = null;

    if (!endpoint || !form || !input || !sendButton || !messagesNode) {
      return;
    }

    var greeting = (
      "Здравствуйте! Я помогу разобраться в меню, подобрать блюдо, " +
      "проверить ингредиенты и аллергены."
    );

    var state = readState();
    var isBusy = false;

    renderMessages();

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
        input.focus();
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      sendCurrentPrompt();
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendCurrentPrompt();
      }
    });

    input.addEventListener("input", resizeInput);

    messagesNode.addEventListener("click", function (event) {
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

    function createInitialState() {
      return {
        sessionId: null,
        messages: [
          {
            role: "assistant",
            text: greeting,
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
          input.focus();
          scrollMessagesToBottom();

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

      scrollMessagesToBottom();
    }

    function stripSimpleMarkdown(text) {
      return String(text || "")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/__([^_]+)__/g, "$1")
        .trim();
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

    function createDishCardsNode(dishes) {
      var list = document.createElement("div");

      list.className = "ai-assistant__dish-list";

      dishes.forEach(function (dish) {
        var link = document.createElement("a");
        var media = document.createElement("span");
        var body = document.createElement("span");
        var title = document.createElement("strong");
        var meta = document.createElement("span");
        var description = document.createElement("span");

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
        description.textContent = dish.description || "Открыть блюдо в меню";

        body.appendChild(title);

        if (meta.textContent) {
          body.appendChild(meta);
        }

        body.appendChild(description);
        link.appendChild(media);
        link.appendChild(body);
        list.appendChild(link);
      });

      return list;
    }

    function createTypingNode() {
      var article = document.createElement("article");
      var dots = document.createElement("span");

      article.className = "ai-assistant__message ai-assistant__message--assistant";
      dots.className = "ai-assistant__typing";
      dots.setAttribute("aria-label", "Ассистент отвечает");

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
      messagesNode.appendChild(
        createMessageNode(message.role, message.text, message.dishes)
      );
      scrollMessagesToBottom();
    }

    function addError(text) {
      messagesNode.appendChild(createMessageNode("error", text, []));
      scrollMessagesToBottom();
    }

    function scrollMessagesToBottom() {
      window.requestAnimationFrame(function () {
        messagesNode.scrollTop = messagesNode.scrollHeight;
      });
    }

    function setBusy(nextBusy) {
      isBusy = nextBusy;
      input.disabled = nextBusy;
      sendButton.disabled = nextBusy;
      messagesNode.setAttribute("aria-busy", String(nextBusy));

      if (resetButton) {
        resetButton.disabled = nextBusy;
      }
    }

    function resizeInput() {
      if (input.offsetParent === null) {
        return;
      }

      input.style.height = "auto";
      input.style.height = Math.min(Math.max(input.scrollHeight, 56), 124) + "px";
    }

    function sendCurrentPrompt() {
      var prompt = input.value.trim();

      if (!prompt || isBusy) {
        return;
      }

      input.value = "";
      resizeInput();
      addMessage("user", prompt, []);
      sendPrompt(prompt, true);
    }

    function sendPrompt(prompt, canRetryWithoutSession) {
      var typingNode = createTypingNode();
      var payload = {
        prompt: prompt,
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
      scrollMessagesToBottom();

      return window.fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfInput ? csrfInput.value : "",
          "X-Requested-With": "XMLHttpRequest",
        },
        signal: controller ? controller.signal : undefined,
        body: JSON.stringify(payload),
      })
        .then(function (response) {
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
              "Не удалось получить ответ. Попробуйте еще раз."
            );
            return;
          }

          addMessage(
            "assistant",
            result.data.answer || "Я не получил текст ответа.",
            result.data.recommended_dishes || []
          );
        })
        .catch(function (error) {
          typingNode.remove();

          if (error && error.name === "AbortError") {
            addError("Ответ занимает слишком много времени. Попробуйте еще раз.");
            return;
          }

          addError(
            "Не удалось связаться с ассистентом. Проверьте соединение."
          );
        })
        .finally(function () {
          window.clearTimeout(timeout);
          setBusy(false);
          resizeInput();
          input.focus();
        });
    }
  }
})();
