# StockLogix: встановлення та ролі

## Куди класти файли

Розпакуй архів у корінь Django-проєкту (де `manage.py`), погоджуючись на заміну:

```
inventory/views.py, urls.py, access.py, portal.py
inventory/templatetags/            (custom_filters.py)
inventory/templates/inventory/     (усі .html; старі clients/deliveries/warehouses.html не потрібні)
inventory/static/inventory/css/    (shop.css, extra.css; твій style.css не чіпаємо)
inventory/static/inventory/img/products/   (ілюстрації товарів)
seed_demo.py, schema.sql           (у корінь)
```

`seed_products.py`, `add_demo_data.py`, `db.sqlite3` більше не потрібні.

## Запуск

1. **База.** Нова: `mysql -u root -p < schema.sql`. Уже існуюча: `seed_demo.py` сам додасть колонку `products.image` і таблицю `support_tickets`.
2. `pip install django mysqlclient`
3. **`config/settings.py`** має містити:
   - `INSTALLED_APPS`: `inventory`, `django.contrib.auth`, `django.contrib.contenttypes`, `django.contrib.sessions`, `django.contrib.messages`, `django.contrib.staticfiles`;
   - `MIDDLEWARE`: `SessionMiddleware`, `AuthenticationMiddleware`, `MessageMiddleware`, `CsrfViewMiddleware` (у стандартному проєкті все це вже є);
   - `TEMPLATES[0]`: `APP_DIRS = True` і context_processors `request`, `auth`, `messages`;
   - `DATABASES['default']`: MySQL (`django.db.backends.mysql`, `NAME: stocklogix`, `OPTIONS: {'charset': 'utf8mb4'}`).
4. **`config/urls.py`:** `path('', include('inventory.urls'))`.
5. `python manage.py migrate` (створює таблиці користувачів Django для входу адміна).
6. `python manage.py createsuperuser`, це твій логін адміністратора.
7. `python seed_demo.py`, потім `python manage.py runserver`.

## Ролі

**Адміністратор** (лише `is_staff`, вхід на `/login/`): уся адмін-панель, усі товари й замовлення, розділ «Клієнти» (хто що замовляв, на яку суму), розділ «Підтримка» (усі скарги, відповіді, статуси). Гість без входу, що відкриє адмін-адресу, потрапляє на сторінку входу.

**Клієнт** (без паролів, реєструється у вікні замовлення): бачить лише каталог, **лише свої** замовлення (`/shop/my-orders/`) і підтримку (`/shop/support/`), де пише скарги та читає відповіді. Чужі замовлення й звернення йому недоступні: у запитах завжди стоїть його id.

**Переглянути як клієнт:** в адмінці «Клієнти» → кнопка «Як клієнт», або «Вигляд клієнта ↗» у меню й випадний список у верхній смузі. Зверху буде смуга «Режим перегляду», кнопка «Повернутися в адмін-панель» повертає назад.

## Важливо знати

- Клієнт упізнається за підписаним cookie у браузері, без пароля. Якщо очистити cookie, він побачить порожні «Мої замовлення» (дані в базі залишаються). Для повноцінних акаунтів із паролем потрібен наступний крок.
- Фото товарів це ілюстрації (SVG): реальні фото з інтернету завантажити не вдалося. Свої кладіть у `static/inventory/img/products/` і вписуйте шлях у полі «Фото» товару.
- Скасування замовлення не повертає товар на склад (замовлення не пам'ятає, з якого складу списано).
- Статуси замовлень текстові («Очікує», «В обробці», «Доставлено», «Скасовано»). Якщо в твоїй базі `status` це `ENUM`, адаптуємо.

## Розгортання на Render

Для збирання статичних файлів вкажи в налаштуваннях вебсервісу Render команду збірки:

```text
pip install -r requirements.txt && python manage.py collectstatic --no-input
```

Команда запуску вебсервісу:

```text
gunicorn config.wsgi:application
```

WhiteNoise віддає зібрані CSS та інші статичні файли в production. Після зміни команди збірки виконай новий deploy.
