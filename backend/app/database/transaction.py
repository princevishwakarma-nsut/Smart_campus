import logging
from contextlib import contextmanager
from app.database.connection import get_db_connection

logger = logging.getLogger(__name__)


@contextmanager
def transaction_scope():
    """
    Context manager providing a transactional database session.
    Automatically begins transaction, commits on success, and rolls back on exception.
    """
    conn = get_db_connection()
    conn.autocommit = False
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        yield conn, cursor
        conn.commit()
    except Exception as e:
        logger.error(f"Transaction failed, rolling back: {e}")
        try:
            conn.rollback()
        except Exception as rb_err:
            logger.error(f"Rollback failed: {rb_err}")
        raise
    finally:
        cursor.close()
        conn.close()
