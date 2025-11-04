# idle_mail_watcher.py

import threading
import time
import requests, os, joblib
import socketio as client_socketio
from bs4 import BeautifulSoup
from core.config import MODEL_BASE
from core.crypto import decrypt
from core.database import get_db_connection
from core.logger import setup_main_logger, write_error_log, write_mail_log
from core.utils import safe_decode_header, get_header_case_insensitive
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from flask_socketio import SocketIO
from imapclient import IMAPClient
from imap_tools import MailBox, AND
from spam_filter import is_whitelisted, get_header_value
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from urllib.parse import unquote

setup_main_logger()

CHECK_TIMEOUT = 300  # alle 5 Minuten IDLE erneuern
NOTIFY_ENDPOINT = 'http://localhost/notify'  # WebSocket-Post-Endpoint
DEBUG = False

def is_spam(user_object, subject, body):
    username = user_object["username"]
    model_dir = os.path.join(MODEL_BASE, username)
    model_path = os.path.join(model_dir, "spam_model.pkl")
    vectorizer_path = os.path.join(model_dir, "spam_vectorizer.pkl")

    try:
        model = joblib.load(model_path)
        vectorizer = joblib.load(vectorizer_path)
        features = vectorizer.transform([subject + "\n" + body])
        prediction = model.predict(features)[0]
        return prediction == 1
    except Exception as e:
        if DEBUG: print(f"[!] Fehler bei Klassifikation für {username}: {e}")
        return False

def safe_parse_date(date_str):
    try:
        dt = parsedate_to_datetime(date_str)
        if dt and (dt.year < 1970 or dt.year > 2100):
            if DEBUG:
                print(f"[!] Unplausibles Datum erkannt ({dt.year}) → wird ignoriert.")
            return None
        return dt
    except Exception as e:
        if DEBUG:
            print(f"[!] Fehler beim Parsen des Datums '{date_str}': {e}")
        return None

def decode_subject(value):
    return safe_decode_header(value)

def fetch_unseen_mails(account):
    unseen_messages = []
    try:
        if DEBUG: print(f"[DEBUG] Verbinde zu {account['email']} via IMAPClient")
        with IMAPClient(account['server'], ssl=True) as client:
            client.login(account['username'], decrypt(account['password_enc']))
            client.select_folder('INBOX')
            uids = client.search(['UNSEEN'])
            if DEBUG: print(f"[DEBUG] {len(uids)} ungelesene UIDs für {account['email']}")
            for uid in uids:
                try:
                    msg_data = client.fetch([uid], ['BODY.PEEK[]'])
                    raw_msg = msg_data[uid][b'BODY[]']
                    mime_msg = message_from_bytes(raw_msg)
                    subject = decode_subject(mime_msg.get("Subject", ""))
                    sender = safe_decode_header(mime_msg.get("From", ""))
                    msg_id = mime_msg.get("Message-ID", None)
                    date = safe_parse_date(mime_msg.get("Date")) if mime_msg.get("Date") else None
                    headers = dict(mime_msg.items())

                    body = ""
                    html_body = ""
                    html_raw = ""
                    text_body = ""
                    if mime_msg.is_multipart():
                        for part in mime_msg.walk():
                            ctype = part.get_content_type()
                            disp = str(part.get("Content-Disposition"))
                            try:
                                content = part.get_payload(decode=True).decode(
                                    part.get_content_charset() or 'utf-8',
                                    errors='replace'
                                )
                            except Exception:
                                continue

                            if ctype == 'text/plain' and 'attachment' not in disp:
                                text_body = content
                            elif ctype == 'text/html' and 'attachment' not in disp:
                                html_raw = content
                                html_body = clean_html(content)
                    else:
                        ctype = mime_msg.get_content_type()
                        try:
                            content = mime_msg.get_payload(decode=True).decode(
                                mime_msg.get_content_charset() or 'utf-8',
                                errors='replace'
                            )
                            if ctype == 'text/plain':
                                text_body = content
                            elif ctype == 'text/html':
                                html_raw = content
                                html_body = clean_html(content)
                        except Exception:
                            pass

                    msg = type("Msg", (), {})()
                    msg.uid = uid
                    msg.subject = subject
                    msg.from_ = sender
                    msg.headers = headers
                    msg.date = date
                    msg.text = text_body
                    msg.html_body = html_body
                    msg.html_raw = html_raw
                    msg.obj = mime_msg

                    unseen_messages.append(msg)
                except Exception as mail_error:
                    if DEBUG: print(f"[!] Fehler beim Verarbeiten von UID={uid}: {mail_error}")
    except Exception as e:
        if DEBUG: print(f"[!] Fehler beim Abrufen via imapclient: {e}")
    return unseen_messages

