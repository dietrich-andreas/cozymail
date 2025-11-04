# database.py
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "/opt/mailfilter-data/mailfilter.db"


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    if not os.path.exists(DB_PATH):
        print("[i] Initialisiere Datenbank...")

    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            username TEXT NOT NULL,
            password_enc TEXT NOT NULL,
            server TEXT NOT NULL,
            junk_folder TEXT NOT NULL,
            x_spam_level INTEGER DEFAULT 5,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            sender_address TEXT NOT NULL,
            added_at TEXT DEFAULT (DATETIME('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )
        """)

        conn.commit()
        print("[✓] Datenbank wurde erfolgreich eingerichtet.")


if __name__ == "__main__":
    init_db()
