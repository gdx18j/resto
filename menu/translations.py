from django.utils.html import format_html_join


LANGUAGES = ("ru", "en", "tr")
DEFAULT_LANGUAGE = "ru"


CATEGORY_TRANSLATIONS = {
    "Акционные наборы": {
        "ru": "Акционные наборы",
        "en": "Special sets",
        "tr": "Avantajlı setler",
    },
    "Горячий кофе": {
        "ru": "Горячий кофе",
        "en": "Hot coffee",
        "tr": "Sıcak kahve",
    },
    "Десерты": {
        "ru": "Десерты",
        "en": "Desserts",
        "tr": "Tatlılar",
    },
    "Другие блюда": {
        "ru": "Другие блюда",
        "en": "Other dishes",
        "tr": "Diğer yemekler",
    },
    "Матча-латте": {
        "ru": "Матча-латте",
        "en": "Matcha latte",
        "tr": "Matcha latte",
    },
    "Меню": {
        "ru": "Меню",
        "en": "Menu sets",
        "tr": "Menü setleri",
    },
    "Напитки": {
        "ru": "Напитки",
        "en": "Drinks",
        "tr": "İçecekler",
    },
    "Сэндвичи": {
        "ru": "Сэндвичи",
        "en": "Sandwiches",
        "tr": "Sandviçler",
    },
    "Тосты": {
        "ru": "Тосты",
        "en": "Toasts",
        "tr": "Tostlar",
    },
    "Холодные напитки": {
        "ru": "Холодные напитки",
        "en": "Cold drinks",
        "tr": "Soğuk içecekler",
    },
    "Холодный кофе": {
        "ru": "Холодный кофе",
        "en": "Iced coffee",
        "tr": "Soğuk kahve",
    },
    "Другое": {
        "ru": "Другое",
        "en": "Other",
        "tr": "Diğer",
    },
}


ALLERGEN_TRANSLATIONS = {
    "peanut": {"ru": "Арахис", "en": "Peanuts", "tr": "Yer fıstığı"},
    "gluten": {"ru": "Глютен", "en": "Gluten", "tr": "Gluten"},
    "mustard": {"ru": "Горчица", "en": "Mustard", "tr": "Hardal"},
    "sesame": {"ru": "Кунжут", "en": "Sesame", "tr": "Susam"},
    "lupin": {"ru": "Люпин", "en": "Lupin", "tr": "Lupin"},
    "honey": {"ru": "Мед", "en": "Honey", "tr": "Bal"},
    "shellfish": {
        "ru": "Моллюски и ракообразные",
        "en": "Shellfish and crustaceans",
        "tr": "Kabuklu deniz ürünleri",
    },
    "milk": {"ru": "Молоко", "en": "Milk", "tr": "Süt"},
    "tree-nuts": {"ru": "Орехи", "en": "Tree nuts", "tr": "Kuruyemişler"},
    "fish": {"ru": "Рыба", "en": "Fish", "tr": "Balık"},
    "celery": {"ru": "Сельдерей", "en": "Celery", "tr": "Kereviz"},
    "soy": {"ru": "Соя", "en": "Soy", "tr": "Soya"},
    "sulfites": {"ru": "Сульфиты", "en": "Sulfites", "tr": "Sülfitler"},
    "egg": {"ru": "Яйца", "en": "Eggs", "tr": "Yumurta"},
}


