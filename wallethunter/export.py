"""BD -> web/data.json (lo que lee el panel). No incluye favoritos ni ajustes privados (esos los sirve el box con PIN)."""
import json, os, time
from .config import DATA_JSON, cfg
from .chains import CHAINS
from . import db, market, smartx
from .net import STATUS
from .tags import tag_defs


def build(c=None):
    c = c or db.connect()
    now = int(time.time())
    wallets = []
    # último fondeo nativo entrante relevante (para el filtro "Fondeada hace < X h")
    lastfund = {}
    mins = cfg().get("recent_funding_min_native", {})
    for r in c.execute("SELECT chain, wallet, amount_native, ts FROM transfers WHERE direction='in' AND asset='native' AND amount_native IS NOT NULL"):
        if r["amount_native"] >= mins.get(r["chain"], mins.get("default", 0.01)):
            k = (r["chain"], r["wallet"])
            if r["ts"] and r["ts"] > lastfund.get(k, 0):
                lastfund[k] = r["ts"]
    # coins escaneados en los que participó cada wallet (comprador temprano o con trades del token en la base)
    coins = {}
    for r in c.execute("SELECT chain, wallet, token FROM token_buyers"):
        coins.setdefault((r[0], r[1]), set()).add(r[2])
    for r in c.execute("SELECT DISTINCT s.chain, s.wallet, s.token FROM swaps s JOIN tokens t ON t.chain=s.chain AND t.address=s.token"):
        coins.setdefault((r[0], r[1]), set()).add(r[2])
    lasttrade = {(r[0], r[1]): r[2] for r in c.execute("SELECT chain, wallet, MAX(ts) FROM swaps GROUP BY chain, wallet")}
    for r in c.execute("SELECT * FROM wallets ORDER BY score DESC NULLS LAST"):
        m = json.loads(r["metrics"]) if r["metrics"] else {}
        wallets.append({
            "c": r["chain"], "a": r["address"], "st": r["status"], "sc": r["score"],
            "pn": _r(m.get("pnl_native"), 3), "pu": _r(m.get("pnl_usd"), 0), "roi": _r(m.get("roi"), 3),
            "wr": _r(m.get("win_rate"), 3), "tr": m.get("trades"), "tk": m.get("tokens"), "w": m.get("wins"),
            "ho": m.get("avg_hold_s"), "en": m.get("avg_entry_s"), "sz": _r(m.get("avg_size_native"), 3),
            "bal": _r(r["balance_native"], 3), "ft": r["first_tx_ts"], "at": r["age_truncated"], "la": r["last_activity"],
            "cl": r["cluster_id"], "bu": m.get("bundles") or [], "tg": json.loads(r["tags"]) if r["tags"] else [],
            "fu": r["funder"], "fl": r["funder_label"], "or": json.loads(r["origins"]) if r["origins"] else [],
            "cp": m.get("copy_of"), "lk": m.get("links") or [], "er": m.get("early_rank_min"), "pf": r["prefiltered"],
            "ht": r["history_truncated"], "ls": r["last_scanned"],
            "ct": sorted(coins.get((r["chain"], r["address"]), set()) | set(json.loads(r["origins"]) if r["origins"] else [])), "fa": r["funded_at"], "lf": lastfund.get((r["chain"], r["address"])), "lx": lasttrade.get((r["chain"], r["address"])),
        })
    tokens = []
    for r in c.execute("SELECT * FROM tokens ORDER BY scanned_at DESC"):
        nb = c.execute("SELECT COUNT(*) FROM token_buyers WHERE chain=? AND token=?", (r["chain"], r["address"])).fetchone()[0]
        nbund = c.execute("SELECT COUNT(*) FROM bundles WHERE chain=? AND token=?", (r["chain"], r["address"])).fetchone()[0]
        tokens.append({"c": r["chain"], "a": r["address"], "sy": r["symbol"], "nm": r["name"], "lt": r["launch_ts"], "cr": r["creator"],
                       "pu": r["price_usd"], "mc": r["mc"], "liq": r["liq"], "sa": r["scanned_at"], "nw": r["n_wallets"], "nb": nb,
                       "bd": nbund, "st": r["status"]})
    bundles = []
    for i, r in enumerate(c.execute("SELECT * FROM bundles ORDER BY ts DESC"), 1):
        bundles.append({"id": r["id"], "c": r["chain"], "t": r["token"], "s": r["slot"], "ts": r["ts"], "w": json.loads(r["wallets"]), "n": _r(r["native_total"], 3)})
    clusters, links = [], 0
    for ch in CHAINS:
        g = db.kv_get(c, f"graph:{ch}")
        if g:
            for cl in g["clusters"]:
                clusters.append({"id": cl["id"], "c": ch, "w": cl["wallets"], "n": cl["size"]})
            links += g.get("links", 0)
    # cruce de coins: wallets que entraron temprano (top 50) en 2+ tokens escaneados
    cross = []
    for r in c.execute("""SELECT chain, wallet, COUNT(*) n, GROUP_CONCAT(token) toks, AVG(rank) ar FROM token_buyers
                          WHERE kind='early' AND rank<=50 GROUP BY chain, wallet HAVING n>=2 ORDER BY n DESC, ar ASC LIMIT 500"""):
        cross.append({"c": r["chain"], "a": r["wallet"], "n": r["n"], "t": r["toks"].split(","), "ar": _r(r["ar"], 1)})
    try:
        sx = smartx.build(c)
    except Exception:
        import logging; logging.getLogger("wh").exception("smart money cruzado"); sx = []
    jobs = [dict(r) for r in c.execute("SELECT id, created, kind, chain, items, status, progress, message, started, finished, origin FROM jobs ORDER BY created DESC LIMIT 60")]
    for j in jobs:
        j["items"] = json.loads(j["items"] or "[]")
        if j["kind"] == "connect":   # privado: en el json público solo la forma corta; el resultado lo sirve el box con PIN
            j["items"] = [a[:4] + "…" + a[-4:] for a in j["items"]]
            j["message"] = (j["message"] or "").split(":")[0] if j["status"] == "done" else j["message"]
    st = {"total": len(wallets), "pending": sum(1 for w in wallets if w["st"] == "pending"), "error": sum(1 for w in wallets if w["st"] == "error"),
          "bots_pre": sum(1 for w in wallets if w["pf"]), "fund_sync": sum(1 for w in wallets if "fondeo_sync" in w["tg"]), "smart": sum(1 for w in wallets if "smart" in w["tg"]),
          "bots": sum(1 for w in wallets if "bot" in w["tg"]), "snipers": sum(1 for w in wallets if "sniper" in w["tg"]),
          "in_bundle": sum(1 for w in wallets if w["bu"]), "bundles": len(bundles), "clusters": len(clusters), "links": links,
          "tokens": len(tokens), "tokens_window": sum(1 for t in tokens if t["sa"] and now - t["sa"] < cfg()["window_days"] * 86400)}
    prices = {}
    for ch in CHAINS:
        hit = market._kraken_cache.get(CHAINS[ch]["kraken"])
        if hit:
            prices[ch] = hit[0]
    srcs = {k: {kk: v.get(kk) for kk in ("ok", "last", "last_ok", "error", "credits_month", "calls_day", "gtfa", "configured")} for k, v in STATUS.data.items()}
    box = db.kv_get(c, "box", {})
    return {"generated": now, "version": 1, "window_days": cfg()["window_days"], "stats": st, "wallets": wallets, "tokens": tokens,
            "bundles": bundles, "clusters": clusters, "cross": cross, "smartx": sx, "smartx_cfg": {k: smartx.conf()[k] for k in ("early_rank", "min_coins")}, "jobs": jobs, "sources": srcs, "prices": prices,
            "tags": tag_defs(), "chains": {k: {"name": v["name"], "native": v["native"], "explorer": v["explorer"], "exn": v.get("explorer_name"), "gmgn": v.get("gmgn"), "tx": v["tx"]} for k, v in CHAINS.items()},
            "box": {"url": box.get("url"), "updated": box.get("updated"), "pin_set": box.get("pin_set", False)},
            "keys": key_status()}


def key_status():
    from .config import secret
    return {"helius": bool(secret("HELIUS_API_KEY")), "etherscan": bool(secret("ETHERSCAN_API_KEY")), "blockscout": bool(secret("BLOCKSCOUT_API_KEY")),
            "telegram": bool(secret("TELEGRAM_BOT_TOKEN"))}


def _r(x, n):
    return None if x is None else round(x, n)


def write(c=None, path=None):
    d = build(c)
    path = path or DATA_JSON
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)
    return d
