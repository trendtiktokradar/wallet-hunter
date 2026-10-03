"""Precios y datos de mercado: Kraken (nativo/USD), DexScreener y GeckoTerminal (pools, lanzamiento, precio)."""
import time, logging
from .net import request, RateLimiter, STATUS
from .chains import CHAINS
from .config import cfg

log = logging.getLogger("wh")
_kraken_cache = {}
_ds_lim = RateLimiter(cfg()["dexscreener"]["rpm"] / 60.0)
_gt_lim = RateLimiter(cfg()["geckoterminal"]["rpm"] / 60.0)
_kr_lim = RateLimiter(1)


def native_usd(chain):
    """Precio USD del token nativo de la chain (Kraken, caché 2 min)."""
    pair = CHAINS[chain]["kraken"]
    hit = _kraken_cache.get(pair)
    if hit and time.time() - hit[1] < 120:
        return hit[0]
    try:
        d = request(f"https://api.kraken.com/0/public/Ticker?pair={pair}", limiter=_kr_lim, source="kraken")
        res = d.get("result") or {}
        v = next(iter(res.values()))
        px = float(v["c"][0])
        _kraken_cache[pair] = (px, time.time())
        return px
    except Exception as e:
        log.warning("Kraken falló (%s): %s", pair, e)
        if hit:
            return hit[0]
        fallback = {"SOLUSD": 150.0, "ETHUSD": 3000.0, "BNBUSD": 700.0, "POLUSD": 0.2}
        return fallback.get(pair, 1.0)


def _norm(chain, a):
    return a.lower() if (a or "")[:2].lower() == "0x" else a


def dexscreener_tokens(chain, addresses):
    """Devuelve {token: {price_usd, liq, launch_ts, symbol, name, pools, is_pumpfun, mc}} (lotes de 30)."""
    out = {}
    dsc = CHAINS[chain]["dexscreener"]
    addrs = list(dict.fromkeys(addresses))
    for i in range(0, len(addrs), 30):
        chunk = addrs[i:i + 30]
        try:
            pairs = request(f"https://api.dexscreener.com/tokens/v1/{dsc}/{','.join(chunk)}", limiter=_ds_lim, source="dexscreener")
        except Exception as e:
            log.warning("DexScreener falló: %s", e)
            out.setdefault("_failed", set()).update(_norm(chain, c) for c in chunk)
            continue
        for p in pairs or []:
            base = p.get("baseToken") or {}
            quote = p.get("quoteToken") or {}
            for side, other in ((base, quote), (quote, base)):
                t = side.get("address")
                if not t:
                    continue
                key = _norm(chain, t)
                if key not in {_norm(chain, c) for c in chunk}:
                    continue
                d = out.setdefault(key, {"pools": [], "liq": 0.0, "launch_ts": None, "price_usd": None, "symbol": side.get("symbol"), "name": side.get("name"), "is_pumpfun": 0, "mc": None})
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                d["pools"].append({"address": p.get("pairAddress"), "dex": p.get("dexId"), "liq": liq, "quote": other.get("symbol"), "created": (p.get("pairCreatedAt") or 0) // 1000 or None})
                if p.get("dexId") in ("pumpfun", "pumpswap") or t.endswith("pump"):
                    d["is_pumpfun"] = 1
                created = (p.get("pairCreatedAt") or 0) // 1000
                if created and (d["launch_ts"] is None or created < d["launch_ts"]):
                    d["launch_ts"] = created
                if side is base and liq >= d["liq"]:
                    d["liq"] = liq
                    try:
                        d["price_usd"] = float(p.get("priceUsd")) if p.get("priceUsd") else d["price_usd"]
                    except ValueError:
                        pass
                    d["mc"] = p.get("marketCap") or p.get("fdv") or d["mc"]
    return out


def gecko_token_pools(chain, token):
    """Pools de GeckoTerminal (respaldo para fecha de lanzamiento y precio)."""
    net = CHAINS[chain]["gecko"]
    try:
        d = request(f"https://api.geckoterminal.com/api/v2/networks/{net}/tokens/{token}/pools?page=1", limiter=_gt_lim, source="geckoterminal")
    except Exception as e:
        log.warning("GeckoTerminal falló: %s", e)
        return None
    pools = []
    for p in d.get("data") or []:
        a = p.get("attributes") or {}
        created = a.get("pool_created_at")
        ts = None
        if created:
            try:
                ts = int(time.mktime(time.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone)
            except Exception:
                ts = None
        pools.append({"address": a.get("address"), "name": a.get("name"), "created": ts, "liq": float(a.get("reserve_in_usd") or 0),
                      "price_usd": float(a.get("base_token_price_usd") or 0) or None})
    return pools


def token_market(chain, token):
    """Info de mercado del token escaneado (DexScreener + GeckoTerminal de respaldo)."""
    ds = dexscreener_tokens(chain, [token]).get(_norm(chain, token)) or {}
    if not ds.get("launch_ts") or not ds.get("price_usd"):
        gp = gecko_token_pools(chain, token) or []
        if gp:
            ts = min([p["created"] for p in gp if p["created"]] or [None]) if any(p["created"] for p in gp) else None
            ds.setdefault("pools", [])
            if not ds.get("pools"):
                ds["pools"] = [{"address": p["address"], "dex": p["name"], "liq": p["liq"], "created": p["created"]} for p in gp]
            if ts and (not ds.get("launch_ts") or ts < ds["launch_ts"]):
                ds["launch_ts"] = ts
            if not ds.get("price_usd"):
                best = max(gp, key=lambda p: p["liq"])
                ds["price_usd"] = best["price_usd"]
                ds["liq"] = best["liq"]
    return ds


def source_check():
    """Prueba rápida de fuentes públicas (para el indicador del panel)."""
    try:
        native_usd("solana")
    except Exception:
        pass
    STATUS.save()
