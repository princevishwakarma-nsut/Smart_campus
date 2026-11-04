import logging
import os
from typing import Optional

import mysql.connector
from mysql.connector import Error, pooling

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[pooling.MySQLConnectionPool] = None


def build_mysql_connection_config() -> dict:
    """Build the active MySQL connection config, including verified TLS for Aiven."""
    config = {
        "host": settings.DB_HOST,
        "port": settings.DB_PORT,
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "database": settings.DB_NAME,
        "autocommit": True,
        "raise_on_warnings": True,
    }

    ssl_ca = (settings.DB_SSL_CA or "").strip().strip('"').strip("'")
    if ssl_ca:
        if not os.path.exists(ssl_ca):
            raise FileNotFoundError(f"DB_SSL_CA file does not exist: {ssl_ca}")
        config["ssl_ca"] = ssl_ca
        config["ssl_verify_cert"] = bool(settings.DB_SSL_VERIFY_CERT)
        config["ssl_verify_identity"] = bool(settings.DB_SSL_VERIFY_IDENTITY)
    elif settings.DB_HOST not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "Remote MySQL connections require a verified TLS CA certificate. "
            "Set DB_SSL_CA to the Aiven CA file path and keep SSL verification enabled."
        )

    return config


def get_connection_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        try:
            conn_config = build_mysql_connection_config()
            _pool = pooling.MySQLConnectionPool(
                pool_name=settings.DB_POOL_NAME,
                pool_size=settings.DB_POOL_SIZE,
                pool_reset_session=True,
                **conn_config,
            )
            logger.info(
                "MySQL connection pool initialized successfully for %s@%s:%s (%s)",
                settings.DB_USER,
                settings.DB_HOST,
                settings.DB_PORT,
                settings.DB_NAME,
            )
        except Error as exc:
            logger.error(f"Failed to initialize MySQL connection pool: {exc}")
            raise
        except Exception:
            logger.exception("Failed to build MySQL connection configuration.")
            raise
    return _pool


def get_db_connection():
    """Retrieve a connection from the pool without silently falling back to another database."""
    pool = get_connection_pool()
    try:
        conn = pool.get_connection()
        return conn
    except Error as exc:
        logger.error(f"Error getting connection from pool: {exc}")
        raise
