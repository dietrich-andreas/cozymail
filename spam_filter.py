# spam_filter.py

import os, re
from core.config import LOG_BASE
from core.crypto import decrypt
from core.database import get_db_connection
from core.logger import setup_main_logger, write_mail_log, write_error_log
from core.utils import safe_decode_header
from email.header import decode_header
from imap_tools import MailBox, AND, MailMessageFlags
from model_utils import is_spam

# Logger initialisieren
setup_main_logger()

DEBUG = False  # auf False setzen, wenn keine Debug-Ausgaben gewünscht

def get_header_value(msg, header_name):
    return safe_decode_header(msg.obj.get(header_name))

def is_whitelisted(sender: str, whitelist: list[str]) -> bool:
    for entry in whitelist:
        pattern = '^' + re.escape(entry).replace(r'\*', '.*') + '$'
        if re.fullmatch(pattern, sender, re.IGNORECASE):
            return True
    return False

def move_spam_from_all_users():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()

        for user in users:
            cursor.execute("SELECT * FROM accounts WHERE user_id = ?", (user["id"],))
            accounts = cursor.fetchall()

            for acc in accounts:
                try:
                    if DEBUG: print(f"[i] Verarbeite Konto: {acc['email']}")

                    pw = decrypt(acc["password_enc"])
                    x_level = acc["x_spam_level"] or 5

                    cursor.execute("SELECT sender_address FROM whitelist WHERE account_id = ?", (acc["id"],))
                    whitelist_entries = [row[0] for row in cursor.fetchall()]

                    with MailBox(acc['server']).login(acc['username'], pw) as mailbox:
                        unseen = list(mailbox.fetch(AND(seen=False), mark_seen=False))
                        if DEBUG: print(f"[i] {len(unseen)} ungelesene Mails gefunden.")

                        for msg in unseen:
                            if DEBUG: print(f"[i] Prüfe Mail: {msg.subject}")

                            if is_whitelisted(msg.from_, whitelist_entries):
                                if DEBUG: print(f"[~] Whitelisted: {msg.from_}")
                                continue

                            spam_level_str = get_header_value(msg, "X-Spam-Level")
                            spam_level = spam_level_str.count("*") if spam_level_str else 0
                            prediction = is_spam(user["username"], msg.subject, msg.text or "")

                            if DEBUG: print(f"Spam-Level: {spam_level}, Prediction: {prediction}")

                            if spam_level >= x_level or prediction:
                                if DEBUG: print(f"🚀 SPAM erkannt! Verschiebe nach {acc['junk_folder']}")
                                mailbox.flag([msg.uid], ['Junk'], value=True)
                                mailbox.move(msg.uid, acc['junk_folder'])
                                reason = []
                                if spam_level >= x_level:
                                    reason.append(f"Level {spam_level} ≥ {x_level}")
                                if prediction:
                                    reason.append("ML")

                                write_mail_log(user["id"], acc["username"], msg, spam_level, ", ".join(reason))

                except Exception as e:
                    print(f"[!] Fehler: {str(e)}")
                    write_error_log(user["id"], acc["username"], f"Fehler: {str(e)}")

def apply_filters_for_account(client, account):
    from core.database import get_db_connection
    from imap_tools import AND
    import re

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM filters WHERE account_id = ? AND active = 1", (account["id"],))
        filters = cursor.fetchall()

    if not filters:
        return

    for f in filters:
        field = f["field"]
        value = f["value"].lower()
        match_mode = f["match_mode"]
        mark_read = bool(f["mark_read"])
        target_folder = f["target_folder"] or "INBOX."

        try:
            client.select_folder("INBOX")
            msgs = list(client.fetch(AND(seen=False), mark_seen=False))

            for msg in msgs:
                content = ""
                if field == "from":
                    content = msg.from_.lower()
                elif field == "subject":
                    content = (msg.subject or "").lower()

                match = False
                if match_mode == "contains" and value in content:
                    match = True
                elif match_mode == "is" and value == content:
                    match = True

                if match:
                    if mark_read:
                        client.add_flags(msg.uid, [r'\Seen'])
                    client.move(msg.uid, target_folder)

                    from core.logger import write_error_log
                    write_error_log(account["user_id"], account["username"], f"✉️ Filter: {msg.subject} → {target_folder}")

        except Exception as e:
            from core.logger import write_error_log
            write_error_log(account["user_id"], account["username"], f"Fehler bei Filterauswertung: {e}")

if __name__ == "__main__":
    move_spam_from_all_users()
