from typing import Generator
from app.database.connection import get_db_connection


def get_db() -> Generator:
    """FastAPI dependency for non-transactional or read queries."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()
