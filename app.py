# app.py

##################################
#           Imports              #
##################################
import logging
logging.basicConfig(
    filename='/opt/mailfilter-data//logs/web_error.log',
    level=logging.DEBUG,  # oder logging.ERROR
    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
)
import eventlet, re
eventlet.monkey_patch()
import ast
import hashlib
import inspect
import joblib
import os
try:
    os.getcwd()
except FileNotFoundError:
    os.chdir('/')
import re
import sqlite3
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr
from functools import wraps

from flask import (Flask, current_app, flash, jsonify, redirect,
                   render_template, render_template_string, request,
                   session, url_for)
from flask_socketio import SocketIO
from imap_tools import AND, MailBox, MailMessageFlags
from sklearn.naive_bayes import MultinomialNB
from urllib.parse import unquote, unquote_plus

from core.auth import get_accounts_for_user, verify_user
from core.config import (ERROR_LOG_FILE, LOG_BASE, LOG_FILE, MODEL_BASE,
                        MODEL_PATH, SPAM_LOG_FILE, SYSTEM_LOG_FILE,
                        VECTORIZER_PATH, get_user_log_path)
from core.crypto import decrypt, encrypt
from core.database import get_db_connection
from core.logger import (get_error_logger, setup_main_logger,
                         write_error_log, write_train_log)


##################################
#          App Setup             #
##################################
app = Flask(__name__)
app.secret_key = '1=!R+)B?op7+BE[v9![Nb.a-E'

# Session/Cookie-Setup
app.config.update(
    SESSION_COOKIE_NAME="cozymail_session",
    SESSION_COOKIE_SAMESITE="Lax",   # wenn nur http:// intern: Lax reicht
    SESSION_COOKIE_SECURE=False,     # True nur bei https
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12)  # Session-Dauer
)

socketio = SocketIO(app, async_mode="eventlet")

# Logger initialisieren
setup_main_logger()
error_logger = get_error_logger()

# Konstanten
DEBUG = True

