"""API del box (la web la llama a través de un túnel de Cloudflare). Todo lo que escribe pide PIN.
  GET  /health
  POST /api/check     {pin}
  POST /api/scan      {pin, kind: tokens|wallets, chain, items}
  POST /api/favs      {pin, op: list|add|remove|alias, chain, address, alias, scan?}  -> favs con last_trade y fondeadores (privado)
  POST /api/aliases   {pin, op: list|set, chain, address, alias}   (alias vacío = borrar)
  POST /api/groups    {pin, op: list|save|delete, group: {id?, name, emoji, chain, wallets[], source}, id}
  POST /api/delete    {pin, op: wallets|token|plan_token, items:[{chain,address}], chain, token, block}
  POST /api/connect   {pin, wallets, chain}                  -> {id}  (comprobación de conexiones: trabajo 'connect')
  POST /api/checks    {pin, op: list|get|status|delete, id}  (comprobaciones guardadas, privadas)
  POST /api/settings  {pin, alerts?}      -> ajustes actuales + estado de Telegram + coste estimado de la vigilancia + fondeadores
  POST /api/telegram  {pin, op: status|detect|test}   (detecta tu chat con getUpdates; «test» manda un mensaje corto)
  POST /api/alerts    {pin}               -> últimas alertas (kind: inflow | dormant | funder, data con los detalles)
"""
import json, logging, os, re, subprocess, threading, time, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from . import db, pin as pinmod, jobs
from .config import cfg, save_settings, ROOT
from .scan import parse_items
from .chains import CHAINS as CHAINS_ALL

log = logging.getLogger("wh")
PORT = int(os.environ.get("WH_PORT", "18795"))
WAKE = threading.Event()
DELETE_LOCK = threading.Lock()
CONNECT_WAKE = threading.Event()