def sync_seen_flags(account):
    """Setzt auf dem IMAP-Server alle Mails als gelesen, die in der DB seen=1 haben."""
    try:
        password = decrypt(account["password_enc"])
        with MailBox(account["server"]).login(account["username"], password) as mailbox:
            mailbox.folder.set("INBOX")

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT uid FROM mails
                    WHERE account_id = ? AND user_id = ? AND seen = 1
                """, (account["id"], account["user_id"]))
                uids = [str(row["uid"]) for row in cursor.fetchall()]

            if uids:
                if DEBUG: print(f"[DEBUG] Setze {len(uids)} Mails als gelesen (IMAP \Seen) → {uids}")
                mailbox.flag(uids, ['\Seen'], True)
    except Exception as e:
        write_error_log(account["user_id"], account["username"], f"Fehler bei sync_seen_flags: {e}")

def mark_mail_as_seen_imap(account_id, uid):
    """Setzt eine einzelne Mail auf dem IMAP-Server sofort als gelesen."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT a.*, u.id as user_id, u.username
                FROM accounts a
                JOIN users u ON a.user_id = u.id
                WHERE a.id = ?
            """, (account_id,))
            account = cursor.fetchone()
            if not account:
                if DEBUG: print(f"[!] Kein Account gefunden für ID {account_id}")
                return

        password = decrypt(account["password_enc"])
        with MailBox(account["server"]).login(account["username"], password) as mailbox:
            mailbox.folder.set("INBOX")
            mailbox.flag([str(uid)], ['\\Seen'], True)
            if DEBUG: print(f"[DEBUG] Mail UID={uid} als gelesen auf IMAP gesetzt für Account-ID {account_id}")
            
            # Update database to reflect the change
            cursor.execute("""
                UPDATE mails SET seen = 1 
                WHERE account_id = ? AND uid = ?
            """, (account_id, uid))
            conn.commit()
    except Exception as e:
        write_error_log(account["user_id"], account["username"], f"Fehler beim Sofort-Setzen als gelesen: UID={uid}, {e}")

def load_whitelist(account_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT sender_address FROM whitelist WHERE account_id = ?", (account_id,))
        return [row[0] for row in cursor.fetchall()]

def apply_filters(account, msg):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT field, mode, value, target_folder, is_read
                FROM filters
                WHERE account_id = ? AND user_id = ? AND active = 1
            """, (account["id"], account["user_id"]))
            filters = cursor.fetchall()

        for field, mode, value, target_folder, is_read in filters:
            haystack = ""
            if field == "subject":
                haystack = msg.subject or ""
            elif field in ("sender", "from"):
                raw = msg.from_ or ""
                _, haystack = parseaddr(raw)
            elif field == "to":
                raw = msg.headers.get("To", "") or ""
                _, haystack = parseaddr(raw)
            elif field == "body":
                haystack = msg.text or ""
            elif field == "headers":
                haystack = str(msg.headers)
            else:
                continue  # Unbekanntes Feld überspringen

            match = False
            if mode == "contains":
                match = value.lower() in haystack.lower()
            elif mode == "startswith":
                match = haystack.lower().startswith(value.lower())
            elif mode == "endswith":
                match = haystack.lower().endswith(value.lower())
            elif mode == "exact":
                match = haystack.lower() == value.lower()
            elif mode == "regex":
                import re
                try:
                    match = bool(re.search(value, haystack))
                except re.error:
                    continue

            if match:
                decoded_folder = unquote(target_folder) or "INBOX"
                if DEBUG: print(f"[DEBUG] Filterregel greift für UID={msg.uid} → {field} {mode} {value} → {decoded_folder}, is_read={is_read}")
                return {
                    "target_folder": decoded_folder,
                    "is_read": bool(is_read)
                }

        # if DEBUG: print(f"[DEBUG] Keine Filterregel für UID={msg.uid}")
        return None
    except Exception as e:
        if DEBUG: print(f"[!] Fehler beim Anwenden der Filter für UID={msg.uid}: {e}")
        return None

