"""
Ролі та кабінети:
  * адміністратор: вхід, клієнти, звернення в підтримку, режим «переглянути як клієнт»;
  * клієнт: свої замовлення та звернення в підтримку.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db import connection, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .access import CLIENT_COOKIE, PREVIEW_COOKIE, is_staff, staff_required
from .views import (
    PAGE_SIZE,
    OrderError,
    _badge,
    _check_email,
    _find_or_create_client,
    _norm_phone,
    _pager,
    _shop_context,
)

logger = logging.getLogger(__name__)

TICKET_STATUSES = ["Нове", "В роботі", "Закрито"]
COOKIE_AGE = 60 * 60 * 24 * 365


def _ticket_badge(status):
    return {"Нове": "pending", "В роботі": "processing", "Закрито": "delivered"}.get(
        status, "processing"
    )


def _support_ready():
    return "support_tickets" in connection.introspection.table_names()


def _set_client_cookie(response, client_id):
    response.set_signed_cookie(
        CLIENT_COOKIE, str(client_id), max_age=COOKIE_AGE,
        httponly=True, samesite="Lax",
    )


# ---------------------------------------------------------------- вхід адміністратора

def login_view(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = ""

    if is_staff(request):
        return redirect(next_url or "dashboard")

    error = None
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", "").strip(),
            password=request.POST.get("password", ""),
        )
        if user is not None and user.is_staff:
            login(request, user)
            return redirect(next_url or "dashboard")
        error = "Невірний логін або пароль, або в цього акаунта немає прав адміністратора."

    google_app = settings.SOCIALACCOUNT_PROVIDERS.get("google", {}).get(
        "APP", {}
    )
    return render(request, "inventory/login.html", {
        "error": error,
        "next": next_url,
        "google_login_enabled": bool(
            google_app.get("client_id") and google_app.get("secret")
        ),
    })


@require_POST
def logout_view(request):
    logout(request)
    response = redirect("shop")
    response.delete_cookie(PREVIEW_COOKIE)
    return response


# ---------------------------------------------------------------- перегляд «як клієнт»

@staff_required
@require_POST
def preview_as(request):
    try:
        client_id = int(request.POST.get("client_id", ""))
    except ValueError:
        messages.error(request, "Оберіть клієнта.")
        return redirect("shop")

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM clients WHERE client_id = %s", [client_id])
        if not cursor.fetchone():
            raise Http404("Клієнта не знайдено")

    response = redirect("shop")
    response.set_signed_cookie(
        CLIENT_COOKIE, str(client_id), httponly=True, samesite="Lax"
    )
    response.set_cookie(PREVIEW_COOKIE, "1", httponly=True, samesite="Lax")
    return response


@require_POST
def preview_exit(request):
    response = redirect("dashboard" if is_staff(request) else "shop")
    response.delete_cookie(CLIENT_COOKIE)
    response.delete_cookie(PREVIEW_COOKIE)
    return response


# ---------------------------------------------------------------- адмін: клієнти

@staff_required
def customers_list(request):
    search = request.GET.get("q", "").strip()
    where, where_params = "", []
    if search:
        where = (
            " WHERE c.full_name LIKE %s OR c.phone LIKE %s OR c.email LIKE %s "
            "OR CAST(c.client_id AS TEXT) LIKE %s"
        )
        where_params = [f"%{search}%"] * 4

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM clients c{where}", where_params)
        total = cursor.fetchone()[0]
        pager = _pager(request, total)
        cursor.execute(
            f"""
            SELECT c.client_id, c.full_name, c.phone, c.email,
                   COUNT(o.order_id),
                   COALESCE(SUM(CASE WHEN o.status <> %s THEN o.total_amount END), 0),
                   MAX(o.order_date)
            FROM clients c
            LEFT JOIN orders o ON o.client_id = c.client_id
            {where}
            GROUP BY c.client_id, c.full_name, c.phone, c.email
            ORDER BY c.client_id DESC
            LIMIT %s OFFSET %s
            """,
            ["Скасовано"] + where_params + [PAGE_SIZE, pager["offset"]],
        )
        customers = [
            {"id": r[0], "name": r[1], "phone": r[2] or "—", "email": r[3] or "—",
             "orders": r[4], "spent": r[5], "last": r[6]}
            for r in cursor.fetchall()
        ]

    return render(request, "inventory/customers.html", {
        "active_page": "customers",
        "customers": customers,
        "search": search,
        "total_records": total,
        "pager": pager,
    })


# ---------------------------------------------------------------- адмін: підтримка

@staff_required
def support_list(request):
    if not _support_ready():
        messages.error(request, "Таблиці підтримки ще немає. Запусти python seed_demo.py.")
        return redirect("dashboard")

    status = request.GET.get("status", "").strip()
    if status not in TICKET_STATUSES:
        status = ""

    where, params = "", []
    if status:
        where, params = " WHERE t.status = %s", [status]

    with connection.cursor() as cursor:
        cursor.execute("SELECT status, COUNT(*) FROM support_tickets GROUP BY status")
        counts = dict(cursor.fetchall())

        cursor.execute(f"SELECT COUNT(*) FROM support_tickets t{where}", params)
        total = cursor.fetchone()[0]
        pager = _pager(request, total)
        cursor.execute(
            f"""
            SELECT t.ticket_id, COALESCE(c.full_name, '—'), t.subject, t.status,
                   t.created_at, t.order_id
            FROM support_tickets t
            LEFT JOIN clients c ON c.client_id = t.client_id
            {where}
            ORDER BY (t.status = 'Закрито'), t.ticket_id DESC
            LIMIT %s OFFSET %s
            """,
            params + [PAGE_SIZE, pager["offset"]],
        )
        tickets = [
            {"id": r[0], "client": r[1], "subject": r[2], "status": r[3],
             "badge": _ticket_badge(r[3]), "created": r[4], "order_id": r[5]}
            for r in cursor.fetchall()
        ]

    return render(request, "inventory/support_list.html", {
        "active_page": "support",
        "tickets": tickets,
        "status": status,
        "statuses": [(s, counts.get(s, 0)) for s in TICKET_STATUSES],
        "total_records": total,
        "pager": pager,
    })


@staff_required
def support_detail(request, ticket_id):
    if not _support_ready():
        return redirect("support_list")

    def load():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.ticket_id, t.subject, t.message, t.status, t.created_at,
                       t.admin_reply, t.replied_at, t.order_id,
                       c.client_id, c.full_name, c.phone, c.email
                FROM support_tickets t
                LEFT JOIN clients c ON c.client_id = t.client_id
                WHERE t.ticket_id = %s
                """,
                [ticket_id],
            )
            return cursor.fetchone()

    ticket = load()
    if not ticket:
        raise Http404("Звернення не знайдено")

    if request.method == "POST":
        status = request.POST.get("status", "")
        reply = request.POST.get("admin_reply", "").strip()
        if status not in TICKET_STATUSES or len(reply) > 2000:
            messages.error(request, "Перевірте статус і текст відповіді (до 2000 символів).")
        else:
            if reply and status == "Нове":
                status = "В роботі"
            with connection.cursor() as cursor:
                if reply and reply != (ticket[5] or ""):
                    cursor.execute(
                        "UPDATE support_tickets SET admin_reply = %s, replied_at = NOW(), "
                        "status = %s WHERE ticket_id = %s",
                        [reply, status, ticket_id],
                    )
                else:
                    cursor.execute(
                        "UPDATE support_tickets SET status = %s WHERE ticket_id = %s",
                        [status, ticket_id],
                    )
            messages.success(request, "Звернення оновлено.")
            return redirect("support_detail", ticket_id=ticket_id)

    return render(request, "inventory/support_detail.html", {
        "active_page": "support",
        "ticket": ticket,
        "badge": _ticket_badge(ticket[3]),
        "statuses": TICKET_STATUSES,
    })