DISH_TRANSLATIONS = {
    "Caesar Salata, Avoya İçecek": {
        "name": {
            "ru": "Салат Цезарь и напиток Avoya",
            "en": "Caesar Salad and Avoya Drink",
            "tr": "Caesar Salata ve Avoya İçecek",
        },
        "description": {
            "ru": "Салат «Цезарь» с курицей и напиток Avoya.",
            "en": "Chicken Caesar salad served with an Avoya drink.",
            "tr": "Tavuklu Caesar salata ve Avoya içecek.",
        },
    },
    "Hypatia & Americano": {
        "name": {
            "ru": "Hypatia и американо",
            "en": "Hypatia and Americano",
            "tr": "Hypatia ve Americano",
        },
        "description": {
            "ru": "Десерт Hypatia и американо.",
            "en": "Hypatia dessert served with an Americano.",
            "tr": "Hypatia tatlısı ve Americano.",
        },
    },
    "Pompei Magnus & Ev Yapımı Limonata": {
        "name": {
            "ru": "Pompei Magnus и домашний лимонад",
            "en": "Pompei Magnus and Homemade Lemonade",
            "tr": "Pompei Magnus ve Ev Yapımı Limonata",
        },
        "description": {
            "ru": "Сэндвич Pompei Magnus и домашний лимонад.",
            "en": "Pompei Magnus sandwich served with homemade lemonade.",
            "tr": "Pompei Magnus sandviç ve ev yapımı limonata.",
        },
    },
    "Americano": {
        "name": {"ru": "Американо", "en": "Americano", "tr": "Americano"},
        "description": {
            "ru": "Горячий американо.",
            "en": "Hot Americano coffee.",
            "tr": "Sıcak Americano kahve.",
        },
    },
    "Cappuccino": {
        "name": {"ru": "Капучино", "en": "Cappuccino", "tr": "Cappuccino"},
        "description": {
            "ru": "Горячий капучино.",
            "en": "Hot cappuccino.",
            "tr": "Sıcak cappuccino.",
        },
    },
    "Caramel Latte": {
        "name": {
            "ru": "Карамельный латте",
            "en": "Caramel Latte",
            "tr": "Karamel Latte",
        },
        "description": {
            "ru": "Горячий латте с карамельным вкусом.",
            "en": "Hot latte with caramel flavor.",
            "tr": "Karamel aromalı sıcak latte.",
        },
    },
    "Filtre Kahve": {
        "name": {
            "ru": "Фильтр-кофе",
            "en": "Filter Coffee",
            "tr": "Filtre Kahve",
        },
        "description": {
            "ru": "Горячий фильтр-кофе.",
            "en": "Hot filter coffee.",
            "tr": "Sıcak filtre kahve.",
        },
    },
    "Latte": {
        "name": {"ru": "Латте", "en": "Latte", "tr": "Latte"},
        "description": {
            "ru": "Горячий латте.",
            "en": "Hot latte.",
            "tr": "Sıcak latte.",
        },
    },
    "Mocha": {
        "name": {"ru": "Мокка", "en": "Mocha", "tr": "Mocha"},
        "description": {
            "ru": "Горячий мокка с шоколадом.",
            "en": "Hot mocha with chocolate.",
            "tr": "Çikolatalı sıcak mocha.",
        },
    },
    "Vanilya Latte": {
        "name": {
            "ru": "Ванильный латте",
            "en": "Vanilla Latte",
            "tr": "Vanilya Latte",
        },
        "description": {
            "ru": "Горячий латте с ванильным вкусом.",
            "en": "Hot latte with vanilla flavor.",
            "tr": "Vanilya aromalı sıcak latte.",
        },
    },
    "White Mocha": {
        "name": {
            "ru": "Белый мокка",
            "en": "White Mocha",
            "tr": "White Mocha",
        },
        "description": {
            "ru": "Горячий мокка с белым шоколадом.",
            "en": "Hot mocha with white chocolate.",
            "tr": "Beyaz çikolatalı sıcak mocha.",
        },
    },
    "Hypatia": {
        "name": {"ru": "Hypatia", "en": "Hypatia", "tr": "Hypatia"},
        "description": {
            "ru": "Десерт с бельгийским шоколадом.",
            "en": "Dessert with Belgian chocolate.",
            "tr": "Belçika çikolatalı tatlı.",
        },
    },
    "Lotus Maximus": {
        "name": {"ru": "Lotus Maximus", "en": "Lotus Maximus", "tr": "Lotus Maximus"},
        "description": {
            "ru": "Десерт с кремом Lotus, печеньем, белым шоколадом и банановым пудингом.",
            "en": "Dessert with Lotus cream, cookies, white chocolate, and banana pudding.",
            "tr": "Lotus kreması, bisküvi, beyaz çikolata ve muzlu pudingli tatlı.",
        },
    },
    "Marcus Antonius": {
        "name": {"ru": "Marcus Antonius", "en": "Marcus Antonius", "tr": "Marcus Antonius"},
        "description": {
            "ru": "Морковный кекс с грецким орехом и кремом.",
            "en": "Carrot cake with walnuts and cream.",
            "tr": "Cevizli ve kremalı havuçlu kek.",
        },
    },
    "Oreolu Cup": {
        "name": {
            "ru": "Десертный стаканчик с Oreo",
            "en": "Oreo Cup",
            "tr": "Oreolu Cup",
        },
        "description": {
            "ru": "Десерт в стакане с кремом и печеньем Oreo.",
            "en": "Cup dessert with cream and Oreo cookies.",
            "tr": "Krema ve Oreo bisküvili kup tatlı.",
        },
    },
    "Rubicon": {
        "name": {"ru": "Rubicon", "en": "Rubicon", "tr": "Rubicon"},
        "description": {
            "ru": "Влажный шоколадный кекс с шоколадным соусом.",
            "en": "Moist chocolate cake with chocolate sauce.",
            "tr": "Çikolata soslu ıslak çikolatalı kek.",
        },
    },
    "Yaban Mersinli Cheesecake": {
        "name": {
            "ru": "Черничный чизкейк",
            "en": "Blueberry Cheesecake",
            "tr": "Yaban Mersinli Cheesecake",
        },
        "description": {
            "ru": "Порционный чизкейк с черникой.",
            "en": "Individual cheesecake with blueberries.",
            "tr": "Yaban mersinli porsiyon cheesecake.",
        },
    },
    "Focaccia": {
        "name": {"ru": "Фокачча", "en": "Focaccia", "tr": "Focaccia"},
        "description": {
            "ru": "Итальянская фокачча с розмарином, оливками и вялеными томатами.",
            "en": "Italian focaccia with rosemary, olives, and sun-dried tomatoes.",
            "tr": "Biberiye, zeytin ve kurutulmuş domatesli İtalyan focaccia.",
        },
    },
    "Iced Matcha Latte": {
        "name": {
            "ru": "Холодный матча-латте",
            "en": "Iced Matcha Latte",
            "tr": "Soğuk Matcha Latte",
        },
        "description": {
            "ru": "Холодный матча-латте.",
            "en": "Iced matcha latte.",
            "tr": "Soğuk matcha latte.",
        },
    },
    "Iced Matcha Mango Latte": {
        "name": {
            "ru": "Холодный матча-латте с манго",
            "en": "Iced Mango Matcha Latte",
            "tr": "Soğuk Mangolu Matcha Latte",
        },
        "description": {
            "ru": "Холодный матча-латте с манго.",
            "en": "Iced matcha latte with mango.",
            "tr": "Mangolu soğuk matcha latte.",
        },
    },
    "Iced Matcha Mix Berry Latte": {
        "name": {
            "ru": "Холодный ягодный матча-латте",
            "en": "Iced Mixed Berry Matcha Latte",
            "tr": "Soğuk Orman Meyveli Matcha Latte",
        },
        "description": {
            "ru": "Холодный матча-латте с ягодным вкусом.",
            "en": "Iced matcha latte with mixed berry flavor.",
            "tr": "Orman meyvesi aromalı soğuk matcha latte.",
        },
    },
    "Caesar Salata Menü": {
        "name": {
            "ru": "Меню с салатом Цезарь",
            "en": "Caesar Salad Menu",
            "tr": "Caesar Salata Menü",
        },
        "description": {
            "ru": "Салат «Цезарь» и напиток Avoya.",
            "en": "Caesar salad served with an Avoya drink.",
            "tr": "Caesar salata ve Avoya içecek.",
        },
    },
    "Cappy (33 cl.)": {
        "name": {"ru": "Cappy 330 мл", "en": "Cappy 330 ml", "tr": "Cappy 330 ml"},
        "description": {
            "ru": "Фруктовый напиток, упаковка 330 мл.",
            "en": "Fruit drink, 330 ml pack.",
            "tr": "Meyveli içecek, 330 ml paket.",
        },
    },
    "Coca-Cola (33 cl.)": {
        "name": {"ru": "Coca-Cola 330 мл", "en": "Coca-Cola 330 ml", "tr": "Coca-Cola 330 ml"},
        "description": {
            "ru": "Газированный напиток, банка 330 мл.",
            "en": "Carbonated soft drink, 330 ml can.",
            "tr": "Gazlı içecek, 330 ml kutu.",
        },
    },
    "Coca-Cola Zero Sugar (33 cl.)": {
        "name": {
            "ru": "Coca-Cola Zero Sugar 330 мл",
            "en": "Coca-Cola Zero Sugar 330 ml",
            "tr": "Coca-Cola Zero Sugar 330 ml",
        },
        "description": {
            "ru": "Газированный напиток без сахара, банка 330 мл.",
            "en": "Sugar-free carbonated soft drink, 330 ml can.",
            "tr": "Şekersiz gazlı içecek, 330 ml kutu.",
        },
    },
    "Fanta (33 cl.)": {
        "name": {"ru": "Fanta 330 мл", "en": "Fanta 330 ml", "tr": "Fanta 330 ml"},
        "description": {
            "ru": "Газированный апельсиновый напиток, банка 330 мл.",
            "en": "Carbonated orange drink, 330 ml can.",
            "tr": "Portakallı gazlı içecek, 330 ml kutu.",
        },
    },
    "Fuse Tea (33 cl.)": {
        "name": {"ru": "Fuse Tea 330 мл", "en": "Fuse Tea 330 ml", "tr": "Fuse Tea 330 ml"},
        "description": {
            "ru": "Холодный чай, упаковка 330 мл.",
            "en": "Iced tea, 330 ml pack.",
            "tr": "Soğuk çay, 330 ml paket.",
        },
    },
    "Schweppes (25 cl.)": {
        "name": {"ru": "Schweppes 250 мл", "en": "Schweppes 250 ml", "tr": "Schweppes 250 ml"},
        "description": {
            "ru": "Газированный напиток в стеклянной бутылке 250 мл.",
            "en": "Carbonated drink in a 250 ml glass bottle.",
            "tr": "250 ml cam şişede gazlı içecek.",
        },
    },
    "Sprite (33 cl.)": {
        "name": {"ru": "Sprite 330 мл", "en": "Sprite 330 ml", "tr": "Sprite 330 ml"},
        "description": {
            "ru": "Газированный напиток, банка 330 мл.",
            "en": "Carbonated soft drink, 330 ml can.",
            "tr": "Gazlı içecek, 330 ml kutu.",
        },
    },
    "Uludağ Premium Su (40 cl.)": {
        "name": {
            "ru": "Uludağ Premium вода 400 мл",
            "en": "Uludağ Premium Water 400 ml",
            "tr": "Uludağ Premium Su 400 ml",
        },
        "description": {
            "ru": "Питьевая вода в стеклянной бутылке 400 мл.",
            "en": "Drinking water in a 400 ml glass bottle.",
            "tr": "400 ml cam şişede içme suyu.",
        },
    },
    "Uludağ Soda (20 cl.)": {
        "name": {
            "ru": "Uludağ сода 200 мл",
            "en": "Uludağ Soda 200 ml",
            "tr": "Uludağ Soda 200 ml",
        },
        "description": {
            "ru": "Минеральная вода в стеклянной бутылке 200 мл.",
            "en": "Mineral water in a 200 ml glass bottle.",
            "tr": "200 ml cam şişede maden suyu.",
        },
    },
    "Crassus": {
        "name": {"ru": "Crassus", "en": "Crassus", "tr": "Crassus"},
        "description": {
            "ru": "Сэндвич на чиабатте с индейкой, соусами, сыром и овощами.",
            "en": "Ciabatta sandwich with turkey, sauces, cheese, and vegetables.",
            "tr": "Hindi, soslar, peynir ve sebzeli ciabatta sandviç.",
        },
    },
    "Octavian": {
        "name": {"ru": "Octavian", "en": "Octavian", "tr": "Octavian"},
        "description": {
            "ru": "Сэндвич на чиабатте с салями, овощами, сырами и фирменным соусом.",
            "en": "Ciabatta sandwich with salami, vegetables, cheeses, and signature sauce.",
            "tr": "Salam, sebzeler, peynirler ve özel soslu ciabatta sandviç.",
        },
    },
    "Pompei Magnus": {
        "name": {"ru": "Pompei Magnus", "en": "Pompei Magnus", "tr": "Pompei Magnus"},
        "description": {
            "ru": "Сэндвич на чиабатте с салями, сырами, рукколой, томатами и оливковой пастой.",
            "en": "Ciabatta sandwich with salami, cheeses, arugula, tomatoes, and olive paste.",
            "tr": "Salam, peynirler, roka, domates ve zeytin ezmeli ciabatta sandviç.",
        },
    },
    "Dana Sucuklu Peynirli Tost": {
        "name": {
            "ru": "Тост с говяжьим суджуком и сыром",
            "en": "Beef Sucuk and Cheese Toast",
            "tr": "Dana Sucuklu Peynirli Tost",
        },
        "description": {
            "ru": "Тост на айвалыкском хлебе с говяжьей колбасой, сыром и овощами.",
            "en": "Ayvalık-style toast with beef sucuk, cheese, and vegetables.",
            "tr": "Dana sucuk, peynir ve sebzeli Ayvalık tostu.",
        },
    },
    "Limonata": {
        "name": {"ru": "Домашний лимонад", "en": "Homemade Lemonade", "tr": "Limonata"},
        "description": {
            "ru": "Домашний лимонад, подаётся холодным.",
            "en": "Homemade lemonade, served cold.",
            "tr": "Ev yapımı limonata, soğuk servis edilir.",
        },
    },
    "Cold Brew No 1": {
        "name": {"ru": "Cold Brew No 1", "en": "Cold Brew No 1", "tr": "Cold Brew No 1"},
        "description": {
            "ru": "Холодный кофе длительного настаивания.",
            "en": "Cold brew coffee.",
            "tr": "Soğuk demleme kahve.",
        },
    },
    "Iced Americano": {
        "name": {"ru": "Холодный американо", "en": "Iced Americano", "tr": "Soğuk Americano"},
        "description": {
            "ru": "Холодный американо.",
            "en": "Iced Americano.",
            "tr": "Soğuk Americano.",
        },
    },
    "Iced Caramel Latte": {
        "name": {
            "ru": "Холодный карамельный латте",
            "en": "Iced Caramel Latte",
            "tr": "Soğuk Karamel Latte",
        },
        "description": {
            "ru": "Холодный латте с карамельным вкусом.",
            "en": "Iced latte with caramel flavor.",
            "tr": "Karamel aromalı soğuk latte.",
        },
    },
    "Iced Latte": {
        "name": {"ru": "Холодный латте", "en": "Iced Latte", "tr": "Soğuk Latte"},
        "description": {
            "ru": "Холодный латте.",
            "en": "Iced latte.",
            "tr": "Soğuk latte.",
        },
    },
    "Iced Mocha": {
        "name": {"ru": "Холодный мокка", "en": "Iced Mocha", "tr": "Soğuk Mocha"},
        "description": {
            "ru": "Холодный мокка с шоколадом.",
            "en": "Iced mocha with chocolate.",
            "tr": "Çikolatalı soğuk mocha.",
        },
    },
    "Iced Vanilla Latte": {
        "name": {
            "ru": "Холодный ванильный латте",
            "en": "Iced Vanilla Latte",
            "tr": "Soğuk Vanilya Latte",
        },
        "description": {
            "ru": "Холодный латте с ванильным вкусом.",
            "en": "Iced latte with vanilla flavor.",
            "tr": "Vanilya aromalı soğuk latte.",
        },
    },
    "Iced White Mocha": {
        "name": {
            "ru": "Холодный белый мокка",
            "en": "Iced White Mocha",
            "tr": "Soğuk White Mocha",
        },
        "description": {
            "ru": "Холодный мокка с белым шоколадом.",
            "en": "Iced mocha with white chocolate.",
            "tr": "Beyaz çikolatalı soğuk mocha.",
        },
    },
}


