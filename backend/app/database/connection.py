import logging
from typing import Optional
import mysql.connector
from mysql.connector import pooling, Error
from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[pooling.MySQLConnectionPool] = None


def get_connection_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        try:
            _pool = pooling.MySQLConnectionPool(
                pool_name=settings.DB_POOL_NAME,
                pool_size=settings.DB_POOL_SIZE,
                pool_reset_session=True,
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                database=settings.DB_NAME,
                autocommit=True
            )
            logger.info("MySQL connection pool initialized successfully.")
        except Error as e:
            logger.error(f"Failed to initialize MySQL connection pool: {e}")
            raise
    return _pool


def get_db_connection():
    """Retrieve a connection from the pool."""
    pool = get_connection_pool()
    try:
        conn = pool.get_connection()
        return conn
    except Error as e:
        logger.error(f"Error getting connection from pool: {e}")
        # Direct fallback attempt if pool exhausted or error
        return mysql.connector.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            autocommit=True
        )
