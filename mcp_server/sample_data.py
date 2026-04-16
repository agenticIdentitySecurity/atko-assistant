import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CUSTOMERS = [
    ("Alice Johnson", "alice@example.com", "USA"),
    ("Bob Smith", "bob@example.com", "UK"),
    ("Charlie Brown", "charlie@example.com", "Canada"),
    ("Diana Prince", "diana@example.com", "USA"),
    ("Eve Wilson", "eve@example.com", "Australia"),
]

PRODUCTS = [
    ("Laptop Pro", "High-performance 16-inch laptop", 1299.99, 50),
    ("Wireless Mouse", "Ergonomic wireless mouse", 29.99, 200),
    ("Mechanical Keyboard", "TKL mechanical keyboard, Cherry MX Blue", 99.99, 150),
    ("4K Monitor", '27-inch 4K IPS monitor', 399.99, 30),
    ("USB-C Hub", "7-port USB-C hub with HDMI", 49.99, 100),
]

ORDERS = [
    # (customer_id, days_ago, status, total_amount)
    (1, 2,  "completed", 1329.98),
    (1, 15, "shipped",   399.99),
    (2, 5,  "pending",   99.99),
    (3, 10, "completed", 49.99),
    (4, 1,  "pending",   1699.97),
    (5, 20, "completed", 29.99),
    (2, 30, "completed", 1299.99),
    (3, 8,  "shipped",   449.98),
    (4, 12, "completed", 99.99),
    (5, 3,  "pending",   399.99),
]

SUBSCRIPTIONS = [
    # (customer_id, service_name, plan, status)
    (1, "Netflix", "Premium", "active"),
    (1, "Spotify", "Family", "active"),
    (2, "Netflix", "Basic", "active"),
    (3, "Peacock", "Standard", "active"),
    (4, "HBO Max", "Ad-Free", "cancelled"),
    (5, "Netflix", "Standard", "active"),
]

ORDER_ITEMS = [
    # (order_id, product_id, quantity, unit_price)
    (1, 1, 1, 1299.99),
    (1, 2, 1, 29.99),
    (2, 4, 1, 399.99),
    (3, 3, 1, 99.99),
    (4, 5, 1, 49.99),
    (5, 1, 1, 1299.99),
    (5, 2, 2, 29.99),
    (5, 3, 2, 99.99),  # note: total might not match exactly — sample data
    (6, 2, 1, 29.99),
    (7, 1, 1, 1299.99),
    (8, 4, 1, 399.99),
    (8, 5, 1, 49.99),
    (9, 3, 1, 99.99),
    (10, 4, 1, 399.99),
]


def insert_sample_data(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # Skip if already populated
    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] > 0:
        logger.info("Sample data already present, skipping")
        return

    now = datetime.now()

    for name, email, country in CUSTOMERS:
        cur.execute(
            "INSERT INTO customers (name, email, country) VALUES (?, ?, ?)",
            (name, email, country),
        )

    for name, desc, price, stock in PRODUCTS:
        cur.execute(
            "INSERT INTO products (name, description, price, stock) VALUES (?, ?, ?, ?)",
            (name, desc, price, stock),
        )

    for customer_id, days_ago, status, total in ORDERS:
        order_date = now - timedelta(days=days_ago)
        cur.execute(
            "INSERT INTO orders (customer_id, order_date, status, total_amount) VALUES (?, ?, ?, ?)",
            (customer_id, order_date.isoformat(), status, total),
        )

    for order_id, product_id, qty, unit_price in ORDER_ITEMS:
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (order_id, product_id, qty, unit_price),
        )

    for customer_id, service_name, plan, status in SUBSCRIPTIONS:
        cur.execute(
            "INSERT INTO subscriptions (customer_id, service_name, plan, status) VALUES (?, ?, ?, ?)",
            (customer_id, service_name, plan, status),
        )

    conn.commit()
    logger.info("Sample data inserted")
