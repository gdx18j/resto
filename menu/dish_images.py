from django.templatetags.static import static


DISH_STATIC_IMAGES = {
    "americano": "americano-8-oz.webp",
    "caesar-salata-avoya-icecek": "caesar-salad.webp",
    "caesar-salata-menu": "caesar-salad.webp",
    "cappuccino": "cappuccino-8-oz.webp",
    "caramel-latte": "caramel-latte-8-oz.webp",
    "cold-brew-no-1": "cold-brew-no1-18-oz.webp",
    "crassus": "crassus.webp",
    "dana-sucuklu-peynirli-tost": "caesar-tost.webp",
    "filtre-kahve": "filtre-kahve-8-oz.webp",
    "focaccia": "focaccia.webp",
    "hypatia": "hypatia.webp",
    "hypatia-americano": "hypatia.webp",
    "iced-americano": "iced-americano-14-oz.webp",
    "iced-caramel-latte": "iced-caramel-latte-14-oz.webp",
    "iced-latte": "iced-latte-14-oz.webp",
    "iced-matcha-latte": "iced-matcha-latte-14-oz.webp",
    "iced-matcha-mango-latte": "iced-matcha-mango-latte-14-oz.webp",
    "iced-matcha-mix-berry-latte": "iced-matcha-mix-berry-latte-14-oz.webp",
    "iced-mocha": "iced-mocha-14-oz.webp",
    "iced-vanilla-latte": "iced-vanilla-latte-14-oz.webp",
    "iced-white-mocha": "iced-white-mocha-14-oz.webp",
    "latte": "latte-8-oz.webp",
    "limonata": "limonata-300-ml.webp",
    "lotus-maximus": "lotus-maximus.webp",
    "marcus-antonius": "marcus-antonius.webp",
    "mocha": "mocha-latte-8-oz.webp",
    "octavian": "octavian.webp",
    "oreolu-cup": "oreolu-cup.webp",
    "patrea": "patrea.webp",
    "pompei-magnus": "pompei-magnus.webp",
    "pompei-magnus-ev-yapm-limonata": "pompei-magnus.webp",
    "rubicon": "rubicon.webp",
    "vanilya-latte": "vanilla-latte-8-oz.webp",
    "white-mocha": "white-mocha-latte-8-oz.webp",
    "yaban-mersinli-cheesecake": "cheesecake-degil.webp",
}


def static_dish_image_url(dish):
    filename = DISH_STATIC_IMAGES.get(getattr(dish, "code", ""))

    if not filename:
        return ""

    return static(f"img/dishes/{filename}")
