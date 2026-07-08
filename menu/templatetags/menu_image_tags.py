from django import template
from django.templatetags.static import static


register = template.Library()


CATEGORY_FALLBACKS = {
    "акционные наборы": "sets",
    "горячий кофе": "coffee",
    "десерты": "desserts",
    "другие блюда": "specials",
    "матча-латте": "matcha",
    "меню": "specials",
    "напитки": "drinks",
    "сэндвичи": "sandwiches",
    "тосты": "toasts",
    "холодный кофе": "coffee",
}


@register.filter
def dish_fallback_image(category_name):
    key = str(category_name or "").strip().lower()
    image_name = CATEGORY_FALLBACKS.get(key, "specials")
    return static(f"img/dish-fallbacks/{image_name}.jpg")
