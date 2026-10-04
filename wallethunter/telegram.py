"""Envío a Telegram. El token (TELEGRAM_BOT_TOKEN) sale del entorno o de state/secrets; nunca se imprime.
El chat se detecta solo: cuando escribes al bot, getUpdates trae tu chat id y se guarda en la base (kv, privado).
Sin token o sin chat solo se registra en el log (modo prueba)."""
import logging, time
from .config import secret, redact
from .net import request

log = logging.getLogger("wh")
_me = {"t": 0, "v": None}


def _api(method, body=None, retries=2):
    tok = secret("TELEGRAM_BOT_TOKEN")
    if not tok:
        raise RuntimeError("falta TELEGRAM_BOT_TOKEN")
    r = request(f"https://api.telegram.org/bot{tok}/{method}", method="POST", body=body or {}, source="telegram", retries=retries)
    if isinstance(r, dict) and not r.get("ok", True):
        raise RuntimeError(r.get("description") or "error de Telegram")
    return r.get("result") if isinstance(r, dict) else r


class _db:
    """Conexión a la base (db.connect() ya la reutiliza por hilo: no se cierra)."""
    def __enter__(self):
        from . import db
        return db.connect()
    def __exit__(self, *a):
        return False


def chat_id():
    v = secret("TELEGRAM_CHAT_ID")
    if v:
        return v
    from . import db
    with _db() as c:
        return (db.kv_get(c, "telegram:chat") or {}).get("id")


def bot():
    """@usuario del bot (getMe, cacheado 1 h)."""
    if not secret("TELEGRAM_BOT_TOKEN"):
        return None
    if time.time() - _me["t"] > 3600:
        try:
            _me["v"] = (_api("getMe") or {}).get("username"); _me["t"] = time.time()
        except Exception as e:
            log.info("Telegram getMe: %s", redact(str(e))[:120]); _me["t"] = time.time() - 3000
    return _me["v"]


def detect_chat():
    """Busca en getUpdates el último chat que escribió al bot y lo guarda. Devuelve {"id", "name"} o None."""
    if not secret("TELEGRAM_BOT_TOKEN"):
        return None
    from . import db
    try:
        ups = _api("getUpdates", {"limit": 100, "timeout": 0, "allowed_updates": ["message", "my_chat_member", "channel_post"]}) or []
    except Exception as e:
        log.info("Telegram getUpdates: %s", redact(str(e))[:120])
        return None
    best = None
    for u in ups:
        m = u.get("message") or u.get("channel_post") or (u.get("my_chat_member") or {})
        ch = m.get("chat") or {}
        if ch.get("id") is None:
            continue
        if best is None or ch.get("type") == "private" or (best["type"] != "private"):
            best = {"id": str(ch["id"]), "type": ch.get("type"), "name": ch.get("username") or ch.get("first_name") or ch.get("title") or "", "ts": m.get("date")}
    with _db() as c:
        db.kv_set(c, "telegram:last_detect", int(time.time()))
        if best:
            db.kv_set(c, "telegram:chat", best)
    if best:
        log.info("Telegram: chat detectado (%s)", best["type"])
    return best


def status():
    from . import db
    with _db() as c:
        ch, last = db.kv_get(c, "telegram:chat") or {}, db.kv_get(c, "telegram:last_detect")
    return {"token": bool(secret("TELEGRAM_BOT_TOKEN")), "chat": bool(chat_id()), "bot": bot(),
            "chat_name": ch.get("name") or None, "chat_type": ch.get("type"), "last_detect": last}


def send(text):
    tok = secret("TELEGRAM_BOT_TOKEN")
    chat = chat_id() if tok else None
    if tok and not chat:
        chat = (detect_chat() or {}).get("id")
    if not tok or not chat:
        log.info("[telegram desactivado] %s", text.replace("\n", " | ")[:300])
        return False
    try:
        _api("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, retries=3)
        return True
    except Exception as e:
        log.warning("Telegram falló: %s", redact(str(e))[:200])
        return False
