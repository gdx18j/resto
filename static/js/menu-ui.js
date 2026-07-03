(function () {
  var shell = document.querySelector(".app-shell");
  var orderingEnabled = shell ? shell.dataset.orderingEnabled === "1" : false;
  var search = document.querySelector(".search-section");
  var categoryStrip = document.querySelector(".category-strip");
  var searchInputs = Array.prototype.slice.call(
    document.querySelectorAll(".menu-search-input")
  );
  var dishCards = Array.prototype.slice.call(
    document.querySelectorAll(".dish-card")
  );
  var menuSections = Array.prototype.slice.call(
    document.querySelectorAll(".menu-section")
  );
  var emptyState = document.querySelector(".menu-search-empty");
  var searchStatus = document.querySelector(".menu-search-count");
  var clearButton = document.querySelector(".search-clear-button");
  var categoryLinks = Array.prototype.slice.call(
    document.querySelectorAll(".category-chip")
  );
  var dishModal = document.querySelector("[data-dish-modal]");
  var dishModalContent = dishModal
    ? dishModal.querySelector("[data-dish-modal-content]")
    : null;
  var dishModalShell = dishModal
    ? dishModal.querySelector(".dish-detail-shell")
    : null;
  var modalManager = window.CaesarModal || null;
  var dishDetails = Object.create(null);
  var dishDetailRequests = Object.create(null);
  var activeDetailRequest = 0;
  var lastDishTrigger = null;
  var lastDishCard = null;
  var searchDebounceTimer = null;

  if (!shell || !search) {
    return;
  }

  if (categoryStrip) {
    categoryStrip.scrollLeft = 0;
  }

  var searchDebounceDelay = 140;
  var activeQuery = "";
  var totalDishes = dishCards.length;

  dishCards.forEach(function (card, index) {
    card.dataset.searchIndex = String(index);
  });

  var translations = {
    ru: {
      found: "Найдено",
      dishOne: "блюдо",
      dishFew: "блюда",
      dishMany: "блюд",
      addToCart: "Добавить в корзину: ",
      increaseItem: "Добавить ещё: ",
      decreaseItem: "Убрать одно: ",
    },
    en: {
      found: "Found",
      dishOne: "dish",
      dishFew: "dishes",
      dishMany: "dishes",
      addToCart: "Add to cart: ",
      increaseItem: "Add one more: ",
      decreaseItem: "Remove one: ",
    },
    tr: {
      found: "Bulundu",
      dishOne: "yemek",
      dishFew: "yemek",
      dishMany: "yemek",
      addToCart: "Sepete ekle: ",
      increaseItem: "Bir tane daha ekle: ",
      decreaseItem: "Bir tane çıkar: ",
    },
  };
  var ruLayout = "йцукенгшщзхъфывапролджэячсмитьбю";
  var enLayout = "qwertyuiop[]asdfghjkl;'zxcvbnm,.";
  var layoutMap = {};

  ruLayout.split("").forEach(function (char, index) {
    layoutMap[char] = enLayout[index];
    layoutMap[enLayout[index]] = char;
  });
  layoutMap.ё = "`";
  layoutMap["`"] = "ё";
  var ruToLatinMap = {
    а: "a",
    б: "b",
    в: "v",
    г: "g",
    д: "d",
    е: "e",
    ж: "zh",
    з: "z",
    и: "i",
    й: "i",
    к: "k",
    л: "l",
    м: "m",
    н: "n",
    о: "o",
    п: "p",
    р: "r",
    с: "s",
    т: "t",
    у: "u",
    ф: "f",
    х: "h",
    ц: "c",
    ч: "ch",
    ш: "sh",
    щ: "sh",
    ы: "y",
    э: "e",
    ю: "yu",
    я: "ya",
    ь: "",
    ъ: "",
  };

  function currentLanguage() {
    var language = document.documentElement.dataset.language || document.documentElement.lang || "ru";
    return translations[language] ? language : "ru";
  }

  function t(key) {
    var language = currentLanguage();
    return translations[language][key] || translations.ru[key] || "";
  }

  function localizedDishName(dish) {
    var language = currentLanguage();
    var names = dish && dish.names ? dish.names : {};

    return names[language] || (dish && dish.name) || names.ru || "";
  }

  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");

    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }

    return "";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }

  function langSpans(values) {
    values = values || {};

    return ["ru", "en", "tr"].map(function (language) {
      return '<span class="lang lang--' + language + '">'
        + escapeHtml(values[language] || values.ru || values.en || values.tr || "")
        + "</span>";
    }).join("");
  }

  function unitSpans(ru, en, tr) {
    return langSpans({ ru: ru, en: en, tr: tr });
  }

  function detailLabel(key) {
    var labels = {
      kicker: {
        ru: "Описание блюда",
        en: "Dish details",
        tr: "Yemek detayı",
      },
      weight: {
        ru: "Вес",
        en: "Weight",
        tr: "Ağırlık",
      },
      time: {
        ru: "Время",
        en: "Time",
        tr: "Süre",
      },
      nutrition: {
        ru: "КБЖУ на порцию",
        en: "Nutrition per serving",
        tr: "Porsiyon besin değeri",
      },
      calories: {
        ru: "Калории",
        en: "Calories",
        tr: "Kalori",
      },
      proteins: {
        ru: "Белки",
        en: "Protein",
        tr: "Protein",
      },
      fats: {
        ru: "Жиры",
        en: "Fat",
        tr: "Yağ",
      },
      carbs: {
        ru: "Углеводы",
        en: "Carbs",
        tr: "Karbonhidrat",
      },
      estimated: {
        ru: "КБЖУ указано ориентировочно. Точные значения можно уточнить у ресторана.",
        en: "Nutrition values are approximate. Exact values can be confirmed with the restaurant.",
        tr: "Besin değerleri yaklaşık verilmiştir. Kesin değerler restoranla teyit edilebilir.",
      },
      ingredients: {
        ru: "Состав",
        en: "Ingredients",
        tr: "İçindekiler",
      },
      andMore: {
        ru: "и другое",
        en: "and more",
        tr: "ve fazlası",
      },
      allergens: {
        ru: "Аллергены",
        en: "Allergens",
        tr: "Alerjenler",
      },
      containsAllergens: {
        ru: "Содержит",
        en: "Contains",
        tr: "İçerir",
      },
      mayContainAllergens: {
        ru: "Может содержать следы",
        en: "May contain traces",
        tr: "İz içerebilir",
      },
      traceAllergens: {
        ru: "Возможны следы",
        en: "Possible traces",
        tr: "İz bulunabilir",
      },
      unknownAllergens: {
        ru: "Информация уточняется",
        en: "Information is being verified",
        tr: "Bilgi doğrulanıyor",
      },
      allergenStatusComplete: {
        ru: "Информация проверена для текущего рецепта.",
        en: "The information is verified for the current recipe.",
        tr: "Bilgiler mevcut tarif için doğrulanmıştır.",
      },
      allergenStatusNeedsReview: {
        ru: "Рецепт изменён или есть сведения, ожидающие проверки. При сильной аллергии уточните состав у персонала.",
        en: "The recipe changed or some information is awaiting review. For severe allergies, confirm the ingredients with staff.",
        tr: "Tarif değişti veya bazı bilgiler inceleme bekliyor. Şiddetli alerjilerde içeriği personelle doğrulayın.",
      },
      allergenStatusPartial: {
        ru: "Подтверждена только часть аллергенной информации. При сильной аллергии уточните состав у персонала.",
        en: "Only part of the allergen information is verified. For severe allergies, confirm the ingredients with staff.",
        tr: "Alerjen bilgilerinin yalnızca bir kısmı doğrulanmıştır. Şiddetli alerjilerde içeriği personelle doğrulayın.",
      },
      allergenStatusUnknown: {
        ru: "Аллергенная информация ещё не проверена полностью. Уточните состав у персонала.",
        en: "The allergen information has not been fully verified yet. Confirm the ingredients with staff.",
        tr: "Alerjen bilgileri henüz tamamen doğrulanmamıştır. İçeriği personelle doğrulayın.",
      },
      loading: {
        ru: "Загружаем описание блюда…",
        en: "Loading dish details…",
        tr: "Yemek detayları yükleniyor…",
      },
      loadError: {
        ru: "Не удалось загрузить описание. Проверьте соединение и попробуйте снова.",
        en: "The details could not be loaded. Check your connection and try again.",
        tr: "Detaylar yüklenemedi. Bağlantınızı kontrol edip tekrar deneyin.",
      },
      retry: {
        ru: "Повторить",
        en: "Try again",
        tr: "Tekrar dene",
      },
      add: {
        ru: "Добавить",
        en: "Add",
        tr: "Ekle",
      },
    };

    return langSpans(labels[key]);
  }

  function nutritionItem(labelKey, value, unitHtml) {
    if (value == null || value === "") {
      return "";
    }

    return [
      "<span>",
      "<small>", detailLabel(labelKey), "</small>",
      "<strong>", escapeHtml(value), unitHtml || "", "</strong>",
      "</span>",
    ].join("");
  }

  function buildDishPurchaseHtml(dish) {
    if (!orderingEnabled) {
      return [
        '<div class="dish-cart-control dish-cart-control--detail">',
        '<span class="dish-price-label dish-price-label--detail">',
        '<strong>', escapeHtml(dish.price), ' ₽</strong>',
        '</span>',
        '</div>',
      ].join("");
    }

    return [
      '<div class="dish-cart-control dish-cart-control--detail"',
      ' data-id="', escapeAttr(dish.cart_id), '"',
      ' data-name="', escapeAttr(dish.name), '"',
      ' data-name-ru="', escapeAttr(dish.names && dish.names.ru), '"',
      ' data-name-en="', escapeAttr(dish.names && dish.names.en), '"',
      ' data-name-tr="', escapeAttr(dish.names && dish.names.tr), '"',
      ' data-price="', escapeAttr(dish.price), '"',
      ' data-dish-cart-control>',
      '<button class="dish-detail__add" type="button" data-add-btn',
      ' data-id="', escapeAttr(dish.cart_id), '"',
      ' data-name="', escapeAttr(dish.name), '"',
      ' data-name-ru="', escapeAttr(dish.names && dish.names.ru), '"',
      ' data-name-en="', escapeAttr(dish.names && dish.names.en), '"',
      ' data-name-tr="', escapeAttr(dish.names && dish.names.tr), '"',
      ' data-price="', escapeAttr(dish.price), '"',
      ' aria-label="', escapeAttr(t("addToCart") + localizedDishName(dish)), '">',
      detailLabel("add"),
      '<svg class="dish-price-button__icon" aria-hidden="true"><use href="#i-cart"/></svg>',
      '<strong>', escapeHtml(dish.price), ' ₽</strong>',
      '</button>',
      '<div class="dish-qty-stepper dish-qty-stepper--detail" data-dish-qty-stepper hidden>',
      '<button class="dish-qty-stepper__btn" type="button" data-dish-qty-action="dec"',
      ' data-id="', escapeAttr(dish.cart_id), '" aria-label="', escapeAttr(t("decreaseItem") + localizedDishName(dish)), '">−</button>',
      '<span class="dish-qty-stepper__count" data-dish-qty-count aria-live="polite">0</span>',
      '<button class="dish-qty-stepper__btn" type="button" data-dish-qty-action="inc"',
      ' data-id="', escapeAttr(dish.cart_id), '" aria-label="', escapeAttr(t("increaseItem") + localizedDishName(dish)), '">+</button>',
      '</div>',
      '</div>',
    ].join("");
  }

  function buildDishDetailHtml(dish) {
    var nutrition = dish.nutrition || {};
    var facts = [];
    var nutritionItems = [];
    var ingredientsHtml = "";
    var allergensHtml = "";
    var mediaHtml;
    var hasNutrition;

    if (dish.serving_weight_g) {
      facts.push([
        "<span>",
        "<small>", detailLabel("weight"), "</small>",
        "<strong>",
        escapeHtml(dish.serving_weight_g),
        unitSpans(" г", " g", " g"),
        "</strong>",
        "</span>",
      ].join(""));
    }

    if (dish.preparation_time_minutes) {
      facts.push([
        "<span>",
        "<small>", detailLabel("time"), "</small>",
        "<strong>",
        escapeHtml(dish.preparation_time_minutes),
        unitSpans(" мин", " min", " dk"),
        "</strong>",
        "</span>",
      ].join(""));
    }

    nutritionItems.push(
      nutritionItem(
        "calories",
        dish.calories_kcal_per_serving,
        unitSpans(" ккал", " kcal", " kcal")
      )
    );
    nutritionItems.push(nutritionItem("proteins", nutrition.proteins_g, " г"));
    nutritionItems.push(nutritionItem("fats", nutrition.fats_g, " г"));
    nutritionItems.push(nutritionItem("carbs", nutrition.carbohydrates_g, " г"));
    nutritionItems = nutritionItems.filter(Boolean);
    hasNutrition = nutritionItems.length > 0;

    if (dish.image_url) {
      mediaHtml = [
        '<div class="dish-detail__media">',
        '<img src="', escapeAttr(dish.image_url), '" alt="" width="960" height="720" decoding="async">',
        "</div>",
      ].join("");
    } else {
      mediaHtml = [
        '<div class="dish-detail__media dish-detail__media--placeholder">',
        '<span class="dish-placeholder">', escapeHtml(dish.placeholder), "</span>",
        "</div>",
      ].join("");
    }

    if (Array.isArray(dish.ingredients) && dish.ingredients.length) {
      ingredientsHtml = [
        '<section class="dish-detail__section">',
        "<h3>", detailLabel("ingredients"), "</h3>",
        '<p class="dish-detail__composition">',
        dish.ingredients.map(function (ingredient, index) {
          return '<span>' + escapeHtml(ingredient) + '</span>'
            + (index < dish.ingredients.length - 1 ? '<span class="dish-detail__comma">, </span>' : "");
        }).join(""),
        dish.has_more_ingredients
          ? '<span class="dish-detail__comma">, </span>' + detailLabel("andMore")
          : "",
        "</p>",
        "</section>",
      ].join("");
    }

    (function () {
      var groups = dish.allergen_groups || {};
      var rows = [];

      function addGroup(key, labelKey) {
        var values = Array.isArray(groups[key]) ? groups[key] : [];

        if (!values.length) {
          return;
        }

        rows.push([
          '<span class="dish-detail__allergen-group">',
          '<small>', detailLabel(labelKey), '</small>',
          '<strong>',
          values.map(function (allergen) {
            return '<span>' + langSpans(allergen) + '</span>';
          }).join('<span class="dish-detail__comma">, </span>'),
          '</strong>',
          '</span>',
        ].join(''));
      }

      addGroup("contains", "containsAllergens");
      addGroup("may_contain", "mayContainAllergens");
      addGroup("traces", "traceAllergens");

      if (Array.isArray(groups.unknown) && groups.unknown.length) {
        rows.push([
          '<span class="dish-detail__allergen-group dish-detail__allergen-group--unknown">',
          '<small>', detailLabel("unknownAllergens"), '</small>',
          '<strong>',
          groups.unknown.map(function (allergen) {
            return '<span>' + langSpans(allergen) + '</span>';
          }).join('<span class="dish-detail__comma">, </span>'),
          '</strong>',
          '</span>',
        ].join(''));
      }

      var statusLabels = {
        complete: "allergenStatusComplete",
        needs_review: "allergenStatusNeedsReview",
        partial: "allergenStatusPartial",
        unknown: "allergenStatusUnknown",
      };
      var status = dish.allergen_data_status || "unknown";
      var statusLabel = statusLabels[status] || statusLabels.unknown;
      var statusHtml = [
        '<p class="dish-detail__allergen-status dish-detail__allergen-status--',
        escapeAttr(status),
        '">',
        detailLabel(statusLabel),
        "</p>",
      ].join("");

      allergensHtml = [
        '<section class="dish-detail__section">',
        "<h3>", detailLabel("allergens"), "</h3>",
        statusHtml,
        rows.length
          ? '<div class="dish-detail__allergens">' + rows.join("") + "</div>"
          : "",
        "</section>",
      ].join("");
    })();

    return [
      '<article class="dish-detail">',
      mediaHtml,
      '<div class="dish-detail__body">',
      '<p class="dish-detail__kicker">', detailLabel("kicker"), "</p>",
      '<h2 id="', escapeAttr(dish.title_id), '">', langSpans(dish.names), "</h2>",
      dish.has_description
        ? '<p class="dish-detail__description">' + langSpans(dish.descriptions) + "</p>"
        : "",
      facts.length ? '<div class="dish-detail__facts">' + facts.join("") + "</div>" : "",
      hasNutrition
        ? [
          '<section class="dish-detail__section">',
          "<h3>", detailLabel("nutrition"), "</h3>",
          '<div class="dish-detail__nutrition">', nutritionItems.join(""), "</div>",
          nutrition.is_estimated
            ? '<p class="dish-detail__note">' + detailLabel("estimated") + "</p>"
            : "",
          "</section>",
        ].join("")
        : "",
      ingredientsHtml,
      allergensHtml,
      buildDishPurchaseHtml(dish),
      "</div>",
      "</div>",
      "</article>",
    ].join("");
  }

  function detailLoadingHtml() {
    return [
      '<section class="dish-detail-state" role="status" aria-live="polite">',
      '<span class="dish-detail-state__spinner" aria-hidden="true"></span>',
      '<h2 id="dish-detail-state-title">', detailLabel("loading"), "</h2>",
      "</section>",
    ].join("");
  }

  function detailErrorHtml() {
    return [
      '<section class="dish-detail-state dish-detail-state--error" role="alert">',
      '<h2 id="dish-detail-state-title">', detailLabel("loadError"), "</h2>",
      '<button class="dish-detail-state__retry" type="button" data-dish-retry>',
      detailLabel("retry"),
      "</button>",
      "</section>",
    ].join("");
  }

  function openDishModal(trigger, contentHtml) {
    if (!dishModal || !dishModalContent) {
      return;
    }

    var wasHidden = dishModal.hidden;
    lastDishTrigger = trigger || lastDishTrigger;
    dishModalContent.innerHTML = contentHtml;
    dishModal.hidden = false;
    dishModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("dish-detail-open");

    var title = dishModalContent.querySelector("h2[id]");
    var closeButton = dishModal.querySelector("[data-dish-close]");

    if (dishModalShell && title) {
      dishModalShell.setAttribute("aria-labelledby", title.id);
    }

    if (!wasHidden) {
      return;
    }

    window.requestAnimationFrame(function () {
      dishModal.classList.add("is-open");

      if (modalManager && dishModalShell) {
        modalManager.open(dishModalShell, {
          root: dishModal,
          container: dishModal.parentElement || document.body,
          opener: lastDishTrigger,
          initialFocus: closeButton || dishModalShell,
          requestClose: closeDishDetails,
        });
      } else if (closeButton) {
        closeButton.focus();
      }
    });
  }

  function loadDishDetails(card) {
    if (!card || !card.id || !card.dataset.detailUrl) {
      return Promise.reject(new Error("Dish detail URL is missing."));
    }

    if (dishDetails[card.id]) {
      return Promise.resolve(dishDetails[card.id]);
    }

    if (dishDetailRequests[card.id]) {
      return dishDetailRequests[card.id];
    }

    dishDetailRequests[card.id] = window.fetch(card.dataset.detailUrl, {
      method: "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
      },
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("Dish detail request failed with status " + response.status + ".");
      }

      return response.json();
    }).then(function (dish) {
      if (!dish || String(dish.cart_id || "") !== card.id) {
        throw new Error("Dish detail response does not match the requested card.");
      }

      dishDetails[card.id] = dish;
      delete dishDetailRequests[card.id];
      return dish;
    }).catch(function (error) {
      delete dishDetailRequests[card.id];
      throw error;
    });

    return dishDetailRequests[card.id];
  }

  function openDishDetails(card, trigger) {
    if (!dishModal || !dishModalContent || !card) {
      return;
    }

    activeDetailRequest += 1;
    var requestNumber = activeDetailRequest;
    lastDishCard = card;
    openDishModal(trigger, detailLoadingHtml());

    loadDishDetails(card).then(function (dish) {
      if (requestNumber !== activeDetailRequest || dishModal.hidden) {
        return;
      }

      openDishModal(trigger, buildDishDetailHtml(dish));
      document.dispatchEvent(new CustomEvent("cc:dishdetailopen"));
    }).catch(function () {
      if (requestNumber !== activeDetailRequest || dishModal.hidden) {
        return;
      }

      openDishModal(trigger, detailErrorHtml());
    });
  }

  function closeDishDetails() {
    if (!dishModal || dishModal.hidden) {
      return;
    }

    activeDetailRequest += 1;

    if (modalManager) {
      modalManager.close(dishModal);
    }

    dishModal.classList.remove("is-open");
    document.body.classList.remove("dish-detail-open");
    dishModal.hidden = true;
    dishModal.setAttribute("aria-hidden", "true");
    dishModalContent.innerHTML = "";

    if (!modalManager && lastDishTrigger) {
      lastDishTrigger.focus();
    }

    lastDishTrigger = null;
    lastDishCard = null;
  }

  function handleDishClick(event) {
    var closeButton = event.target.closest("[data-dish-close]");

    if (closeButton) {
      closeDishDetails();
      return;
    }

    var retryButton = event.target.closest("[data-dish-retry]");

    if (retryButton && lastDishCard) {
      openDishDetails(lastDishCard, lastDishTrigger || retryButton);
      return;
    }

    var openButton = event.target.closest("[data-dish-open]");

    if (!openButton) {
      return;
    }

    var card = openButton.closest("[data-dish-card]");

    if (!card) {
      return;
    }

    event.preventDefault();
    openDishDetails(card, openButton);
  }

  function handleDishKeydown(event) {
    if (event.key === "Escape") {
      closeDishDetails();
    }
  }

  function normalize(value) {
    return (value || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/ё/g, "е")
      .replace(/ı/g, "i")
      .replace(/ğ/g, "g")
      .replace(/ş/g, "s")
      .replace(/ç/g, "c")
      .replace(/[^a-z0-9а-я\s]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function tokenize(value) {
    return normalize(value)
      .split(/\s+/)
      .filter(Boolean);
  }

  function unique(values) {
    var seen = {};

    return values.filter(function (value) {
      if (!value || seen[value]) {
        return false;
      }

      seen[value] = true;
      return true;
    });
  }

  function swapKeyboardLayout(value) {
    return (value || "")
      .toString()
      .toLowerCase()
      .split("")
      .map(function (char) {
        return layoutMap[char] || char;
      })
      .join("");
  }

  function queryVariants(query) {
    var normalized = normalize(query);
    var swapped = normalize(swapKeyboardLayout(query));
    var normalizedTokens = tokenize(normalized);
    var transliterated = normalize(transliterateRuToLatin(normalized));
    var swappedTransliterated = normalize(transliterateRuToLatin(swapped));

    if (
      normalizedTokens.length === 1
      && normalizedTokens[0].length <= 3
      && /[а-я]/.test(normalizedTokens[0])
    ) {
      return unique([normalized, swapped]);
    }

    return unique([normalized, swapped, transliterated, swappedTransliterated]);
  }

  function transliterateRuToLatin(value) {
    return (value || "")
      .toString()
      .split("")
      .map(function (char) {
        return Object.prototype.hasOwnProperty.call(ruToLatinMap, char)
          ? ruToLatinMap[char]
          : char;
      })
      .join("");
  }

  function wordList(value) {
    return tokenize(value).filter(function (token) {
      return token.length > 1;
    });
  }

  function getSearchDoc(card) {
    if (card._searchDoc) {
      return card._searchDoc;
    }

    var name = normalize(card.dataset.searchName);
    var ingredients = normalize(card.dataset.searchIngredients);
    var combined = normalize(card.dataset.searchText);

    card._searchDoc = {
      name: name,
      ingredients: ingredients,
      combined: combined,
      nameWords: wordList(name),
      ingredientWords: wordList(ingredients),
      combinedWords: wordList(combined),
      index: Number(card.dataset.searchIndex) || 0,
    };

    return card._searchDoc;
  }

  function maxDistanceFor(token) {
    if (token.length <= 3) {
      return 0;
    }

    if (token.length <= 5) {
      return 1;
    }

    return 2;
  }

  function boundedDistance(a, b, limit) {
    var i;
    var j;
    var prev;
    var prevPrev;
    var curr;
    var next;
    var minInRow;
    var cost;

    if (a === b) {
      return 0;
    }

    if (Math.abs(a.length - b.length) > limit) {
      return limit + 1;
    }

    prevPrev = null;
    prev = [];
    for (j = 0; j <= b.length; j += 1) {
      prev[j] = j;
    }

    for (i = 1; i <= a.length; i += 1) {
      curr = [i];
      minInRow = curr[0];

      for (j = 1; j <= b.length; j += 1) {
        cost = a.charAt(i - 1) === b.charAt(j - 1) ? 0 : 1;
        next = Math.min(
          prev[j] + 1,
          curr[j - 1] + 1,
          prev[j - 1] + cost
        );

        if (
          prevPrev
          && i > 1
          && j > 1
          && a.charAt(i - 1) === b.charAt(j - 2)
          && a.charAt(i - 2) === b.charAt(j - 1)
        ) {
          next = Math.min(next, prevPrev[j - 2] + 1);
        }

        curr[j] = next;
        minInRow = Math.min(minInRow, next);
      }

      if (minInRow > limit) {
        return limit + 1;
      }

      prevPrev = prev;
      prev = curr;
    }

    return prev[b.length];
  }

  function tokenScore(token, words, phrase) {
    var best = 0;
    var limit = maxDistanceFor(token);

    if (!token) {
      return 0;
    }

    if (phrase.indexOf(token) !== -1) {
      best = Math.max(best, token.length <= 2 ? 70 : 92);
    }

    words.forEach(function (word) {
      var distance;
      var prefix;

      if (word === token) {
        best = Math.max(best, 120);
        return;
      }

      if (word.indexOf(token) === 0) {
        best = Math.max(best, 108);
        return;
      }

      if (word.indexOf(token) !== -1) {
        best = Math.max(best, token.length <= 2 ? 62 : 86);
      }

      if (limit === 0) {
        return;
      }

      distance = boundedDistance(token, word, limit);
      if (distance <= limit) {
        best = Math.max(best, 82 - distance * 14);
      }

      prefix = word.slice(0, Math.min(word.length, token.length));
      distance = boundedDistance(token, prefix, limit);
      if (distance <= limit) {
        best = Math.max(best, 76 - distance * 12);
      }
    });

    return best;
  }

  function scoreField(tokens, words, phrase, weight) {
    var total = 0;

    if (!tokens.length) {
      return 0;
    }

    for (var index = 0; index < tokens.length; index += 1) {
      var score = tokenScore(tokens[index], words, phrase);

      if (score <= 0) {
        return 0;
      }

      total += score;
    }

    return (total / tokens.length) * weight;
  }

  function scoreCardForTokens(card, tokens, phrase) {
    var doc = getSearchDoc(card);
    var nameScore = scoreField(tokens, doc.nameWords, doc.name, 1.28);
    var ingredientScore = scoreField(tokens, doc.ingredientWords, doc.ingredients, 0.96);
    var combinedScore = scoreField(tokens, doc.combinedWords, doc.combined, 0.78);
    var score = Math.max(nameScore, ingredientScore, combinedScore);
    var matchType = "";

    if (!score) {
      return { score: 0, matchType: "" };
    }

    if (nameScore >= ingredientScore && nameScore >= combinedScore) {
      matchType = "name";
    } else if (ingredientScore >= combinedScore) {
      matchType = "ingredients";
    } else {
      matchType = "mixed";
    }

    if (doc.name.indexOf(phrase) !== -1) {
      score += 28;
      matchType = "name";
    } else if (doc.ingredients.indexOf(phrase) !== -1) {
      score += 16;
      matchType = "ingredients";
    }

    return { score: score, matchType: matchType };
  }

  function syncInputs(value, sourceInput) {
    searchInputs.forEach(function (input) {
      if (input !== sourceInput) {
        input.value = value;
      }
    });
  }

  function setCategoryVisibility(section, isVisible) {
    if (!section.id) {
      return;
    }

    categoryLinks.forEach(function (link) {
      if (link.getAttribute("href") === "#" + section.id) {
        link.hidden = !isVisible;
      }
    });
  }

  function searchCard(card, query) {
    var variants = queryVariants(query);
    var best = { score: 0, matchType: "" };

    variants.forEach(function (variant) {
      var tokens = tokenize(variant);
      var result;

      if (!tokens.length) {
        best = { score: 1, matchType: "all" };
        return;
      }

      result = scoreCardForTokens(card, tokens, variant);

      if (result.score > best.score) {
        best = result;
      }
    });

    return best;
  }

  function sortSectionCards(section, hasQuery) {
    var grid = section.querySelector(".dish-grid");
    var cards;

    if (!grid) {
      return;
    }

    cards = Array.prototype.slice.call(grid.querySelectorAll(".dish-card"));
    cards.sort(function (a, b) {
      if (!hasQuery) {
        return getSearchDoc(a).index - getSearchDoc(b).index;
      }

      return (Number(b.dataset.searchScore) || 0) - (Number(a.dataset.searchScore) || 0)
        || getSearchDoc(a).index - getSearchDoc(b).index;
    });

    cards.forEach(function (card) {
      grid.appendChild(card);
    });
  }

  function dishWord(count) {
    if (currentLanguage() !== "ru") {
      return count === 1 ? t("dishOne") : t("dishMany");
    }

    var absCount = Math.abs(count);
    var mod100 = absCount % 100;
    var mod10 = absCount % 10;

    if (mod100 >= 11 && mod100 <= 14) {
      return t("dishMany");
    }

    if (mod10 === 1) {
      return t("dishOne");
    }

    if (mod10 >= 2 && mod10 <= 4) {
      return t("dishFew");
    }

    return t("dishMany");
  }

  function updateSearchStatus(query, visibleTotal) {
    if (searchStatus) {
      if (!query) {
        searchStatus.textContent = "";
      } else {
        searchStatus.textContent = t("found") + " " + visibleTotal + " " + dishWord(visibleTotal);
      }
    }

    if (clearButton) {
      clearButton.hidden = !query;
    }
  }

  function filterMenu(query) {
    var normalizedQuery = normalize(query);
    var hasQuery = normalizedQuery.length > 0;
    var visibleTotal = 0;

    activeQuery = query;

    dishCards.forEach(function (card) {
      if (card.dataset.menuRemoved === "1") {
        card.hidden = true;
        card.dataset.matchType = "";
        card.dataset.searchScore = "0";
        return;
      }

      var result = hasQuery ? searchCard(card, query) : { score: 1, matchType: "all" };
      var isVisible = !hasQuery || result.score > 0;

      card.hidden = !isVisible;
      card.dataset.matchType = result.matchType || "";
      card.dataset.searchScore = String(result.score || 0);

      if (isVisible) {
        visibleTotal += 1;
      }
    });

    menuSections.forEach(function (section) {
      var visibleCards = Array.prototype.slice
        .call(section.querySelectorAll(".dish-card"))
        .filter(function (card) {
          return !card.hidden;
        });
      var isVisible = visibleCards.length > 0;
      var count = section.querySelector(".section-count");

      sortSectionCards(section, hasQuery);
      section.hidden = !isVisible;
      setCategoryVisibility(section, isVisible);

      if (count) {
        count.textContent = visibleCards.length;
      }
    });

    if (emptyState) {
      emptyState.hidden = visibleTotal > 0 || normalizedQuery.length === 0;
    }

    updateSearchStatus(normalizedQuery, visibleTotal);
  }

  function scheduleFilterMenu(value) {
    activeQuery = value;

    if (searchDebounceTimer) {
      window.clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }

    if (!normalize(value)) {
      filterMenu(value);
      return;
    }

    searchDebounceTimer = window.setTimeout(function () {
      searchDebounceTimer = null;
      filterMenu(value);
    }, searchDebounceDelay);
  }

  function setSearchQuery(value) {
    searchInputs.forEach(function (input) {
      input.value = value;
    });

    if (searchDebounceTimer) {
      window.clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }

    filterMenu(value);
  }

  searchInputs.forEach(function (input) {
    input.addEventListener("input", function () {
      syncInputs(input.value, input);
      scheduleFilterMenu(input.value);
    });
  });

  if (clearButton) {
    clearButton.addEventListener("click", function () {
      setSearchQuery("");

      var visibleInput = searchInputs.find(function (input) {
        return window.getComputedStyle(input).display !== "none";
      });

      if (visibleInput) {
        visibleInput.focus();
      }
    });
  }

  window.addEventListener("cc:languagechange", function () {
    if (searchDebounceTimer) {
      window.clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }

    filterMenu(activeQuery);
  });

  document.addEventListener("click", function (event) {
    handleDishClick(event);
  });
  document.addEventListener("keydown", handleDishKeydown);

  updateSearchStatus("", totalDishes);
})();