##################################
#          Decorators            #
##################################
def db_handler(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith("/api/"):
                return jsonify({"status": "unauthenticated", "redirect": "/login"}), 401
            return redirect(url_for('login'))
        
        # Basisparameter
        params = {
            'user_id': session.get("user_id"),
            'conn': None,
            'cursor': None
        }
        
        # Zusätzliche Parameter dynamisch prüfen
        sig = inspect.signature(func)
        if 'account' in sig.parameters:
            params['account'] = request.args.get("account")
        if 'logtype' in sig.parameters:
            params['logtype'] = request.args.get("type", "log")
        
        with get_db_connection() as conn:
            params['conn'] = conn
            params['cursor'] = conn.cursor()
            try:
                return func(*args, **{**kwargs, **params})
            except Exception as e:
                conn.rollback()
                error_logger.error(f"Error in {func.__name__}: {str(e)}")
                raise
    return wrapper

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

##################################
#          Web Pages             #
##################################
@app.route('/', methods=['GET'])
@db_handler
def index(cursor, conn, user_id, account, **kwargs):
    cursor.execute("""
        SELECT a.*, 
               (SELECT COUNT(*) FROM mails 
                WHERE account_id = a.id AND seen = 0) as unread_count
        FROM accounts a
        WHERE a.user_id = ?
        ORDER BY a.sort_order ASC
    """, (user_id,))

    accounts = []
    for acc in cursor.fetchall():
        acc_dict = dict(acc)
        # 2. Formatierung für die Anzeige hinzufügen
        acc_dict['unread_display'] = f"{acc_dict['username']} ({acc_dict.get('unread_count', 0)})"
        accounts.append(acc_dict)
    
    if not accounts:
        return "Keine Mailkonten konfiguriert.", 400

    # Aktives Konto bestimmen
    account_id = request.args.get("account", accounts[0]['id'])
    account = next((a for a in accounts if str(a['id']) == str(account_id)), None)
    if not account:
        return "Ungültiges Konto.", 404

    # Mails laden
    cursor.execute("""
        SELECT id, uid, sender, subject, date, seen
        FROM mails
        WHERE user_id = ? AND account_id = ? AND seen = 0 AND flagged_action IS NULL
        ORDER BY datetime(date) DESC
    """, (user_id, account['id']))
    
    mails = []
    for row in cursor.fetchall():
        _, email = parseaddr(row['sender'] or "")
        email = email.strip().lower()
        domain = email.split('@')[-1] if '@' in email else "(unbekannt)"
        
        cursor.execute("""
            SELECT 1 FROM whitelist 
            WHERE user_id = ?
              AND (sender_address = ? OR sender_address = ?)
        """, (user_id, email, f"*@{domain}"))
        
        mails.append({
            **dict(row),
            'from_': email,
            'domain': domain,
            'whitelisted': cursor.fetchone() is not None,
            'unread_display': f"{account['username']} ({account.get('unread_count', 0)})"
        })

    return render_template("inbox.html", mails=mails, accounts=accounts, active_account=account['id'], debug_mode=False)

@app.route("/account/<int:account_id>/delete", methods=["POST"])
@db_handler
def delete_account(cursor, conn, user_id, account_id):
    cursor.execute("DELETE FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id))
    conn.commit()
    return redirect(url_for("accounts"))

@app.route("/account/<int:account_id>/edit", methods=["GET", "POST"])
@db_handler
def edit_account(cursor, conn, user_id, account_id):
    if request.method == "GET":
        cursor.execute("SELECT * FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id))
        account = cursor.fetchone()
        
        if not account:
            abort(404)

    if request.method == "POST":
        updates = {
            'username': request.form["username"].strip(),
            'server': request.form["server"].strip(),
            'trash_folder': request.form["trash_folder"].strip(),
            'junk_folder': request.form["junk_folder"].strip(),
            'x_spam_level': int(request.form["x_spam_level"].strip()),
            'spam_filter_active': 1 if request.form.get("spam_filter_active") else 0
        }
        
        if password := request.form["password"].strip():
            updates['password_enc'] = encrypt(password)
            query = """
                UPDATE accounts 
                SET username = ?, server = ?, password_enc = ?, junk_folder = ?, trash_folder = ?, x_spam_level = ?, spam_filter_active = ?
                WHERE id = ? AND user_id = ?
            """
            params = (
                updates['username'], updates['server'], updates['password_enc'], updates['junk_folder'], updates['trash_folder'], updates['x_spam_level'], updates['spam_filter_active'], account_id, user_id
            )
        else:
            query = """
                UPDATE accounts 
                SET username = ?, server = ?, junk_folder = ?, trash_folder = ?, x_spam_level = ?, spam_filter_active = ?
                WHERE id = ? AND user_id = ?
            """
            params = (
                updates['username'], updates['server'], updates['junk_folder'], updates['trash_folder'], updates['x_spam_level'], updates['spam_filter_active'], account_id, user_id
            )
        
        cursor.execute(query, params)
        conn.commit()
        return redirect(url_for("accounts"))

    return render_template("edit_account.html", account=dict(account))

@app.route("/accounts", methods=["GET", "POST"])
@login_required
def accounts():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        email = request.form["email"].strip()
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        server = request.form["server"].strip()
        junk_folder = request.form["junk_folder"].strip()
        trash_folder = request.form["trash_folder"].strip()
        spam_filter_active = 1 if request.form.get("spam_filter_active") == "on" else 0
        encrypted_pw = encrypt(password)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO accounts (user_id, email, username, password_enc, server, junk_folder, trash_folder, spam_filter_active, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, (SELECT IFNULL(MAX(sort_order), -1) + 1 FROM accounts WHERE user_id = ?))
            """, (user_id, email, username, encrypted_pw, server, junk_folder, trash_folder, spam_filter_active, user_id))
            conn.commit()

        return redirect(url_for("accounts"))

    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 25))
    except ValueError:
        page = 1
        per_page = 25
    offset = (page - 1) * per_page

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts WHERE user_id = ?", (user_id,))
        total = cursor.fetchone()[0]

        cursor.execute("""
            SELECT * FROM accounts 
            WHERE user_id = ? 
            ORDER BY sort_order ASC, id ASC 
            LIMIT ? OFFSET ?
        """, (user_id, per_page, offset))
        accounts = [dict(row) for row in cursor.fetchall()]

    num_pages = (total + per_page - 1) // per_page
    return render_template("accounts.html",
                           accounts=accounts,
                           page=page,
                           per_page=per_page,
                           num_pages=num_pages,
                           total=total)

@app.route("/accounts/reorder", methods=["POST"])
@login_required
def reorder_accounts():
    user_id = session.get("user_id")
    order = request.json.get("order")

    if not order:
        return jsonify({"status": "error", "message": "Keine Reihenfolge erhalten"}), 400

    with get_db_connection() as conn:
        cursor = conn.cursor()
        for index, acc_id in enumerate(order):
            cursor.execute("""
                UPDATE accounts
                SET sort_order = ?
                WHERE id = ? AND user_id = ?
            """, (index, acc_id, user_id))
        conn.commit()

    return jsonify({"status": "ok"})

@app.route("/delete_log", methods=["POST"])
def delete_log():
    log_type = request.args.get("type")

    log_map = {
        "log": LOG_FILE,
        "error": ERROR_LOG_FILE,
        "system": SYSTEM_LOG_FILE,
        "spam": SPAM_LOG_FILE
    }

    log_file = log_map.get(log_type)

    try:
        if not log_file or not os.path.exists(log_file):
            return jsonify({"status": "error", "message": "Logdatei nicht gefunden"}), 404

        open(log_file, "w").close()
        return jsonify({"status": "success"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/delete_old_log_entries", methods=["POST"])
def delete_old_log_entries():
    try:
        data = request.get_json()
        log_type = data.get("type")
        days = int(data.get("days", 0))

        log_map = {
            "log": LOG_FILE,
            "error": ERROR_LOG_FILE,
            "system": SYSTEM_LOG_FILE,
            "spam": SPAM_LOG_FILE
        }

        log_file = log_map.get(log_type)

        if not log_file or not os.path.exists(log_file):
            return jsonify({"status": "error", "message": "Logdatei nicht gefunden"}), 404

        cutoff = datetime.now() - timedelta(days=days)
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        kept_lines = []
        for line in lines:
            try:
                timestamp_str = line.split(" - ")[0]
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                if timestamp >= cutoff:
                    kept_lines.append(line)
            except Exception:
                kept_lines.append(line)

        with open(log_file, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)

        return jsonify({"status": "success"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/filters", methods=["GET", "POST"])
@login_required
def filters():
    user_id = session.get("user_id")
    username = session.get("username")
    selected_account = request.args.get("account")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE user_id = ? ORDER BY sort_order ASC, id ASC", (user_id,))
        accounts = cursor.fetchall()

        # Fallback: Erstes Konto als aktiv
        if not selected_account and accounts:
            selected_account = accounts[0]["id"]
        else:
            selected_account = int(selected_account or 0)

        # Neuen Filter anlegen
        if request.method == "POST":
            field = request.form["field"]
            mode = request.form["mode"]
            value = request.form["value"].strip()
            target_folder = request.form["target_folder"].strip() or "INBOX."
            is_read = 1 if request.form.get("is_read") == "on" else 0
            active = 1 if request.form.get("active") == "on" else 0

            cursor.execute("""
                INSERT INTO filters (user_id, account_id, field, mode, value, target_folder, is_read, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, selected_account, field, mode, value, target_folder, is_read, active))
            conn.commit()
            return redirect(url_for("filters", account=selected_account))

        # Filterliste abrufen
        cursor.execute("""
            SELECT * FROM filters WHERE user_id = ? AND account_id = ?
            ORDER BY created_at DESC
        """, (user_id, selected_account))
        filters = cursor.fetchall()

    return render_template(
        "filters.html",
        accounts=accounts,
        active_account=selected_account,
        filters=filters
    )

@app.route("/filters/delete", methods=["POST"])
@login_required
def delete_filter():
    user_id = session.get("user_id")
    filter_id = request.form["filter_id"]
    account_id = request.form["account_id"]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM filters WHERE id = ? AND user_id = ?", (filter_id, user_id))
        conn.commit()

    return redirect(url_for("filters", account=account_id))

@app.route("/filters/<int:filter_id>/edit", methods=["GET", "POST"])
@login_required
def edit_filter(filter_id):
    user_id = session.get("user_id")
    account_id = request.args.get("account_id", type=int)

    # Filter + Account validieren
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM filters
            WHERE id = ? AND user_id = ?
        """, (filter_id, user_id))
        frow = cursor.fetchone()
        if not frow:
            flash("Filter nicht gefunden.", "error")
            return redirect(url_for("filters", account=account_id or 0))

        # account_id aus URL validieren oder aus Filter ziehen
        if not account_id:
            account_id = frow["account_id"]

        cursor.execute("""
            SELECT username FROM accounts
            WHERE id = ? AND user_id = ?
        """, (account_id, user_id))
        acc = cursor.fetchone()
        account_username = acc["username"] if acc else "(Konto)"

        if request.method == "POST":
            # Form-Daten
            field = request.form["field"].strip()
            mode = request.form["mode"].strip()
            value = request.form["value"].strip()
            target_folder = (request.form.get("target_folder") or "INBOX.").strip()
            is_read = 1 if request.form.get("is_read") == "on" else 0
            active = 1 if request.form.get("active") == "on" else 0

            # Update
            cursor.execute("""
                UPDATE filters
                   SET field = ?, mode = ?, value = ?, target_folder = ?, is_read = ?, active = ?
                 WHERE id = ? AND user_id = ?
            """, (field, mode, value, target_folder, is_read, active, filter_id, user_id))
            conn.commit()

            flash("Änderungen gespeichert.", "success")
            return redirect(url_for("filters", account=account_id))

        # GET → Formular rendern
        filter_dict = dict(frow)
        return render_template(
            "filters_edit.html",
            filter=filter_dict,
            account_id=account_id,
            account_username=account_username
        )

@app.route("/filters/<int:filter_id>/toggle", methods=["POST"])
@login_required
def toggle_filter(filter_id):
    user_id = session.get("user_id")
    account_id = request.form.get("account_id")

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT active FROM filters WHERE id = ? AND user_id = ?", (filter_id, user_id))
        row = c.fetchone()
        if not row:
            flash("Filter nicht gefunden.", "error")
            return redirect(url_for("filters", account=account_id or 0))

        new_active = 0 if row["active"] else 1
        c.execute("UPDATE filters SET active = ? WHERE id = ? AND user_id = ?", (new_active, filter_id, user_id))
        conn.commit()

    return redirect(url_for("filters", account=account_id))

@app.template_filter('urldecode')
def urldecode(value: str) -> str:
    if not value:
        return ""
    # unquote_plus: dekodiert %xx UND '+' → ' '
    try:
        return unquote_plus(value)
    except Exception:
        # Fallback – gibt Rohwert zurück statt 500
        return value

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        if user := verify_user(username, password):
            session.update({
                'logged_in': True,
                'user_id': user['id'],
                'username': user['username']
            })
            session.permanent = True   # <-- wichtig
            return redirect(url_for('index'))
    return render_template("login.html")

@app.route("/log")
@login_required
def view_logs():
    try:
        user_id = session.get("user_id")
        username = session.get("username")
        selected_account = request.args.get("account")

        accounts = get_accounts_for_user(user_id)
        account_usernames = [a["username"] for a in accounts]

        if selected_account and selected_account not in account_usernames:
            return "Kein Konto gefunden.", 404

        if not selected_account and accounts:
            selected_account = accounts[0]["username"]

        # Hilfsfunktion zum Lesen und Rückwärtsdrehen der Zeilen
        def read(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    return lines[::-1] if lines else ["[Leer]\n"]
            except Exception as e:
                return [f"[Fehler beim Lesen: {e}]\n"]

        # Pfade generieren
        log_paths = {
            "log": get_user_log_path(user_id, selected_account, "log"),
            "error": get_user_log_path(user_id, selected_account, "error"),
            "train": get_user_log_path(user_id, selected_account, "train"),
            "system": get_user_log_path(user_id, logtype="system"),
            "spam": get_user_log_path(user_id, logtype="spam")
        }

        # Aktueller Pfad für Anzeige initial auf "log"
        current_log_path = log_paths.get("log")

        return render_template(
            "log.html",
            accounts=accounts,
            selected_account=selected_account,
            current_log_path=current_log_path,
            log_paths=log_paths
        )

    except Exception as e:
        error_logger.exception(f"❌ Fehler in view_logs(): {e}")
        return "Interner Fehler beim Laden der Logs", 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/mark_ham", methods=["POST"])
def mark_ham():
    uid = request.form["uid"]
    account_id = request.form["account_id"]
    user_id = session.get("user_id")

    # Hole die Mail-Daten aus dem Speicher / Cache / DB
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        acc = cursor.fetchone()

    if not acc:
        flash("Konto nicht gefunden", "error")
        return redirect(url_for("inbox"))

    try:
        password = decrypt(acc["password_enc"])
    except Exception:
        flash("Fehler beim Entschlüsseln des Passworts", "error")
        return redirect(url_for("index", account=account_id))

    from imap_tools import MailBox, AND

    try:
        with MailBox(acc['server']).login(acc['username'], password) as mailbox:
            mailbox.folder.set("INBOX")
            msg = next(mailbox.fetch(AND(uid=uid), mark_seen=False), None)

            if not msg:
                flash("Mail nicht gefunden", "error")
                return redirect(url_for("index", account=account_id))

            mail = {
                "uid": msg.uid,
                "from_": msg.from_,
                "subject": msg.subject or "",
                "text": msg.text or "",
                "raw": msg.obj.as_string()
            }

    except Exception as e:
        flash(f"Verbindungsfehler: {e}", "error")
        return redirect(url_for("index", account=account_id))

    # Modell trainieren mit Label "ham"
    train_model(account_id, mail, label="ham")

    # Whitelist-Eintrag in SQLite
    add_to_whitelist_sqlite(user_id, account_id, mail["from_"])

    flash("Als kein Spam markiert, trainiert und Whitelist aktualisiert.", "success")
    return redirect(url_for("index", account=account_id))

@app.route("/mark_read", methods=["POST"])
@login_required
def mark_read():
    user_id = session.get("user_id")
    uid = request.form.get("uid")
    account_id = request.form.get("account_id")

    if not uid or not account_id:
        return redirect(url_for("index"))

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id))
        acc = cursor.fetchone()

    if not acc:
        return redirect(url_for("index"))

    try:
        password = decrypt(acc["password_enc"])
    except Exception:
        return "Fehler beim Entschlüsseln des Passworts", 500

    try:
        with MailBox(acc["server"]).login(acc["username"], password) as mailbox:
            mailbox.folder.set("INBOX")
            mailbox.flag(uid, "\\Seen", True)
    except Exception as e:
        write_error_log(user_id, acc["username"], f"Fehler beim Setzen des Gelesen-Status UID={uid}: {e}")

    return redirect(url_for("index", account=account_id))

@app.route("/notify", methods=["POST"])
def notify():
    try:
        data = request.get_json()
        socketio.emit("mail_received", {          # <-- DAS ist die wichtige Änderung
            "account_id": data.get("account_id"),
            "subject": data.get("subject", "Neue Mail"),
            "timestamp": datetime.now().isoformat()
        }, namespace="/")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        error_logger.error(f"Notify error: {e}")
        return jsonify({"status": "error"}), 500

@app.route("/socket-test")
def socket_test():
    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
          <script>
            const DEBUG = true;
          </script>
          <script src="{{ url_for('static', filename='libs/socket.io.min.js') }}"></script>
          <script>
            document.addEventListener("DOMContentLoaded", function() {
              const socket = io();
              socket.on("connect", () => {
                if (DEBUG) console.log("✅ WebSocket verbunden");
              });
              socket.on("mail:deleted", data => {
                if (DEBUG) console.log("🗑️ Mail gelöscht:", data);
              });
            });
          </script>
        </head>
        <body>
          <h1>Socket.IO Test</h1>
          <table>
            <tr>
              <td class="from-info">
                <span class="nowrap-from">absender@example.com</span><br>
                <span class="domain">
                  example.com
                  <span class="tag is-success is-light is-rounded" title="Absender ist auf der Whitelist">✅ Whitelist</span>
                </span>
              </td>
            </tr>
          </table>
        </body>
        </html>
    """)

@app.route("/whitelist", methods=["GET", "POST"])
@db_handler
def whitelist(cursor, conn, user_id, **kwargs):
    if request.method == "POST":
        sender = request.form["sender_address"].strip().lower()
        cursor.execute("""
            INSERT OR IGNORE INTO whitelist (user_id, sender_address)
            VALUES (?, ?)
        """, (user_id, sender))
        conn.commit()
        return redirect(url_for("whitelist"))

    cursor.execute("""
        SELECT id, sender_address FROM whitelist
        WHERE user_id = ?
        ORDER BY sender_address COLLATE NOCASE
    """, (user_id,))
    return render_template("whitelist.html", 
                         whitelist=[dict(row) for row in cursor.fetchall()])

@app.route("/whitelist/delete", methods=["POST"])
@login_required
def delete_whitelist_entry():
    entry_id = request.form["id"]
    user_id = session.get("user_id")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM whitelist WHERE id = ? AND user_id = ?", (entry_id, user_id))
        conn.commit()

    return redirect(url_for("whitelist"))

##################################
#         API Endpoints          #
##################################
@app.route("/api/mail")
@db_handler
def api_mail(cursor, conn, user_id):
    mail_id = request.args.get("id")
    if not mail_id:
        return jsonify({}), 400

    cursor.execute("""
        SELECT id, uid, sender, subject, date, headers, body, html_body, html_raw, raw
        FROM mails
        WHERE user_id = ? AND id = ?
    """, (user_id, mail_id))
    row = cursor.fetchone()
    if not row:
        return jsonify({})

    mail = dict(row)

    # -----------------------------------------------
    # Header-Parsing und Formatierung
    # -----------------------------------------------
    from core.utils import get_header_case_insensitive
    import ast, re

    raw_headers = mail.get("headers") or ""
    headers_pretty = raw_headers

    try:
        # 1) Wörtliche \r\n und \n in echte Newlines umwandeln
        headers_pretty = raw_headers.replace("\\r\\n", "\n").replace("\\n", "\n")

        # 2) Falls es ein dict-String ist (wie {'From': '...', 'To': '...'})
        #    -> schöner darstellen als Textblock
        header_dict = None
        try:
            header_dict = ast.literal_eval(raw_headers)
        except Exception:
            header_dict = None

        if isinstance(header_dict, dict):
            # Schlüssel alphabetisch sortieren für Stabilität
            formatted_lines = []
            for k, v in sorted(header_dict.items()):
                # Zeilenumbrüche in Values etwas einrücken
                v_clean = re.sub(r'[\r\n]+', ' ', str(v)).strip()
                formatted_lines.append(f"{k}: {v_clean}")
            headers_pretty = "\n".join(formatted_lines)

        # 3) Empfänger aus Header extrahieren
        mail["recipient"] = ""
        if isinstance(header_dict, dict):
            mail["recipient"] = get_header_case_insensitive(header_dict, "To")

    except Exception as e:
        mail["recipient"] = ""
        current_app.logger.warning(f"Fehler beim Header-Parsing in /api/mail: {e}")

    # "Hübsche" Header dem JSON mitgeben
    mail["headers_pretty"] = headers_pretty

    return jsonify(mail)

@app.route("/api/mail/delete", methods=["POST"])
@db_handler
def api_delete_mail(cursor, conn, user_id):
    data = request.get_json()
    mail_id = data.get("id")
    if not mail_id:
        return jsonify({"status": "error"}), 400

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE mails
            SET flagged_action = 'deleted'
            WHERE user_id = ? AND id = ?
        """, (user_id, mail_id))
        conn.commit()

    # Socket.IO Nachricht senden
    socketio.emit("mail:deleted", {"id": mail_id}, namespace="/")
    return jsonify({"status": "ok"})

@app.route("/api/mail/ham", methods=["POST"])
@db_handler
def api_mark_ham(cursor, conn, user_id):
    """
    Markiert eine Mail als 'Ham', trainiert optional und fügt EINE Whitelist-Regel hinzu:
    - scope='address'  -> exact: user@example.com
    - scope='domain'   -> wildcard: *@example.com
    """
    username = session.get("username")
    data = request.get_json() or {}
    mail_id = data.get("id")
    scope   = (data.get("scope") or "address").strip().lower()  # 'address' | 'domain'

    if not mail_id:
        return jsonify({"status": "error", "message": "Mail-ID fehlt"}), 400

    # Mail-Daten
    cursor.execute("""
        SELECT id, subject, body, raw, account_id, sender
        FROM mails
        WHERE user_id = ? AND id = ?
    """, (user_id, mail_id))
    row = cursor.fetchone()
    if not row:
        return jsonify({"status": "not found", "message": "Mail nicht gefunden"}), 404

    subject = row["subject"] or ""
    body    = row["body"] or row["raw"] or ""

    from email.utils import parseaddr
    _, email_addr = parseaddr(row["sender"] or "")
    email_addr = email_addr.strip().lower()

    # Ziel-Wert je nach Scope bestimmen
    if scope == "domain":
        if "@" not in email_addr:
            return jsonify({"status": "error", "message": "Absenderadresse ohne Domain"}), 400
        domain = email_addr.split("@", 1)[1]
        whitelist_value = f"*@{domain}"
    else:
        # default: address
        whitelist_value = email_addr

    # Optionales Training (best effort)
    try:
        model_path      = os.path.join(MODEL_BASE, username, "spam_model.pkl")
        vectorizer_path = os.path.join(MODEL_BASE, username, "spam_vectorizer.pkl")
        if os.path.exists(vectorizer_path):
            vectorizer = joblib.load(vectorizer_path)
            X = vectorizer.transform([subject + "\n" + body])
            model = joblib.load(model_path) if os.path.exists(model_path) else MultinomialNB()
            model.partial_fit(X, [0], classes=[0, 1])  # 0 = ham
            joblib.dump(model, model_path)
    except Exception as e:
        error_logger.warning(f"⚠️ Training übersprungen in api_mark_ham(): {e}")

    # Eintrag (nur einer) nutzerweit setzen
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO whitelist (user_id, sender_address)
            VALUES (?, ?)
        """, (user_id, whitelist_value))
        conn.commit()
    except Exception as e:
        error_logger.error(f"❌ Whitelist-Insert fehlgeschlagen: {e}")
        return jsonify({"status": "error", "message": "Whitelist konnte nicht aktualisiert werden"}), 500

    # Mail aus der Liste entfernen (wie zuvor) – alternativ: seen=1 statt löschen
    cursor.execute("DELETE FROM mails WHERE user_id = ? AND id = ?", (user_id, mail_id))
    conn.commit()

    socketio.emit("mail:deleted", {"id": mail_id}, namespace="/")
    return jsonify({"status": "ok", "message": f"Whitelist aktualisiert: {whitelist_value}"})

