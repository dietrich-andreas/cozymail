# core/create_database.py
# Erstellt/aktualisiert das SQLite-Schema für CozyMail.

from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = "/opt/mailfilter-data/mailfilter.db"


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

-- =========================
-- USERS
-- =========================
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password TEXT NOT NULL
);

-- =========================
-- ACCOUNTS
-- =========================
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  email TEXT NOT NULL,
  username TEXT NOT NULL,
  password_enc TEXT NOT NULL,
  server TEXT NOT NULL,
  junk_folder TEXT NOT NULL,
  x_spam_level INTEGER DEFAULT 3,
  sort_order INTEGER DEFAULT 0,
  trash_folder TEXT DEFAULT 'INBOX.Trash',
  unread_count INTEGER DEFAULT 0,
  spam_filter_active INTEGER DEFAULT 1,
  uid_validity INTEGER DEFAULT NULL,
  last_seen_uid INTEGER DEFAULT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =========================
-- FILTERS
-- =========================
CREATE TABLE IF NOT EXISTS filters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  field TEXT NOT NULL,
  mode TEXT NOT NULL,
  value TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  is_read INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  target_folder TEXT,
  usage_count INTEGER DEFAULT 0,
  last_used   TEXT DEFAULT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

-- =========================
-- MAILS
-- =========================
CREATE TABLE IF NOT EXISTS mails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  uid TEXT NOT NULL,
  msg_id TEXT,
  date TEXT,
  sender TEXT,
  subject TEXT,
  headers TEXT,
  body TEXT,
  raw TEXT,
  seen INTEGER DEFAULT 0,
  flagged_action TEXT DEFAULT NULL, -- z.B. 'mark_spam' als leichte Queue
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  html_body TEXT,
  html_raw TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

-- =========================
-- WHITELIST
-- =========================
CREATE TABLE IF NOT EXISTS whitelist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  sender_address TEXT NOT NULL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, sender_address),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =========================
-- INDIZES
-- =========================

-- USERS
-- (username bereits UNIQUE)

-- ACCOUNTS
CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_sort ON accounts(user_id, sort_order);

-- FILTERS
CREATE INDEX IF NOT EXISTS idx_filters_user_acc ON filters(user_id, account_id);
CREATE INDEX IF NOT EXISTS idx_filters_active ON filters(active);

-- MAILS
CREATE INDEX IF NOT EXISTS idx_mails_user_acc_uid ON mails(user_id, account_id, uid);
CREATE INDEX IF NOT EXISTS idx_mails_seen ON mails(seen);
CREATE INDEX IF NOT EXISTS idx_mails_flagged_action ON mails(flagged_action);
CREATE INDEX IF NOT EXISTS idx_mails_created_at ON mails(created_at);

-- WHITELIST
CREATE INDEX IF NOT EXISTS idx_whitelist_user   ON whitelist(user_id);
CREATE INDEX IF NOT EXISTS idx_whitelist_sender ON whitelist(sender_address);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def ensure_database(db_path: Optional[str] = None) -> str:
    path = db_path or DEFAULT_DB_PATH
    with get_connection(path) as conn:
        create_schema(conn)
    return path


if __name__ == "__main__":
    db_file = ensure_database()
    print(f"Schema ist aktuell. Datenbank: {db_file}")
