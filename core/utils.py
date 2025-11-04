# core/utils.py

from email.header import decode_header

def get_header_case_insensitive(headers, key):
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return ""

def safe_decode_header(value):
    if not value:
        return ""
    parts = decode_header(value)
    result = ''
    for part, enc in parts:
        try:
            if isinstance(part, bytes):
                enc = enc or 'utf-8'
                if enc.lower() == 'unknown-8bit':
                    enc = 'utf-8'
                result += part.decode(enc, errors='replace')
            else:
                result += part
        except Exception:
            continue
    return result
