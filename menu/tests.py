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
