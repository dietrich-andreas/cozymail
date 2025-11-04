# spam_model_trainer.py (multi-user, refactored)
import os
import joblib
from imap_tools import MailBox, AND
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB

from core.config import HAM_MAIL_LIMIT, MODEL_BASE, SPAM_MAIL_LIMIT
from core.crypto import decrypt
from core.database import get_db_connection
from core.logger import get_logger, write_train_log

logger = get_logger("trainer")


def fetch_texts(mailbox, folder, label, limit=100, only_seen=False):
    mailbox.folder.set(folder)
    if only_seen:
        messages = list(mailbox.fetch(AND(seen=True), limit=limit, reverse=True, mark_seen=False))
    else:
        messages = list(mailbox.fetch(limit=limit, reverse=True, mark_seen=False))
    return [(msg.subject + "\n" + msg.text, label) for msg in messages if msg.text]


def train_model_for_account(account, username):
    try:
        password = decrypt(account["password_enc"])
    except Exception as e:
        msg = f"Passwort konnte nicht entschlüsselt werden für {account['username']}: {e}"
        logger.error(msg)
        write_train_log(account["user_id"], account["username"], f"❌ {msg}")
        return

    logger.info(f"🔄 Trainiere Modell für {account['username']} ({username})")
    write_train_log(account["user_id"], account["username"], "🔄 Training gestartet")

    try:
        with MailBox(account['server']).login(account['username'], password) as mailbox:
            # Trainingsdaten abrufen: Junk = Spam, INBOX = Ham
            spam_data = fetch_texts(mailbox, account['junk_folder'], 1, limit=SPAM_MAIL_LIMIT, only_seen=False)
            ham_data = fetch_texts(mailbox, "INBOX", 0, limit=HAM_MAIL_LIMIT, only_seen=False)
    except Exception as e:
        msg = f"Fehler beim Zugriff auf IMAP-Postfach von {account['username']}: {e}"
        logger.error(msg)
        write_train_log(account["user_id"], account["username"], f"❌ {msg}")
        return

    data = spam_data + ham_data
    if not data:
        msg = f"Keine Trainingsdaten für {account['username']}"
        logger.warning(msg)
        write_train_log(account["user_id"], account["username"], f"⚠️ {msg}")
        return

    try:
        texts, labels = zip(*data)
        vectorizer = TfidfVectorizer(stop_words='english', lowercase=True)
        X = vectorizer.fit_transform(texts)
        model = MultinomialNB()
        model.fit(X, labels)

        model_dir = os.path.join(MODEL_BASE, username)
        os.makedirs(model_dir, exist_ok=True)
        joblib.dump(model, os.path.join(model_dir, "spam_model.pkl"))
        joblib.dump(vectorizer, os.path.join(model_dir, "spam_vectorizer.pkl"))

        msg = f"✅ Modell gespeichert in {model_dir}"
        logger.info(msg)
        write_train_log(account["user_id"], account["username"], msg)

    except Exception as e:
        msg = f"Fehler beim Modelltraining oder Speichern: {e}"
        logger.error(msg)
        write_train_log(account["user_id"], account["username"], f"❌ {msg}")

def train_all():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()

        for user in users:
            cursor.execute("SELECT * FROM accounts WHERE user_id = ?", (user["id"],))
            accounts = cursor.fetchall()
            for account in accounts:
                train_model_for_account(account, user["username"])
    conn.close()


if __name__ == "__main__":
    train_all()
