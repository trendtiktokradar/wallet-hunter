"""Borrado desde la web (con PIN) o la CLI: wallets sueltas o un coin entero, con copia de seguridad automática.
- Wallets borradas: fuera de wallets/trades/transferencias/compradores/fondeadores, y de favoritos, alias y grupos.
- Coin borrado: se va el token con sus wallets, trades, bundles, clusters, vínculos y trabajos. Se conservan las wallets
  que también participaron en otros coins escaneados (o están en ⭐), pero solo con sus datos de esos otros coins.
- Lista de bloqueo opcional: las wallets borradas no se vuelven a añadir al re-escanear esos coins."""
import glob, json, os, sqlite3, time
from . import db
from .config import DB_PATH, ROOT

BACKUP_DIR = os.environ.get("WH_BACKUP_DIR") or os.path.join(ROOT, "data", "backups")
KEEP_BACKUPS = 10


def backup(c, reason="delete"):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    base = os.path.join(BACKUP_DIR, f"auto-{time.strftime('%Y%m%d-%H%M%S')}-{reason}")
    path, i = base + ".db", 1
    while os.path.exists(path):
        path, i = f"{base}-{i}.db", i + 1
    c.commit()
    dst = sqlite3.connect(path)
    c.backup(dst)
    dst.close()
    olds = sorted(glob.glob(os.path.join(BACKUP_DIR, "auto-*.db")))
    for p in olds[:-KEEP_BACKUPS]:
        try:
            os.remove(p)
        except OSError:
            pass
    return path


def _coins_of(c, chain, address):
    """Coins escaneados asociados a una wallet (compradores tempranos, origen o trades de tokens escaneados)."""
    s = {r[0] for r in c.execute("SELECT token FROM token_buyers WHERE chain=? AND wallet=?", (chain, address))}
    r = c.execute("SELECT origins FROM wallets WHERE chain=? AND address=?", (chain, address)).fetchone()
    if r and r[0]:
        s |= set(json.loads(r[0]))
    s |= {r[0] for r in c.execute("SELECT DISTINCT s.token FROM swaps s JOIN tokens t ON t.chain=s.chain AND t.address=s.token WHERE s.chain=? AND s.wallet=?", (chain, address))}
    return s


def is_blocked(c, chain, address, token):
    return c.execute("SELECT 1 FROM blocklist WHERE chain=? AND address=? AND token IN (?, '*')", (chain, address, token)).fetchone() is not None


def blocked_set(c, chain, token):
    return {r[0] for r in c.execute("SELECT address FROM blocklist WHERE chain=? AND token IN (?, '*')", (chain, token))}


def _purge_wallet(c, chain, a, block, rep):
    """Borra una wallet y todo lo suyo (incluidos favoritos, alias y presencia en grupos)."""
    if block:
        for t in (_coins_of(c, chain, a) or {"*"}):
            c.execute("INSERT OR IGNORE INTO blocklist(chain,address,token,added) VALUES(?,?,?,?)", (chain, a, t, int(time.time())))
        rep["blocked"] = rep.get("blocked", 0) + 1
    for tbl, col in (("swaps", "wallet"), ("transfers", "wallet"), ("token_buyers", "wallet"), ("alerts", "wallet"), ("funders", "address"),
                     ("favorites", "address"), ("aliases", "address"), ("wallets", "address")):
        n = c.execute(f"DELETE FROM {tbl} WHERE chain=? AND {col}=?", (chain, a)).rowcount
        rep[tbl] = rep.get(tbl, 0) + n
    for g in db.groups(c):
        if a in g["wallets"] and (not g["chain"] or g["chain"] == chain):
            ws = [x for x in g["wallets"] if x != a]
            if ws:
                c.execute("UPDATE groups SET wallets=?, updated=? WHERE id=?", (json.dumps(ws), int(time.time()), g["id"]))
            else:
                c.execute("DELETE FROM groups WHERE id=?", (g["id"],))
                rep["groups_deleted"] = rep.get("groups_deleted", 0) + 1
            rep["groups_touched"] = rep.get("groups_touched", 0) + 1


def _refresh_token_counts(c, chains):
    for r in c.execute("SELECT chain, address FROM tokens").fetchall():
        if r[0] in chains:
            n = c.execute("SELECT COUNT(*) FROM wallets WHERE chain=? AND origins LIKE ?", (r[0], f'%"{r[1]}"%')).fetchone()[0]
            c.execute("UPDATE tokens SET n_wallets=? WHERE chain=? AND address=?", (n, r[0], r[1]))


def _recompute(c, chains, recompute):
    if not recompute:
        return
    from .scan import Scanner
    sc = Scanner(c, progress=lambda m: None)
    for ch in chains:
        sc.recompute(ch)


def delete_wallets(c, items, block=False, recompute=True, do_backup=True):
    items = [(ch, a) for ch, a in dict.fromkeys((str(ch), str(a).strip()) for ch, a in items) if ch and a]
    found = [(ch, a) for ch, a in items if c.execute("SELECT 1 FROM wallets WHERE chain=? AND address=?", (ch, a)).fetchone()]
    rep = {"requested": len(items), "deleted_wallets": len(found)}
    if do_backup and found:
        rep["backup"] = backup(c, "wallets")
    for ch, a in found:
        _purge_wallet(c, ch, a, block, rep)
    chains = {ch for ch, _ in found}
    _refresh_token_counts(c, chains)
    c.commit()
    _recompute(c, chains, recompute)
    return rep