def save_mail_to_db(account, msg):
    # Zuerst prüfen, ob UID für dieses Konto bereits existiert
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM mails WHERE account_id = ? AND uid = ?", (account["id"], msg.uid))
        exists = cursor.fetchone()[0] > 0

    if exists:
        #if DEBUG: print(f"[DEBUG] Mail UID={msg.uid} existiert bereits – übersprungen")
        return
    user_id = account["user_id"]
    account_id = account["id"]

    try:
        raw_headers = msg.obj.as_string()
    except Exception:
        raw_headers = ""

    if DEBUG: print(f"[DEBUG] Speichere Mail UID={msg.uid} von {msg.from_} in Datenbank")

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO mails (user_id, account_id, uid, msg_id, date, sender, subject, headers, body, html_body, html_raw, raw, seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                user_id,
                account_id,
                msg.uid,
                msg.headers.get("Message-ID") or f"no-id-{msg.uid}",
                msg.date.isoformat() if msg.date else None,
                str(msg.from_),
                str(msg.subject),
                str(str(msg.headers)),
                msg.text or "",
                str(getattr(msg, "html_body", "")),
                str(getattr(msg, "html_raw", "")),      # <-- NEU
                raw_headers
            ))
            conn.commit()
            if DEBUG: print(f"[DEBUG] Mail UID={msg.uid} wurde erfolgreich gespeichert (rowcount={cursor.rowcount})")
    except Exception as db_error:
        if DEBUG: print(f"[!] Fehler beim Speichern der Mail UID={msg.uid}: {db_error}")

def process_flagged_mails(account):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Markierte Spam Mails
        cursor.execute("""
            SELECT * FROM mails
            WHERE account_id = ? AND user_id = ? AND flagged_action = 'spam'
        """, (account["id"], account["user_id"]))
        rows = cursor.fetchall()

        for row in rows:
            subject = row["subject"] or ""
            body = row["body"] or row["raw"] or ""
            uid = row["uid"]
            username = account["username"]

            model_dir = os.path.join(MODEL_BASE, username)
            model_path = os.path.join(model_dir, "spam_model.pkl")
            vectorizer_path = os.path.join(model_dir, "spam_vectorizer.pkl")

            if os.path.exists(vectorizer_path):
                vectorizer = joblib.load(vectorizer_path)
                X = vectorizer.transform([subject + "\n" + body])
                if os.path.exists(model_path):
                    model = joblib.load(model_path)
                else:
                    model = MultinomialNB()
                    model.partial_fit(X, [1], classes=[0, 1])
                model.partial_fit(X, [1])
                joblib.dump(model, model_path)

            try:
                password = decrypt(account["password_enc"])
                with MailBox(account["server"]).login(account["username"], password) as mailbox:
                    mailbox.folder.set("INBOX")
                    mailbox.flag(uid, 'Junk', True)
                    mailbox.move(uid, account["junk_folder"])
            except Exception as e:
                write_error_log(account["user_id"], account["username"], f"Fehler beim Verschieben UID={uid}: {e}")

            cursor.execute("DELETE FROM mails WHERE id = ?", (row["id"],))
        conn.commit()

        # Markierte Gelöschte Mails
        cursor.execute("""
            SELECT * FROM mails
            WHERE account_id = ? AND user_id = ? AND flagged_action = 'deleted'
        """, (account["id"], account["user_id"]))
        deleted_rows = cursor.fetchall()

        for row in deleted_rows:
            uid = row["uid"]
            try:
                with MailBox(account["server"]).login(account["username"], decrypt(account["password_enc"])) as mailbox:
                    mailbox.folder.set("INBOX")
                    mailbox.flag(uid, "\\Seen", True)
                    mailbox.move(uid, account["trash_folder"])
            except Exception as e:
                write_error_log(account["user_id"], account["username"], f"Fehler beim Verschieben UID={uid} in Papierkorb: {e}")

            # Danach aus DB entfernen
            cursor.execute("DELETE FROM mails WHERE id = ?", (row["id"],))
        conn.commit()