@app.route("/api/mail/read", methods=["POST"])
@db_handler
def api_mark_read(cursor, conn, user_id):
    from flask import current_app, request, jsonify

    data = request.get_json(silent=True) or {}
    mail_id = data.get("id")
    if not mail_id:
        return jsonify({"status": "error", "message": "Mail-ID fehlt"}), 400

    try:
        # 1) Mail + Account laden
        cursor.execute("""
            SELECT m.uid, a.server, a.username, a.password_enc, a.id AS account_id
            FROM mails m
            JOIN accounts a ON m.account_id = a.id
            WHERE m.user_id = ? AND m.id = ?
        """, (user_id, mail_id))
        mail_data = cursor.fetchone()
        if not mail_data:
            return jsonify({"status": "not found", "message": "Mail nicht gefunden"}), 404

        # 2) Sofort auf IMAP als gelesen markieren
        password = decrypt(mail_data["password_enc"])
        from imap_tools import MailBox
        with MailBox(mail_data["server"]).login(mail_data["username"], password) as mailbox:
            mailbox.folder.set("INBOX")
            mailbox.flag([str(mail_data["uid"])], ['\\Seen'], True)

        # 3) DB aktualisieren
        cursor.execute("""
            UPDATE mails SET seen = 1
            WHERE user_id = ? AND id = ?
        """, (user_id, mail_id))
        conn.commit()

        # 4) Frontend informieren – fehlschlag darf die Antwort NICHT kaputtmachen
        try:
            sio = (current_app.extensions.get("socketio")
                   if hasattr(current_app, "extensions") else None)
            if sio:
                sio.emit("mail:read", {
                    "id": mail_id,
                    "account_id": mail_data["account_id"]
                }, namespace="/")
            else:
                current_app.logger.debug("socketio nicht registriert – 'mail:read' nicht gesendet.")
        except Exception as emit_err:
            current_app.logger.warning(f"socketio.emit fehlgeschlagen: {emit_err}")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        # Fallback-Logger, falls error_logger nicht existiert
        try:
            error_logger.error(f"Fehler in api_mark_read: {e}")
        except Exception:
            current_app.logger.exception("Fehler in api_mark_read")
        return jsonify({"status": "error", "message": "Serverfehler beim Markieren als gelesen"}), 500

