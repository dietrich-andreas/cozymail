#logger.py
import os
import logging
from datetime import datetime
from core.config import LOG_BASE, ERROR_LOG_FILE

# Zentralen Logger einrichten (wird einmalig im Hauptprogramm aufgerufen)
def setup_main_logger():
    os.makedirs(LOG_BASE, exist_ok=True)
    log_file = os.path.join(LOG_BASE, "spam_filter.log")

    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format='%(asctime)s - %(message)s'
    )

    # Werkzeug-Logger stummschalten (z. B. HTTP GET /log…)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Fehlerlogger zur globalen Nutzung
def get_error_logger():
    logger = logging.getLogger("mailfilter_error")
    if not logger.handlers:
        handler = logging.FileHandler(ERROR_LOG_FILE)
        handler.setLevel(logging.ERROR)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.setLevel(logging.ERROR)
        logger.addHandler(handler)
    return logger

def get_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        os.makedirs(LOG_BASE, exist_ok=True)
        log_file = os.path.join(LOG_BASE, f"{name}.log")
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
    return logger

def get_spam_logger():
    logger = logging.getLogger("mailfilter_spam")
    if not logger.handlers:
        handler = logging.FileHandler(SPAM_LOG_FILE)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
    return logger

def write_system_log(message):
    path = SYSTEM_LOG_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} - {message}\n")

# Logdatei pro Konto schreiben (Analysezwecke)
def write_mail_log(user_id, account_email, msg, spam_level, prediction):
    path = os.path.join(LOG_BASE, str(user_id), account_email, "mailfilter.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()};{msg.date};{msg.from_};{msg.subject};{spam_level};{'SPAM' if prediction else 'HAM'}\n")

# Fehlerlog pro Konto schreiben (optional fürs Frontend)
def write_error_log(user_id, account_email, message):
    path = os.path.join(LOG_BASE, str(user_id), account_email, "mailfilter.error.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} - {message}\n")

# Trainingslog pro Konto schreiben (für spätere Analyse im Frontend oder Debugging)
def write_train_log(user_id, account_email, message):
    path = os.path.join(LOG_BASE, str(user_id), account_email, "train.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} - {message}\n")

# Fehlerlog pro Benutzer allgemein (optional)
def write_user_error_log(user_id, message):
    path = os.path.join(LOG_BASE, str(user_id), "mailfilter.error.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} - {message}\n")
