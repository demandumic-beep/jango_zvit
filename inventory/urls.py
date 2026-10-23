import re

from django.conf import settings
from django.urls import path, re_path
from django.views.static import serve

from . import portal, views

urlpatterns = [
    # --- адмін-панель (лише для is_staff)
    path("", views.dashboard, name="dashboard"),

    path("products/", views.products, name="products"),
    path("products/add/", views.add_product, name="add_product"),
    path("products/<int:product_id>/edit/", views.edit_product, name="edit_product"),
    path("products/<int:product_id>/delete/", views.delete_product, name="delete_product"),

    path("orders/", views.orders_list, name="orders_list"),
    path("orders/new/", views.order_new, name="order_new"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:order_id>/status/", views.order_set_status, name="order_set_status"),

    path("customers/", portal.customers_list, name="customers_list"),
    path("support/", portal.support_list, name="support_list"),
    path("support/<int:ticket_id>/", portal.support_detail, name="support_detail"),

    path("stock/", views.manage_stock, name="manage_stock"),
    path(
        "stock/<int:warehouse_id>/<int:product_id>/delete/",
        views.stock_delete,
        name="stock_delete",
    ),

    # --- вхід і режим «переглянути як клієнт»
    path("login/", portal.login_view, name="login"),
    path("logout/", portal.logout_view, name="logout"),
    path("view-as/", portal.preview_as, name="preview_as"),
    path("view-as/exit/", portal.preview_exit, name="preview_exit"),

    # --- клієнтська частина (відкрита)
    path("shop/", views.shop, name="shop"),
    path("shop/order/", views.shop_order, name="shop_order"),
    path("shop/order/<int:order_id>/done/", views.shop_order_done, name="shop_order_done"),
    path("shop/my-orders/", portal.my_orders, name="my_orders"),
    path("shop/support/", portal.my_support, name="my_support"),

    path("manage/<str:table>/", views.manage_table, name="manage_table"),
    path("manage/<str:table>/add/", views.add_record, name="add_record"),
    path("manage/<str:table>/<int:record_id>/edit/", views.edit_record, name="edit_record"),
    path("manage/<str:table>/<int:record_id>/delete/", views.delete_record, name="delete_record"),
]

# Фото товарів, завантажені з комп'ютера (лише в режимі розробки, DEBUG=True).
if settings.DEBUG:
    urlpatterns += [
        re_path(
            r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