@app.route("/api/mail/spam", methods=["POST"])
@db_handler
def api_mark_spam(cursor, conn, user_id):
    data = request.get_json() or {}
    mail_id = data.get("id")
    seen_param = bool(data.get("seen", True))  # Default: True

    if not mail_id:
        return jsonify({"status": "error", "message": "Mail-ID fehlt"}), 400

    # Existenz & Zugehörigkeit prüfen (JOIN ist unnötig, da wir IMAP nicht anfassen)
    cursor.execute("""
        SELECT id
        FROM mails
        WHERE user_id = ? AND id = ?
    """, (user_id, mail_id))
    if cursor.fetchone() is None:
        return jsonify({"status": "not found", "message": "Mail nicht gefunden"}), 404

    try:
        # Nur DB setzen: seen = 1/0 und flagged_action = 'spam'
        cursor.execute("""
            UPDATE mails
               SET seen = ?, flagged_action = 'spam'
             WHERE user_id = ? AND id = ?
        """, (1 if seen_param else 0, user_id, mail_id))
        conn.commit()
    except Exception as e:
        error_logger.error(f"DB-Update in api_mark_spam fehlgeschlagen: {e}")
        return jsonify({"status": "error", "message": "DB-Update fehlgeschlagen"}), 500

    # Kein Socket-Emit nötig; das Frontend ruft fetchMails() & fetchUnreadCounts() ohnehin auf
    return jsonify({
        "status": "ok",
        "message": f"Spam markiert (seen={'1' if seen_param else '0'})"
    })

