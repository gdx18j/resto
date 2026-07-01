"""
Интеграция с ЮKassa.

В тестовом режиме нужно:
1. Зарегистрироваться на https://yookassa.ru/ (обычным пользователем, без ИП)
2. Включить тестовый магазин в личном кабинете
3. Скопировать shopId и тестовый секретный ключ
4. Положить их в .env:
       YOOKASSA_SHOP_ID=ваш_id
       YOOKASSA_SECRET_KEY=ваш_тестовый_ключ
5. Тестовые карты для проверки оплаты:
       успешная оплата:  5555 5555 5555 4444, любой CVC, любая будущая дата
       отклонённая:      5555 5555 5555 4477

Когда появится ИП/самозанятость — просто меняете значения в .env
на боевые ключи, остальной код трогать не нужно.
"""

import uuid

from django.conf import settings

try:
    from yookassa import Configuration, Payment
    YOOKASSA_AVAILABLE = True
except ImportError:
    YOOKASSA_AVAILABLE = False


def _configure():
    if not YOOKASSA_AVAILABLE:
        raise RuntimeError(
            "Пакет yookassa не установлен. Выполните: pip install yookassa"
        )
    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY


def create_payment(order, return_url):
    """Создаёт платёж в ЮKassa и возвращает ссылку на страницу оплаты.

    На этой странице ЮKassa сама показывает гостю выбор способа:
    - оплата картой (открывается форма ввода карты)
    - оплата по СБП (показывается QR-код для сканирования банковским приложением)

    Поэтому отдельно генерировать свой QR для ПК-версии не нужно —
    он уже встроен в эту страницу.

    Если включён settings.YOOKASSA_MOCK — вместо реального запроса
    в ЮKassa возвращаем ссылку на локальную страницу-симулятор оплаты
    (см. orders.views.mock_pay).
    """
    if settings.YOOKASSA_MOCK:
        return create_mock_payment(order)

    _configure()

    table_label = order.table.number if order.table else "—"

    payment = Payment.create(
        {
            "amount": {
                "value": f"{order.total:.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "capture": True,
            "description": f"Заказ №{order.id}, стол {table_label}",
            "metadata": {
                "order_id": str(order.id),
            },
        },
        uuid.uuid4(),  # ключ идемпотентности — защита от повторного списания при повторном клике
    )

    order.yookassa_payment_id = payment.id
    order.status = order.STATUS_PENDING
    order.save(update_fields=["yookassa_payment_id", "status"])

    return payment.confirmation.confirmation_url


def fetch_payment(payment_id):
    """Получить актуальный статус платежа из ЮKassa (на случай если
    вебхук не дошёл и нужно сверить статус вручную)."""
    _configure()
    return Payment.find_one(payment_id)


def create_mock_payment(order):
    """Заглушка вместо реального создания платежа в ЮKassa.

    Помечает заказ как "ожидает оплаты" и присваивает ему
    фейковый payment_id с префиксом mock_, чтобы его можно было
    отличить от настоящих платежей ЮKassa (например, в вебхуке).
    Возвращает относительный URL на страницу-симулятор оплаты.
    """
    from django.urls import reverse

    order.yookassa_payment_id = f"mock_{uuid.uuid4().hex[:16]}"
    order.status = order.STATUS_PENDING
    order.save(update_fields=["yookassa_payment_id", "status"])

    return reverse("orders:mock_pay", args=[order.id])
