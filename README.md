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

1. **База.** Цей Render-застосунок використовує PostgreSQL. Таблиці створює `python manage.py migrate`; початкові товари й залишки додає `python manage.py seed_demo`.
2. `pip install -r requirements.txt`
3. **`config/settings.py`** має містити:
   - `INSTALLED_APPS`: `inventory`, `django.contrib.auth`, `django.contrib.contenttypes`, `django.contrib.sessions`, `django.contrib.messages`, `django.contrib.staticfiles`;
   - `MIDDLEWARE`: `SessionMiddleware`, `AuthenticationMiddleware`, `MessageMiddleware`, `CsrfViewMiddleware` (у стандартному проєкті все це вже є);
   - `TEMPLATES[0]`: `APP_DIRS = True` і context_processors `request`, `auth`, `messages`;
   - `DATABASES['default']`: MySQL (`django.db.backends.mysql`, `NAME: stocklogix`, `OPTIONS: {'charset': 'utf8mb4'}`).
4. **`config/urls.py`:** `path('', include('inventory.urls'))`.
5. `python manage.py migrate` (створює таблиці користувачів Django для входу адміна).
6. Локально створи адміністратора командою `python manage.py createsuperuser`; на Render акаунт створює `python manage.py ensure_admin` із `ADMIN_USERNAME` та `ADMIN_PASSWORD`.
7. `python manage.py seed_demo`, потім `python manage.py runserver`.

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

У Render → **Environment** додай `ADMIN_USERNAME`, `ADMIN_PASSWORD` і, за потреби, `ADMIN_EMAIL`. Пароль задай у Render, не зберігай його у Git. На **Settings → Start Command** вкажи:

```text
python manage.py migrate --noinput && python manage.py seed_demo && python manage.py ensure_admin && gunicorn config.wsgi:application
```

Ця команда записана також у `Procfile`. Після push змін запусти новий deploy і перевір у логах, що `migrate`, `seed_demo` та `ensure_admin` успішно завершилися до запуску Gunicorn. `seed_demo` додає 16 початкових товарів, категорії, склади й початкові залишки; повторний запуск не перезаписує наявні товари або кількості. `ensure_admin` створює або підтверджує staff/superuser-акаунт із заданими змінними середовища; входь на `/login/` саме з `ADMIN_USERNAME` та `ADMIN_PASSWORD` (Google-вхід сам собою не надає адміністративних прав). У production `DEBUG` за замовчуванням вимкнено; встанови `ALLOWED_HOSTS` із доменом Render та власними доменами. WhiteNoise віддає зібрані CSS та інші статичні файли.
