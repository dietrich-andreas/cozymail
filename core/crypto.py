### core/crypto.py
import os
from cryptography.fernet import Fernet
from core.config import KEY_FILE

def generate_key():
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    print("[✓] Neuer Fernet-Schlüssel wurde generiert.")

def load_key():
    if not os.path.exists(KEY_FILE):
        raise FileNotFoundError("Verschlüsselungsschlüssel fehlt. Bitte generate_key() aufrufen.")
    with open(KEY_FILE, "rb") as f:
        return f.read()

def encrypt(text: str) -> str:
    fernet = Fernet(load_key())
    return fernet.encrypt(text.encode()).decode()

def decrypt(token: str) -> str:
    fernet = Fernet(load_key())
    return fernet.decrypt(token.encode()).decode()

if __name__ == "__main__":
    if not os.path.exists(KEY_FILE):
        generate_key()
    else:
        print("[i] Schlüssel existiert bereits.")