def idle_monitor(account):
    email = account['email']
    server = account['server']
    username = account['username']
    password = decrypt(account['password_enc'])
    user = account['user']

    while True:
        # Trigger Bereinigung beim ersten Ereignis nach Start oder Push-Änderung
        sync_account_uidvalidity(account)
        try:
            with IMAPClient(server, ssl=True) as client:
                client.login(username, password)
                client.select_folder("INBOX")
                # if DEBUG: print(f"[DEBUG] IDLE aktiv für {email}")
                client.idle()
                responses = client.idle_check(timeout=CHECK_TIMEOUT)
                sync_account_uidvalidity(account)  # Auch nach IMAP-Push prüfen
                client.idle_done()

                if not responses:
                    continue

            mails = fetch_unseen_mails(account)

            whitelist = load_whitelist(account.get("id"))

            for msg in mails:
                try:
                    # if DEBUG: print(f"[DEBUG] Prüfe Mail UID={msg.uid} From={msg.from_}")

                    # 1. Filter
                    target = apply_filters(account, msg)
                    if target:
                        folder_name = target['target_folder']
                        if DEBUG: print(f"[DEBUG] Filter aktiv – verschiebe UID={msg.uid} in {folder_name}")
                        with MailBox(server).login(username, password) as mailbox:
                            mailbox.folder.set("INBOX")
                            if not target['is_read']:
                                mailbox.flag(str(msg.uid), ['\\Seen'], value=False)
                            try:
                                result = mailbox.move(str(msg.uid), folder_name)
                                if DEBUG: print(f"[DEBUG] Ergebnis von mailbox.move(): {result}")
                            except Exception as move_error:
                                print(f"[!] Fehler beim Verschieben UID={msg.uid} → {folder_name}: {move_error}")
                        continue

                    # 2. Whitelist
                    if is_whitelisted(msg.from_, whitelist):
                        # if DEBUG: print(f"[DEBUG] Absender {msg.from_} auf Whitelist – keine Spamprüfung")
                        save_mail_to_db(account, msg)
                        continue

                    # 3. Spamprüfung
                    spam_level_raw = get_header_case_insensitive(msg.headers, "X-Spam-Level")
                    spam_level_str = safe_decode_header(spam_level_raw)
                    spam_level = spam_level_str.count("*") if spam_level_str else 0
                    prediction = is_spam(user, msg.subject, msg.text or "")
                    x_level = account.get("x_spam_level") or 5

                    if DEBUG and (prediction or spam_level > 0):
                        reason = []
                        if spam_level > 0:
                            reason.append(f"Level {spam_level}")
                        if prediction:
                            reason.append("Machine Learning (ML) Spam Prediction")
                        print(f"[DEBUG] 3. Spamprüfung: Treffer → UID={msg.uid} → {' + '.join(reason)}")

                    if spam_level >= x_level or prediction:
                        if DEBUG:
                            print(f"[DEBUG] X   Spam erkannt UID={msg.uid} - From={msg.from_} – Verschiebe in Junk")
                            print(f"[DEBUG] XX  Spam-Level: {spam_level}, ML: {prediction}, Schwelle: {x_level}")
                            print(f"[DEBUG] XXX Zielordner für Junk: {account.get('junk_folder')}")
                        with MailBox(server).login(username, password) as mailbox:
                            mailbox.folder.set("INBOX")
                            mailbox.flag(str(msg.uid), 'Junk', True)
                            result = mailbox.move(str(msg.uid), account["junk_folder"])
                            if DEBUG: print(f"[DEBUG] XXXX Ergebnis von mailbox.move(): {result}")
                            #folders = mailbox.folder.list()
                            #if DEBUG: print("[DEBUG] Verfügbare Ordner:", [f.name for f in folders])
                        reason = []
                        if spam_level >= x_level:
                            reason.append(f"Level {spam_level} ≥ {x_level}")
                        if prediction:
                            reason.append("ML")
                        write_mail_log(account["user_id"], username, msg, spam_level, ", ".join(reason))
                        continue

                    # if DEBUG: print(f"[DEBUG] Kein Spam und kein Filter – speichere Mail UID={msg.uid} - Account={account['email']} - FROM={msg.from_}")

                    # 4. Speichern in DB
                    try:
                        save_mail_to_db(account, msg)
                        
                        # Nur HTTP-Benachrichtigung senden
                        try:
                            requests.post(NOTIFY_ENDPOINT, json={
                                "account_id": account['id'],
                                "subject": msg.subject[:100],
                                "uid": msg.uid
                            }, timeout=2)
                        except Exception as notify_error:
                            if DEBUG: print(f"[!] Fehler beim HTTP Notify: {notify_error}")

                            # Fallback: HTTP-Request
                            requests.post(NOTIFY_ENDPOINT, json={
                                "account_id": account['id'],
                                "subject": msg.subject[:100],
                                "uid": msg.uid
                            }, timeout=2)

                    except Exception as inner_error:
                        write_error_log(account["user_id"], account["username"], f"Mail-Verarbeitung fehlgeschlagen: {inner_error}")

                except Exception as inner:
                    write_error_log(0, username, f"Fehler bei Mail-Verarbeitung: {inner}")

                try:
                    requests.post(NOTIFY_ENDPOINT, json={
                        "user": username,
                        "msg": f"Neue Nachricht bei {email}"
                    })
                except Exception as ping_error:
                    write_error_log(0, username, f"Fehler beim POST an {NOTIFY_ENDPOINT}: {ping_error}")

            process_flagged_mails(account)
            sync_seen_flags(account)

        except Exception as e:
            write_error_log(0, username, f"Fehler im IDLE-Thread: {e}")
            time.sleep(10)

        try:
            if 'last_sync' not in account:
                account['last_sync'] = time.time()
            if time.time() - account['last_sync'] > 300:
                sync_account_uidvalidity(account)
                account['last_sync'] = time.time()
        except:
            pass