# ---------------------------------------------------------------- клієнт: мої замовлення

def my_orders(request):
    context = _shop_context(request)
    client = context["client"]
    orders = []
    if client:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT o.order_id, o.order_date, o.status, o.total_amount,
                       d.tracking_number, d.status
                FROM orders o
                LEFT JOIN deliveries d ON d.order_id = o.order_id
                WHERE o.client_id = %s
                ORDER BY o.order_id DESC
                LIMIT 200
                """,
                [client["id"]],
            )
            orders = [
                {"id": r[0], "date": r[1], "status": r[2], "badge": _badge(r[2]),
                 "total": r[3], "tracking": r[4] or "—", "delivery": r[5] or "—"}
                for r in cursor.fetchall()
            ]
    context.update({"orders": orders, "page": "orders"})
    return render(request, "inventory/my_orders.html", context)


# ---------------------------------------------------------------- клієнт: підтримка

def my_support(request):
    if not _support_ready():
        messages.error(request, "Підтримка тимчасово недоступна.")
        return redirect("shop")

    context = _shop_context(request)
    client = context["client"]
    posted = None

    if request.method == "POST":
        posted = request.POST
        try:
            subject = posted.get("subject", "").strip()
            body = posted.get("message", "").strip()
            if not 3 <= len(subject) <= 150:
                raise OrderError("Тема має містити від 3 до 150 символів.")
            if not 10 <= len(body) <= 2000:
                raise OrderError("Опишіть проблему (від 10 до 2000 символів).")

            order_id = None
            raw_order = posted.get("order_id", "").strip()

            with transaction.atomic():
                with connection.cursor() as cursor:
                    if client:
                        client_id = client["id"]
                    else:
                        name = posted.get("full_name", "").strip()
                        if len(name) < 3 or len(name) > 150:
                            raise OrderError("Вкажіть ПІБ (щонайменше 3 символи).")
                        client_id = _find_or_create_client(
                            cursor, name, _norm_phone(posted.get("phone", "")),
                            _check_email(posted.get("email", "")), "",
                        )

                    if raw_order:
                        if not raw_order.isdigit():
                            raise OrderError("Некоректне замовлення.")
                        cursor.execute(
                            "SELECT 1 FROM orders WHERE order_id = %s AND client_id = %s",
                            [int(raw_order), client_id],
                        )
                        if not cursor.fetchone():
                            raise OrderError("Це замовлення вам не належить.")
                        order_id = int(raw_order)

                    cursor.execute(
                        "INSERT INTO support_tickets "
                        "(client_id, order_id, subject, message, status) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        [client_id, order_id, subject, body, "Нове"],
                    )

            messages.success(request, "Звернення надіслано. Ми відповімо тут, на цій сторінці.")
            response = redirect("my_support")
            _set_client_cookie(response, client_id)
            return response
        except OrderError as exc:
            messages.error(request, str(exc))
        except Exception:
            logger.exception("Не вдалося створити звернення")
            messages.error(request, "Не вдалося надіслати звернення. Спробуйте ще раз.")

    tickets, orders = [], []
    if client:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ticket_id, subject, message, status, created_at,
                       admin_reply, replied_at, order_id
                FROM support_tickets
                WHERE client_id = %s
                ORDER BY ticket_id DESC
                LIMIT 50
                """,
                [client["id"]],
            )
            tickets = [
                {"id": r[0], "subject": r[1], "message": r[2], "status": r[3],
                 "badge": _ticket_badge(r[3]), "created": r[4], "reply": r[5],
                 "replied": r[6], "order_id": r[7]}
                for r in cursor.fetchall()
            ]
            cursor.execute(
                "SELECT order_id, order_date, total_amount FROM orders "
                "WHERE client_id = %s ORDER BY order_id DESC LIMIT 100",
                [client["id"]],
            )
            orders = [{"id": r[0], "date": r[1], "total": r[2]} for r in cursor.fetchall()]

    context.update({"tickets": tickets, "orders": orders, "posted": posted, "page": "support"})
    return render(request, "inventory/my_support.html", context)