def normalize_language(language):
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def translated_values(source, key, fallback):
    translations = source.get(key, {})
    return {
        language: translations.get(language) or fallback
        for language in LANGUAGES
    }


def translated_string(source, key, fallback, language=DEFAULT_LANGUAGE):
    values = translated_values(source, key, fallback)
    return values[normalize_language(language)]


def localized_text_html(values):
    return format_html_join(
        "",
        '<span class="lang lang--{}">{}</span>',
        ((language, values[language]) for language in LANGUAGES),
    )


def localized_category_values(name):
    return translated_values(CATEGORY_TRANSLATIONS, name, name)


def localized_category_html(name):
    return localized_text_html(localized_category_values(name))


def localized_allergen_values(allergen):
    return translated_values(ALLERGEN_TRANSLATIONS, allergen.code, allergen.name)


def localized_allergen_html(allergen):
    return localized_text_html(localized_allergen_values(allergen))


def localized_dish_values(dish, field):
    dish_translation = DISH_TRANSLATIONS.get(dish.name, {})
    return translated_values(dish_translation, field, getattr(dish, field))


def localized_dish_string(dish, field, language=DEFAULT_LANGUAGE):
    dish_translation = DISH_TRANSLATIONS.get(dish.name, {})
    return translated_string(
        dish_translation,
        field,
        getattr(dish, field),
        language=language,
    )


def localized_dish_html(dish, field):
    return localized_text_html(localized_dish_values(dish, field))
