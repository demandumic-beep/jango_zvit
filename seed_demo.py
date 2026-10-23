"""
Заповнює базу демонстраційними даними: категорії, 3 склади, клієнти і 16 товарів
із фото та залишками. Можна запускати повторно, дублів не буде.

Запуск із кореня проєкту (де manage.py):  python seed_demo.py
Замініть "config.settings", якщо ваш пакет налаштувань називається інакше.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection, transaction  # noqa: E402

IMG = "inventory/img/products/{}.svg"

CATEGORIES = [
    "Периферія",
    "Аудіотехніка",
    "Комп'ютерна техніка",
    "Комп'ютерні комплектуючі",
    "Мережеве обладнання",
    "Аксесуари",
    "Смартфони та гаджети",
]

# (назва, опис, ціна, категорія, файл фото, залишки: центральний / північний / резервний)
PRODUCTS = [
    ("Клавіатура Logitech K380", "Бездротова компактна клавіатура", 2200, "Периферія", "keyboard", (12, 6, 4)),
    ("Миша Logitech G102", "Ігрова дротова миша", 1200, "Периферія", "mouse", (20, 8, 5)),
    ("Навушники JBL Tune 770NC", "Бездротові навушники з шумозаглушенням", 3500, "Аудіотехніка", "headphones", (9, 4, 2)),
    ("Монітор Samsung 24", "Монітор для роботи та навчання", 5200, "Комп'ютерна техніка", "monitor", (7, 3, 0)),
    ("Ноутбук Lenovo IdeaPad", "Ноутбук для навчання та офісу", 28000, "Комп'ютерна техніка", "laptop", (4, 2, 1)),
    ("Флешка Kingston 64GB", "USB-накопичувач на 64 ГБ", 350, "Аксесуари", "flash", (2, 1, 0)),
    ("SSD Kingston 1TB", "Твердотільний накопичувач 1 ТБ", 3200, "Комп'ютерні комплектуючі", "ssd", (10, 5, 3)),
    ("Оперативна пам'ять DDR4 16GB", "Модуль оперативної пам'яті 16 ГБ", 1700, "Комп'ютерні комплектуючі", "ram", (15, 7, 4)),
    ("Вебкамера Logitech C920", "Вебкамера для відеозв'язку Full HD", 2800, "Периферія", "webcam", (6, 3, 2)),
    ("Роутер TP-Link Archer C6", "Wi-Fi роутер для дому", 1900, "Мережеве обладнання", "router", (11, 5, 3)),
    ("Килимок для миші", "Тканинний килимок для миші", 250, "Аксесуари", "mousepad", (30, 12, 8)),
    ("Зарядний пристрій USB-C", "Мережевий зарядний пристрій 30 Вт", 650, "Аксесуари", "charger", (18, 9, 6)),
    ("Повербанк 20000 мАг", "Портативний акумулятор із швидким заряджанням", 1400, "Смартфони та гаджети", "powerbank", (14, 6, 4)),
    ("Смарт-годинник Fit", "Фітнес-годинник із пульсометром", 2900, "Смартфони та гаджети", "smartwatch", (8, 4, 2)),
    ("Bluetooth-колонка Mini", "Портативна колонка з вологозахистом", 1500, "Аудіотехніка", "speaker", (13, 5, 3)),
    ("Смартфон 128GB", "Смартфон із AMOLED-екраном", 14500, "Смартфони та гаджети", "smartphone", (5, 3, 0)),
]

CLIENTS = [
    ("Олександр К.", "+380671112233", "oleksandr@example.com", "Львів"),
    ("Марія П.", "+380932223344", "maria@example.com", "Шептицький"),
    ("Андрій М.", "+380503334455", "andrii@example.com", "Буськ"),
    ("Ірина С.", "+380634445566", "iryna@example.com", "Львів"),
]

WAREHOUSES = [
    ("Центральний склад", "Львів"),
    ("Північний склад", "Шептицький"),
    ("Резервний склад", "Львівська область"),
]


def has_column(cursor, table, column):
    cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", [column])
    return cursor.fetchone() is not None


def main():
    with transaction.atomic(), connection.cursor() as cursor:
        # 1. Колонка для фото (якщо база створена зі старої схеми)
        if not has_column(cursor, "products", "image"):
            cursor.execute("ALTER TABLE products ADD COLUMN image VARCHAR(255) NULL")
            print("Додано колонку products.image")

        # 1б. Таблиця звернень у підтримку (для бази, створеної раніше)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS support_tickets (
                ticket_id   INT AUTO_INCREMENT PRIMARY KEY,
                client_id   INT NOT NULL,
                order_id    INT NULL,
                subject     VARCHAR(150) NOT NULL,
                message     TEXT NOT NULL,
                status      VARCHAR(30) NOT NULL DEFAULT 'Нове',
                created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                admin_reply TEXT NULL,
                replied_at  DATETIME NULL,
                CONSTRAINT fk_tickets_client
                    FOREIGN KEY (client_id) REFERENCES clients (client_id) ON DELETE CASCADE,
                CONSTRAINT fk_tickets_order
                    FOREIGN KEY (order_id) REFERENCES orders (order_id) ON DELETE SET NULL
            ) ENGINE=InnoDB
            """
        )

        # 2. Категорії
        category_ids = {}
        for name in CATEGORIES:
            cursor.execute("SELECT category_id FROM categories WHERE name = %s", [name])
            row = cursor.fetchone()
            if row:
                category_ids[name] = row[0]
            else:
                cursor.execute("INSERT INTO categories (name) VALUES (%s)", [name])
                category_ids[name] = cursor.lastrowid

        # 3. Клієнти
        for full_name, phone, email, address in CLIENTS:
            cursor.execute("SELECT 1 FROM clients WHERE phone = %s", [phone])
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO clients (full_name, phone, email, address) "
                    "VALUES (%s, %s, %s, %s)",
                    [full_name, phone, email, address],
                )

        # 4. Товари
        product_ids = {}
        for name, desc, price, category, slug, _stock in PRODUCTS:
            cursor.execute("SELECT product_id FROM products WHERE name = %s LIMIT 1", [name])
            row = cursor.fetchone()
            if row:
                product_ids[name] = row[0]
                cursor.execute(
                    "UPDATE products SET category_id=%s, description=%s, price=%s, image=%s "
                    "WHERE product_id=%s",
                    [category_ids[category], desc, price, IMG.format(slug), row[0]],
                )
            else:
                cursor.execute(
                    "INSERT INTO products (category_id, name, description, price, image) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [category_ids[category], name, desc, price, IMG.format(slug)],
                )
                product_ids[name] = cursor.lastrowid
            print("Товар:", name)

        first_product_id = next(iter(product_ids.values()))

        # 5. Склади (стара схема мала зайві циклічні колонки: підтримуємо її теж)
        legacy = has_column(cursor, "warehouses", "warehouse_products_warehouse_id")
        warehouse_ids = []
        for name, address in WAREHOUSES:
            cursor.execute("SELECT warehouse_id FROM warehouses WHERE name = %s", [name])
            row = cursor.fetchone()
            if row:
                warehouse_ids.append(row[0])
                continue
            if legacy:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                try:
                    cursor.execute("SELECT COALESCE(MAX(warehouse_id), 0) + 1 FROM warehouses")
                    new_id = cursor.fetchone()[0]
                    cursor.execute(
                        "INSERT INTO warehouses (warehouse_id, name, address, "
                        "warehouse_products_warehouse_id, warehouse_products_product_id) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        [new_id, name, address, new_id, first_product_id],
                    )
                finally:
                    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                warehouse_ids.append(new_id)
            else:
                cursor.execute(
                    "INSERT INTO warehouses (name, address) VALUES (%s, %s)",
                    [name, address],
                )
                warehouse_ids.append(cursor.lastrowid)

        # 6. Залишки (існуючі кількості не перезаписуємо)
        for name, _d, _p, _c, _s, stock in PRODUCTS:
            for warehouse_id, quantity in zip(warehouse_ids, stock):
                cursor.execute(
                    "INSERT INTO warehouse_products (warehouse_id, product_id, quantity) "
                    "VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE quantity = quantity",
                    [warehouse_id, product_ids[name], quantity],
                )

        # 7. Кілька демонстраційних звернень, щоб адмін-розділ не був порожнім
        cursor.execute("SELECT COUNT(*) FROM support_tickets")
        if cursor.fetchone()[0] == 0:
            cursor.execute("SELECT client_id FROM clients ORDER BY client_id LIMIT 2")
            ids = [row[0] for row in cursor.fetchall()]
            demo = [
                ("Питання щодо доставки", "Добрий день! Коли очікувати доставку мого замовлення?"),
                ("Скарга на товар", "Отримав товар із подряпинами на корпусі. Прошу замінити."),
            ]
            for client_id, (subject, message) in zip(ids, demo):
                cursor.execute(
                    "INSERT INTO support_tickets (client_id, subject, message, status) "
                    "VALUES (%s, %s, %s, 'Нове')",
                    [client_id, subject, message],
                )

    print(f"Готово: {len(PRODUCTS)} товарів, {len(WAREHOUSES)} склади, {len(CLIENTS)} клієнти.")


if __name__ == "__main__":
    main()
