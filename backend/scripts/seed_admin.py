import os
import getpass
import mysql.connector
from mysql.connector import Error, IntegrityError
from argon2 import PasswordHasher
from dotenv import load_dotenv

load_dotenv()


def create_admin():
    print("\n===== Smart Campus: Initial Admin Setup =====\n")

    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD")
    database = os.getenv("DB_NAME", "smart_campus")

    if not db_password:
        db_password = getpass.getpass("MySQL Password: ")

    connection = None
    cursor = None

    try:
        connection = mysql.connector.connect(
            host=host,
            port=port,
            user=db_user,
            password=db_password,
            database=database
        )
        cursor = connection.cursor()

        # Check if an Admin already exists
        cursor.execute(
            "SELECT user_id, email, name FROM users WHERE role = %s LIMIT 1",
            ("Admin",)
        )
        existing_admin = cursor.fetchone()

        if existing_admin:
            print("\nAn Admin account already exists in the database.")
            print("User ID:", existing_admin[0])
            print("Email:  ", existing_admin[1])
            print("Name:   ", existing_admin[2])
            return

        # Prompt for new Admin details
        name = input("Admin Name: ").strip()
        email = input("Admin Email: ").strip().lower()

        if not name or "@" not in email:
            print("Invalid name or email.")
            return

        password = getpass.getpass("Admin Password: ")
        confirm_password = getpass.getpass("Confirm Password: ")

        if password != confirm_password:
            print("Passwords do not match.")
            return

        if len(password) < 8:
            print("Password must contain at least 8 characters.")
            return

        # Check whether email is already registered
        cursor.execute(
            "SELECT user_id FROM users WHERE email = %s",
            (email,)
        )
        if cursor.fetchone():
            print("\nThis email is already registered.")
            return

        # Secure password hashing with Argon2id
        password_hasher = PasswordHasher()
        password_hash = password_hasher.hash(password)

        cursor.execute(
            """
            INSERT INTO users (
                department_id,
                name,
                email,
                password_hash,
                role,
                is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (None, name, email, password_hash, "Admin", 1)
        )
        connection.commit()

        print("\nAdmin account created successfully!")
        print("User ID:", cursor.lastrowid)
        print("Name:   ", name)
        print("Email:  ", email)
        print("Role:    Admin")

    except IntegrityError:
        if connection and connection.is_connected():
            connection.rollback()
        print("\nIntegrity Error: This email may already exist.")
    except Error as error:
        if connection and connection.is_connected():
            connection.rollback()
        print("\nMySQL Error:", error)
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
            print("\nMySQL connection closed.")


if __name__ == "__main__":
    create_admin()
