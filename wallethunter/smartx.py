"""Smart money cruzado: wallets que fueron compradoras TEMPRANAS y además RENTABLES en 2+ coins escaneados.
Sin llamadas a APIs: usa token_buyers (ranking de compra temprana), swaps y precios ya guardados.
Se excluyen bots, snipers, miembros de bundle y wallets prefiltradas como bot."""
import json
from collections import defaultdict
from .metrics import wallet_metrics
from .config import cfg

EXCLUDE = ("bot", "sniper", "bundle")
DEFAULTS = {"early_rank": 50, "min_coins": 2, "min_pnl_native": 0.0, "limit": 300}


def conf():
    return dict(DEFAULTS, **(cfg().get("smartx") or {}))


def build(c):
    C = conf()
    out = []
    for (chain,) in c.execute("SELECT DISTINCT chain FROM tokens").fetchall():
        scanned = {r[0] for r in c.execute("SELECT address FROM tokens WHERE chain=?", (chain,))}
        if len(scanned) < C["min_coins"]:
            continue
        early = defaultdict(dict)   # wallet -> token -> rank
        for r in c.execute("SELECT wallet, token, rank FROM token_buyers WHERE chain=? AND kind='early' AND rank<=?", (chain, C["early_rank"])):
            if r[1] in scanned:
                early[r[0]][r[1]] = r[2]
        cands = [w for w, t in early.items() if len(t) >= C["min_coins"]]
        if not cands:
            continue
        info = {}
        for i in range(0, len(cands), 500):
            ch = cands[i:i + 500]
            for r in c.execute(f"SELECT address, status, tags, prefiltered, score FROM wallets WHERE chain=? AND address IN ({','.join('?' * len(ch))})", (chain, *ch)):
                info[r[0]] = r
        prices = {r["token"]: dict(r) for r in c.execute("SELECT * FROM token_prices WHERE chain=?", (chain,))}
        for r in c.execute("SELECT address, launch_ts FROM tokens WHERE chain=? AND launch_ts IS NOT NULL", (chain,)):
            prices.setdefault(r[0], {})["launch_ts"] = r[1]
        for w in cands:
            r = info.get(w)
            if not r or r["status"] in ("pending", "error") or r["prefiltered"]:
                continue     # sin analizar no se puede descartar que sea un bot
            tags = json.loads(r["tags"]) if r["tags"] else []
            if any(t in tags for t in EXCLUDE):
                continue
            toks = list(early[w])
            sw = [dict(x) for x in c.execute(f"SELECT token, ts, slot, side, token_amount, native_amount, dex FROM swaps WHERE chain=? AND wallet=? AND token IN ({','.join('?' * len(toks))})",
                                             (chain, w, *toks))]
            per = {t["token"]: t for t in wallet_metrics(sw, prices, 1.0, window_days=3650)["per_token"]}
            coins = []
            for t in toks:
                p = per.get(t)
                if not p or p["pnl"] <= C["min_pnl_native"]:
                    continue
                coins.append({"t": t, "r": early[w][t], "pn": round(p["pnl"], 3), "roi": round(p["pnl"] / p["cost"], 3) if p["cost"] else None,
                              "en": p["entry"], "fb": p["first_buy"], "in": round(p["cost"], 3), "out": round(p["proceeds"], 3), "un": round(p["unreal"], 3)})
            if len(coins) >= C["min_coins"]:
                coins.sort(key=lambda x: -x["pn"])
                out.append({"c": chain, "a": w, "n": len(coins), "ne": len(toks), "pn": round(sum(x["pn"] for x in coins), 3),
                            "inv": round(sum(x["in"] for x in coins), 3), "sc": r["score"], "coins": coins})
    out.sort(key=lambda x: (-x["n"], -x["pn"]))
    return out[:C["limit"]]
