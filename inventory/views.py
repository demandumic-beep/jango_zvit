import logging
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db import connection, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse

from .access import CLIENT_COOKIE, PREVIEW_COOKIE, is_staff, staff_required
from .notifications import send_order_status_email

logger = logging.getLogger(__name__)

PAGE_SIZE = 25

TABLES = {
    "categories": "Категорії",
    "warehouses": "Склади",
    "warehouse_products": "Складські залишки",
    "clients": "Клієнти",
    "orders": "Замовлення",
    "order_items": "Товари в замовленнях",
    "deliveries": "Доставки",
}

LABELS = {
    "categories": {
        "category_id": "Код категорії",
        "name": "Назва категорії",
    },
    "warehouses": {
        "warehouse_id": "Код складу",
        "name": "Назва складу",
        "address": "Адреса",
    },
    "warehouse_products": {
        "warehouse_id": "Код складу",
        "product_id": "Код товару",
        "quantity": "Кількість",
    },
    "clients": {
        "client_id": "Код клієнта",
        "full_name": "ПІБ клієнта",
        "phone": "Телефон",
        "email": "Електронна пошта",
        "address": "Адреса",
    },
    "orders": {
        "order_id": "Код замовлення",
        "client_id": "Клієнт",
        "order_date": "Дата замовлення",
        "status": "Статус",
        "total_amount": "Сума замовлення",
    },
    "order_items": {
        "order_item_id": "Код позиції",
        "order_id": "Замовлення",
        "product_id": "Товар",
        "quantity": "Кількість",
        "price": "Ціна",
    },
    "deliveries": {
        "delivery_id": "Код доставки",
        "order_id": "Замовлення",
        "delivery_address": "Адреса доставки",
        "delivery_method": "Спосіб доставки",
        "tracking_number": "Номер відстеження",
        "status": "Статус доставки",
        "delivery_date": "Дата доставки",
    },
}

# Службові стовпці зі старої схеми (циклічні зв'язки): у інтерфейсі їх не показуємо.
HIDDEN_COLUMNS = {
    "warehouses": {"warehouse_products_warehouse_id", "warehouse_products_product_id"},
    "clients": {"orders_order_id"},
    "orders": {"order_items_order_item_id", "deliveries_delivery_id"},
}

ORDER_STATUSES = ["Очікує", "В обробці","Відправлено","Доставлено", "Скасовано"]
DELIVERY_STATUSES = ["Очікує", "В дорозі","Відправлено","Доставлено", "Скасовано"]

STATUS_CHOICES = {
    ("orders", "status"): ORDER_STATUSES,
    ("deliveries", "status"): DELIVERY_STATUSES,
}

# (таблиця, поле) -> (таблиця-довідник, поле-ключ, поле-підпис)
FK_LOOKUPS = {
    ("orders", "client_id"): ("clients", "client_id", "full_name"),
    ("order_items", "order_id"): ("orders", "order_id", "order_id"),
    ("order_items", "product_id"): ("products", "product_id", "name"),
    ("deliveries", "order_id"): ("orders", "order_id", "order_id"),
}

# Логістика: ключ -> (назва, днів до доставки, потрібна адреса)
DELIVERY_METHODS = {
    "nova": ("Нова пошта", 2, True),
    "ukr": ("Укрпошта", 4, True),
    "courier": ("Кур'єр по Львову", 1, True),
    "pickup": ("Самовивіз зі складу", 0, False),
}


class OrderError(Exception):
    """Помилка, текст якої безпечно показувати користувачу."""


# ---------------------------------------------------------------- допоміжні

def _text(value):
    return value.decode() if isinstance(value, bytes) else value


def _schema(table):
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        return [tuple(_text(x) for x in row) for row in cursor.fetchall()]


def _visible_schema(table):
    hidden = HIDDEN_COLUMNS.get(table, set())
    return [col for col in _schema(table) if col[0] not in hidden]


@lru_cache(maxsize=None)
def _has_image_column():
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(
            cursor, "products"
        )
    return any(column.name == "image" for column in columns)


def _img(alias="p"):
    return f"{alias}.image" if _has_image_column() else "NULL"


def _require_table(table):
    if table not in TABLES:
        raise Http404("Розділ не знайдено")


def _badge(status):
    if status == "Доставлено":
        return "delivered"
    if status in ("Очікує", "Скасовано"):
        return "pending"
    return "processing"


def _pager(request, total):
    try:
        page = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 1), pages)
    return {
        "page": page,
        "pages": pages,
        "offset": (page - 1) * PAGE_SIZE,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev": page - 1,
        "next": page + 1,
    }


def _norm_phone(raw):
    cleaned = re.sub(r"[^\d+]", "", raw or "")
    if cleaned.startswith("0") and len(cleaned) == 10:
        cleaned = "+38" + cleaned
    elif cleaned.startswith("380"):
        cleaned = "+" + cleaned
    if not re.fullmatch(r"\+\d{11,13}", cleaned):
        raise OrderError("Вкажіть телефон у форматі +380XXXXXXXXX.")
    return cleaned


def _check_email(raw):
    raw = (raw or "").strip()
    if raw and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
        raise OrderError("Перевірте електронну пошту.")
    return raw


