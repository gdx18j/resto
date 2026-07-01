from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Category, Dish


class DishManagementTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Меню")
        self.dish = Dish.objects.create(
            category=category,
            name="Americano",
            price=Decimal("150.00"),
            is_active=True,
            is_available=True,
        )
        self.staff = get_user_model().objects.create_user(
            email="staff@example.com",
            password="pass12345",
            is_staff=True,
        )

    def test_staff_can_hide_dish_from_menu(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("menu:hide_dish", args=[self.dish.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.dish.refresh_from_db()
        self.assertFalse(self.dish.is_active)

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
