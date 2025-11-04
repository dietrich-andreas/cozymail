### core/auth.py
import hashlib
from core.database import get_db_connection

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_user(username: str, password: str) -> dict | None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        hashed = hash_password(password)
        cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed))
        user = cursor.fetchone()
        return dict(user) if user else None

def get_accounts_for_user(user_id: int) -> list[dict]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE user_id = ? ORDER BY sort_order ASC, id ASC", (user_id,))
        return [dict(row) for row in cursor.fetchall()]