-- StockLogix: чиста схема MySQL (без циклічних зв'язків).
-- Запускати на НОВІЙ порожній базі:  mysql -u root -p < schema.sql
-- Якщо таблиці вже існують, команди CREATE TABLE видадуть помилку і нічого не зіпсують.

CREATE DATABASE IF NOT EXISTS stocklogix
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE stocklogix;

CREATE TABLE categories (
    category_id INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE products (
    product_id  INT AUTO_INCREMENT PRIMARY KEY,
    category_id INT NOT NULL,
    name        VARCHAR(150) NOT NULL,
    description VARCHAR(255) NULL,
    price       DECIMAL(10,2) NOT NULL CHECK (price >= 0),
    image       VARCHAR(255) NULL,
    CONSTRAINT fk_products_category
        FOREIGN KEY (category_id) REFERENCES categories (category_id)
) ENGINE=InnoDB;

CREATE TABLE warehouses (
    warehouse_id INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    address      VARCHAR(255) NULL
) ENGINE=InnoDB;

CREATE TABLE warehouse_products (
    warehouse_id INT NOT NULL,
    product_id   INT NOT NULL,
    quantity     INT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    PRIMARY KEY (warehouse_id, product_id),
    CONSTRAINT fk_wp_warehouse
        FOREIGN KEY (warehouse_id) REFERENCES warehouses (warehouse_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_wp_product
        FOREIGN KEY (product_id) REFERENCES products (product_id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE clients (
    client_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    phone     VARCHAR(30)  NULL,
    email     VARCHAR(150) NULL,
    address   VARCHAR(255) NULL,
    UNIQUE KEY uq_clients_phone (phone)
) ENGINE=InnoDB;

CREATE TABLE orders (
    order_id     INT AUTO_INCREMENT PRIMARY KEY,
    client_id    INT NOT NULL,
    order_date   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status       VARCHAR(30) NOT NULL DEFAULT 'Очікує',
    total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    CONSTRAINT fk_orders_client
        FOREIGN KEY (client_id) REFERENCES clients (client_id)
) ENGINE=InnoDB;

CREATE TABLE order_items (
    order_item_id INT AUTO_INCREMENT PRIMARY KEY,
    order_id      INT NOT NULL,
    product_id    INT NOT NULL,
    quantity      INT NOT NULL CHECK (quantity > 0),
    price         DECIMAL(10,2) NOT NULL,
    CONSTRAINT fk_oi_order
        FOREIGN KEY (order_id) REFERENCES orders (order_id) ON DELETE CASCADE,
    CONSTRAINT fk_oi_product
        FOREIGN KEY (product_id) REFERENCES products (product_id)
) ENGINE=InnoDB;

CREATE TABLE deliveries (
    delivery_id      INT AUTO_INCREMENT PRIMARY KEY,
    order_id         INT NOT NULL,
    delivery_address VARCHAR(255) NOT NULL,
    delivery_method  VARCHAR(50)  NULL,
    tracking_number  VARCHAR(50)  NULL,
    status           VARCHAR(30)  NOT NULL DEFAULT 'Очікує',
    delivery_date    DATE NULL,
    CONSTRAINT fk_deliveries_order
        FOREIGN KEY (order_id) REFERENCES orders (order_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE support_tickets (
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
) ENGINE=InnoDB;
