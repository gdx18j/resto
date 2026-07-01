import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from menu.models import Category, Dish
from orders.models import Order, Payment


class OrderApiTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Меню")
        self.dish = Dish.objects.create(
            category=category,
            name="Americano",
            price=Decimal("150.00"),
            is_active=True,
            is_available=True,
        )

    def post_json(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_quote_uses_server_price(self):
        response = self.post_json(
            reverse("orders:quote"),
            {
                "items": [
                    {
                        "id": f"dish-{self.dish.id}",
                        "quantity": 2,
                        "price": "1.00",
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], "300.00")
        self.assertEqual(data["items"][0]["unit_price"], "150.00")

    def test_create_order_persists_server_totals_and_payment(self):
        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "guests_count": 2,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 3,
                        "price": "1.00",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        order = Order.objects.get()
        self.assertIn(reverse("orders:success", args=[order.id]), data["confirmation_url"])
        self.assertEqual(order.total_amount, Decimal("450.00"))
        self.assertEqual(order.items.get().unit_price, Decimal("150.00"))
        self.assertEqual(order.payments.get().method, Payment.Method.CARD)

    def test_success_page_is_available_for_order_session(self):
        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CASH,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        success_response = self.client.get(reverse("orders:success", args=[order.id]))

        self.assertEqual(success_response.status_code, 200)
        self.assertContains(success_response, f"data-items=")

    def test_history_page_lists_authenticated_user_orders(self):
        user = get_user_model().objects.create_user(
            email="orders@example.com",
            password="password-123",
        )
        self.client.force_login(user)

        create_response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 2,
                    }
                ],
            },
        )

        self.assertEqual(create_response.status_code, 201)
        order = Order.objects.get(user=user)
        history_response = self.client.get(reverse("orders:history"))

        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, f'data-order-id="{order.id}"')

    def test_create_order_accepts_online_payment_method(self):
        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.ONLINE,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.get().payments.get().method, Payment.Method.ONLINE)
