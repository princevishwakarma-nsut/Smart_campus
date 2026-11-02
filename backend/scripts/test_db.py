import os
import getpass
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("DB_HOST", "127.0.0.1")
port = int(os.getenv("DB_PORT", "3306"))
user = os.getenv("DB_USER", "root")
password = os.getenv("DB_PASSWORD")
database = os.getenv("DB_NAME", "smart_campus")

if not password:
    password = getpass.getpass("Enter MySQL password: ")

try:
    connection = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database
    )

    if connection.is_connected():
        print("MySQL connected successfully!")

        cursor = connection.cursor()

        cursor.execute("SELECT DATABASE()")
        print("Connected database:", cursor.fetchone()[0])

        cursor.execute("SHOW TABLES")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"\nTables in database ({len(tables)}):")

        for table in tables:
            print(" -", table)

        cursor.close()

except Error as error:
    print("MySQL connection failed:", error)

finally:
    if "connection" in locals() and connection.is_connected():
        connection.close()
        print("\nConnection closed.")