def plan_token(c, chain, token):
    """Qué pasaría al borrar el coin: wallets que se van y las que se quedan (con otros coins o en ⭐)."""
    others = {(r[0], r[1]) for r in c.execute("SELECT chain, address FROM tokens") if not (r[0] == chain and r[1] == token)}
    cand = {r[0] for r in c.execute("SELECT wallet FROM token_buyers WHERE chain=? AND token=?", (chain, token))}
    cand |= {r[0] for r in c.execute("SELECT address FROM wallets WHERE chain=? AND origins LIKE ?", (chain, f'%"{token}"%'))}
    cand = {a for a in cand if c.execute("SELECT 1 FROM wallets WHERE chain=? AND address=?", (chain, a)).fetchone()}
    favs = {r[0] for r in c.execute("SELECT address FROM favorites WHERE chain=?", (chain,))}
    delete, keep, keep_fav = [], [], []
    for a in sorted(cand):
        other = {t for t in _coins_of(c, chain, a) if (chain, t) in others}
        if other:
            keep.append(a)
        elif a in favs:
            keep_fav.append(a)
        else:
            delete.append(a)
    jobs = []
    for j in c.execute("SELECT id, kind, items, status FROM jobs"):
        it = json.loads(j["items"] or "[]")
        if j["kind"] == "tokens" and it and all(i == token for i in it):
            jobs.append(dict(j))
    running = any(j["status"] == "running" for j in jobs)
    return {"delete": delete, "keep_other_coins": keep, "keep_favorites": keep_fav, "jobs": [j["id"] for j in jobs], "running": running,
            "exists": c.execute("SELECT 1 FROM tokens WHERE chain=? AND address=?", (chain, token)).fetchone() is not None}


def delete_token(c, chain, token, block=False, recompute=True, do_backup=True):
    p = plan_token(c, chain, token)
    if p["running"]:
        raise RuntimeError("Ese coin se está escaneando ahora mismo: espera a que termine.")
    rep = {"token": token, "chain": chain, "deleted_wallets": len(p["delete"]), "kept_wallets": len(p["keep_other_coins"]) + len(p["keep_favorites"]),
           "kept_favorites": len(p["keep_favorites"]), "jobs_deleted": len(p["jobs"])}
    if not p["exists"] and not p["delete"] and not p["jobs"]:
        rep["not_found"] = True
        return rep
    if do_backup:
        rep["backup"] = backup(c, "coin")
    for a in p["delete"]:
        _purge_wallet(c, chain, a, block, rep)
    # wallets que se quedan: solo con los datos de sus otros coins
    for a in p["keep_other_coins"] + p["keep_favorites"]:
        rep["kept_swaps_removed"] = rep.get("kept_swaps_removed", 0) + c.execute("DELETE FROM swaps WHERE chain=? AND wallet=? AND token=?", (chain, a, token)).rowcount
        c.execute("DELETE FROM transfers WHERE chain=? AND wallet=? AND asset=?", (chain, a, token))
        r = c.execute("SELECT origins FROM wallets WHERE chain=? AND address=?", (chain, a)).fetchone()
        o = [t for t in json.loads(r[0] or "[]") if t != token] if r else []
        c.execute("UPDATE wallets SET origins=? WHERE chain=? AND address=?", (json.dumps(o), chain, a))
    c.execute("DELETE FROM token_buyers WHERE chain=? AND token=?", (chain, token))
    c.execute("DELETE FROM bundles WHERE chain=? AND token=?", (chain, token))
    c.execute("DELETE FROM tokens WHERE chain=? AND address=?", (chain, token))
    for jid in p["jobs"]:
        c.execute("DELETE FROM jobs WHERE id=?", (jid,))
    # fondeadores consultados solo para wallets borradas y precios que ya nadie usa
    keep_f = {(r[0], r[1]) for r in c.execute("SELECT chain, funder FROM wallets WHERE funder IS NOT NULL")} | {(r[0], r[1]) for r in c.execute("SELECT chain, address FROM wallets")}
    for r in c.execute("SELECT chain, address FROM funders WHERE chain=?", (chain,)).fetchall():
        if (r[0], r[1]) not in keep_f:
            c.execute("DELETE FROM funders WHERE chain=? AND address=?", (r[0], r[1]))
    live = {r[0] for r in c.execute("SELECT DISTINCT token FROM swaps WHERE chain=?", (chain,))} | {r[0] for r in c.execute("SELECT address FROM tokens WHERE chain=?", (chain,))}
    for r in c.execute("SELECT DISTINCT token FROM token_prices WHERE chain=?", (chain,)).fetchall():
        if r[0] not in live:
            c.execute("DELETE FROM token_prices WHERE chain=? AND token=?", (chain, r[0]))
    _refresh_token_counts(c, {chain})
    c.commit()
    _recompute(c, {chain}, recompute)
    return rep
