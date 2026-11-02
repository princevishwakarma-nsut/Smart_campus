import os
import sys
import mysql.connector
from dotenv import load_dotenv

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
backend_dir = os.path.join(root_dir, "backend")
env_path = os.path.join(backend_dir, ".env")
load_dotenv(env_path)

sys.path.insert(0, backend_dir)

try:
    from app.core.config import settings
    db_host = settings.DB_HOST
    db_port = settings.DB_PORT
    db_user = settings.DB_USER
    db_password = settings.DB_PASSWORD
    db_name = settings.DB_NAME
except Exception:
    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_port = int(os.getenv("DB_PORT", 3306))
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "smart_campus")


def seed_equipment(target_db=None):
    database_name = target_db or db_name
    print(f"Seeding equipment catalogue into database: {database_name}...")
    conn = mysql.connector.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=database_name
    )
    cursor = conn.cursor(dictionary=True)

    seed_file = os.path.join(os.path.dirname(__file__), "equipment_seed.sql")
    with open(seed_file, "r", encoding="utf-8") as f:
        sql = f.read()

    # Filter out line comments while preserving SQL statements
    cleaned_lines = []
    for line in sql.splitlines():
        trimmed = line.strip()
        if not trimmed.startswith("--"):
            cleaned_lines.append(line)
    cleaned_sql = "\n".join(cleaned_lines)

    # Split by statements
    stmts = [s.strip() for s in cleaned_sql.split(";") if s.strip()]
    for stmt in stmts:
        cursor.execute(stmt)
    conn.commit()

    # Log initial stock added into equipment_stock_movements for any item without movements
    cursor.execute("""
        SELECT item_id, total_quantity, item_name
        FROM equipment_items
        WHERE item_id NOT IN (SELECT DISTINCT item_id FROM equipment_stock_movements)
    """)
    items = cursor.fetchall()
    for it in items:
        cursor.execute("""
            INSERT INTO equipment_stock_movements (item_id, movement_type, quantity, notes)
            VALUES (%s, 'Stock Added', %s, %s)
        """, (it["item_id"], it["total_quantity"], f"Initial demo seed stock for {it['item_name']}"))
    if items:
        conn.commit()
        print(f"Recorded initial stock addition movements for {len(items)} items.")

    # Verification query
    cursor.execute("""
        SELECT category, COUNT(*) as item_count, SUM(total_quantity) as total_units
        FROM equipment_items
        WHERE is_active = 1
        GROUP BY category
        ORDER BY category ASC
    """)
    summary = cursor.fetchall()
    print("\n--- Stock Summary by Category ---")
    for row in summary:
        print(f"  {row['category']}: {row['item_count']} item types, {row['total_units']} total units")

    cursor.close()
    conn.close()
    print("Equipment seeded successfully.")


if __name__ == "__main__":
    seed_equipment()
