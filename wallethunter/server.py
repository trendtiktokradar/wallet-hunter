"""API del box (la web la llama a través de un túnel de Cloudflare). Todo lo que escribe pide PIN.
  GET  /health
  POST /api/check     {pin}
  POST /api/scan      {pin, kind: tokens|wallets, chain, items}
  POST /api/favs      {pin, op: list|add|remove|alias, chain, address, alias}
  POST /api/aliases   {pin, op: list|set, chain, address, alias}   (alias vacío = borrar)
  POST /api/settings  {pin, alerts?}      -> devuelve ajustes actuales
  POST /api/alerts    {pin}               -> últimas alertas
"""
import json, logging, os, re, subprocess, threading, time, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import db, pin as pinmod, jobs
from .config import cfg, save_settings, ROOT
from .scan import parse_items

log = logging.getLogger("wh")
PORT = int(os.environ.get("WH_PORT", "18795"))
WAKE = threading.Event()


class H(BaseHTTPRequestHandler):
    server_version = "WalletHunter"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, {"ok": True, "pin_set": pinmod.is_set(), "t": int(time.time())})
        if self.path.split("?")[0] == "/data.json":
            from .config import DATA_JSON
            try:
                body = open(DATA_JSON, "rb").read()
            except OSError:
                return self._send(404, {"error": "sin datos"})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send(404, {"error": "no encontrado"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 20000:
                return self._send(413, {"error": "demasiado grande"})
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "JSON inválido"})
        if not pinmod.is_set():
            return self._send(403, {"error": "pin_not_set", "msg": "Falta configurar el PIN en el box"})
        ok = pinmod.check(req.get("pin"))
        if ok is None:
            return self._send(429, {"error": "bloqueado", "msg": "Demasiados PIN incorrectos. Espera 1 hora."})
        if not ok:
            return self._send(401, {"error": "pin", "msg": "PIN incorrecto"})
        c = db.connect()
        p = self.path.split("?")[0]
        try:
            if p == "/api/check":
                return self._send(200, {"ok": True})
            if p == "/api/scan":
                items = req.get("items")
                items = parse_items(items if isinstance(items, str) else " ".join(items or []))
                jid = jobs.enqueue(c, req.get("kind", "tokens"), req.get("chain", "auto"), items, origin="web")
                WAKE.set()
                return self._send(200, {"ok": True, "id": jid, "items": items})
            if p == "/api/favs":
                op = req.get("op", "list")
                ch, a = req.get("chain"), (req.get("address") or "").strip()
                if op in ("add", "alias") and ch and a:
                    c.execute("INSERT INTO favorites(chain,address,alias,added) VALUES(?,?,?,?) ON CONFLICT(chain,address) DO UPDATE SET alias=COALESCE(excluded.alias, alias)",
                              (ch, a, (req.get("alias") or None) and str(req.get("alias"))[:40], int(time.time())))
                    if req.get("alias"):
                        db.set_alias(c, ch, a, req.get("alias"))
                elif op == "remove" and ch and a:
                    c.execute("DELETE FROM favorites WHERE chain=? AND address=?", (ch, a))
                c.commit()
                favs = [dict(r) for r in c.execute("SELECT chain, address, alias, added FROM favorites ORDER BY added DESC")]
                return self._send(200, {"ok": True, "favs": favs})
            if p == "/api/aliases":
                if req.get("op") == "set":
                    ch, a = req.get("chain"), (req.get("address") or "").strip()
                    if not ch or not a or len(a) > 64:
                        raise ValueError("faltan chain/address")
                    db.set_alias(c, ch, a, req.get("alias"))
                return self._send(200, {"ok": True, "aliases": db.aliases(c)})
            if p == "/api/settings":
                if isinstance(req.get("alerts"), dict):
                    a = req["alerts"]
                    clean = {}
                    if "enabled" in a: clean["enabled"] = bool(a["enabled"])
                    if "min_inflow_usd" in a: clean["min_inflow_usd"] = max(0.0, float(a["min_inflow_usd"]))
                    if "only_from_funder_or_cex" in a: clean["only_from_funder_or_cex"] = bool(a["only_from_funder_or_cex"])
                    if "poll_minutes" in a: clean["poll_minutes"] = max(2, min(120, int(a["poll_minutes"])))
                    if a.get("watch") in ("favorites", "favorites+smart"): clean["watch"] = a["watch"]
                    if isinstance(a.get("min_inflow_native"), dict):
                        clean["min_inflow_native"] = {k: max(0.0, float(v)) for k, v in a["min_inflow_native"].items() if isinstance(v, (int, float))}
                    save_settings(clean)
                from .config import secret
                return self._send(200, {"ok": True, "alerts": cfg()["alerts"], "telegram": bool(secret("TELEGRAM_BOT_TOKEN") and secret("TELEGRAM_CHAT_ID"))})
            if p == "/api/alerts":
                rows = [dict(r) for r in c.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 100")]
                return self._send(200, {"ok": True, "alerts": rows})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            log.exception("api")
            return self._send(500, {"error": "error interno"})
        self._send(404, {"error": "no encontrado"})


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log.info("API del box en http://127.0.0.1:%s", PORT)
    return srv


class Tunnel:
    """Quick tunnel de Cloudflare (gratis, sin cuenta). La URL cambia en cada arranque: se publica en data.json/box.json."""
    def __init__(self):
        self.proc, self.url, self.fails = None, None, 0
        self.bin = os.path.expanduser("~/.local/bin/cloudflared")
        self.logf = os.path.join(ROOT, "logs", "cloudflared.log")

    def start(self):
        if not os.path.exists(self.bin):
            log.warning("cloudflared no instalado: la web no podrá lanzar escaneos")
            return None
        self.stop()
        os.makedirs(os.path.dirname(self.logf), exist_ok=True)
        lf = open(self.logf, "w")
        self.proc = subprocess.Popen([self.bin, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"], stdout=lf, stderr=subprocess.STDOUT)
        for _ in range(60):
            time.sleep(1)
            try:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", open(self.logf).read())
            except Exception:
                m = None
            if m:
                self.url = m.group(0)
                log.info("túnel activo: %s", self.url)
                self.fails = 0
                return self.url
        log.warning("el túnel no dio URL")
        return None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except Exception:
                self.proc.kill()
        self.proc, self.url = None, None

    def healthy(self):
        if not self.proc or self.proc.poll() is not None or not self.url:
            return False
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=15) as r:
                ok = r.status == 200
        except Exception:
            ok = False
        self.fails = 0 if ok else self.fails + 1
        return self.fails < 3

    def ensure(self):
        if not self.healthy():
            return self.start()
        return self.url
