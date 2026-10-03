"""Métricas por wallet a partir de sus swaps de los últimos N días. Reglas fijas."""
import statistics, time
from collections import defaultdict


def _median(xs):
    return statistics.median(xs) if xs else None


def wallet_metrics(swaps, prices, native_usd, now=None, window_days=30):
    """swaps: lista de dicts (token, ts, slot, side, token_amount, native_amount, dex).
    prices: {token: {"price_native":..., "launch_ts":..., "is_pumpfun":..., "liq":...}}"""
    now = now or int(time.time())
    since = now - window_days * 86400
    swaps = sorted([s for s in swaps if s["ts"] >= since], key=lambda s: (s["ts"], s.get("slot") or 0))
    pos = defaultdict(lambda: {"buys": [], "sells": []})
    for s in swaps:
        pos[s["token"]]["buys" if s["side"] == "buy" else "sells"].append(s)
    per_token = []
    holds, entries, buy_sizes = [], [], []
    for tok, p in pos.items():
        cost = sum(b["native_amount"] for b in p["buys"])
        if cost <= 0:
            continue  # solo ventas: compró antes de la ventana, no se puede medir
        proceeds = sum(x["native_amount"] for x in p["sells"])
        bought = sum(b["token_amount"] for b in p["buys"])
        sold = sum(x["token_amount"] for x in p["sells"])
        info = prices.get(tok) or {}
        px = info.get("price_native")
        remaining = max(bought - sold, 0.0)
        unreal = remaining * px if (px and remaining > bought * 0.01) else 0.0
        pnl = proceeds + unreal - cost
        first_buy = p["buys"][0]["ts"]
        hold = None
        if p["sells"] and sold >= bought * 0.9:
            hold = max(0, p["sells"][-1]["ts"] - first_buy)
            holds.append(hold)
        elif p["sells"]:
            holds.append(max(0, p["sells"][0]["ts"] - first_buy))
        lt = info.get("launch_ts")
        entry = None
        if lt and lt - 5 <= first_buy <= lt + 7 * 86400:
            # solo cuenta si compró en su primera semana (memecoins); tokens viejos no dicen nada de "entrada temprana"
            entry = max(0, first_buy - lt)
            entries.append(entry)
        buy_sizes += [b["native_amount"] for b in p["buys"]]
        avg_buy_px = cost / bought if bought else None
        pump_sell = 0.0
        if avg_buy_px:
            for x in p["sells"]:
                if x["token_amount"] and x["native_amount"] / x["token_amount"] >= 2 * avg_buy_px:
                    pump_sell += x["native_amount"]
        rugged = bool(px is not None and avg_buy_px and px < 0.1 * avg_buy_px) or (info.get("liq") is not None and info.get("liq") < 500 and info.get("price_native") is not None)
        per_token.append({"token": tok, "cost": cost, "proceeds": proceeds, "unreal": unreal, "pnl": pnl, "win": pnl > 0,
                          "hold": hold, "entry": entry, "first_buy": first_buy, "pump_sell_share": pump_sell / proceeds if proceeds else 0,
                          "rugged": rugged, "pumpfun": bool(info.get("is_pumpfun") or tok.endswith("pump")), "n_buys": len(p["buys"]), "n_sells": len(p["sells"])})
    n = len(per_token)
    wins = sum(1 for t in per_token if t["win"])
    pnl = sum(t["pnl"] for t in per_token)
    invested = sum(t["cost"] for t in per_token)
    pos_profit = sum(t["pnl"] for t in per_token if t["pnl"] > 0)
    top = max((t["pnl"] for t in per_token), default=0)
    hours = [time.gmtime(s["ts"]).tm_hour for s in swaps]
    conc = 0.0
    if hours:
        cnt = [0] * 24
        for h in hours:
            cnt[h] += 1
        conc = max(sum(cnt[(h + k) % 24] for k in range(6)) for h in range(24)) / len(hours)
    first_ts = swaps[0]["ts"] if swaps else now
    active_days = max(1.0, min(window_days, (now - first_ts) / 86400))
    dexes = [s.get("dex") or "" for s in swaps]
    return {
        "tokens": n, "wins": wins, "win_rate": wins / n if n else None, "trades": len(swaps),
        "pnl_native": pnl, "pnl_usd": pnl * native_usd, "invested_native": invested,
        "roi": pnl / invested if invested else None,
        "avg_hold_s": _median(holds), "avg_entry_s": _median(entries),
        "avg_size_native": sum(buy_sizes) / len(buy_sizes) if buy_sizes else None,
        "top_token_share": top / pos_profit if pos_profit > 0 else None,
        "hour_concentration": conc, "trades_per_day": len(swaps) / active_days,
        "pumpfun_share": sum(1 for t in per_token if t["pumpfun"]) / n if n else 0,
        "raydium_share": sum(1 for d in dexes if d.startswith("RAYDIUM")) / len(dexes) if dexes else 0,
        "pump_seller_share": (sum(1 for t in per_token if t["pump_sell_share"] >= 0.5) / max(1, sum(1 for t in per_token if t["proceeds"] > 0))) if per_token else 0,
        "rug_share": sum(1 for t in per_token if t["rugged"]) / n if n else 0,
        "median_hold_s": _median([t["hold"] for t in per_token if t["hold"] is not None]),
        "best_token": max(per_token, key=lambda t: t["pnl"])["token"] if per_token else None,
        "per_token": sorted(per_token, key=lambda t: -t["pnl"])[:40],
    }