# ---------------------------------------------------------------- дашборд

@staff_required
def dashboard(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM products")
        products_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM orders WHERE status NOT IN (%s, %s)",
            ["Доставлено", "Скасовано"],
        )
        active_orders = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status NOT IN (%s, %s)",
            ["Доставлено", "Скасовано"],
        )
        pending_deliveries = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM clients")
        clients_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT o.order_id, COALESCE(c.full_name, '—'), o.total_amount,
                   o.status
            FROM orders o
            LEFT JOIN clients c ON c.client_id = o.client_id
            ORDER BY o.order_id DESC
            LIMIT 5
            """
        )
        recent_orders = [
            {"id": r[0], "client": r[1], "total": r[2], "status": r[3],
             "badge": _badge(r[3])}
            for r in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT COALESCE(SUM(q), 0),
                   COALESCE(SUM(q > 5), 0),
                   COALESCE(SUM(q BETWEEN 1 AND 5), 0),
                   COALESCE(SUM(q = 0), 0),
                   COUNT(*)
            FROM (
                SELECT p.product_id, COALESCE(SUM(wp.quantity), 0) AS q
                FROM products p
                LEFT JOIN warehouse_products wp ON wp.product_id = p.product_id
                GROUP BY p.product_id
            ) t
            """
        )
        units, normal, low, empty, total = [int(x) for x in cursor.fetchone()]

    def pct(value):
        return round(value * 100 / total) if total else 0

    return render(request, "inventory/dashboard.html", {
        "active_page": "dashboard",
        "products_count": products_count,
        "active_orders": active_orders,
        "pending_deliveries": pending_deliveries,
        "clients_count": clients_count,
        "recent_orders": recent_orders,
        "units": units,
        "normal_pct": pct(normal),
        "low_pct": pct(low),
        "empty_pct": pct(empty),
        "need_restock": low + empty,
    })


# ---------------------------------------------------------------- товари

