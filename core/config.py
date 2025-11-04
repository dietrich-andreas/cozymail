# config.py

import os

DB_PATH = "/opt/mailfilter-data/mailfilter.db"
LOG_BASE = "/opt/mailfilter-data/logs"
MODEL_BASE = "/opt/mailfilter-data/models"
KEY_FILE = "/opt/mailfilter-data/secrets/fernet.key"

LOG_FILE = f"{LOG_BASE}/mailfilter.log"
ERROR_LOG_FILE = f"{LOG_BASE}/mailfilter.error.log"
SPAM_LOG_FILE = f"{LOG_BASE}/spam_filter.log"
SYSTEM_LOG_FILE = f"{LOG_BASE}/system.log"

MODEL_PATH = f"{MODEL_BASE}/spam_model.pkl"
VECTORIZER_PATH = f"{MODEL_BASE}/spam_vectorizer.pkl"

# Maximale Anzahl an E-Mails aus dem Junk-Ordner für das Spam-Training
SPAM_MAIL_LIMIT = 200
# Maximale Anzahl an E-Mails aus dem Posteingang (INBOX) für das Ham-Training
HAM_MAIL_LIMIT = 500

def get_user_log_path(user_id, account_name=None, logtype="log"):
    """
    Liefert den vollständigen Pfad zur Logdatei eines Nutzers/Kontos.
    logtype: "log", "error", "train", "system", "spam"
    """
    user_path = os.path.join(LOG_BASE, str(user_id))
    if logtype == "spam":
        return SPAM_LOG_FILE
    elif logtype == "system":
        return SYSTEM_LOG_FILE
    elif account_name:
        if logtype == "log":
            return os.path.join(user_path, account_name, "mailfilter.log")
        elif logtype == "error":
            return os.path.join(user_path, account_name, "mailfilter.error.log")
        elif logtype == "train":
            return os.path.join(user_path, account_name, "train.log")
    if logtype in {"log", "error", "train"} and not account_name:
	    raise ValueError(f"Ungültiger Logtyp oder fehlender account_name: {logtype}")
