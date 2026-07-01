from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from orders.models import Restaurant

from .models import Category, Dish


class MenuRenderingTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Меню")
        self.dish = Dish.objects.create(
            category=category,
            name="Americano",
            price=Decimal("150.00"),
            is_active=True,
            is_available=True,
        )
    def test_menu_uses_single_detail_payload_instead_of_per_dish_templates(self):
        Dish.objects.create(
            category=self.dish.category,
            name="Latte",
            price=Decimal("220.00"),
            is_active=True,
            is_available=True,
        )

        response = self.client.get(reverse("menu:dish_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertNotIn("dish-detail-template-", html)
        self.assertEqual(html.count('id="dish-detail-data"'), 1)
        self.assertEqual(html.count("data-dish-modal hidden"), 1)

    def test_menu_is_scoped_to_selected_restaurant(self):
        second_restaurant = Restaurant.objects.create(
            name="Second Caesar",
            slug="second-caesar",
        )
        second_category = Category.objects.create(
            restaurant=second_restaurant,
            name="Меню",
        )
        second_dish = Dish.objects.create(
            restaurant=second_restaurant,
            category=second_category,
            name="Only second restaurant",
            price=Decimal("300.00"),
            is_active=True,
            is_available=True,
        )

        response = self.client.get(
            reverse("menu:dish_list"),
            {"restaurant": second_restaurant.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="dish-{second_dish.id}"')
        self.assertNotContains(response, f'id="dish-{self.dish.id}"')