@staff_required
def products(request):
    search = request.GET.get("q", "").strip()

    sql = f"""
        SELECT p.product_id, p.name, c.name, p.price,
               COALESCE(SUM(wp.quantity), 0), {_img()}
        FROM products p
        LEFT JOIN categories c ON c.category_id = p.category_id
        LEFT JOIN warehouse_products wp ON wp.product_id = p.product_id
    """
    params = []

    if search:
        sql += """
            WHERE p.name LIKE %s OR c.name LIKE %s
            OR CAST(p.product_id AS CHAR) LIKE %s
        """
        params = [f"%{search}%"] * 3

    sql += """
        GROUP BY p.product_id, p.name, c.name, p.price
        ORDER BY p.product_id DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    items = [{
        "id": row[0],
        "name": row[1],
        "category": row[2] or "Без категорії",
        "price": row[3],
        "quantity": int(row[4]),
        "image": row[5],
    } for row in rows]

    return render(request, "inventory/products.html", {
        "active_page": "products",
        "items": items,
        "search": search,
        "total_products": len(items),
        "low_stock": sum(1 for x in items if 0 < x["quantity"] <= 5),
        "out_of_stock": sum(1 for x in items if x["quantity"] == 0),
        "total_units": sum(x["quantity"] for x in items),
    })


MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_DIR = "products"


class PhotoError(ValueError):
    """Помилка з фото, текст якої безпечно показувати адміністратору."""


def _detect_image_ext(head):
    """Визначає тип зображення за вмістом файлу, а не за іменем."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _save_photo(upload):
    """Зберігає фото з комп'ютера в MEDIA_ROOT/products, повертає шлях для БД."""
    if upload.size > MAX_PHOTO_BYTES:
        raise PhotoError("Фото завелике: максимум 5 МБ.")
    head = upload.read(16)
    upload.seek(0)
    ext = _detect_image_ext(head)
    if not ext:
        raise PhotoError("Підтримуються лише фото JPG, PNG, WEBP або GIF.")

    folder = Path(settings.MEDIA_ROOT) / PHOTO_DIR
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    with open(folder / filename, "wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    return f"{settings.MEDIA_URL}{PHOTO_DIR}/{filename}"


def _delete_photo(path):
    """Видаляє файл фото, але лише якщо він був завантажений через сайт."""
    prefix = f"{settings.MEDIA_URL}{PHOTO_DIR}/"
    if not path or not str(path).startswith(prefix):
        return
    target = Path(settings.MEDIA_ROOT) / PHOTO_DIR / Path(str(path)).name
    try:
        target.unlink(missing_ok=True)
    except OSError:
        logger.warning("Не вдалося видалити файл %s", target)


def _read_product_form(request, category_ids):
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()

    if not name or len(name) > 150:
        raise ValueError
    if len(description) > 255:
        raise ValueError

    price = Decimal(request.POST.get("price", "").strip())
    if not price.is_finite() or price < 0:
        raise ValueError

    category_id = int(request.POST.get("category_id", "").strip())
    if category_id not in category_ids:
        raise ValueError

    return category_id, name, description or None, price


@staff_required
def add_product(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT category_id, name FROM categories ORDER BY name")
        categories = cursor.fetchall()

    if request.method == "POST":
        image = None
        try:
            category_id, name, description, price = _read_product_form(
                request, [c[0] for c in categories]
            )
            upload = request.FILES.get("image_file")
            if upload and _has_image_column():
                image = _save_photo(upload)
            try:
                with connection.cursor() as cursor:
                    if _has_image_column():
                        cursor.execute(
                            "INSERT INTO products "
                            "(category_id, name, description, price, image) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            [category_id, name, description, price, image],
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO products "
                            "(category_id, name, description, price) "
                            "VALUES (%s, %s, %s, %s)",
                            [category_id, name, description, price],
                        )
            except Exception:
                _delete_photo(image)
                raise
            messages.success(request, "Товар успішно додано.")
            return redirect("products")
        except PhotoError as exc:
            messages.error(request, str(exc))
        except (ValueError, InvalidOperation, TypeError):
            messages.error(request, "Перевір назву, категорію та ціну.")

    return render(request, "inventory/add_product.html", {
        "active_page": "products",
        "categories": categories,
        "posted": request.POST if request.method == "POST" else None,
        "has_image": _has_image_column(),
    })


@staff_required
def edit_product(request, product_id):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT product_id, category_id, name, description, price, "
            f"{_img('products')} FROM products WHERE product_id = %s",
            [product_id],
        )
        product = cursor.fetchone()

        cursor.execute("SELECT category_id, name FROM categories ORDER BY name")
        categories = cursor.fetchall()

    if not product:
        raise Http404("Товар не знайдено")

    if request.method == "POST":
        old_image = product[5]
        new_file = None
        try:
            category_id, name, description, price = _read_product_form(
                request, [c[0] for c in categories]
            )
            image = old_image
            upload = request.FILES.get("image_file")
            if upload and _has_image_column():
                new_file = _save_photo(upload)
                image = new_file
            elif request.POST.get("remove_photo"):
                image = None
            try:
                with connection.cursor() as cursor:
                    if _has_image_column():
                        cursor.execute(
                            "UPDATE products SET category_id=%s, name=%s, "
                            "description=%s, price=%s, image=%s "
                            "WHERE product_id=%s",
                            [category_id, name, description, price, image,
                             product_id],
                        )
                    else:
                        cursor.execute(
                            "UPDATE products SET category_id=%s, name=%s, "
                            "description=%s, price=%s WHERE product_id=%s",
                            [category_id, name, description, price, product_id],
                        )
            except Exception:
                _delete_photo(new_file)
                raise
            if image != old_image:
                _delete_photo(old_image)
            messages.success(request, "Товар оновлено.")
            return redirect("products")
        except PhotoError as exc:
            messages.error(request, str(exc))
        except (ValueError, InvalidOperation, TypeError):
            messages.error(request, "Перевір правильність заповнення полів.")

    return render(request, "inventory/edit_product.html", {
        "active_page": "products",
        "product": product,
        "categories": categories,
        "has_image": _has_image_column(),
    })


@require_POST
@staff_required
def delete_product(request, product_id):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_img('products')} FROM products WHERE product_id=%s",
                    [product_id],
                )
                row = cursor.fetchone()
                cursor.execute(
                    "DELETE FROM products WHERE product_id=%s", [product_id]
                )
        if row:
            _delete_photo(row[0])
        messages.success(request, "Товар видалено.")
    except Exception:
        logger.exception("Не вдалося видалити товар %s", product_id)
        messages.error(
            request,
            "Не вдалося видалити товар: він використаний у замовленнях "
            "або у складських залишках.",
        )
    return redirect("products")


# ---------------------------------------------------------------- довільні таблиці

