"""Carga config.json + rutas. Los secretos SOLO se leen del entorno y nunca se imprimen."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.environ.get("WH_STATE_DIR", os.path.join(ROOT, "state"))
WEB_DIR = os.path.join(ROOT, "web")
DB_PATH = os.environ.get("WH_DB", os.path.join(STATE_DIR, "wallethunter.db"))
DATA_JSON = os.environ.get("WH_DATA", os.path.join(WEB_DIR, "data.json"))

_cfg = None


def cfg():
    global _cfg
    if _cfg is None:
        with open(os.path.join(ROOT, "config.json")) as f:
            _cfg = json.load(f)
        # ajustes guardados desde la web (alertas, etc.)
        p = os.path.join(STATE_DIR, "settings.json")
        if os.path.exists(p):
            try:
                with open(p) as f:
                    s = json.load(f)
                if isinstance(s.get("alerts"), dict):
                    _cfg["alerts"].update(s["alerts"])
            except Exception:
                pass
        if os.environ.get("WH_MAX_WALLETS"):
            _cfg["max_wallets_per_token"] = int(os.environ["WH_MAX_WALLETS"])
    return _cfg


def save_settings(alerts: dict):
    os.makedirs(STATE_DIR, exist_ok=True)
    p = os.path.join(STATE_DIR, "settings.json")
    cur = {}
    if os.path.exists(p):
        try:
            cur = json.load(open(p))
        except Exception:
            cur = {}
    cur.setdefault("alerts", {}).update(alerts)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cur, f, indent=1)
    os.replace(tmp, p)
    global _cfg
    _cfg = None


def secret(name):
    """Devuelve el secreto del entorno o None (nunca lo imprime)."""
    v = os.environ.get(name, "").strip()
    if not v:
        # también se aceptan ficheros de secretos fuera del repo (permisos 600)
        p = os.path.join(STATE_DIR, "secrets", name)
        if os.path.exists(p):
            v = open(p).read().strip()
    return v or None


def redact(text, *names):
    """Quita cualquier secreto conocido de un texto (para logs y errores)."""
    if not text:
        return text
    for n in names or ("HELIUS_API_KEY", "ETHERSCAN_API_KEY", "BLOCKSCOUT_API_KEY", "TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN_TIKTOK_RADAR", "WH_PIN"):
        v = secret(n)
        if v and len(v) > 4:
            text = str(text).replace(v, "***")
    return text
