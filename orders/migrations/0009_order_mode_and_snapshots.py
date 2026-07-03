from django.db import migrations, models
from django.db.models import Q


ORDER_SNAPSHOT_FIELDS = [
    "order_mode",
    "restaurant_name_snapshot",
    "restaurant_slug_snapshot",
    "table_number_snapshot",
    "table_title_snapshot",
]

ORDER_ITEM_SNAPSHOT_FIELDS = [
    "dish_code_snapshot",
    "category_name_snapshot",
    "category_code_snapshot",
]


def _flush(model, objects, fields, using):
    if not objects:
        return

    model.objects.using(using).bulk_update(
        objects,
        fields,
        batch_size=500,
    )
    objects.clear()


def populate_order_snapshots(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    OrderItem = apps.get_model("orders", "OrderItem")
    using = schema_editor.connection.alias

    orders_to_update = []
    orders = (
        Order.objects.using(using)
        .select_related("restaurant", "table")
        .all()
    )

    for order in orders.iterator(chunk_size=500):
        restaurant = order.restaurant
        table = order.table

        order.order_mode = "table" if table is not None else "legacy"
        order.restaurant_name_snapshot = (
            restaurant.name or f"Restaurant #{restaurant.pk}"
        )
        order.restaurant_slug_snapshot = (
            restaurant.slug or f"restaurant-{restaurant.pk}"
        )
        order.table_number_snapshot = (
            (table.number or f"table-{table.pk}")
            if table is not None
            else ""
        )
        order.table_title_snapshot = table.title if table is not None else ""
        orders_to_update.append(order)

        if len(orders_to_update) >= 500:
            _flush(
                Order,
                orders_to_update,
                ORDER_SNAPSHOT_FIELDS,
                using,
            )

    _flush(
        Order,
        orders_to_update,
        ORDER_SNAPSHOT_FIELDS,
        using,
    )

    items_to_update = []
    items = (
        OrderItem.objects.using(using)
        .select_related("dish", "dish__category")
        .all()
    )

    for item in items.iterator(chunk_size=500):
        dish = item.dish
        category = dish.category

        item.dish_code_snapshot = dish.code or f"dish-{dish.pk}"
        item.category_name_snapshot = category.name if category is not None else ""
        item.category_code_snapshot = category.code if category is not None else ""
        items_to_update.append(item)

        if len(items_to_update) >= 500:
            _flush(
                OrderItem,
                items_to_update,
                ORDER_ITEM_SNAPSHOT_FIELDS,
                using,
            )

    _flush(
        OrderItem,
        items_to_update,
        ORDER_ITEM_SNAPSHOT_FIELDS,
        using,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0008_order_history_and_money_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="order_mode",
            field=models.CharField(
                choices=[
                    ("legacy", "Старый формат"),
                    ("table", "За столом"),
                    ("pickup", "Самовывоз"),
                    ("counter", "У стойки"),
                    ("delivery", "Доставка"),
                ],
                db_index=True,
                default="legacy",
                max_length=20,
                verbose_name="Режим заказа",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="restaurant_name_snapshot",
            field=models.CharField(
                blank=True,
                max_length=160,
                verbose_name="Название ресторана при заказе",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="restaurant_slug_snapshot",
            field=models.SlugField(
                blank=True,
                max_length=180,
                verbose_name="Код ресторана при заказе",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="table_number_snapshot",
            field=models.CharField(
                blank=True,
                max_length=24,
                verbose_name="Номер стола при заказе",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="table_title_snapshot",
            field=models.CharField(
                blank=True,
                max_length=80,
                verbose_name="Название стола при заказе",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="dish_code_snapshot",
            field=models.SlugField(
                blank=True,
                max_length=220,
                verbose_name="Код блюда при заказе",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="category_name_snapshot",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="Категория при заказе",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="category_code_snapshot",
            field=models.SlugField(
                blank=True,
                max_length=200,
                verbose_name="Код категории при заказе",
            ),
        ),
        migrations.RunPython(
            populate_order_snapshots,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=Q(
                    order_mode__in=[
                        "legacy",
                        "table",
                        "pickup",
                        "counter",
                        "delivery",
                    ]
                ),
                name="order_mode_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=(
                    Q(order_mode="table")
                    & ~Q(table_number_snapshot="")
                )
                | (
                    ~Q(order_mode="table")
                    & Q(table__isnull=True)
                    & Q(table_number_snapshot="")
                    & Q(table_title_snapshot="")
                ),
                name="order_mode_table_consistency",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(restaurant_name_snapshot="")
                    & ~Q(restaurant_slug_snapshot="")
                ),
                name="order_restaurant_snapshot_present",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(
                condition=~Q(dish_code_snapshot=""),
                name="order_item_dish_snapshot_present",
            ),
        ),
    ]