@app.route("/api/mails")
@db_handler
def api_mails(cursor, conn, user_id):
    try:
        account_id = request.args.get("account_id")
        if not account_id:
            return jsonify({"error": "account_id parameter required"}), 400
        
        # Mails abrufen
        cursor.execute("""
            SELECT id, uid, sender, subject, date, seen
            FROM mails
            WHERE user_id = ? AND account_id = ? AND seen = 0 AND flagged_action IS NULL
            ORDER BY datetime(date) DESC
        """, (user_id, account_id))
        
        mails = []
        for row in cursor.fetchall():
            sender = row["sender"] or ""
            _, email = parseaddr(sender)
            email = email.strip().lower()
            domain = email.split("@")[-1] if "@" in email else "(unbekannt)"
            
            cursor.execute("""
                SELECT 1 FROM whitelist 
                WHERE user_id = ?
                  AND (sender_address = ? OR sender_address = ?)
            """, (user_id, email, f"*@{domain}"))
            
            mails.append({
                "id": row["id"],
                "uid": row["uid"],
                "sender": row["sender"],
                "subject": row["subject"],
                "date": row["date"],
                "seen": bool(row["seen"]),
                "from": email,
                "domain": domain,
                "whitelisted": cursor.fetchone() is not None
            })
        
        return jsonify(mails)
    except Exception as e:
        error_logger.error(f"Fehler in api_mails: {str(e)}")
        return jsonify({"error": "Server error"}), 500

