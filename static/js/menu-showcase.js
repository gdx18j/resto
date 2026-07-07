(function () {
  "use strict";

  function closest(target, selector) {
    return target && typeof target.closest === "function"
      ? target.closest(selector)
      : null;
  }

  function setupSeasonalShowcase() {
    var carousels = document.querySelectorAll(".seasonal-menu");
    var desktopQuery = window.matchMedia("(min-width: 620px)");

    Array.prototype.forEach.call(carousels, function (carousel) {
      if (carousel.dataset.seasonalShowcaseReady === "true") {
        return;
      }
      carousel.dataset.seasonalShowcaseReady = "true";

      var track = carousel.querySelector("[data-seasonal-track]");
      var dotsRoot = carousel.querySelector("[data-seasonal-dots]");
      var cards = track
        ? Array.prototype.slice.call(track.querySelectorAll("[data-seasonal-card]"))
        : [];
      var activeIndex = 0;
      var ticking = false;
      var dots = [];
      var startX = 0;
      var startY = 0;
      var wheelLocked = false;
      var autoplayPaused = false;
      var resumeTimer = null;

      carousel.classList.toggle("seasonal-menu--single", cards.length === 1);
      carousel.classList.toggle("seasonal-menu--pair", cards.length === 2);
      carousel.classList.toggle("seasonal-menu--stack", cards.length >= 3);

      if (!track || !dotsRoot || cards.length <= 1) {
        if (dotsRoot) {
          dotsRoot.hidden = true;
        }
        if (cards[0]) {
          cards[0].classList.add("is-active");
          cards[0].setAttribute("aria-hidden", "false");
        }
        return;
      }

      function isDesktopStack() {
        return carousel.classList.contains("seasonal-menu--desktop")
          && cards.length >= 3
          && desktopQuery.matches;
      }

      function normalize(index) {
        return ((index % cards.length) + cards.length) % cards.length;
      }

      function signedDistance(index) {
        var distance = index - activeIndex;

        if (distance > cards.length / 2) {
          distance -= cards.length;
        } else if (distance < -cards.length / 2) {
          distance += cards.length;
        }

        return distance;
      }

      function setActiveDot(nextDot) {
        dots.forEach(function (dot, index) {
          var isActive = index === nextDot;

          dot.classList.toggle("is-active", isActive);
          dot.setAttribute("aria-current", isActive ? "true" : "false");
          dot.setAttribute("aria-selected", isActive ? "true" : "false");
        });
      }

      function clearCardState() {
        cards.forEach(function (card) {
          card.classList.remove(
            "is-active",
            "is-prev",
            "is-next",
            "is-before-prev",
            "is-after-next"
          );
          card.removeAttribute("aria-hidden");
        });
      }

      function nativeClosestIndex() {
        var trackRect = track.getBoundingClientRect();
        var closestIndex = 0;
        var closestDistance = Infinity;

        cards.forEach(function (card, index) {
          var distance = Math.abs(card.getBoundingClientRect().left - trackRect.left);

          if (distance < closestDistance) {
            closestDistance = distance;
            closestIndex = index;
          }
        });

        return closestIndex;
      }

      function scrollToNativeCard(index) {
        var card = cards[index];

        if (card) {
          card.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
            inline: "start",
          });
        }
      }

      function renderStack() {
        cards.forEach(function (card, index) {
          var distance = signedDistance(index);

          card.classList.remove(
            "is-active",
            "is-prev",
            "is-next",
            "is-before-prev",
            "is-after-next"
          );

          if (distance === 0) {
            card.classList.add("is-active");
            card.setAttribute("aria-hidden", "false");
          } else if (distance === -1) {
            card.classList.add("is-prev");
            card.setAttribute("aria-hidden", "false");
          } else if (distance === 1) {
            card.classList.add("is-next");
            card.setAttribute("aria-hidden", "false");
          } else if (distance < -1) {
            card.classList.add("is-before-prev");
            card.setAttribute("aria-hidden", "true");
          } else {
            card.classList.add("is-after-next");
            card.setAttribute("aria-hidden", "true");
          }
        });

        setActiveDot(activeIndex);
      }

      function render() {
        if (isDesktopStack()) {
          renderStack();
        } else {
          clearCardState();
          activeIndex = nativeClosestIndex();
          setActiveDot(activeIndex);
        }
      }

      function setActiveIndex(index) {
        activeIndex = normalize(index);

        if (isDesktopStack()) {
          renderStack();
        } else {
          setActiveDot(activeIndex);
          scrollToNativeCard(activeIndex);
        }
      }

      function pauseAutoplay() {
        autoplayPaused = true;
      }

      function resumeAutoplay() {
        autoplayPaused = false;
      }

      function pauseAfterManualAction() {
        if (!isDesktopStack()) {
          return;
        }

        pauseAutoplay();
        window.clearTimeout(resumeTimer);
        resumeTimer = window.setTimeout(resumeAutoplay, 4200);
      }

      function requestUpdate() {
        if (!ticking) {
          ticking = true;
          window.requestAnimationFrame(function () {
            ticking = false;
            render();
          });
        }
      }

      function createArrowButton(direction) {
        var button = document.createElement("button");
        var isPrev = direction === -1;

        button.className = "seasonal-menu__arrow seasonal-menu__arrow--" + (isPrev ? "prev" : "next");
        button.type = "button";
        button.setAttribute("aria-label", isPrev ? "Предыдущее сезонное блюдо" : "Следующее сезонное блюдо");
        button.textContent = isPrev ? "‹" : "›";
        button.addEventListener("click", function () {
          pauseAfterManualAction();
          setActiveIndex(activeIndex + direction);
        });
        carousel.appendChild(button);
      }

      dotsRoot.textContent = "";
      dotsRoot.hidden = false;
      dotsRoot.setAttribute("role", "tablist");
      track.setAttribute("tabindex", "0");

      cards.forEach(function (card, index) {
        var dot = document.createElement("button");

        dot.className = "seasonal-menu__dot";
        dot.type = "button";
        dot.setAttribute("role", "tab");
        dot.setAttribute("aria-label", String(index + 1));
        dot.addEventListener("click", function () {
          pauseAfterManualAction();
          setActiveIndex(index);
        });
        dotsRoot.appendChild(dot);
        dots.push(dot);

        card.addEventListener("click", function (event) {
          if (!isDesktopStack() || closest(event.target, "a, button")) {
            return;
          }

          if (index !== activeIndex) {
            event.preventDefault();
            pauseAfterManualAction();
            setActiveIndex(index);
          }
        });
      });

      if (carousel.classList.contains("seasonal-menu--desktop") && cards.length >= 3) {
        createArrowButton(-1);
        createArrowButton(1);
      }

      track.addEventListener("scroll", function () {
        if (!isDesktopStack()) {
          requestUpdate();
        }
      }, { passive: true });

      track.addEventListener("keydown", function (event) {
        if (event.key === "ArrowRight") {
          pauseAfterManualAction();
          setActiveIndex(activeIndex + 1);
          event.preventDefault();
        } else if (event.key === "ArrowLeft") {
          pauseAfterManualAction();
          setActiveIndex(activeIndex - 1);
          event.preventDefault();
        }
      });

      track.addEventListener("wheel", function (event) {
        var delta;

        if (!isDesktopStack()) {
          return;
        }

        delta = Math.abs(event.deltaY) > Math.abs(event.deltaX)
          ? event.deltaY
          : event.deltaX;

        if (Math.abs(delta) < 8 || wheelLocked) {
          return;
        }

        wheelLocked = true;
        event.preventDefault();
        pauseAfterManualAction();
        setActiveIndex(activeIndex + (delta > 0 ? 1 : -1));
        window.setTimeout(function () {
          wheelLocked = false;
        }, 240);
      }, { passive: false });

      track.addEventListener("pointerdown", function (event) {
        if (!isDesktopStack() || closest(event.target, "a, button")) {
          return;
        }

        startX = event.clientX;
        startY = event.clientY;
      });

      track.addEventListener("pointerup", function (event) {
        var deltaX;
        var deltaY;

        if (!isDesktopStack()) {
          return;
        }

        deltaX = event.clientX - startX;
        deltaY = event.clientY - startY;

        if (Math.abs(deltaX) < 36 || Math.abs(deltaX) <= Math.abs(deltaY)) {
          return;
        }

        pauseAfterManualAction();
        setActiveIndex(activeIndex + (deltaX < 0 ? 1 : -1));
      });

      carousel.addEventListener("pointerenter", pauseAutoplay);
      carousel.addEventListener("pointerleave", resumeAutoplay);
      carousel.addEventListener("focusin", pauseAutoplay);
      carousel.addEventListener("focusout", resumeAutoplay);
      window.addEventListener("resize", requestUpdate, { passive: true });

      if (typeof desktopQuery.addEventListener === "function") {
        desktopQuery.addEventListener("change", requestUpdate);
      } else if (typeof desktopQuery.addListener === "function") {
        desktopQuery.addListener(requestUpdate);
      }

      window.setInterval(function () {
        if (!isDesktopStack() || autoplayPaused) {
          return;
        }

        setActiveIndex(activeIndex + 1);
      }, 5600);

      render();
    });
  }

  setupSeasonalShowcase();
})();
