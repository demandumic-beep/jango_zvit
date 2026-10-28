from django.core.management.base import BaseCommand
from django.db import connection, transaction


PRODUCTS = [
    ("Клавіатура Logitech K380", "Бездротова компактна клавіатура", "2200", "Периферія", "keyboard", (12, 6, 4)),
    ("Миша Logitech G102", "Ігрова дротова миша", "1200", "Периферія", "mouse", (20, 8, 5)),
    ("Навушники JBL Tune 770NC", "Бездротові навушники з шумозаглушенням", "3500", "Аудіотехніка", "headphones", (9, 4, 2)),
    ("Монітор Samsung 24", "Монітор для роботи та навчання", "5200", "Комп'ютерна техніка", "monitor", (7, 3, 0)),
    ("Ноутбук Lenovo IdeaPad", "Ноутбук для навчання та офісу", "28000", "Комп'ютерна техніка", "laptop", (4, 2, 1)),
    ("Флешка Kingston 64GB", "USB-накопичувач на 64 ГБ", "350", "Аксесуари", "flash", (2, 1, 0)),
    ("SSD Kingston 1TB", "Твердотільний накопичувач 1 ТБ", "3200", "Комп'ютерні комплектуючі", "ssd", (10, 5, 3)),
    ("Оперативна пам'ять DDR4 16GB", "Модуль оперативної пам'яті 16 ГБ", "1700", "Комп'ютерні комплектуючі", "ram", (15, 7, 4)),
    ("Вебкамера Logitech C920", "Вебкамера для відеозв'язку Full HD", "2800", "Периферія", "webcam", (6, 3, 2)),
    ("Роутер TP-Link Archer C6", "Wi-Fi роутер для дому", "1900", "Мережеве обладнання", "router", (11, 5, 3)),
    ("Килимок для миші", "Тканинний килимок для миші", "250", "Аксесуари", "mousepad", (30, 12, 8)),
    ("Зарядний пристрій USB-C", "Мережевий зарядний пристрій 30 Вт", "650", "Аксесуари", "charger", (18, 9, 6)),
    ("Повербанк 20000 мАг", "Портативний акумулятор із швидким заряджанням", "1400", "Смартфони та гаджети", "powerbank", (14, 6, 4)),
    ("Смарт-годинник Fit", "Фітнес-годинник із пульсометром", "2900", "Смартфони та гаджети", "smartwatch", (8, 4, 2)),
    ("Bluetooth-колонка Mini", "Портативна колонка з вологозахистом", "1500", "Аудіотехніка", "speaker", (13, 5, 3)),
    ("Смартфон 128GB", "Смартфон із AMOLED-екраном", "14500", "Смартфони та гаджети", "smartphone", (5, 3, 0)),
]

WAREHOUSES = [
    ("Центральний склад", "Львів"),
    ("Північний склад", "Шептицький"),
    ("Резервний склад", "Львівська область"),
]


class Command(BaseCommand):
    help = "Creates the initial product catalog and stock without overwriting existing data."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            from django.core.management.base import CommandError

            raise CommandError(
                "The production seed command requires the PostgreSQL database."
            )

        with transaction.atomic(), connection.cursor() as cursor:
            category_ids = {}
            categories = dict.fromkeys(product[3] for product in PRODUCTS)
            for category in categories:
                cursor.execute(
                    "INSERT INTO categories (name) VALUES (%s) "
                    "ON CONFLICT (name) DO NOTHING",
                    [category],
                )
                cursor.execute(
                    "SELECT category_id FROM categories WHERE name = %s",
                    [category],
                )
                category_ids[category] = cursor.fetchone()[0]

            warehouse_ids = []
            for name, address in WAREHOUSES:
                cursor.execute(
                    "SELECT warehouse_id FROM warehouses WHERE name = %s "
                    "ORDER BY warehouse_id LIMIT 1",
                    [name],
                )
                row = cursor.fetchone()
                if row:
                    warehouse_ids.append(row[0])
                    continue
                cursor.execute(
                    "INSERT INTO warehouses (name, address) VALUES (%s, %s) "
                    "RETURNING warehouse_id",
                    [name, address],
                )
                warehouse_ids.append(cursor.fetchone()[0])

            product_ids = {}
            for name, description, price, category, slug, _stock in PRODUCTS:
                image = f"inventory/img/products/{slug}.svg"
                cursor.execute(
                    "SELECT product_id FROM products WHERE name = %s "
                    "ORDER BY product_id LIMIT 1",
                    [name],
                )
                row = cursor.fetchone()
                if row:
                    product_ids[name] = row[0]
                else:
                    cursor.execute(
                        "INSERT INTO products "
                        "(category_id, name, description, price, image) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING product_id",
                        [category_ids[category], name, description, price, image],
                    )
                    product_ids[name] = cursor.fetchone()[0]
                cursor.execute(
                    "UPDATE products SET image = %s "
                    "WHERE product_id = %s AND image IS NULL",
                    [image, product_ids[name]],
                )

            for name, _description, _price, _category, _slug, stock in PRODUCTS:
                for warehouse_id, quantity in zip(warehouse_ids, stock):
                    cursor.execute(
                        "INSERT INTO warehouse_products "
                        "(warehouse_id, product_id, quantity) "
                        "VALUES (%s, %s, %s) "
                        "ON CONFLICT (warehouse_id, product_id) DO NOTHING",
                        [warehouse_id, product_ids[name], quantity],
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Catalog ready: {len(PRODUCTS)} products, "
                f"{len(category_ids)} categories, {len(warehouse_ids)} warehouses."
            )
        )