@app.route("/api/unread_counts")
@db_handler
def api_unread_counts(cursor, conn, user_id):
    try:
        cursor.execute("""
            SELECT a.id AS account_id, COALESCE(COUNT(m.id), 0) AS unread
            FROM accounts a
            LEFT JOIN mails m ON m.account_id = a.id AND m.user_id = a.user_id AND m.seen = 0
            WHERE a.user_id = ?
            GROUP BY a.id
            ORDER BY a.sort_order ASC
        """, (user_id,))
        result = [{"account_id": row[0], "unread": row[1]} for row in cursor.fetchall()]
        return jsonify(result)
    except Exception as e:
        error_logger.error(f"Fehler in api_unread_counts: {str(e)}")
        return jsonify({"error": "Server error"}), 500

@app.route("/logdata")
@db_handler
def logdata(cursor, conn, user_id, account, logtype):
    try:
        path = get_user_log_path(user_id, account, logtype)
        data = parse_log_file(path, logtype)
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Fehler beim Laden von {logtype}-Logs für {account}: {e}")
        return jsonify([])

##################################
#         Socket.IO Events       #
##################################
@socketio.on("connect", namespace="/")
def handle_connect():
    # if DEBUG: print("✅ Client verbunden:", request.sid)
    pass

@socketio.on("disconnect")
def test_disconnect():
    pass

