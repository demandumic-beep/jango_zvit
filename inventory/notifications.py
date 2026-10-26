"""Листи клієнтам про зміну статусу замовлення."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import connection

logger = logging.getLogger(__name__)

# Що написати клієнту для кожного статусу замовлення.
STATUS_TEXT = {
    "Очікує": "Ваше замовлення прийнято й очікує на обробку.",
    "В обробці": "Ваше замовлення в обробці: ми зібрали товар і передали його в доставку, посилка вже в дорозі.",
    "Доставлено": "Ваше замовлення доставлено. Дякуємо за покупку!",
    "Скасовано": "Ваше замовлення скасовано. Якщо це сталося помилково, напишіть нам у розділі «Підтримка».",
}


def _load_order(order_id):
    """Бере з бази дані клієнта, суму, доставку й товари замовлення."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.full_name, c.email, o.total_amount,
                   d.delivery_method, d.delivery_address,
                   d.tracking_number, d.delivery_date
            FROM orders o
            JOIN clients c ON c.client_id = o.client_id
            LEFT JOIN deliveries d ON d.order_id = o.order_id
            WHERE o.order_id = %s
            LIMIT 1
            """,
            [order_id],
        )
        head = cursor.fetchone()
        if not head:
            return None
        cursor.execute(
            """
            SELECT p.name, oi.quantity, oi.price
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            WHERE oi.order_id = %s
            """,
            [order_id],
        )
        items = cursor.fetchall()
    return head, items


def send_order_status_email(order_id, status):
    """
    Надсилає клієнту лист про новий статус замовлення.
    Повертає True, якщо лист відправлено, і False, якщо пошти немає або сталася помилка.
    Помилка пошти не повинна ламати роботу сайту, тому її лише записуємо в журнал.
    """
    loaded = _load_order(order_id)
    if not loaded:
        return False
    (name, email, total, method, address, tracking, date_), items = loaded
    if not email:
        return False

    lines = [
        f"Вітаємо, {name}!",
        "",
        STATUS_TEXT.get(status, f"Статус вашого замовлення змінено на «{status}»."),
        "",
        f"Замовлення №{order_id}",
        f"Статус: {status}",
    ]
    for product, quantity, price in items:
        lines.append(f" - {product}: {quantity} шт. x {price} грн")
    lines.append(f"Сума: {total} грн")
    if method:
        lines.append(f"Доставка: {method}")
    if address:
        lines.append(f"Адреса: {address}")
    if tracking:
        lines.append(f"Трек-номер: {tracking}")
    if date_:
        lines.append(f"Орієнтовна дата: {date_:%d.%m.%Y}")
    lines += ["", "З повагою,", "команда StockLogix"]

    try:
        send_mail(
            subject=f"StockLogix: замовлення №{order_id}, {status}",
            message="\n".join(lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Не вдалося надіслати лист про замовлення %s", order_id)
        return False
    return True
