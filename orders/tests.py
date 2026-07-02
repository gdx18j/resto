import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from menu.models import Category, Dish, DishIngredient, Ingredient
from orders import services as order_services
from orders.admin import OrderAdmin
from orders.models import (
    Order,
    OrderItemModifier,
    OrderStatusHistory,
    Payment,
    Restaurant,
    Table,
    TableQrTokenAudit,
    hash_table_qr_token,
)
from orders.services import ValidatedCartModifier
from orders.statuses import OrderTransitionError, OrderVersionConflict, transition_order


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class OrderApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.defaults["HTTP_HOST"] = "localhost"
        category = Category.objects.create(name="Меню")
        self.dish = Dish.objects.create(
            category=category,
            name="Americano",
            price=Decimal("150.00"),
            is_active=True,
            is_available=True,
        )
        self._idempotency_counter = 0

    def create_removable_ingredient(self, name):
        ingredient = Ingredient.objects.create(name=name)

        return DishIngredient.objects.create(
            dish=self.dish,
            ingredient=ingredient,
            can_be_removed=True,
        )

    def next_idempotency_key(self):
        self._idempotency_counter += 1
        return f"test-key-{self._idempotency_counter}"

    def post_json(self, url, payload, idempotency_key=None):
        extra = {}
        if isinstance(payload, dict):
            payload = payload.copy()

            if not payload.get("table_token"):
                payload.setdefault("restaurant_slug", self.dish.restaurant.slug)

            if (
                url == reverse("orders:create")
                and not payload.get("table_token")
                and not payload.get("order_source")
                and not payload.get("order_mode")
                and not payload.get("fulfillment")
                and not payload.get("source")
            ):
                payload["order_source"] = "counter"

            if (
                url == reverse("orders:create")
                and payload.get("items")
                and not payload.get("quote_id")
            ):
                try:
                    quote_data = order_services.quote_cart(payload)
                    payload["quote_id"] = quote_data["quote_id"]
                    payload["pricing_revision"] = quote_data["pricing_revision"]
                    payload["quote_fingerprint"] = quote_data["fingerprint"]
                except order_services.CartValidationError:
                    pass

        if idempotency_key:
            extra["HTTP_IDEMPOTENCY_KEY"] = idempotency_key

        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            **extra,
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
        self.assertTrue(data["quote_id"])
        self.assertTrue(data["pricing_revision"])
        self.assertTrue(data["expires_at"])
        self.assertTrue(data["fingerprint"])

    def test_quote_accepts_strict_dish_cart_id(self):
        response = self.post_json(
            reverse("orders:quote"),
            {
                "items": [
                    {
                        "id": f"dish-{self.dish.id}",
                        "quantity": 1,
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["dish_id"], self.dish.id)

    def test_quote_generates_line_id_instead_of_trusting_client_id(self):
        onion = self.create_removable_ingredient("Onion")
        response = self.post_json(
            reverse("orders:quote"),
            {
                "items": [
                    {
                        "id": f"dish-{self.dish.id}",
                        "quantity": 1,
                        "note": "no onion",
                        "modifiers": [
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": onion.id,
                            }
                        ],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        line_id = response.json()["items"][0]["id"]
        self.assertRegex(line_id, rf"^dish-{self.dish.id}-[0-9a-f]{{12}}$")
        self.assertNotEqual(line_id, f"dish-{self.dish.id}")

    def test_quote_ignores_arbitrary_client_line_id_when_dish_id_is_present(self):
        response = self.post_json(
            reverse("orders:quote"),
            {
                "items": [
                    {
                        "id": "x" * 5000,
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["id"], f"dish-{self.dish.id}")

    def test_quote_rejects_permissive_dish_id_suffixes(self):
        invalid_values = [
            f"anything{self.dish.id}",
            f"dish-{self.dish.id}-extra",
            str(self.dish.id),
            True,
        ]

        for value in invalid_values:
            with self.subTest(value=value):
                response = self.post_json(
                    reverse("orders:quote"),
                    {
                        "items": [
                            {
                                "id": value,
                                "quantity": 1,
                            }
                        ]
                    },
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "invalid_cart")

    def test_quote_rejects_too_long_item_note_without_truncating(self):
        response = self.post_json(
            reverse("orders:quote"),
            {
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                        "note": "x" * 256,
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "item_note_too_long")

    def test_create_order_rejects_too_long_comment_without_truncating(self):
        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "comment": "x" * 2001,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "order_comment_too_long")
        self.assertEqual(Order.objects.count(), 0)

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
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        order = Order.objects.get()
        self.assertIn(reverse("orders:success", args=[order.id]), data["confirmation_url"])
        self.assertEqual(order.total_amount, Decimal("450.00"))
        self.assertEqual(order.items.get().unit_price, Decimal("150.00"))
        self.assertEqual(order.payments.get().method, Payment.Method.CARD)
        history = order.status_history.get()
        self.assertEqual(history.from_status, "")
        self.assertEqual(history.to_status, Order.Status.CREATED)
        self.assertEqual(history.order_version, 0)

    def test_create_order_validates_and_prices_cart_once(self):
        payload = {
            "restaurant_slug": self.dish.restaurant.slug,
            "order_source": "counter",
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 2,
                }
            ],
        }
        quote_data = order_services.quote_cart(payload)
        payload["quote_id"] = quote_data["quote_id"]

        with patch("orders.services._get_dishes_by_id", wraps=order_services._get_dishes_by_id) as get_dishes_mock:
            response = self.client.post(
                reverse("orders:create"),
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=self.next_idempotency_key(),
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(get_dishes_mock.call_count, 1)

    def test_same_dish_with_different_modifiers_stays_separate_order_items(self):
        onion = self.create_removable_ingredient("Onion")
        cheese = self.create_removable_ingredient("Cheese")

        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                        "modifiers": [
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": onion.id,
                            }
                        ],
                    },
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                        "modifiers": [
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": cheese.id,
                            }
                        ],
                    },
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 2)
        modifier_names = [
            item.modifiers.get().name
            for item in order.items.order_by("id")
        ]
        self.assertEqual(modifier_names, ["Onion", "Cheese"])

    def test_quote_preserves_separate_cart_lines_for_different_modifiers(self):
        onion = self.create_removable_ingredient("Onion")
        cheese = self.create_removable_ingredient("Cheese")

        response = self.post_json(
            reverse("orders:quote"),
            {
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                        "modifiers": [
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": onion.id,
                            }
                        ],
                    },
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                        "modifiers": [
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": cheese.id,
                            }
                        ],
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["items"]), 2)
        self.assertNotEqual(data["items"][0]["id"], data["items"][1]["id"])

    def test_same_dish_with_same_modifiers_and_note_merges_regardless_modifier_order(self):
        onion = self.create_removable_ingredient("Onion")
        cheese = self.create_removable_ingredient("Cheese")
        first_modifiers = [
            {
                "type": OrderItemModifier.Type.REMOVE,
                "dish_ingredient_id": onion.id,
            },
            {
                "type": OrderItemModifier.Type.REMOVE,
                "dish_ingredient_id": cheese.id,
            },
        ]
        second_modifiers = list(reversed(first_modifiers))

        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                        "note": "cut in half",
                        "modifiers": first_modifiers,
                    },
                    {
                        "dish_id": self.dish.id,
                        "quantity": 2,
                        "note": "cut in half",
                        "modifiers": second_modifiers,
                    },
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 201)
        order_item = Order.objects.get().items.get()
        self.assertEqual(order_item.quantity, 3)
        self.assertEqual(order_item.note, "cut in half")
        self.assertEqual(order_item.modifiers.count(), 2)

    def test_duplicate_modifier_is_rejected(self):
        onion = self.create_removable_ingredient("Onion")

        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                        "modifiers": [
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": onion.id,
                            },
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": onion.id,
                            },
                        ],
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "duplicate_modifier")
        self.assertEqual(Order.objects.count(), 0)

    def test_modifier_price_delta_is_included_in_quote_and_order_totals(self):
        topping = self.create_removable_ingredient("Extra cheese")
        paid_modifier = ValidatedCartModifier(
            type=OrderItemModifier.Type.REMOVE,
            dish_ingredient=topping,
            name="Extra cheese",
            price_delta=Decimal("25.00"),
        )
        payload = {
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 2,
                    "modifiers": [
                        {
                            "type": OrderItemModifier.Type.REMOVE,
                            "dish_ingredient_id": topping.id,
                        }
                    ],
                }
            ],
        }

        with patch("orders.services._normalize_modifiers", return_value=(paid_modifier,)):
            quote_response = self.post_json(reverse("orders:quote"), payload)
            create_response = self.post_json(
                reverse("orders:create"),
                payload,
                idempotency_key=self.next_idempotency_key(),
            )

        self.assertEqual(quote_response.status_code, 200)
        quote_data = quote_response.json()
        self.assertEqual(quote_data["items"][0]["unit_price"], "175.00")
        self.assertEqual(quote_data["items"][0]["line_total"], "350.00")
        self.assertEqual(quote_data["items"][0]["modifiers"][0]["price_delta"], "25.00")
        self.assertEqual(quote_data["total"], "350.00")

        self.assertEqual(create_response.status_code, 201)
        order = Order.objects.get()
        order_item = order.items.get()
        self.assertEqual(order.total_amount, Decimal("350.00"))
        self.assertEqual(order_item.unit_price, Decimal("175.00"))
        self.assertEqual(order_item.line_total, Decimal("350.00"))
        self.assertEqual(order_item.modifiers.get().price_delta, Decimal("25.00"))
        self.assertEqual(order.payments.get().amount, Decimal("350.00"))

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
            idempotency_key=self.next_idempotency_key(),
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
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(create_response.status_code, 201)
        order = Order.objects.get(user=user)
        history_response = self.client.get(reverse("orders:history"))

        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, f'data-order-id="{order.id}"')
        self.assertContains(history_response, "data-order-history-search")
        self.assertContains(history_response, 'data-order-filter="active"')

    def test_history_page_is_paginated(self):
        user = get_user_model().objects.create_user(
            email="paged-orders@example.com",
            password="password-123",
        )

        for index in range(12):
            Order.objects.create(
                restaurant=self.dish.restaurant,
                user=user,
                subtotal_amount=Decimal(index),
                total_amount=Decimal(index),
            )

        self.client.force_login(user)

        first_response = self.client.get(reverse("orders:history"))
        second_response = self.client.get(reverse("orders:history"), {"page": 2})

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(len(first_response.context["orders"]), 10)
        self.assertEqual(first_response.context["paginator"].count, 12)
        self.assertContains(first_response, "Страница 1")

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(len(second_response.context["orders"]), 2)
        self.assertEqual(second_response.context["page_obj"].number, 2)

    def test_history_repeat_json_preserves_modifiers_and_notes(self):
        onion = self.create_removable_ingredient("Onion")
        user = get_user_model().objects.create_user(
            email="repeat-json@example.com",
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
                        "quantity": 1,
                        "note": "no toast",
                        "modifiers": [
                            {
                                "type": OrderItemModifier.Type.REMOVE,
                                "dish_ingredient_id": onion.id,
                            }
                        ],
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(create_response.status_code, 201)

        history_response = self.client.get(reverse("orders:history"))
        items = json.loads(history_response.context["orders"][0].items_json)

        self.assertTrue(items[0]["id"].startswith("order-item-"))
        self.assertEqual(items[0]["dish_id"], self.dish.id)
        self.assertEqual(items[0]["note"], "no toast")
        self.assertEqual(items[0]["modifiers"][0]["type"], OrderItemModifier.Type.REMOVE)
        self.assertEqual(items[0]["modifiers"][0]["dish_ingredient_id"], onion.id)

        repeat_result = history_response.context["orders"][0].repeat_result
        self.assertEqual(repeat_result["changed"], [])
        self.assertEqual(repeat_result["unavailable"], [])
        self.assertEqual(repeat_result["available"][0]["dish_id"], self.dish.id)
        self.assertEqual(repeat_result["available"][0]["note"], "no toast")
        self.assertEqual(
            repeat_result["available"][0]["modifiers"][0]["dish_ingredient_id"],
            onion.id,
        )

    def test_history_repeat_result_classifies_changed_and_unavailable_items(self):
        user = get_user_model().objects.create_user(
            email="repeat-changed@example.com",
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
                        "quantity": 1,
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )
        self.assertEqual(create_response.status_code, 201)

        self.dish.price = Decimal("175.00")
        self.dish.save(update_fields=["price"])

        history_response = self.client.get(reverse("orders:history"))
        repeat_result = history_response.context["orders"][0].repeat_result
        self.assertEqual(repeat_result["available"], [])
        self.assertEqual(repeat_result["unavailable"], [])
        self.assertEqual(repeat_result["changed"][0]["dish_id"], self.dish.id)
        self.assertEqual(repeat_result["changed"][0]["price"], "175.00")
        self.assertEqual(repeat_result["changed"][0]["changes"], ["price_changed"])

        self.dish.is_available = False
        self.dish.save(update_fields=["is_available"])

        history_response = self.client.get(reverse("orders:history"))
        repeat_result = history_response.context["orders"][0].repeat_result
        self.assertEqual(repeat_result["available"], [])
        self.assertEqual(repeat_result["changed"], [])
        self.assertEqual(repeat_result["unavailable"][0]["dish_id"], self.dish.id)
        self.assertEqual(repeat_result["unavailable"][0]["reason"], "dish_unavailable")

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
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.get().payments.get().method, Payment.Method.ONLINE)

    def test_create_order_uses_table_from_qr_token(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="12",
        )
        table_token = table.plain_qr_token
        spoofed_table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="99",
        )

        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "table_token": table_token,
                "table_id": spoofed_table.id,
                "table_number": spoofed_table.number,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.get().table, table)

    def test_qr_token_determines_restaurant_even_with_conflicting_slug(self):
        restaurant_b = Restaurant.objects.create(
            name="Branch B",
            slug="branch-b",
        )
        category_b = Category.objects.create(
            restaurant=restaurant_b,
            name="Menu B",
        )
        dish_b = Dish.objects.create(
            restaurant=restaurant_b,
            category=category_b,
            name="Branch B dish",
            price=Decimal("320.00"),
            is_active=True,
            is_available=True,
        )
        table_b = Table.objects.create(
            restaurant=restaurant_b,
            number="7",
        )
        table_b_token = table_b.plain_qr_token
        payload = {
            "restaurant_slug": self.dish.restaurant.slug,
            "table_token": table_b_token,
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": dish_b.id,
                    "quantity": 1,
                }
            ],
        }

        quote_response = self.post_json(reverse("orders:quote"), payload)
        create_response = self.post_json(
            reverse("orders:create"),
            payload,
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(quote_response.status_code, 200)
        self.assertEqual(quote_response.json()["total"], "320.00")
        self.assertEqual(create_response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.restaurant, restaurant_b)
        self.assertEqual(order.table, table_b)

    def test_create_order_rejects_untrusted_table_id_without_token(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="12",
        )

        with self.assertLogs("orders.services", level="WARNING") as logs:
            response = self.client.post(
                reverse("orders:create"),
                data=json.dumps(
                    {
                        "restaurant_slug": self.dish.restaurant.slug,
                        "payment_method": Payment.Method.CARD,
                        "table_id": table.id,
                        "items": [
                            {
                                "dish_id": self.dish.id,
                                "quantity": 1,
                            }
                        ],
                    }
                ),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=self.next_idempotency_key(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "table_token_required")
        self.assertEqual(Order.objects.count(), 0)
        self.assertTrue(any("missing_table_token" in message for message in logs.output))

    def test_ordering_context_rejects_table_id_even_with_server_restaurant(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="12",
        )

        with self.assertRaises(order_services.CartValidationError) as error:
            order_services.resolve_ordering_context(
                {
                    "table_id": table.id,
                    "items": [
                        {
                            "dish_id": self.dish.id,
                            "quantity": 1,
                        }
                    ],
                },
                restaurant=self.dish.restaurant,
                allow_menu_context=True,
            )

        self.assertEqual(error.exception.code, "table_token_required")

    def test_table_order_mode_requires_qr_token(self):
        response = self.post_json(
            reverse("orders:create"),
            {
                "order_mode": "table",
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "table_token_required")
        self.assertEqual(Order.objects.count(), 0)

    def test_delivery_order_mode_is_explicit_no_table_mode(self):
        response = self.post_json(
            reverse("orders:create"),
            {
                "order_mode": "delivery",
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertIsNone(order.table)

    def test_create_order_without_table_requires_explicit_counter_or_pickup_mode(self):
        response = self.client.post(
            reverse("orders:create"),
            data=json.dumps(
                {
                    "restaurant_slug": self.dish.restaurant.slug,
                    "payment_method": Payment.Method.CARD,
                    "items": [
                        {
                            "dish_id": self.dish.id,
                            "quantity": 1,
                        }
                    ],
                }
            ),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "order_mode_required")
        self.assertEqual(Order.objects.count(), 0)

    def test_qr_order_rejects_invalid_unknown_and_revoked_tokens(self):
        revoked_table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="13",
            is_active=False,
        )
        revoked_table_token = revoked_table.plain_qr_token
        base_payload = {
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 1,
                }
            ],
        }
        cases = [
            ("not a token", 400, "invalid_table_token"),
            ("missing-token", 404, "table_token_not_found"),
            (revoked_table_token, 410, "table_token_revoked"),
        ]

        for token, status_code, error_code in cases:
            with self.subTest(token=token):
                payload = {
                    **base_payload,
                    "table_token": token,
                }
                response = self.client.post(
                    reverse("orders:create"),
                    data=json.dumps(payload),
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=self.next_idempotency_key(),
                )

                self.assertEqual(response.status_code, status_code)
                self.assertEqual(response.json()["code"], error_code)

        self.assertEqual(Order.objects.count(), 0)

    def test_table_qr_token_is_long_and_stored_as_hash(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="14",
        )
        token = table.plain_qr_token

        self.assertGreaterEqual(len(token), 32)
        self.assertNotEqual(table.qr_token_hash, token)
        self.assertEqual(table.qr_token_hash, hash_table_qr_token(token))
        self.assertEqual(table.qr_token_version, 1)
        self.assertEqual(table.qr_token_kind, "current")
        self.assertIsNotNone(table.qr_token_created_at)
        self.assertFalse(hasattr(table, "qr_token"))
        audit_event = table.qr_token_audit_events.get()
        self.assertEqual(audit_event.action, TableQrTokenAudit.Action.ISSUED)
        self.assertEqual(audit_event.token_hash, table.qr_token_hash)

    def test_rotating_qr_token_revokes_previous_token(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="15",
        )
        old_token = table.plain_qr_token
        old_hash = table.qr_token_hash

        new_token = table.rotate_qr_token(reason="Compromised QR")
        table.refresh_from_db()

        self.assertNotEqual(new_token, old_token)
        self.assertNotEqual(table.qr_token_hash, old_hash)
        self.assertEqual(table.qr_token_version, 2)
        self.assertIsNotNone(table.qr_token_rotated_at)
        self.assertIsNone(table.qr_token_revoked_at)
        self.assertTrue(
            table.qr_token_audit_events.filter(
                action=TableQrTokenAudit.Action.REVOKED,
                token_hash=old_hash,
            ).exists()
        )

        old_response = self.client.get(reverse("menu:table_menu", args=[old_token]))
        new_response = self.client.get(reverse("menu:table_menu", args=[new_token]))

        self.assertEqual(old_response.status_code, 410)
        self.assertEqual(new_response.status_code, 200)

    def test_expired_qr_token_is_rejected(self):
        table = Table.objects.create(
            restaurant=self.dish.restaurant,
            number="16",
        )
        token = table.plain_qr_token
        table.qr_token_expires_at = timezone.now() - timedelta(minutes=1)
        table.save(update_fields=["qr_token_expires_at"])

        response = self.client.post(
            reverse("orders:create"),
            data=json.dumps(
                {
                    "payment_method": Payment.Method.CARD,
                    "table_token": token,
                    "items": [
                        {
                            "dish_id": self.dish.id,
                            "quantity": 1,
                        }
                    ],
                }
            ),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["code"], "table_token_expired")
        self.assertEqual(Order.objects.count(), 0)

    def test_create_order_requires_idempotency_key(self):
        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "idempotency_key_required")
        self.assertEqual(Order.objects.count(), 0)

    def test_create_order_requires_quote_id_for_new_order(self):
        response = self.client.post(
            reverse("orders:create"),
            data=json.dumps(
                {
                    "restaurant_slug": self.dish.restaurant.slug,
                    "order_source": "counter",
                    "payment_method": Payment.Method.CARD,
                    "items": [
                        {
                            "dish_id": self.dish.id,
                            "quantity": 1,
                        }
                    ],
                }
            ),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "quote_required")
        self.assertEqual(Order.objects.count(), 0)

    def test_create_order_rejects_changed_price_after_quote(self):
        payload = {
            "restaurant_slug": self.dish.restaurant.slug,
            "order_source": "counter",
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 1,
                }
            ],
        }
        quote_response = self.post_json(reverse("orders:quote"), payload)
        quote_data = quote_response.json()
        self.dish.price = Decimal("175.00")
        self.dish.save(update_fields=["price"])

        response = self.client.post(
            reverse("orders:create"),
            data=json.dumps(
                {
                    **payload,
                    "quote_id": quote_data["quote_id"],
                    "pricing_revision": quote_data["pricing_revision"],
                    "quote_fingerprint": quote_data["fingerprint"],
                }
            ),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "quote_changed")
        self.assertEqual(Order.objects.count(), 0)

    def test_create_order_replays_existing_order_for_same_idempotency_key_and_payload(self):
        payload = {
            "payment_method": Payment.Method.CARD,
            "guests_count": 2,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 2,
                }
            ],
        }
        key = self.next_idempotency_key()

        first_response = self.post_json(reverse("orders:create"), payload, idempotency_key=key)
        second_response = self.post_json(reverse("orders:create"), payload, idempotency_key=key)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.json()["idempotency_replayed"])
        self.assertEqual(first_response.json()["order"]["id"], second_response.json()["order"]["id"])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Order.objects.get().items.count(), 1)

    def test_idempotent_replay_returns_existing_order_without_revalidating_menu(self):
        payload = {
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 1,
                }
            ],
        }
        key = self.next_idempotency_key()

        first_response = self.post_json(reverse("orders:create"), payload, idempotency_key=key)
        self.dish.is_available = False
        self.dish.save(update_fields=["is_available"])

        with patch("orders.services._get_dishes_by_id", wraps=order_services._get_dishes_by_id) as get_dishes_mock:
            second_response = self.client.post(
                reverse("orders:create"),
                data=json.dumps(
                    {
                        **payload,
                        "restaurant_slug": self.dish.restaurant.slug,
                        "order_source": "counter",
                    }
                ),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.json()["idempotency_replayed"])
        self.assertEqual(get_dishes_mock.call_count, 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_create_order_rejects_same_idempotency_key_with_different_payload(self):
        key = self.next_idempotency_key()

        first_response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": self.dish.id,
                        "quantity": 1,
                    }
                ],
            },
            idempotency_key=key,
        )
        second_response = self.post_json(
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
            idempotency_key=key,
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 409)
        self.assertEqual(second_response.json()["code"], "idempotency_conflict")
        self.assertEqual(Order.objects.count(), 1)

    def test_same_idempotency_key_is_scoped_per_guest_session(self):
        payload = {
            "restaurant_slug": self.dish.restaurant.slug,
            "order_source": "counter",
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 1,
                }
            ],
        }
        key = "shared-key"
        other_client = Client(HTTP_HOST="localhost")

        first_quote = self.client.post(
            reverse("orders:quote"),
            data=json.dumps(payload),
            content_type="application/json",
        ).json()
        first_response = self.client.post(
            reverse("orders:create"),
            data=json.dumps({**payload, "quote_id": first_quote["quote_id"]}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

        second_quote = other_client.post(
            reverse("orders:quote"),
            data=json.dumps(payload),
            content_type="application/json",
        ).json()
        second_response = other_client.post(
            reverse("orders:create"),
            data=json.dumps({**payload, "quote_id": second_quote["quote_id"]}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(Order.objects.count(), 2)
        self.assertNotEqual(
            first_response.json()["order"]["id"],
            second_response.json()["order"]["id"],
        )

    def test_integrity_error_without_matching_idempotency_record_is_reraised(self):
        payload = {
            "restaurant_slug": self.dish.restaurant.slug,
            "order_source": "counter",
            "payment_method": Payment.Method.CARD,
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 1,
                }
            ],
        }
        quote = order_services.quote_cart(payload)

        with patch.object(Order.objects, "create", side_effect=IntegrityError("other constraint")):
            with self.assertRaises(IntegrityError):
                order_services.create_order_from_payload(
                    {
                        **payload,
                        "quote_id": quote["quote_id"],
                        "idempotency_key": self.next_idempotency_key(),
                    },
                    request=None,
                )

    def test_create_order_rejects_dish_from_another_restaurant(self):
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
            name="Second restaurant dish",
            price=Decimal("300.00"),
            is_active=True,
            is_available=True,
        )

        response = self.post_json(
            reverse("orders:create"),
            {
                "payment_method": Payment.Method.CARD,
                "items": [
                    {
                        "dish_id": second_dish.id,
                        "quantity": 1,
                    }
                ],
            },
            idempotency_key=self.next_idempotency_key(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "dish_unavailable")
        self.assertEqual(Order.objects.count(), 0)

    @override_settings(
        RATE_LIMIT_RULES={
            "orders:quote": {
                "methods": ["POST"],
                "identity": "ip",
                "limits": [
                    {
                        "name": "test",
                        "limit": 1,
                        "window": 60,
                    }
                ],
            }
        }
    )
    def test_quote_endpoint_returns_json_rate_limit_response(self):
        cache.clear()
        payload = {
            "items": [
                {
                    "dish_id": self.dish.id,
                    "quantity": 1,
                }
            ],
        }

        first_response = self.post_json(reverse("orders:quote"), payload)
        second_response = self.post_json(reverse("orders:quote"), payload)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 429)
        self.assertEqual(second_response["Retry-After"], "60")
        self.assertEqual(second_response.json()["code"], "rate_limited")


class OrderStatusTransitionTests(TestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(
            name="Caesar Test",
            slug="caesar-test",
        )
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            subtotal_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
        )

    def test_transition_service_updates_status_version_timestamps_and_history(self):
        user = get_user_model().objects.create_user(
            email="status@example.com",
            password="password-123",
        )

        updated_order = transition_order(
            self.order,
            Order.Status.CONFIRMED,
            expected_version=0,
            actor=user,
            reason="Kitchen accepted",
        )

        self.assertEqual(updated_order.status, Order.Status.CONFIRMED)
        self.assertEqual(updated_order.version, 1)
        self.assertIsNotNone(updated_order.confirmed_at)

        history = OrderStatusHistory.objects.get(order=self.order)
        self.assertEqual(history.from_status, Order.Status.CREATED)
        self.assertEqual(history.to_status, Order.Status.CONFIRMED)
        self.assertEqual(history.changed_by, user)
        self.assertEqual(history.reason, "Kitchen accepted")
        self.assertEqual(history.order_version, 1)

    def test_transition_service_rejects_skipped_statuses(self):
        with self.assertRaises(OrderTransitionError):
            transition_order(self.order, Order.Status.COMPLETED, expected_version=0)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CREATED)
        self.assertEqual(self.order.version, 0)
        self.assertFalse(OrderStatusHistory.objects.exists())

    def test_transition_service_rejects_too_long_reason(self):
        with self.assertRaises(OrderTransitionError):
            transition_order(
                self.order,
                Order.Status.CONFIRMED,
                expected_version=0,
                reason="x" * 256,
            )

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CREATED)
        self.assertFalse(OrderStatusHistory.objects.exists())

    def test_transition_service_uses_optimistic_locking(self):
        transition_order(self.order, Order.Status.CONFIRMED, expected_version=0)

        with self.assertRaises(OrderVersionConflict):
            transition_order(self.order.id, Order.Status.COOKING, expected_version=0)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.order.version, 1)
        self.assertEqual(OrderStatusHistory.objects.count(), 1)

    def test_direct_model_save_cannot_change_status(self):
        self.order.status = Order.Status.COMPLETED

        with self.assertRaises(ValueError):
            self.order.save()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CREATED)

    def test_queryset_update_cannot_change_status(self):
        with self.assertRaises(ValueError):
            Order.objects.filter(id=self.order.id).update(status=Order.Status.COMPLETED)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CREATED)

    def test_model_transition_to_uses_service(self):
        self.order.transition_to(Order.Status.CONFIRMED)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.order.version, 1)
        self.assertEqual(
            self.order.status_history.get().to_status,
            Order.Status.CONFIRMED,
        )

    def test_status_history_is_append_only(self):
        self.order.transition_to(Order.Status.CONFIRMED)
        history = self.order.status_history.get()

        history.reason = "changed later"
        with self.assertRaises(ValueError):
            history.save()

        with self.assertRaises(ValueError):
            history.delete()

    def test_order_admin_makes_status_and_version_readonly(self):
        order_admin = OrderAdmin(Order, admin.site)

        readonly_fields = order_admin.get_readonly_fields(request=None, obj=self.order)

        self.assertIn("status", readonly_fields)
        self.assertIn("version", readonly_fields)