@socketio.on("new_mail", namespace="/")
def handle_new_mail(data):
    """Broadcast an alle Clients wenn neue Mail eintrifft"""
    try:
        account_id = data.get("account_id")
        if DEBUG: print(f"📬 Neue Mail für Konto {account_id}")
        
        # Broadcast an alle Clients des betroffenen Accounts
        socketio.emit('mail_received', {
            'account_id': account_id,
            'subject': data.get("subject", "Neue Mail"),
            'timestamp': datetime.now().isoformat()
        }, room=f"account_{account_id}", namespace="/")
        
    except Exception as e:
        error_logger.error(f"Fehler in handle_new_mail: {str(e)}")

@socketio.on('mark_seen')
def handle_mark_seen(data):
    account_id = data.get("account_id")
    uid = data.get("uid")
    if account_id is None or uid is None:
        if DEBUG: print("[!] Ungültige Daten bei mark_seen Event")
        return
    if DEBUG: print(f"[DEBUG] Empfange mark_seen Event → account_id={account_id}, uid={uid}")
    mark_mail_as_seen_imap(account_id, uid)

##################################
#         Helper Functions       #
##################################
def add_to_whitelist_sqlite(user_id, _account_id, sender_address):
    """Nutzerweite Whitelist (account_id bewusst ignoriert)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO whitelist (user_id, sender_address)
                VALUES (?, ?)
            """, (user_id, sender_address.strip().lower()))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Fehler beim Einfügen in Whitelist: {e}")

def clean_timestamp(raw):
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return raw 

def decode_header_text(text, default="(kein Betreff)"):
    """Zentrale Funktion für Header-Decoding (ersetzt decode() und decode_subject())"""
    if not text:
        return default
    try:
        decoded_parts = decode_header(text)
        return ''.join(
            part.decode(enc or 'utf-8') if isinstance(part, bytes) else part
            for part, enc in decoded_parts
        )
    except Exception as e:
        error_logger.error(f"Header-Decoding fehlgeschlagen: {e}")
        return text[:100] + "..." if len(text) > 100 else text

