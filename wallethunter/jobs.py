"""Cola de trabajos (pestaña Trabajos): pending -> running -> done/error."""
import json, logging, time, uuid, base64
from . import db
from .config import cfg, secret
from .chains import CHAINS
from .net import request

log = logging.getLogger("wh")
MAX_ITEMS = 25


def enqueue(c, kind, chain, items, origin="cli", job_id=None):
    if kind not in ("tokens", "wallets", "connect"):
        raise ValueError("tipo inválido")
    if chain not in CHAINS and chain not in ("auto", "evm"):
        raise ValueError("chain inválida")
    items = [i for i in items if i][:MAX_ITEMS]
    if not items:
        raise ValueError("no hay direcciones válidas")
    jid = job_id or time.strftime("%y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4]
    c.execute("INSERT OR IGNORE INTO jobs(id,created,kind,chain,items,status,progress,origin) VALUES(?,?,?,?,?,?,?,?)",
              (jid, int(time.time()), kind, chain, json.dumps(items), "pending", "en cola", origin))
    c.commit()
    return jid


def set_progress(c, jid, msg):
    c.execute("UPDATE jobs SET progress=? WHERE id=?", (msg[:200], jid))
    c.commit()


def reset_stuck(c):
    """Tras un reinicio, lo que quedó 'running' vuelve a la cola."""
    n = c.execute("UPDATE jobs SET status='pending', progress='reanudado tras reinicio' WHERE status='running'").rowcount
    c.commit()
    return n


def next_pending(c, kinds=("tokens", "wallets")):
    """Los escaneos van en el bucle principal; las comprobaciones de conexiones ('connect') en su propio hilo."""
    q = ",".join("?" * len(kinds))
    r = c.execute(f"SELECT * FROM jobs WHERE status='pending' AND kind IN ({q}) ORDER BY created LIMIT 1", tuple(kinds)).fetchone()
    return dict(r) if r else None


def run_job(c, job, on_progress=None):
    from .scan import Scanner
    jid = job["id"]
    c.execute("UPDATE jobs SET status='running', started=?, message=NULL WHERE id=?", (int(time.time()), jid))
    c.commit()
    def prog(msg):
        set_progress(c, jid, msg)
        log.info("[%s] %s", jid, msg)
        if on_progress:
            on_progress()
    items = json.loads(job["items"])
    results, errors = [], []
    try:
        if job["kind"] == "connect":
            from . import connect
            try:
                results.append(connect.run_job(c, job, prog))
            except Exception as e:
                log.exception("conexiones %s", jid)
                connect.save(c, jid, job["chain"], items, "error", error=str(e)[:300])
                raise
            sc = None
        else:
            sc = Scanner(c, progress=prog)
        if job["kind"] == "connect":
            pass
        elif job["kind"] == "tokens":
            for i, ca in enumerate(items, 1):
                prog(f"token {i}/{len(items)}: {ca[:8]}…")
                try:
                    r = sc.scan_token(job["chain"], ca)
                    results.append(f"{r.get('symbol') or ca[:6]}: {r['wallets']} wallets")
                except Exception as e:
                    log.exception("token %s", ca)
                    errors.append(f"{ca[:8]}…: {str(e)[:120]}")
        else:
            # añadir una wallet a mano la saca de la lista de bloqueo
            for it in items:
                c.execute("DELETE FROM blocklist WHERE address=?", (it.strip(),))
            c.commit()
            r = sc.scan_wallets(job["chain"], items, force=True)
            results.append(f"{r['scanned']} wallets analizadas")
        status = "error" if errors and not results else "done"
        msg = "; ".join(results + errors)
    except Exception as e:
        log.exception("job %s", jid)
        status, msg = "error", str(e)[:300]
    from .config import redact
    c.execute("UPDATE jobs SET status=?, finished=?, message=?, progress=? WHERE id=?",
              (status, int(time.time()), redact(msg), "terminado" if status == "done" else "con errores", jid))
    c.commit()
    return status


def pull_github_queue(c):
    """Respaldo para cuando la web está en Vercel con /api/queue: lee queue.json de la rama 'queue'."""
    tok = secret("GITHUB_TOKEN_TIKTOK_RADAR")
    g = cfg()["github"]
    if not tok:
        return 0
    url = f"https://api.github.com/repos/{g['owner']}/{g['repo']}/contents/queue.json?ref={g['queue_branch']}"
    try:
        r = request(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}, retries=2)
    except Exception as e:
        if "404" not in str(e):
            log.debug("cola GitHub: %s", e)
        return 0
    try:
        q = json.loads(base64.b64decode(r.get("content") or "").decode() or "[]")
    except Exception:
        return 0
    seen = set(db.kv_get(c, "gh_queue_seen", []))
    n = 0
    for req in q if isinstance(q, list) else []:
        rid = str(req.get("id"))
        if not rid or rid in seen:
            continue
        seen.add(rid)
        try:
            from .scan import parse_items
            enqueue(c, req.get("kind", "tokens"), req.get("chain", "auto"), parse_items(" ".join(req.get("items") or [])), origin="web-vercel", job_id=rid[:40])
            n += 1
        except Exception as e:
            log.warning("petición de la cola inválida: %s", e)
    db.kv_set(c, "gh_queue_seen", list(seen)[-500:])
    return n
