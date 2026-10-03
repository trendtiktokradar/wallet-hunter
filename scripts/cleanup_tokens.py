"""Borra tokens escaneados y todo lo que existe SOLO por ellos (wallets, trades, bundles, clusters, vínculos, trabajos).
Conserva tokens/trabajos de otros escaneos, y las wallets que aparecen en ellos o en favoritos/alias/grupos.
Uso: python3 scripts/cleanup_tokens.py chain:CA [chain:CA ...]   (hacer copia de la BD antes; parar el servicio)"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wallethunter import db

def main(specs):
    c = db.connect()
    targets = [tuple(s.split(":", 1)) for s in specs]
    tset = set(targets)
    rep = {"deleted": {}, "kept": {}}
    # tokens y trabajos que se conservan
    keep_tokens = [(r["chain"], r["address"]) for r in c.execute("SELECT chain, address FROM tokens") if (r["chain"], r["address"]) not in tset]
    jobs = [dict(r) for r in c.execute("SELECT id, kind, chain, items, status, origin, created FROM jobs")]
    del_jobs, keep_jobs = [], []
    for j in jobs:
        items = json.loads(j["items"] or "[]")
        if j["kind"] == "tokens" and items and all(any(i == a for _, a in targets) for i in items):
            del_jobs.append(j)
        else:
            keep_jobs.append(j)
    # wallets a conservar
    keep_w = set()
    for ch, t in keep_tokens:
        keep_w |= {(r[0], r[1]) for r in c.execute("SELECT chain, wallet FROM token_buyers WHERE chain=? AND token=?", (ch, t))}
    for j in keep_jobs:
        if j["kind"] == "wallets":
            keep_w |= {(j["chain"], i) for i in json.loads(j["items"] or "[]")}
    for tbl in ("favorites", "aliases"):
        keep_w |= {(r[0], r[1]) for r in c.execute(f"SELECT chain, address FROM {tbl}")}
    for g in db.groups(c):
        keep_w |= {(g["chain"], a) for a in g["wallets"]} if g["chain"] else {(r[0], r[1]) for a in g["wallets"] for r in c.execute("SELECT chain, address FROM wallets WHERE address=?", (a,))}
    all_w = {(r[0], r[1]) for r in c.execute("SELECT chain, address FROM wallets")}
    del_w = all_w - keep_w
    # referencias privadas que apuntan solo a wallets borradas (no se tocan; se informa)
    dangling = {tbl: [r[0] + ":" + r[1] for r in c.execute(f"SELECT chain, address FROM {tbl}") if (r[0], r[1]) in del_w] for tbl in ("favorites", "aliases")}
    def count(sql, args=()):
        return c.execute(sql, args).fetchone()[0]
    n = lambda k, v: rep["deleted"].__setitem__(k, rep["deleted"].get(k, 0) + v)
    for ch, a in del_w:
        n("swaps", c.execute("DELETE FROM swaps WHERE chain=? AND wallet=?", (ch, a)).rowcount)
        n("transfers", c.execute("DELETE FROM transfers WHERE chain=? AND wallet=?", (ch, a)).rowcount)
        n("wallets", c.execute("DELETE FROM wallets WHERE chain=? AND address=?", (ch, a)).rowcount)
        n("alerts", c.execute("DELETE FROM alerts WHERE chain=? AND wallet=?", (ch, a)).rowcount)
    for ch, t in targets:
        n("token_buyers", c.execute("DELETE FROM token_buyers WHERE chain=? AND token=?", (ch, t)).rowcount)
        n("bundles", c.execute("DELETE FROM bundles WHERE chain=? AND token=?", (ch, t)).rowcount)
        n("tokens", c.execute("DELETE FROM tokens WHERE chain=? AND address=?", (ch, t)).rowcount)
    # wallets conservadas: quitar los tokens borrados de su origen
    for r in c.execute("SELECT chain, address, origins FROM wallets").fetchall():
        o = json.loads(r["origins"] or "[]")
        o2 = [t for t in o if (r["chain"], t) not in tset]
        if o2 != o:
            c.execute("UPDATE wallets SET origins=? WHERE chain=? AND address=?", (json.dumps(o2), r["chain"], r["address"]))
    # fondeadores consultados solo para wallets borradas
    keep_f = {(r[0], r[1]) for r in c.execute("SELECT chain, funder FROM wallets WHERE funder IS NOT NULL")} | {(r[0], r[1]) for r in c.execute("SELECT chain, address FROM wallets")}
    for r in c.execute("SELECT chain, address FROM funders").fetchall():
        if (r[0], r[1]) not in keep_f:
            n("funders", c.execute("DELETE FROM funders WHERE chain=? AND address=?", (r[0], r[1])).rowcount)
    # precios de tokens que ya no tradea ninguna wallet
    live = {(r[0], r[1]) for r in c.execute("SELECT DISTINCT chain, token FROM swaps")} | {(r[0], r[1]) for r in c.execute("SELECT chain, address FROM tokens")}
    for r in c.execute("SELECT DISTINCT chain, token FROM token_prices").fetchall():
        if (r[0], r[1]) not in live:
            n("token_prices", c.execute("DELETE FROM token_prices WHERE chain=? AND token=?", (r[0], r[1])).rowcount)
    for j in del_jobs:
        n("jobs", c.execute("DELETE FROM jobs WHERE id=?", (j["id"],)).rowcount)
    n("graphs (clusters/vínculos)", c.execute("DELETE FROM kv WHERE key LIKE 'graph:%'").rowcount)
    c.commit()
    c.execute("VACUUM")
    rep["deleted_jobs"] = [f'{j["id"]} {j["kind"]} {j["chain"]} {j["origin"]} {j["status"]} {json.loads(j["items"])}' for j in del_jobs]
    rep["kept_jobs"] = [f'{j["id"]} {j["kind"]} {j["chain"]} {j["origin"]} {j["status"]} {json.loads(j["items"])}' for j in keep_jobs]
    rep["kept_tokens"] = [f"{ch}:{t}" for ch, t in keep_tokens]
    rep["kept_wallets"] = len(keep_w & all_w)
    rep["dangling_private_refs"] = dangling
    print(json.dumps(rep, indent=1, ensure_ascii=False))

if __name__ == "__main__":
    main(sys.argv[1:])