def extract_domain(addr):
    """Extrahiert die Domain aus einer E-Mail-Adresse"""
    return addr.split("@")[-1] if "@" in addr else "(unbekannt)"

def extract_features(mail):
    """
    Extrahiert Textfeatures aus einer Mail, geeignet für den Vektorizer.
    Erwartet: mail["subject"], mail["text"] (alternativ raw oder leer)
    """
    subject = mail.get("subject", "")
    body = mail.get("text", "") or mail.get("raw", "")
    return subject + "\n" + body

def format_log_lines(lines):
    html = ""
    for line in lines:
        css_class = ""
        if "[ERROR]" in line or "Fehler" in line:
            css_class = "error-line"
        elif "[WARN]" in line or "Warnung" in line:
            css_class = "warn-line"
        elif "[✓]" in line:
            css_class = "success-line"
        html += f'<div class="{css_class}">{line.strip()}</div>\n'
    return html

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def is_whitelisted(sender, entries):
    sender = sender.strip().lower()
    for entry in entries:
        entry = entry.strip().lower()
        if entry.startswith("*@"):
            domain = entry[2:]
            if sender.endswith("@" + domain):
                return True
        if entry == sender:
            return True
    return False

def load_model(model_path):
    """Lädt das Modell, wenn es existiert. Sonst None."""
    if os.path.exists(model_path):
        return joblib.load(model_path)
    else:
        return None

def load_vectorizer(vectorizer_path):
    if os.path.exists(vectorizer_path):
        return joblib.load(vectorizer_path)
    else:
        return None

def parse_log_file(path, logtype):
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return [{"timestamp": "", "level": "ERROR", "message": f"[Fehler beim Lesen der Datei: {e}]"}]

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue

        if logtype == "spam":
            parts = line.split(";")
            if len(parts) == 6:
                entries.append({
                    "timestamp": clean_timestamp(parts[0]),
                    "received": parts[1],
                    "from": parts[2],
                    "subject": parts[3],
                    "score": parts[4],
                    "label": parts[5],
                })
        elif logtype == "log":
            parts = line.split(";")
            if len(parts) >= 6:
                entries.append({
                    "timestamp": clean_timestamp(parts[0]),
                    "level": "INFO",
                    "message": ";".join(parts[1:])  # Rest der Zeile
                })
        else:
            if " - " in line:
                timestamp, message = line.split(" - ", 1)
                level = "INFO"
                if "Fehler" in message or "ERROR" in message:
                    level = "ERROR"
                elif "WARN" in message:
                    level = "WARN"
                elif "DEBUG" in message:
                    level = "DEBUG"
                entries.append({
                    "timestamp": timestamp,
                    "level": level,
                    "message": message
                })
            else:
                entries.append({
                    "timestamp": "",
                    "level": "INFO",
                    "message": line
                })

    return entries

def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()[::-1]
    except Exception as e:
        return [f"[Fehler beim Lesen: {e}]"]

def save_model(model, model_path):
    """Speichert das Modell an gegebener Stelle"""
    joblib.dump(model, model_path)

def train_model(account_id, mail, label="ham"):
    user_dir = os.path.join(MODEL_BASE, session["username"])
    os.makedirs(user_dir, exist_ok=True)

    model_path = os.path.join(user_dir, "spam_model.pkl")
    vectorizer_path = os.path.join(user_dir, "spam_vectorizer.pkl")

    text = extract_features(mail)
    y_label = 0 if label == "ham" else 1  # 0 = kein Spam, 1 = Spam

    # Vektorizer laden oder abbrechen
    if not os.path.exists(vectorizer_path):
        write_train_log(session["user_id"], account_id, "❌ Kein Vektorizer vorhanden – Training abgebrochen.")
        return

    vectorizer = joblib.load(vectorizer_path)
    X = vectorizer.transform([text])

    # Modell laden oder initialisieren
    if os.path.exists(model_path):
        model = joblib.load(model_path)
    else:
        model = MultinomialNB()

    # Vorherige Counts sichern
    prev_counts = list(model.class_count_) if hasattr(model, "class_count_") else [0, 0]

    # Training
    model.partial_fit(X, [y_label], classes=[0, 1])
    new_counts = list(model.class_count_)

    joblib.dump(model, model_path)

    log_line = (
        f"✅ Training ({label}): Betreff={mail.get('subject', '')} – "
        f"Klassen: {model.classes_.tolist()}, "
        f"Counts vorher: {prev_counts}, nachher: {new_counts}"
    )
    write_train_log(session["user_id"], account_id, log_line)

##################################
#         Template Filters       #
##################################
@app.template_filter('header_breaks')
def header_breaks(s):
    if not s:
        return ""
    return s.replace('\r\n', '<br>').replace('\n', '<br>').replace('\r', '<br>')

@app.template_filter('decode_header')
def decode_header_filter(text):
    return decode_header_text(text)

##################################
#          Main Execution        #
##################################
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=80, debug=False)