def start_connect_worker():
    """Hilo propio para las comprobaciones de conexiones: no esperan a que acabe un escaneo largo."""
    def work():
        c = db.connect()
        while True:
            try:
                job = jobs.next_pending(c, kinds=("connect",))
                while job:
                    WAKE.set()
                    jobs.run_job(c, job)
                    WAKE.set()   # el bucle republica data.json (Trabajos)
                    job = jobs.next_pending(c, kinds=("connect",))
            except Exception:
                log.exception("hilo de conexiones")
            CONNECT_WAKE.wait(30)
            CONNECT_WAKE.clear()
    t = threading.Thread(target=work, daemon=True, name="connect")
    t.start()
    return t


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
            if n > 200000:
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
                    if req.get("scan") and ch in CHAINS_ALL and not c.execute("SELECT 1 FROM wallets WHERE chain=? AND address=?", (ch, a)).fetchone():
                        jobs.enqueue(c, "wallets", ch, [a], origin="web"); WAKE.set()   # (p. ej. desde una alerta de fondeador: que salga en la tabla)
                elif op == "remove" and ch and a:
                    c.execute("DELETE FROM favorites WHERE chain=? AND address=?", (ch, a))
                c.commit()
                from . import watcher
                favs = [dict(r) for r in c.execute("SELECT chain, address, alias, added FROM favorites ORDER BY added DESC")]
                fun = {}
                for r in c.execute("SELECT chain, wallet, funder, label FROM fav_funders"):
                    fun.setdefault((r[0], r[1]), []).append({"address": r[2], "label": r[3]})
                for f in favs:   # último trade (dormidas) y fondeadores: privados, solo con PIN
                    f["last_trade"] = watcher.last_trade(c, f["chain"], f["address"])
                    f["watched"] = db.kv_get(c, f"watch:{f['chain']}:{f['address']}") is not None
                    f["funders"] = fun.get((f["chain"], f["address"]), [])
                return self._send(200, {"ok": True, "favs": favs, "dormant_days": watcher.settings()["dormant_days"]})
            if p == "/api/aliases":
                if req.get("op") == "set":
                    ch, a = req.get("chain"), (req.get("address") or "").strip()
                    if not ch or not a or len(a) > 64:
                        raise ValueError("faltan chain/address")
                    db.set_alias(c, ch, a, req.get("alias"))
                return self._send(200, {"ok": True, "aliases": db.aliases(c)})
            if p == "/api/groups":
                op = req.get("op", "list")
                gid = None
                if op == "save":
                    gid = db.save_group(c, req.get("group") or {})
                elif op == "delete":
                    db.delete_group(c, req.get("id"))
                return self._send(200, {"ok": True, "id": gid, "groups": db.groups(c)})
            if p == "/api/delete":
                from . import delete, export
                op, block = req.get("op"), bool(req.get("block"))
                with DELETE_LOCK:
                    if op == "wallets":
                        items = [(str(i.get("chain") or ""), str(i.get("address") or "")) for i in (req.get("items") or []) if isinstance(i, dict)][:2000]
                        if not items:
                            raise ValueError("no hay wallets")
                        r = delete.delete_wallets(c, items, block=block)
                    elif op in ("token", "plan_token"):
                        ch, t = str(req.get("chain") or ""), str(req.get("token") or "").strip()
                        if not ch or not t:
                            raise ValueError("faltan chain/token")
                        if op == "plan_token":
                            pl = delete.plan_token(c, ch, t)
                            return self._send(200, {"ok": True, "delete": len(pl["delete"]), "keep_other_coins": len(pl["keep_other_coins"]),
                                                    "keep_favorites": len(pl["keep_favorites"]), "jobs": len(pl["jobs"]), "running": pl["running"]})
                        try:
                            r = delete.delete_token(c, ch, t, block=block)
                        except RuntimeError as e:
                            return self._send(409, {"error": "busy", "msg": str(e)})
                    else:
                        raise ValueError("op no válida")
                    export.write(c)
                r["backup"] = os.path.basename(r["backup"]) if r.get("backup") else None
                log.info("borrado desde la web: %s", {k: v for k, v in r.items() if k != "backup"})
                WAKE.set()   # el bucle detecta el cambio y republica data.json
                return self._send(200, {"ok": True, "result": r})
            if p == "/api/connect":
                from . import connect
                chain, ws = connect.clean_wallets(req.get("wallets") or req.get("items") or "", req.get("chain") or "auto")
                jid = jobs.enqueue(c, "connect", chain, ws, origin="web")
                connect.save(c, jid, chain, ws, "pending")
                CONNECT_WAKE.set(); WAKE.set()
                return self._send(200, {"ok": True, "id": jid, "chain": chain, "wallets": ws})
            if p == "/api/checks":
                from . import connect
                op, cid = req.get("op", "list"), str(req.get("id") or "")[:40]
                if op == "list":
                    return self._send(200, {"ok": True, "checks": connect.list_checks(c)})
                if op in ("get", "status"):
                    j = c.execute("SELECT status, progress, message, chain, items FROM jobs WHERE id=? AND kind='connect'", (cid,)).fetchone()
                    if not j:
                        return self._send(404, {"error": "no encontrada"})
                    out = {"ok": True, "id": cid, "status": j["status"], "progress": j["progress"], "message": j["message"], "chain": j["chain"], "wallets": json.loads(j["items"] or "[]")}
                    if j["status"] == "done":
                        out["result"] = connect.get_check(c, cid)
                    return self._send(200, out)
                if op == "delete":
                    connect.delete_check(c, cid)
                    WAKE.set()
                    return self._send(200, {"ok": True, "checks": connect.list_checks(c)})
                raise ValueError("op no válida")
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
                    if "dormant_alert" in a: clean["dormant_alert"] = bool(a["dormant_alert"])
                    if "dormant_days" in a: clean["dormant_days"] = max(1, min(365, int(a["dormant_days"])))
                    if "funder_watch" in a: clean["funder_watch"] = bool(a["funder_watch"])
                    if "funder_poll_minutes" in a: clean["funder_poll_minutes"] = max(10, min(240, int(a["funder_poll_minutes"])))
                    if "funder_new_max_txs" in a: clean["funder_new_max_txs"] = max(1, min(50, int(a["funder_new_max_txs"])))
                    if isinstance(a.get("funder_min_native"), dict):
                        clean["funder_min_native"] = {k: max(0.0, float(v)) for k, v in a["funder_min_native"].items() if isinstance(v, (int, float)) and k in CHAINS_ALL}
                    save_settings(clean)
                    from . import watcher as _w
                    _w.WAKE.set()
                from . import watcher, telegram
                return self._send(200, {"ok": True, "alerts": watcher.settings(), "telegram": telegram.status(), "estimate": watcher.estimate(c),
                                        "funders": watcher.funder_list(c)})
            if p == "/api/telegram":
                from . import telegram
                op = req.get("op", "status")
                if op == "detect":
                    ch = telegram.detect_chat()
                    return self._send(200, {"ok": True, "found": bool(ch), "telegram": telegram.status()})
                if op == "test":
                    st = telegram.status()
                    if not st["token"]:
                        return self._send(400, {"error": "Falta el token del bot (TELEGRAM_BOT_TOKEN) en el box"})
                    if not st["chat"] and not telegram.detect_chat():
                        return self._send(400, {"error": "Aún no sé tu chat: abre el bot en Telegram, pulsa Start o escríbele algo y vuelve a probar"})
                    ok = telegram.send("✅ Prueba de Wallet Hunter: las alertas llegarán a este chat.")
                    return self._send(200 if ok else 502, {"ok": ok, "telegram": telegram.status()} if ok else {"error": "Telegram no aceptó el mensaje"})
                return self._send(200, {"ok": True, "telegram": telegram.status()})
            if p == "/api/alerts":
                rows = [dict(r) for r in c.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 100")]
                for r in rows:   # kind: inflow | dormant | funder ; data: detalles en JSON
                    try: r["data"] = json.loads(r["data"]) if r.get("data") else None
                    except ValueError: r["data"] = None
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
