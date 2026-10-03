"""PIN para lanzar escaneos desde la web. Se guarda solo un hash (PBKDF2) en state/pin.json."""
import hashlib, hmac, json, os, secrets, time, threading
from .config import STATE_DIR, secret

_P = os.path.join(STATE_DIR, "pin.json")
_lock = threading.Lock()
_bad = []  # tiempos de PIN incorrectos


def _hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def set_pin(pin):
    pin = str(pin).strip()
    if len(pin) < 4:
        raise ValueError("El PIN debe tener al menos 4 caracteres")
    salt = secrets.token_hex(16)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_P, "w") as f:
        json.dump({"salt": salt, "hash": _hash(pin, salt), "set": int(time.time())}, f)
    os.chmod(_P, 0o600)


def is_set():
    return bool(secret("WH_PIN")) or os.path.exists(_P)


def check(pin):
    """True/False; None si está bloqueado por demasiados intentos."""
    with _lock:
        now = time.time()
        while _bad and now - _bad[0] > 3600:
            _bad.pop(0)
        if len(_bad) >= 10:
            return None
        ok = False
        if pin:
            env = secret("WH_PIN")
            if env:
                ok = hmac.compare_digest(str(pin), env)
            elif os.path.exists(_P):
                with open(_P) as f:
                    d = json.load(f)
                ok = hmac.compare_digest(_hash(str(pin), d["salt"]), d["hash"])
        if not ok:
            _bad.append(now)
        return ok
