from django.db import migrations, models


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    category_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories (category_id),
    name VARCHAR(150) NOT NULL,
    description VARCHAR(255),
    price DECIMAL(10, 2) NOT NULL CHECK (price >= 0),
    image VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    address VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS warehouse_products (
    warehouse_id INTEGER NOT NULL REFERENCES warehouses (warehouse_id)
        ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products (product_id)
        ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    PRIMARY KEY (warehouse_id, product_id)
);

CREATE TABLE IF NOT EXISTS clients (
    client_id SERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    phone VARCHAR(30) UNIQUE,
    email VARCHAR(150),
    address VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients (client_id),
    order_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(30) NOT NULL DEFAULT 'Очікує',
    total_amount DECIMAL(12, 2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products (product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    price DECIMAL(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    delivery_address VARCHAR(255) NOT NULL,
    delivery_method VARCHAR(50),
    tracking_number VARCHAR(50),
    status VARCHAR(30) NOT NULL DEFAULT 'Очікує',
    delivery_date DATE
);

CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients (client_id) ON DELETE CASCADE,
    order_id INTEGER REFERENCES orders (order_id) ON DELETE SET NULL,
    subject VARCHAR(150) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'Нове',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    admin_reply TEXT,
    replied_at TIMESTAMP
);
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=statement.strip(),
                    reverse_sql=migrations.RunSQL.noop,
                )
                for statement in POSTGRES_SCHEMA.split(";")
                if statement.strip()
            ],
            state_operations=[
                migrations.CreateModel(
                    name="Product",
                    fields=[
                        (
                            "product_id",
                            models.AutoField(
                                primary_key=True, serialize=False
                            ),
                        ),
                        ("category_id", models.IntegerField()),
                        ("name", models.CharField(max_length=150)),
                        (
                            "description",
                            models.CharField(
                                blank=True, max_length=255, null=True
                            ),
                        ),
                        (
                            "price",
                            models.DecimalField(
                                decimal_places=2, max_digits=10
                            ),
                        ),
                    ],
                    options={"db_table": "products", "managed": False},
                ),
            ],
        ),
    ]