def cleanup_inbox_mails(conn, account_id, uids_in_inbox):
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM mails WHERE account_id = ?", (account_id,))
    uids_in_db = {int(row[0]) for row in cursor.fetchall()}
    uids_missing = uids_in_db - set(int(uid) for uid in uids_in_inbox)
    if uids_missing:
        cursor.executemany("DELETE FROM mails WHERE account_id = ? AND uid = ?", [(account_id, uid) for uid in uids_missing])
        if DEBUG: print(f"[DEBUG] Entferne {len(uids_missing)} Mails aus DB für Konto-ID {account_id} (nicht mehr im Posteingang)")

def clean_html(raw_html):
    """
    Bereinigt HTML-Inhalte aus Mails:
    - entfernt gefährliche Tags
    - entschärft href und src
    - entfernt background= Attribute (externe Bilder)
    - entfernt background-image in style Attributen
    """
    soup = BeautifulSoup(raw_html, "lxml")

    # Entferne unsichere komplette Tags
    for tag in soup(["script", "iframe", "style", "link", "object", "embed"]):
        tag.decompose()
    # Links und Ressourcen entschärfen
    for tag in soup.find_all(href=True):
        tag['href'] = "#"
    for tag in soup.find_all(src=True):
        tag['src'] = ""
    # 💡 NEU: background= entfernen
    for tag in soup.find_all(attrs={"background": True}):
        del tag["background"]
    # 💡 NEU: background-image / background url im style entfernen
    for tag in soup.find_all(style=True):
        style = tag["style"]
        style_lower = style.lower()
        if "background-image" in style_lower or "background:" in style_lower:
            del tag["style"]
    # Auch noch event handler (onload, onclick, ...)
    for tag in soup.find_all():
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr.lower().startswith("on"):
                del tag.attrs[attr]
    return str(soup)

def sync_account_uidvalidity(account):
    try:
        with IMAPClient(account['server'], ssl=True) as client:
            client.login(account['username'], decrypt(account['password_enc']))
            client.select_folder("INBOX")
            folder_info = client.folder_status("INBOX", ["UIDVALIDITY", "UIDNEXT"])
            # if DEBUG: print(f"[DEBUG] folder_info = {folder_info}")
            new_uidvalidity = folder_info.get(b"UIDVALIDITY")
            new_uidnext = folder_info.get(b"UIDNEXT")
            if new_uidnext is not None:
                new_last_uid = new_uidnext - 1
            else:
                new_last_uid = None

            uids_inbox = client.search(["UNSEEN"])

        with get_db_connection() as conn:
            cleanup_inbox_mails(conn, account["id"], uids_inbox)

            if new_uidvalidity is not None:
                cursor = conn.cursor()
                cursor.execute("SELECT uid_validity FROM accounts WHERE id = ?", (account["id"],))
                row = cursor.fetchone()
                old_uidvalidity = row[0] if row else None

                if old_uidvalidity != new_uidvalidity:
                    cursor.execute("DELETE FROM mails WHERE account_id = ?", (account["id"],))
                    # if DEBUG: print(f"[DEBUG] UIDVALIDITY geändert für {account['email']} → Mails gelöscht")

                cursor.execute("""
                    UPDATE accounts SET uid_validity = ?, last_seen_uid = ?
                    WHERE id = ?
                """, (new_uidvalidity, new_last_uid, account["id"]))
                conn.commit()
                # if DEBUG:  print(f"[DEBUG] UIDVALIDITY aktualisiert: {new_uidvalidity}, LAST_UID: {new_last_uid} für {account['email']}")
    except Exception as e:
        write_error_log(0, account["username"], f"Fehler bei UIDVALIDITY-Sync: {e}")

def start_all_idles():
    # if DEBUG: print("[DEBUG] Starte Idle-Threads für alle Accounts ...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()

        for user in users:
            cursor.execute("SELECT * FROM accounts WHERE user_id = ?", (user["id"],))
            accounts = cursor.fetchall()
            for acc in accounts:
                if DEBUG: print(f"[DEBUG] Starte Thread für: {acc['email']} ({acc['username']})")
                acc_dict = dict(acc)
                sync_account_uidvalidity(acc_dict)
                acc_dict["user"] = dict(user)
                t = threading.Thread(target=idle_monitor, args=(acc_dict,), daemon=True)
                t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    start_all_idles()
