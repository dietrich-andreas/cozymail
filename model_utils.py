# model_utils.py
import os
import joblib

MODEL_BASE = "/opt/mailfilter-data/models"

def is_spam(username, subject, body):
    model_dir = os.path.join(MODEL_BASE, username)
    try:
        model = joblib.load(os.path.join(model_dir, "spam_model.pkl"))
        vectorizer = joblib.load(os.path.join(model_dir, "spam_vectorizer.pkl"))
        text = subject + " " + body
        X = vectorizer.transform([text])
        return model.predict(X)[0] == 1
    except Exception as e:
        print(f"[!] Fehler bei Klassifikation für {username}: {e}")
        return False

def save_model(username, model, vectorizer):
    model_dir = os.path.join(MODEL_BASE, username)
    os.makedirs(model_dir, exist_ok=True)
    joblib.dump(model, os.path.join(model_dir, "spam_model.pkl"))
    joblib.dump(vectorizer, os.path.join(model_dir, "spam_vectorizer.pkl"))


def load_model(username):
    model_dir = os.path.join(MODEL_BASE, username)
    model = joblib.load(os.path.join(model_dir, "spam_model.pkl"))
    vectorizer = joblib.load(os.path.join(model_dir, "spam_vectorizer.pkl"))
    return model, vectorizer
