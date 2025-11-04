# create_user.py
import sqlite3
import hashlib
import getpass
from crypto import encrypt
from database import get_connection, init_db


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def create_user():
    conn = get_connection()
    cursor = conn.cursor()

    username = input("Benutzername: ").strip()
    password = getpass.getpass("Passwort: ").strip()

    hashed = hash_password(password)
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        print("[!] Benutzername bereits vergeben.")
        conn.close()
        return

    while True:
        print("\nNeues E-Mail-Konto hinzufügen:")
        email = input("  Mailadresse (Anzeige): ").strip()
        imap_user = input("  Benutzername für IMAP-Login: ").strip()
        imap_pass = getpass.getpass("  IMAP-Passwort: ").strip()
        imap_server = input("  IMAP-Server (z. B. imap.mail.de): ").strip()
        junk_folder = input("  Junk-Ordner (z. B. INBOX.Junk): ").strip()

        enc_password = encrypt(imap_pass)

        cursor.execute("""
            INSERT INTO accounts (user_id, email, username, password_enc, server, junk_folder)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, email, imap_user, enc_password, imap_server, junk_folder))

        add_more = input("Weiteres Konto hinzufügen? (j/N): ").strip().lower()
        if add_more != 'j':
            break

    conn.commit()
    conn.close()
    print("[✓] Benutzer und Mailkonto(s) wurden gespeichert.")


if __name__ == '__main__':
    init_db()
    create_user()