@staff_required
def manage_table(request, table):
    _require_table(table)

    full_schema = _schema(table)
    schema = _visible_schema(table)
    columns = [col[0] for col in schema]
    pks = [col[0] for col in full_schema if col[3] == "PRI"]
    pk = pks[0] if len(pks) == 1 and pks[0] in columns else None

    search = request.GET.get("q", "").strip()
    where = ""
    params = []
    if search:
        where = " WHERE " + " OR ".join(
            f"CAST(`{col}` AS CHAR) LIKE %s" for col in columns
        )
        params = [f"%{search}%"] * len(columns)

    cols_sql = ", ".join(f"`{col}`" for col in columns)
    order_by = f"`{pk}` DESC" if pk else f"`{columns[0]}`"

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`{where}", params)
        total = cursor.fetchone()[0]
        pager = _pager(request, total)
        cursor.execute(
            f"SELECT {cols_sql} FROM `{table}`{where} "
            f"ORDER BY {order_by} LIMIT %s OFFSET %s",
            params + [PAGE_SIZE, pager["offset"]],
        )
        rows = cursor.fetchall()

    pk_index = columns.index(pk) if pk else None
    records = [
        {"id": row[pk_index] if pk_index is not None else None,
         "values": list(row)}
        for row in rows
    ]

    return render(request, "inventory/manage_table.html", {
        "active_page": table,
        "table": table,
        "table_title": TABLES[table],
        "columns": columns,
        "column_labels": LABELS.get(table, {}),
        "records": records,
        "search": search,
        "total_records": total,
        "pager": pager,
    })


@staff_required
def add_record(request, table):
    return edit_record(request, table, None)


def _fk_options(table, id_col, label_col):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT `{id_col}`, `{label_col}` FROM `{table}` "
            f"ORDER BY `{id_col}`"
        )
        rows = cursor.fetchall()
    options = []
    for row_id, label in rows:
        text = f"№{row_id}" if id_col == label_col else f"{label} (№{row_id})"
        options.append({"value": str(row_id), "label": text})
    return options


def _build_field(table, col, existing, record_id):
    name, dtype, nullable, _key, default, extra = col
    dtype = dtype.lower()
    base = dtype.split("(")[0]

    field_type, kind, options, step = "text", "text", None, None

    if (table, name) in STATUS_CHOICES:
        field_type, kind = "select", "choice"
        options = [{"value": s, "label": s} for s in STATUS_CHOICES[(table, name)]]
    elif (table, name) in FK_LOOKUPS:
        field_type, kind = "select", "fk"
        options = _fk_options(*FK_LOOKUPS[(table, name)])
    elif base == "enum":
        field_type, kind = "select", "choice"
        values = re.findall(r"'((?:[^']|'')*)'", dtype)
        options = [{"value": v.replace("''", "'"), "label": v.replace("''", "'")}
                   for v in values]
    elif base in ("text", "mediumtext", "longtext"):
        field_type = "textarea"
    elif base == "date":
        field_type, kind = "date", "date"
    elif base in ("datetime", "timestamp"):
        field_type, kind = "datetime-local", "datetime"
    elif base == "time":
        field_type = "time"
    elif base in ("int", "integer", "smallint", "bigint", "tinyint", "mediumint"):
        field_type, kind, step = "number", "int", "1"
    elif base in ("decimal", "float", "double"):
        field_type, kind, step = "number", "decimal", "0.01"
    elif name in ("description", "address", "delivery_address"):
        field_type = "textarea"

    value = existing.get(name) if record_id is not None else default
    if value is None:
        value = ""
    elif kind == "date" and hasattr(value, "strftime"):
        value = value.strftime("%Y-%m-%d")
    elif kind == "datetime":
        if hasattr(value, "strftime"):
            value = value.strftime("%Y-%m-%dT%H:%M")
        elif "CURRENT_TIMESTAMP" in str(value).upper() or str(value).lower() == "now()":
            value = datetime.now().strftime("%Y-%m-%dT%H:%M")
        else:
            value = ""
    else:
        value = str(value)

    return {
        "name": name,
        "label": LABELS.get(table, {}).get(name, name),
        "type": field_type,
        "kind": kind,
        "value": value,
        "options": options,
        "step": step,
        "nullable": nullable,
        "required": (not nullable) and default is None,
        "help": "",
    }


def _convert(field, raw):
    kind = field["kind"]
    if kind == "int":
        number = int(raw)
        if number < 0:
            raise ValueError
        return number
    if kind == "decimal":
        number = Decimal(raw)
        if not number.is_finite() or number < 0:
            raise ValueError
        return number
    if kind == "date":
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    if kind == "datetime":
        raw = raw.replace("T", " ")
        if len(raw) == 16:
            raw += ":00"
        datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return raw
    if kind in ("fk", "choice"):
        allowed = [opt["value"] for opt in field["options"]]
        if raw not in allowed:
            raise ValueError
        return int(raw) if kind == "fk" else raw
    return raw


@staff_required
def edit_record(request, table, record_id=None):
    _require_table(table)

    schema = _schema(table)
    pks = [col[0] for col in schema if col[3] == "PRI"]
    if len(pks) != 1:
        messages.error(
            request,
            "Цю таблицю редагують на сторінці «Складські залишки».",
        )
        return redirect("manage_table", table=table)

    primary_key = pks[0]
    hidden = HIDDEN_COLUMNS.get(table, set())
    existing = {}

    if record_id is not None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM `{table}` WHERE `{primary_key}` = %s",
                [record_id],
            )
            row = cursor.fetchone()
            column_names = [c[0] for c in cursor.description]
        if row is None:
            raise Http404("Запис не знайдено")
        existing = dict(zip(column_names, row))

    fields = []
    for col in schema:
        name, extra = col[0], (col[5] or "").lower()
        if name == primary_key or name in hidden:
            continue
        if "auto_increment" in extra or "generated" in extra:
            continue
        fields.append(_build_field(table, col, existing, record_id))

    if request.method == "POST":
        values, errors = {}, []

        for field in fields:
            raw = request.POST.get(field["name"], "").strip()
            if raw == "":
                if field["required"]:
                    errors.append(f"Заповніть поле «{field['label']}».")
                elif record_id is not None and field["nullable"]:
                    values[field["name"]] = None
                continue
            try:
                values[field["name"]] = _convert(field, raw)
            except (ValueError, InvalidOperation):
                errors.append(f"Некоректне значення в полі «{field['label']}».")

        if not errors and not values:
            errors.append("Немає даних для збереження.")

        if not errors:
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        if record_id is None:
                            cols_sql = ", ".join(f"`{n}`" for n in values)
                            marks = ", ".join(["%s"] * len(values))
                            cursor.execute(
                                f"INSERT INTO `{table}` ({cols_sql}) "
                                f"VALUES ({marks})",
                                list(values.values()),
                            )
                        else:
                            assignments = ", ".join(f"`{n}` = %s" for n in values)
                            cursor.execute(
                                f"UPDATE `{table}` SET {assignments} "
                                f"WHERE `{primary_key}` = %s",
                                list(values.values()) + [record_id],
                            )
                messages.success(request, "Зміни успішно збережено.")
                return redirect("manage_table", table=table)
            except Exception:
                logger.exception("Помилка збереження запису в %s", table)
                messages.error(
                    request,
                    "Не вдалося зберегти запис. Перевірте, що пов'язані "
                    "записи існують і дані коректні.",
                )
        else:
            for error in errors:
                messages.error(request, error)

        for field in fields:
            field["value"] = request.POST.get(field["name"], "")

    return render(request, "inventory/edit_record.html", {
        "active_page": table,
        "table": table,
        "table_title": TABLES[table],
        "record_id": record_id,
        "fields": fields,
    })


@require_POST
@staff_required
def delete_record(request, table, record_id):
    _require_table(table)

    pks = [col[0] for col in _schema(table) if col[3] == "PRI"]
    if len(pks) != 1:
        raise Http404("Неможливо визначити ключ запису")

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM `{table}` WHERE `{pks[0]}` = %s", [record_id]
                )
        messages.success(request, "Запис видалено.")
    except Exception:
        logger.exception("Не вдалося видалити запис %s з %s", record_id, table)
        messages.error(
            request,
            "Запис не видалено: він пов'язаний з іншими даними.",
        )
    return redirect("manage_table", table=table)


# ---------------------------------------------------------------- склад

@staff_required
def manage_stock(request):
    if request.method == "POST":
        try:
            product_id = int(request.POST.get("product_id", ""))
            warehouse_id = int(request.POST.get("warehouse_id", ""))
            quantity = int(request.POST.get("quantity", "").strip())
            if quantity < 0:
                raise ValueError

            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM products WHERE product_id = %s",
                        [product_id],
                    )
                    if not cursor.fetchone():
                        raise ValueError
                    cursor.execute(
                        "SELECT 1 FROM warehouses WHERE warehouse_id = %s",
                        [warehouse_id],
                    )
                    if not cursor.fetchone():
                        raise ValueError
                    cursor.execute(
                        """
                        INSERT INTO warehouse_products
                            (warehouse_id, product_id, quantity)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE quantity = VALUES(quantity)
                        """,
                        [warehouse_id, product_id, quantity],
                    )
            messages.success(request, "Кількість товару збережено.")
        except (ValueError, TypeError):
            messages.error(
                request,
                "Перевірте товар, склад і кількість (ціле число від нуля).",
            )
        except Exception:
            logger.exception("Не вдалося зберегти залишок")
            messages.error(request, "Не вдалося зберегти залишок.")
        return redirect("manage_stock")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.product_id, p.name, p.price,
                   COALESCE(SUM(wp.quantity), 0) AS quantity
            FROM products p
            LEFT JOIN warehouse_products wp ON wp.product_id = p.product_id
            GROUP BY p.product_id, p.name, p.price
            ORDER BY p.name
            """
        )
        products_rows = cursor.fetchall()

        cursor.execute(
            "SELECT warehouse_id, name, address FROM warehouses ORDER BY name"
        )
        warehouses = cursor.fetchall()

        cursor.execute(
            """
            SELECT wp.warehouse_id, wp.product_id, p.name, w.name, wp.quantity
            FROM warehouse_products wp
            JOIN products p ON p.product_id = wp.product_id
            JOIN warehouses w ON w.warehouse_id = wp.warehouse_id
            ORDER BY w.name, p.name
            """
        )
        stock_records = cursor.fetchall()

    return render(request, "inventory/stock.html", {
        "active_page": "warehouse_products",
        "products": products_rows,
        "warehouses": warehouses,
        "stock_records": stock_records,
    })


@require_POST
@staff_required
def stock_delete(request, warehouse_id, product_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM warehouse_products "
                "WHERE warehouse_id = %s AND product_id = %s",
                [warehouse_id, product_id],
            )
        messages.success(request, "Запис залишку видалено.")
    except Exception:
        logger.exception("Не вдалося видалити залишок")
        messages.error(request, "Не вдалося видалити запис залишку.")
    return redirect("manage_stock")


# ---------------------------------------------------------------- замовлення (ядро)

def _find_or_create_client(cursor, name, phone, email, address):
    """Реєстрація клієнта: шукаємо за телефоном або поштою, інакше створюємо."""
    cursor.execute(
        "SELECT client_id FROM clients WHERE phone = %s "
        "OR (%s <> '' AND email = %s) LIMIT 1",
        [phone, email, email],
    )
    row = cursor.fetchone()
    if row:
        cursor.execute(
            "UPDATE clients SET full_name = %s, email = %s, address = %s "
            "WHERE client_id = %s",
            [name, email or None, address or None, row[0]],
        )
        return row[0]
    cursor.execute(
        "INSERT INTO clients (full_name, phone, email, address) "
        "VALUES (%s, %s, %s, %s)",
        [name, phone, email or None, address or None],
    )
    return cursor.lastrowid


def _allocate(cursor, product_id, quantity):
    """Бере товар зі складів (спочатку з найбільшим залишком) і списує його."""
    cursor.execute(
        """
        SELECT wp.warehouse_id, wp.quantity, w.name, w.address
        FROM warehouse_products wp
        JOIN warehouses w ON w.warehouse_id = wp.warehouse_id
        WHERE wp.product_id = %s AND wp.quantity > 0
        ORDER BY wp.quantity DESC
        FOR UPDATE
        """,
        [product_id],
    )
    stock = cursor.fetchall()
    available = sum(row[1] for row in stock)
    if available < quantity:
        raise OrderError(available)

    taken, left = [], quantity
    for warehouse_id, qty, wname, waddress in stock:
        if left == 0:
            break
        take = min(qty, left)
        cursor.execute(
            "UPDATE warehouse_products SET quantity = quantity - %s "
            "WHERE warehouse_id = %s AND product_id = %s",
            [take, warehouse_id, product_id],
        )
        taken.append((warehouse_id, take, wname, waddress))
        left -= take
    return taken


def _place_order(client_id, items, method_key, address):
    """
    Створює замовлення, позиції, доставку і списує залишки зі складів.
    items: {product_id: quantity}. Усе виконується однією транзакцією.
    """
    if method_key not in DELIVERY_METHODS:
        raise OrderError("Оберіть спосіб доставки.")
    method_name, days, needs_address = DELIVERY_METHODS[method_key]
    address = (address or "").strip()
    if needs_address and len(address) < 5:
        raise OrderError("Вкажіть адресу доставки.")
    if len(address) > 255:
        raise OrderError("Адреса задовга.")

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM clients WHERE client_id = %s", [client_id]
            )
            if not cursor.fetchone():
                raise OrderError("Клієнта не знайдено.")

            cursor.execute(
                "INSERT INTO orders (client_id, order_date, status, total_amount) "
                "VALUES (%s, NOW(), %s, 0)",
                [client_id, "Очікує"],
            )
            order_id = cursor.lastrowid
            total = Decimal("0")
            pickup_point = None

            for product_id, quantity in items.items():
                cursor.execute(
                    "SELECT name, price FROM products WHERE product_id = %s",
                    [product_id],
                )
                product = cursor.fetchone()
                if not product:
                    raise OrderError("Один із товарів більше не існує.")
                name, price = product

                try:
                    taken = _allocate(cursor, product_id, quantity)
                except OrderError as exc:
                    raise OrderError(
                        f"Недостатньо товару «{name}»: є {exc.args[0]} шт., "
                        f"потрібно {quantity}."
                    )

                if pickup_point is None and taken:
                    pickup_point = f"{taken[0][2]}, {taken[0][3] or ''}".strip(", ")

                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, price) "
                    "VALUES (%s, %s, %s, %s)",
                    [order_id, product_id, quantity, price],
                )
                total += price * quantity

            cursor.execute(
                "UPDATE orders SET total_amount = %s WHERE order_id = %s",
                [total, order_id],
            )

            if not needs_address:
                address = f"Самовивіз: {pickup_point or 'уточніть у менеджера'}"

            tracking = f"SL{date.today():%y%m%d}{order_id:05d}"
            cursor.execute(
                """
                INSERT INTO deliveries
                    (order_id, delivery_address, delivery_method,
                     tracking_number, status, delivery_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [order_id, address, method_name, tracking, "Очікує",
                 date.today() + timedelta(days=days)],
            )
    return order_id


def _collect_lines(post):
    lines = []
    for pid, qty in zip(post.getlist("product_id"), post.getlist("quantity")):
        pid, qty = pid.strip(), qty.strip()
        if pid or qty:
            lines.append({"product_id": pid, "quantity": qty})
    return lines


def _merge_lines(lines):
    merged = {}
    for line in lines:
        try:
            pid, qty = int(line["product_id"]), int(line["quantity"])
        except ValueError:
            raise OrderError("Перевірте товари та кількість у замовленні.")
        if qty <= 0 or qty > 999:
            raise OrderError("Кількість має бути від 1 до 999.")
        merged[pid] = merged.get(pid, 0) + qty
    if not merged:
        raise OrderError("Додайте хоча б один товар до замовлення.")
    return merged


# ---------------------------------------------------------------- замовлення (адмінка)

@staff_required
def orders_list(request):
    search = request.GET.get("q", "").strip()
    where, params = "", []
    if search:
        where = (
            " WHERE CAST(o.order_id AS CHAR) LIKE %s "
            "OR c.full_name LIKE %s OR o.status LIKE %s"
        )
        params = [f"%{search}%"] * 3

    base = " FROM orders o LEFT JOIN clients c ON c.client_id = o.client_id"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*){base}{where}", params)
        total = cursor.fetchone()[0]
        pager = _pager(request, total)
        cursor.execute(
            f"SELECT o.order_id, COALESCE(c.full_name, '—'), o.order_date, "
            f"o.total_amount, o.status{base}{where} "
            f"ORDER BY o.order_id DESC LIMIT %s OFFSET %s",
            params + [PAGE_SIZE, pager["offset"]],
        )
        rows = cursor.fetchall()

    orders = [
        {"id": r[0], "client": r[1], "date": r[2], "total": r[3],
         "status": r[4], "badge": _badge(r[4])}
        for r in rows
    ]
    return render(request, "inventory/orders.html", {
        "active_page": "orders",
        "orders": orders,
        "search": search,
        "total_records": total,
        "pager": pager,
    })


@staff_required
def order_detail(request, order_id):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT o.order_id, o.order_date, o.status, o.total_amount,
                   c.client_id, c.full_name, c.phone, c.email
            FROM orders o
            LEFT JOIN clients c ON c.client_id = o.client_id
            WHERE o.order_id = %s
            """,
            [order_id],
        )
        order = cursor.fetchone()
        if not order:
            raise Http404("Замовлення не знайдено")

        cursor.execute(
            """
            SELECT oi.product_id, p.name, oi.quantity, oi.price,
                   oi.quantity * oi.price
            FROM order_items oi
            LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE oi.order_id = %s
            """,
            [order_id],
        )
        items = cursor.fetchall()

        cursor.execute(
            "SELECT delivery_address, delivery_method, tracking_number, "
            "status, delivery_date FROM deliveries WHERE order_id = %s",
            [order_id],
        )
        deliveries = cursor.fetchall()

    return render(request, "inventory/order_detail.html", {
        "active_page": "orders",
        "order": order,
        "badge": _badge(order[2]),
        "items": items,
        "deliveries": deliveries,
        "statuses": ORDER_STATUSES,
    })


def _order_form_context():
    with connection.cursor() as cursor:
        cursor.execute("SELECT client_id, full_name FROM clients ORDER BY full_name")
        clients = [{"id": r[0], "name": r[1]} for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT p.product_id, p.name, p.price,
                   COALESCE(SUM(wp.quantity), 0)
            FROM products p
            LEFT JOIN warehouse_products wp ON wp.product_id = p.product_id
            GROUP BY p.product_id, p.name, p.price
            ORDER BY p.name
            """
        )
        products_list = [
            {"id": r[0], "name": r[1], "price": r[2], "stock": int(r[3])}
            for r in cursor.fetchall()
        ]
    return {"clients": clients, "products": products_list}


@staff_required
def order_new(request):
    posted_client = ""
    posted_method = "nova"
    posted_address = ""
    lines = [{"product_id": "", "quantity": "1"}]

    if request.method == "POST":
        posted_client = request.POST.get("client_id", "")
        posted_method = request.POST.get("delivery_method", "nova")
        posted_address = request.POST.get("delivery_address", "")
        lines = _collect_lines(request.POST) or lines
        try:
            try:
                client_id = int(posted_client)
            except ValueError:
                raise OrderError("Оберіть клієнта.")
            order_id = _place_order(
                client_id, _merge_lines(lines), posted_method, posted_address
            )
            messages.success(request, f"Замовлення №{order_id} створено, залишки списано.")
            return redirect("order_detail", order_id=order_id)
        except OrderError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Не вдалося створити замовлення")
            messages.error(request, "Не вдалося створити замовлення.")

    context = _order_form_context()
    context.update({
        "active_page": "orders",
        "lines": lines,
        "posted_client": posted_client,
        "posted_method": posted_method,
        "posted_address": posted_address,
        "methods": [(k, v[0]) for k, v in DELIVERY_METHODS.items()],
    })
    return render(request, "inventory/order_new.html", context)


@require_POST
@staff_required
def order_set_status(request, order_id):
    status = request.POST.get("status", "")
    if status not in ORDER_STATUSES:
        messages.error(request, "Некоректний статус.")
        return redirect("order_detail", order_id=order_id)

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM orders WHERE order_id = %s", [order_id])
            row = cursor.fetchone()
            if not row:
                raise Http404("Замовлення не знайдено")
            old_status = row[0]
            cursor.execute(
                "UPDATE orders SET status = %s WHERE order_id = %s",
                [status, order_id],
            )
            delivery_status = {
                "Доставлено": "Доставлено",
                "Скасовано": "Скасовано",
                "В обробці": "В дорозі",
            }.get(status)
            if delivery_status:
                cursor.execute(
                    "UPDATE deliveries SET status = %s WHERE order_id = %s",
                    [delivery_status, order_id],
                )
    if status == old_status:
        messages.success(request, "Статус оновлено.")
    elif send_order_status_email(order_id, status):
        messages.success(request, "Статус оновлено, клієнту надіслано лист.")
    else:
        messages.warning(
            request,
            "Статус оновлено, але лист клієнту не надіслано "
            "(немає пошти або помилка відправки).",
        )
    return redirect("order_detail", order_id=order_id)


# ---------------------------------------------------------------- магазин (клієнтська частина)

def _current_client(request):
    raw = request.get_signed_cookie(CLIENT_COOKIE, default=None, max_age=60 * 60 * 24 * 365)
    if not raw or not raw.isdigit():
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT client_id, full_name, phone, email, address "
            "FROM clients WHERE client_id = %s",
            [int(raw)],
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "phone": row[2],
            "email": row[3] or "", "address": row[4] or ""}


def _is_preview(request):
    return is_staff(request) and request.COOKIES.get(PREVIEW_COOKIE) == "1"


def _preview_clients(request):
    """Список клієнтів для перемикача «переглянути як…» (лише для адміна)."""
    if not is_staff(request):
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT client_id, full_name FROM clients ORDER BY full_name LIMIT 300"
        )
        return [{"id": r[0], "name": r[1]} for r in cursor.fetchall()]


def _shop_context(request):
    """Спільні змінні для всіх клієнтських сторінок."""
    return {
        "client": _current_client(request),
        "is_staff": is_staff(request),
        "preview": _is_preview(request),
        "preview_clients": _preview_clients(request),
    }


def _render_shop(request, posted=None, open_product=None):
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()

    filters, params = [], []
    if search:
        filters.append("(p.name LIKE %s OR p.description LIKE %s)")
        params += [f"%{search}%"] * 2
    if category.isdigit():
        filters.append("p.category_id = %s")
        params.append(int(category))
    where = (" WHERE " + " AND ".join(filters)) if filters else ""

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT p.product_id, p.name, p.description, p.price,
                   COALESCE(c.name, 'Без категорії'),
                   COALESCE(SUM(wp.quantity), 0), {_img()}
            FROM products p
            LEFT JOIN categories c ON c.category_id = p.category_id
            LEFT JOIN warehouse_products wp ON wp.product_id = p.product_id
            {where}
            GROUP BY p.product_id, p.name, p.description, p.price, c.name
            ORDER BY p.name
            """,
            params,
        )
        goods = [
            {"id": r[0], "name": r[1], "description": r[2] or "",
             "price": r[3], "category": r[4], "stock": int(r[5]),
             "image": r[6]}
            for r in cursor.fetchall()
        ]
        cursor.execute("SELECT category_id, name FROM categories ORDER BY name")
        categories = [{"id": r[0], "name": r[1]} for r in cursor.fetchall()]

    return render(request, "inventory/shop.html", {
        "goods": goods,
        "categories": categories,
        "search": search,
        "category": category,
        "client": _current_client(request),
        "is_staff": is_staff(request),
        "preview": _is_preview(request),
        "preview_clients": _preview_clients(request),
        "posted": posted,
        "open_product": open_product,
        "methods": [(k, v[0], v[1]) for k, v in DELIVERY_METHODS.items()],
    })


def shop(request):
    return _render_shop(request)


@require_POST
def shop_order(request):
    post = request.POST
    open_product = post.get("product_id")
    try:
        try:
            product_id = int(post.get("product_id", ""))
            quantity = int(post.get("quantity", ""))
        except ValueError:
            raise OrderError("Перевірте товар і кількість.")
        if not 1 <= quantity <= 99:
            raise OrderError("Кількість має бути від 1 до 99.")

        name = post.get("full_name", "").strip()
        if len(name) < 3 or len(name) > 150:
            raise OrderError("Вкажіть ПІБ (щонайменше 3 символи).")
        phone = _norm_phone(post.get("phone", ""))
        email = _check_email(post.get("email", ""))
        address = post.get("delivery_address", "").strip()

        with transaction.atomic():
            with connection.cursor() as cursor:
                client_id = _find_or_create_client(
                    cursor, name, phone, email, address
                )
            order_id = _place_order(
                client_id, {product_id: quantity},
                post.get("delivery_method", ""), address,
            )
    except OrderError as exc:
        messages.error(request, str(exc))
        return _render_shop(request, posted=post, open_product=open_product)
    except Exception:
        logger.exception("Не вдалося оформити замовлення")
        messages.error(request, "Не вдалося оформити замовлення. Спробуйте ще раз.")
        return _render_shop(request, posted=post, open_product=open_product)

    response = redirect(reverse("shop_order_done", args=[order_id]) + "?new=1")
    response.set_signed_cookie(
        CLIENT_COOKIE, str(client_id), max_age=60 * 60 * 24 * 365,
        httponly=True, samesite="Lax",
    )
    return response


def shop_order_done(request, order_id):
    client = _current_client(request)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT order_id, client_id, order_date, status, total_amount "
            "FROM orders WHERE order_id = %s",
            [order_id],
        )
        order = cursor.fetchone()
        if not order or not client or order[1] != client["id"]:
            raise Http404("Замовлення не знайдено")

        cursor.execute(
            """
            SELECT p.name, oi.quantity, oi.price, oi.quantity * oi.price
            FROM order_items oi
            LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE oi.order_id = %s
            """,
            [order_id],
        )
        items = cursor.fetchall()

        cursor.execute(
            "SELECT delivery_address, delivery_method, tracking_number, "
            "status, delivery_date FROM deliveries WHERE order_id = %s",
            [order_id],
        )
        delivery = cursor.fetchone()

    context = _shop_context(request)
    context.update({
        "order": order,
        "items": items,
        "delivery": delivery,
        "is_new": request.GET.get("new") == "1",
    })
    return render(request, "inventory/shop_order_done.html", context)
