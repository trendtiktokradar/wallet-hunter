"""Mapa de wallets (pestaña «Mapa de Wallets»): fondeo y movimientos bajo demanda.

No es un monitor. Cada búsqueda lee un intervalo acotado y se puede reutilizar desde la caché.
No inventa direcciones, fechas ni importes: si la fuente no responde, el resultado dice que no está disponible.

Definiciones que el panel repite junto al grafo
-----------------------------------------------
- Ventana: como máximo `window_days` días hacia atrás y, a la vez, como máximo `tx_cap`
  transferencias por wallet (una página). Lo que quede fuera no se afirma ni se niega.
- Fondeo confirmado: entrada de SOL ≥ `min_native_sol` que no forma parte de un swap
  (la clasificación sale de la misma transacción parseada). Se listan hasta `funding_cap`
  contrapartes, por importe. Una entrada de SOL sin transacción parseada se muestra aparte
  como «entrada sin clasificar»: puede ser una venta.
- Movimientos: entradas y salidas de esa misma lectura (SOL y tokens), las más recientes,
  hasta `movement_cap`.
- Saltos: 1 = solo las wallets pedidas. 2 = además se lee el fondeo confirmado de sus
  orígenes que no son servicio ni exchange, con tope `max_hop_lookups`.
- Páginas: como máximo `max_pages` (el cliente pide la siguiente con el cursor devuelto).
- Vacío: en lo revisado no apareció nada. No es prueba de que no exista fuera del tope.
- Servicio o exchange: solo con fuente (lista de `services.py` con su cita, hot wallets de
  `cex.py`, o caché de autodetección ya medida). Si no hay fuente, queda «sin identificar».
  Compartir un servicio, un puente o un exchange no es propiedad común.
- Swap verificado: `deltas.extract` ve el token y la contrapartida (SOL/stable) en sentidos
  opuestos. Una transferencia de token sin esa contrapartida no es compra ni venta.
- Coin: la CA solo fija el contexto. «Primeros compradores» lee como máximo
  `first_buyers_tx_cap` transacciones antiguas del mint (no todos los holders). Un intervalo
  no puede pasar de `interval_max_days` ni de `interval_tx_cap` transacciones recientes.
  El enlace de Axiom se construye solo si hay un pool devuelto por la base o por el mercado;
  si no hay pool, no hay enlace.
- Coincidencia alta: ver `coincidence_rule`. No es un score, ni un bundler, ni «mismo dueño».
  Sin muestra mínima no hay badge. Una coin popular compartida no basta.

Las direcciones de Solana no se pasan a minúsculas.
"""
import hashlib, json, logging, re, time
from .config import cfg, secret
from .chains import WSOL, STABLES, is_evm_address, is_sol_address
from . import cex, db, services
from .deltas import extract, is_quote

log = logging.getLogger("wh")
NATIVE = "native"
SIG_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{64,128}")
AXIOM_POOL = "https://axiom.trade/meme/{pool}"

DEFAULTS = {
    "window_days": 30,
    "max_wallets": 12,
    "tx_cap": 100,
    "funding_cap": 8,
    "min_native_sol": 0.05,
    "movement_cap": 40,
    "max_hops": 2,
    "max_hop_lookups": 8,
    "max_pages": 3,
    "cache_hours": 12,
    "first_buyers_tx_cap": 200,
    "first_buyers_cap": 12,
    "interval_tx_cap": 300,
    "interval_max_days": 7,
    "coincidence": {
        "min_distinct_tokens": 8,
        "min_overlap_tokens": 5,
        "min_overlap_ratio": 0.35,
        "near_window_s": 600,
        "popular_min_wallets": 4,
    },
}


def limits():
    raw = (cfg().get("map") or {}) if cfg else {}
    out = dict(DEFAULTS)
    for k, v in raw.items():
        if k == "coincidence" and isinstance(v, dict):
            out["coincidence"] = dict(DEFAULTS["coincidence"])
            out["coincidence"].update(v)
        elif k in out:
            out[k] = v
    return out


def coincidence_rule(L=None):
    L = L or limits()
    co = L["coincidence"]
    pct = int(round(float(co["min_overlap_ratio"]) * 100))
    return (
        f"Coincidencia alta solo si, en lo revisado, cada wallet tiene al menos {co['min_distinct_tokens']} "
        f"coins distintas con un swap verificado (una recepción de token no entra en la muestra), comparten "
        f"al menos {co['min_overlap_tokens']} y al menos el {pct} % de la muestra más pequeña, después de quitar "
        f"SOL, stables y las coins que salgan en {co['popular_min_wallets']} o más wallets de esta búsqueda, "
        "y además hay una contraparte que no sea servicio ni exchange (transferencia directa o el mismo fondeador confirmado). "
        "No es un score ni una afirmación de mismo dueño o de bundler. Si la muestra no llega, no hay badge. "
        "Una sola coin, aunque sea muy conocida, no basta."
    )


def _num(x):
    return str(x).replace(".", ",")


def empty_note(L):
    return (
        f"En lo revisado (como máximo {L['window_days']} días y {L['tx_cap']} transferencias) no apareció "
        f"ninguna entrada de SOL ≥ {_num(L['min_native_sol'])} ni otros movimientos. "
        "Eso no demuestra que no existan fuera de ese intervalo o por encima del tope."
    )


def coverage_text(L, partial):
    txt = (
        f"Revisado: como máximo {L['window_days']} días y {L['tx_cap']} transferencias por wallet (hasta {L['max_pages']} páginas). "
        f"Fondeo = entradas de SOL ≥ {_num(L['min_native_sol'])} que no son un swap, hasta {L['funding_cap']} contrapartes. "
        "Un resultado vacío es «no apareció en ese intervalo», no una prueba de que no exista."
    )
    if partial:
        txt += " Cobertura parcial: el tope cortó la lectura; no es el historial completo."
    return txt


def parse_sol(token):
    """Devuelve la dirección Solana tal cual (con sus mayúsculas) o None. Nunca aplica lower()."""
    if not isinstance(token, str):
        return None
    token = token.strip()
    if not token or token.lower().startswith("0x") or is_evm_address(token):
        return None
    tail = token.split("/")[-1].split("?")[0].split("#")[0]
    m = re.search(r"([1-9A-HJ-NP-Za-km-z]{32,44})$", tail)
    addr = m.group(1) if m else token
    if not is_sol_address(addr):
        return None
    return addr


def parse_wallets(items):
    if isinstance(items, list):
        parts = [str(x) for x in items]
    else:
        parts = re.split(r"[\s,;]+", items or "")
    good, bad = [], []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.lower().startswith("0x") or is_evm_address(part):
            bad.append(part)
            continue
        addr = parse_sol(part)
        if not addr:
            bad.append(part)
            continue
        if addr not in good:
            good.append(addr)
    return good, bad


def clean_request(req):
    """Valida el cuerpo de /api/map. Las direcciones Solana salen con su caja original."""
    L = limits()
    if not isinstance(req, dict):
        raise ValueError("petición no válida")
    mode = req.get("mode") or "wallets"
    if mode not in ("wallets", "coin"):
        raise ValueError("modo no válido")
    scope = req.get("scope") or "context"
    if scope not in ("context", "first_buyers", "interval"):
        raise ValueError("ámbito de coin no válido")
    wallets, bad = parse_wallets(req.get("wallets") if req.get("wallets") is not None else req.get("items") or "")
    if len(wallets) > L["max_wallets"]:
        raise ValueError(f"Máximo {L['max_wallets']} wallets por búsqueda")
    if bad and not wallets and scope == "context":
        raise ValueError("Ninguna dirección Solana válida. Se distinguen mayúsculas y minúsculas; este mapa no reescribe la dirección ni analiza EVM.")
    coin = None
    if mode == "coin" or req.get("coin") or req.get("ca"):
        if mode != "coin":
            mode = "coin"
        raw_coin = req.get("coin") or req.get("ca") or ""
        coin = parse_sol(str(raw_coin))
        if not coin:
            raise ValueError("CA de Solana no válida. Se distingue mayúsculas y minúsculas; no se convierte a minúsculas.")
    if scope == "context" and not wallets:
        raise ValueError("Pega al menos una wallet")
    if scope in ("first_buyers", "interval") and not coin:
        raise ValueError("Para primeros compradores o un intervalo hace falta la CA")
    try:
        hops = int(req.get("hops") or 1)
    except (TypeError, ValueError):
        raise ValueError("saltos no válidos")
    if hops < 1 or hops > int(L["max_hops"]):
        raise ValueError(f"Este mapa recorre como máximo {L['max_hops']} saltos hacia atrás")
    try:
        page = int(req.get("page") or 1)
    except (TypeError, ValueError):
        raise ValueError("página no válida")
    if page < 1 or page > int(L["max_pages"]):
        raise ValueError(f"Como máximo {L['max_pages']} páginas por wallet en una búsqueda")
    cursors = {}
    raw_c = req.get("cursors") or {}
    if raw_c and not isinstance(raw_c, dict):
        raise ValueError("cursors no válidos")
    for k, v in (raw_c or {}).items():
        addr = parse_sol(str(k))
        if addr and isinstance(v, str) and 8 <= len(v) <= 200 and re.fullmatch(r"[A-Za-z0-9_-]+", v):
            cursors[addr] = v
    if page > 1 and not cursors:
        raise ValueError("Para otra página hace falta el cursor de la anterior")
    interval = None
    if scope == "interval":
        try:
            fr, to = int(req.get("from_ts")), int(req.get("to_ts"))
        except (TypeError, ValueError):
            raise ValueError("Intervalo no válido")
        if fr <= 0 or to <= fr:
            raise ValueError("Intervalo no válido")
        if to - fr > int(L["interval_max_days"]) * 86400:
            raise ValueError(f"El intervalo máximo es {L['interval_max_days']} días, no todo el historial de holders")
        interval = {"from_ts": fr, "to_ts": to}
    spec = {
        "mode": "coin" if coin else "wallets",
        "scope": scope if coin else "context",
        "wallets": wallets,
        "coin": coin,
        "hops": hops,
        "page": page,
        "cursors": cursors,
        "interval": interval,
        "rejected": bad[:8],
    }
    return spec


def tx_url(sig):
    if isinstance(sig, str) and SIG_RE.fullmatch(sig):
        return "https://solscan.io/tx/" + sig
    return None


def acc_url(addr):
    if is_sol_address(addr or ""):
        return "https://solscan.io/account/" + addr
    return None


def entity_of(c, addr):
    """Clasifica solo con fuente. Sin fuente → sin identificar (no es un exchange)."""
    if not addr:
        return {"kind": "unidentified", "label": None, "source": None, "verified": False}
    if services.ignored("solana", addr):
        known = services.known("solana", addr) or {}
        return {"kind": "ignored", "label": known.get("name"), "source": known.get("source"), "verified": bool(known.get("verified"))}
    name = cex.label("solana", addr)
    if name:
        return {"kind": "cex", "label": name, "source": "Hot wallets públicas en wallethunter/cex.py", "verified": True}
    known = services.known("solana", addr)
    if known:
        return {"kind": "service", "label": known.get("name"), "source": known.get("source"), "verified": bool(known.get("verified")), "why": known.get("why")}
    hit = services.cache_get(c, "solana", addr) if c is not None else None
    if hit and hit[0]:
        why = (hit[1] or {}).get("why")
        return {"kind": "service", "label": "servicio/hub", "source": "Caché de autodetección (actividad ya medida, no un nombre de exchange)", "verified": False, "why": why, "auto": True}
    return {"kind": "unidentified", "label": None, "source": None, "verified": False}


def _is_serviceish(ent):
    return ent["kind"] in ("service", "cex", "ignored")


def rows_from_deltas(addr, deltas):
    """Convierte deltas ya parseados en filas del mapa. El swap queda marcado; el resto es transferencia."""
    rows = []
    for d in deltas or []:
        swaps, trs = extract(d, addr)
        if swaps:
            sw = dict(swaps[0])
            side = sw["side"]
            rows.append({
                "tx": d.tx, "ts": d.ts, "from": addr if side == "buy" else sw.get("counterparty"),
                "to": sw.get("counterparty") if side == "buy" else addr,
                "asset": NATIVE, "amount": float(sw.get("native_amount") or 0),
                "kind": "swap_buy" if side == "buy" else "swap_sell",
                "swap": {"side": side, "token": sw["token"], "token_amount": sw.get("token_amount"), "native_amount": sw.get("native_amount"), "wallet": addr},
            })
            continue
        for t in trs:
            incoming = t["direction"] == "in"
            kind = ("token_in" if incoming else "token_out") if t["asset"] != NATIVE else ("native_in" if incoming else "native_out")
            rows.append({
                "tx": t["tx"], "ts": t["ts"],
                "from": t["counterparty"] if incoming else addr,
                "to": addr if incoming else t["counterparty"],
                "asset": NATIVE if t["asset"] == NATIVE else t["asset"],
                "amount": float(t.get("amount") or 0),
                "kind": kind, "swap": None,
            })
    return rows


def rows_from_transfers(addr, raw):
    """getTransfersByAddress sin parsear la tx: no se afirma que una entrada de SOL sea fondeo."""
    rows = []
    for x in raw or []:
        if x.get("type") not in (None, "transfer"):
            continue
        mint = x.get("mint") or x.get("asset")
        asset = NATIVE if mint in (None, NATIVE, "So11111111111111111111111111111111111111111", WSOL) or x.get("asset") == NATIVE else mint
        src, dst = x.get("from") or x.get("fromUserAccount"), x.get("to") or x.get("toUserAccount")
        if asset == NATIVE and src == addr:
            kind = "native_out"
        elif asset == NATIVE and dst == addr:
            kind = "sol_in_unclassified"
        elif dst == addr:
            kind = "token_in"
        elif src == addr:
            kind = "token_out"
        else:
            continue
        rows.append({
            "tx": x.get("tx") or x.get("signature"), "ts": x.get("ts") if x.get("ts") is not None else x.get("blockTime"),
            "from": src, "to": dst, "asset": asset, "amount": float(x.get("amount") if x.get("amount") is not None else x.get("uiAmount") or 0),
            "kind": kind, "swap": None,
        })
    return rows


def merge_rows(transfer_rows, delta_rows):
    """Si la misma firma está parseada, manda el delta (ahí sí se separa swap de fondeo)."""
    parsed = {r.get("tx") for r in delta_rows or [] if r.get("tx")}
    out = [r for r in delta_rows or []]
    for r in transfer_rows or []:
        if r.get("tx") and r["tx"] in parsed:
            continue
        out.append(r)
    return out


def apply_window(rows, now, window_days):
    cut = int(now) - int(window_days) * 86400
    kept, dropped_old = [], 0
    for r in rows:
        ts = r.get("ts")
        if ts is None or int(ts) >= cut:
            kept.append(r)
        else:
            dropped_old += 1
    return kept, dropped_old


class CachedSource:
    """Reutiliza la lectura de una dirección con los mismos topes. No guarda errores."""

    def __init__(self, inner, c, L):
        self.inner, self.c, self.L = inner, c, L
        self.hits = self.misses = 0

    def _sig(self, kind, limit, before):
        return f"{kind}:{limit}:{before or ''}"

    def _get(self, addr, kind, sig):
        if self.c is None:
            return None
        row = self.c.execute(
            "SELECT payload, ts FROM map_cache WHERE chain='solana' AND address=? AND kind=? AND sig=?",
            (addr, kind, sig)).fetchone()
        if not row:
            return None
        if time.time() - int(row["ts"]) > float(self.L["cache_hours"]) * 3600:
            return None
        try:
            return json.loads(row["payload"])
        except (TypeError, ValueError):
            return None

    def _put(self, addr, kind, sig, data):
        if self.c is None or data.get("error"):
            return
        self.c.execute(
            "INSERT OR REPLACE INTO map_cache(chain,address,kind,sig,payload,ts) VALUES('solana',?,?,?,?,?)",
            (addr, kind, sig, json.dumps(data), int(time.time())))
        self.c.commit()

    def read(self, addr, before=None, limit=None):
        limit = int(limit or self.L["tx_cap"])
        sig = self._sig("transfers", limit, before)
        hit = self._get(addr, "transfers", sig)
        if hit is not None:
            self.hits += 1
            return hit
        self.misses += 1
        data = self.inner.read(addr, before=before, limit=limit)
        self._put(addr, "transfers", sig, data)
        return data

    def token_early(self, mint, limit):
        sig = self._sig("early", int(limit), None)
        hit = self._get(mint, "token", sig)
        if hit is not None:
            self.hits += 1
            return hit
        self.misses += 1
        data = self.inner.token_early(mint, limit)
        if _jsonable(data):
            self._put(mint, "token", sig, data)
        return data

    def token_interval(self, mint, fr, to, limit):
        sig = self._sig("interval", int(limit), f"{fr}:{to}")
        hit = self._get(mint, "token", sig)
        if hit is not None:
            self.hits += 1
            return hit
        self.misses += 1
        data = self.inner.token_interval(mint, fr, to, limit)
        if _jsonable(data):
            self._put(mint, "token", sig, data)
        return data


def _jsonable(data):
    try:
        json.dumps(data)
        return True
    except (TypeError, ValueError):
        return False


class HeliusMapSource:
    """Lecturas acotadas. Se construye solo cuando hay key; los tests no la usan."""

    def __init__(self):
        from .sol import Helius
        self.h = Helius()

    def read(self, addr, before=None, limit=100):
        limit = max(1, min(int(limit), 100))
        opts = {"limit": limit, "sortOrder": "desc"}
        if before:
            opts["paginationToken"] = before
        try:
            raw = self.h.rpc("getTransfersByAddress", [addr, opts], credits=10) or {}
        except Exception as e:
            log.info("mapa transferencias %s: %s", addr[:4], str(e)[:120])
            return {"rows": [], "truncated": False, "next_cursor": None, "error": "No se pudo leer transferencias de esta wallet", "parsed": False}
        transfer_rows = rows_from_transfers(addr, raw.get("data") or [])
        cursor = raw.get("paginationToken")
        delta_rows, parsed = [], False
        try:
            if self.h.gtfa_available():
                gopts = {"limit": limit, "order": "desc", "filters": {"status": "succeeded"}}
                r = self.h.gtfa(addr, **gopts)
                from .deltas import from_rpc
                deltas = [from_rpc(t) for t in (r.get("data") or [])]
                delta_rows = rows_from_deltas(addr, deltas)
                parsed = True
        except Exception as e:
            log.info("mapa gtfa %s: %s", addr[:4], str(e)[:120])
        rows = merge_rows(transfer_rows, delta_rows)
        return {"rows": rows, "truncated": bool(cursor) or len(raw.get("data") or []) >= limit, "next_cursor": cursor, "error": None, "parsed": parsed}

    def token_early(self, mint, limit):
        return self._token(mint, limit, order="asc", fr=None, to=None)

    def token_interval(self, mint, fr, to, limit):
        return self._token(mint, limit, order="desc", fr=fr, to=to)

    def _token(self, mint, limit, order, fr, to):
        limit = max(1, min(int(limit), 300))
        try:
            if not self.h.gtfa_available():
                return {"events": [], "truncated": True, "unavailable": "Hace falta getTransactionsForAddress (plan Developer de Helius) para leer la coin sin recorrer todo el historial. No se ha hecho ese recorrido."}
            r = self.h.gtfa(mint, order=order, limit=limit, filters={"status": "succeeded"})
        except Exception as e:
            log.info("mapa coin %s: %s", mint[:4], str(e)[:120])
            return {"events": [], "truncated": False, "unavailable": "No se pudo leer la coin en el tope pedido"}
        from .deltas import from_rpc
        deltas = [from_rpc(t) for t in (r.get("data") or [])]
        if fr or to:
            deltas = [d for d in deltas if d.ts and (fr or 0) <= int(d.ts) <= (to or 10 ** 12)]
            reached = bool(deltas) or not r.get("paginationToken")
            if r.get("paginationToken") and deltas and order == "desc" and min(int(d.ts) for d in deltas if d.ts) > (fr or 0):
                reached = False
        else:
            reached = not r.get("paginationToken")
        events = events_from_deltas(deltas, mint)
        note = None if reached else "El tope de transacciones no cubre todo el tramo pedido. No se sigue paginando."
        return {"events": events, "truncated": not reached, "unavailable": note}


def events_from_deltas(deltas, mint):
    """Compras/ventas verificadas y recepciones, por separado, solo de este mint."""
    found = []
    for d in deltas or []:
        owners = []
        for (o, m) in getattr(d, "tokens", {}) or {}:
            if m == mint and o not in owners:
                owners.append(o)
        for o in owners:
            if not is_sol_address(o or ""):
                continue
            swaps, trs = extract(d, o)
            hit = False
            for sw in swaps:
                if sw["token"] == mint:
                    found.append({
                        "address": o, "kind": "swap_buy" if sw["side"] == "buy" else "swap_sell",
                        "verified": True, "ts": sw["ts"], "tx": sw["tx"], "url": tx_url(sw["tx"]),
                        "token_amount": sw.get("token_amount"), "native_amount": sw.get("native_amount"),
                    })
                    hit = True
            if hit:
                continue
            for t in trs:
                if t["asset"] == mint:
                    found.append({
                        "address": o, "kind": "token_in" if t["direction"] == "in" else "token_out",
                        "verified": False, "ts": t["ts"], "tx": t["tx"], "url": tx_url(t["tx"]),
                        "token_amount": t.get("amount"), "native_amount": None,
                    })
    return found


def lookup_pool(c, mint, fetch=None):
    """Pool solo si una fuente lo devolvió. Sin pool no hay enlace de Axiom."""
    symbol, pools = None, []
    if c is not None:
        try:
            row = c.execute("SELECT symbol, pools FROM tokens WHERE chain='solana' AND address=?", (mint,)).fetchone()
        except Exception:
            row = None
        if row:
            symbol = row["symbol"]
            try:
                pools = json.loads(row["pools"] or "[]") or []
            except (TypeError, ValueError):
                pools = []
    source = "base local (escaneo previo)" if pools else None
    if not pools and fetch:
        try:
            mk = fetch(mint) or {}
        except Exception as e:
            log.info("pool %s: %s", mint[:4], str(e)[:80])
            mk = {}
        symbol = symbol or mk.get("symbol")
        pools = mk.get("pools") or []
        if pools:
            source = "DexScreener/GeckoTerminal"
    best = None
    for p in pools:
        if not isinstance(p, dict):
            continue
        addr = p.get("address")
        if is_sol_address(addr or "") and (best is None or (p.get("liq") or 0) > (best.get("liq") or 0)):
            best = p
    if not best:
        return {"symbol": symbol, "pool": None, "axiom": None, "source": None}
    pool = best["address"]
    return {"symbol": symbol, "pool": pool, "axiom": AXIOM_POOL.format(pool=pool), "source": source}


def _aliases(c):
    if c is None:
        return {}
    try:
        return {a["address"]: a["alias"] for a in db.aliases(c) if a["chain"] == "solana"}
    except Exception:
        return {}


def _funders(rows, addr, L):
    groups = {}
    for r in rows:
        if r.get("to") != addr or r.get("asset") != NATIVE:
            continue
        if r.get("kind") not in ("native_in", "funding", "sol_in_unclassified"):
            continue
        if float(r.get("amount") or 0) < float(L["min_native_sol"]):
            continue
        src = r.get("from")
        if not src or src == addr:
            continue
        groups.setdefault(src, []).append(r)
    ranked = sorted(groups.items(), key=lambda kv: -sum(float(x.get("amount") or 0) for x in kv[1]))
    return ranked[: int(L["funding_cap"])]


def _movements(rows, addr, L):
    out = []
    for r in rows:
        if addr not in (r.get("from"), r.get("to")):
            continue
        out.append(r)
    out.sort(key=lambda r: int(r.get("ts") or 0), reverse=True)
    cap = int(L["movement_cap"])
    return out[:cap], len(out) > cap


def _swaps(rows, addr):
    out = []
    for r in rows:
        sw = r.get("swap")
        if not sw or not sw.get("token"):
            continue
        if sw.get("wallet") not in (None, addr) and addr not in (r.get("from"), r.get("to")):
            continue
        if is_quote("solana", sw["token"]):
            continue
        out.append({"token": sw["token"], "side": sw.get("side"), "ts": sw.get("ts") or r.get("ts"), "wallet": addr})
    return out


def _quote_or_empty(token):
    return (not token) or is_quote("solana", token)


def popular_mints(swap_index, popular_min):
    counts = {}
    for swaps in swap_index.values():
        for token in {s["token"] for s in swaps}:
            counts[token] = counts.get(token, 0) + 1
    return {m for m, n in counts.items() if n >= int(popular_min)}


def _link_sets(by_wallet, entities):
    """Contrapartes que sí pueden apoyar una coincidencia: directo, o fondeador confirmado que no es servicio/CEX."""
    direct = {}
    funders = {}
    for addr, info in by_wallet.items():
        funders[addr] = {}
        for f in info["funders"]:
            if f["confirmed"] and not _is_serviceish(entities.get(f["address"], {"kind": "unidentified"})):
                funders[addr][f["address"]] = f
        direct[addr] = set()
        for m in info["movements_all"]:
            other = m["from"] if m.get("to") == addr else m.get("to") if m.get("from") == addr else None
            if not other or other == addr or other not in by_wallet:
                continue
            if _is_serviceish(entities.get(other, {"kind": "unidentified"})):
                continue
            if m.get("kind") in ("swap_buy", "swap_sell"):
                continue
            direct[addr].add(other)
    return direct, funders


def _near_buys(sw_a, sw_b, shared, window_s):
    buys_a = [s for s in sw_a if s["side"] == "buy" and s["token"] in shared]
    buys_b = [s for s in sw_b if s["side"] == "buy" and s["token"] in shared]
    if not buys_a and not buys_b:
        return 0, "sin compras verificadas en las coins compartidas; una venta o una recepción no cuenta como compra próxima"
    if any(s.get("ts") is None for s in buys_a + buys_b):
        return None, "compras próximas no calculables: falta la fecha en alguna compra verificada"
    n = 0
    for a in buys_a:
        for b in buys_b:
            if a["token"] == b["token"] and abs(int(a["ts"]) - int(b["ts"])) <= int(window_s):
                n += 1
    return n, f"{n} compras de la misma coin con ≤ {int(window_s) // 60} min de diferencia"


def tokens_of(swaps, popular):
    return {s["token"] for s in swaps if s.get("token") and not _quote_or_empty(s["token"]) and s["token"] not in popular}


def judge_pair(addr_a, addr_b, sw_a, sw_b, link_why, partial_a, partial_b, unavailable, popular, L):
    co = L["coincidence"]
    A, B = tokens_of(sw_a, popular), tokens_of(sw_b, popular)
    detail = {
        "sample_a": len(A), "sample_b": len(B),
        "min_distinct_tokens": co["min_distinct_tokens"],
        "min_overlap_tokens": co["min_overlap_tokens"],
        "min_overlap_ratio": co["min_overlap_ratio"],
        "partial": bool(partial_a or partial_b),
        "link": link_why,
    }
    if unavailable:
        return None, "historial de swaps no disponible: no se infiere actividad", detail
    if len(A) < int(co["min_distinct_tokens"]) or len(B) < int(co["min_distinct_tokens"]):
        return None, "muestra insuficiente de swaps verificados", detail
    if not link_why:
        return None, "sin contraparte distinta de un servicio o un exchange en lo revisado", detail
    inter = A & B
    denom = min(len(A), len(B))
    ratio = (len(inter) / denom) if denom else 0
    detail.update({"overlap": len(inter), "denom": denom, "ratio": round(ratio, 4), "tokens": sorted(inter)})
    if len(inter) < int(co["min_overlap_tokens"]) or ratio < float(co["min_overlap_ratio"]):
        return None, "el solape de coins distintas no llega al mínimo (una coin compartida no basta)", detail
    near_n, near_txt = _near_buys(sw_a, sw_b, inter, co["near_window_s"])
    pct = int(round(ratio * 100))
    partial_txt = " Cobertura parcial: el badge usa solo lo revisado." if detail["partial"] else ""
    motive = (
        f"Con esta contraparte: {len(inter)} coins distintas en común de {denom} en la muestra más pequeña ({pct} %). "
        f"Ventana revisada: {L['window_days']} días, tope {L['tx_cap']} tx por wallet.{partial_txt} "
        f"Contraparte: {link_why}. Compras próximas: {near_txt}. "
        "Es una hipótesis de solape, no una prueba de mismo dueño ni de coordinación."
    )
    hit = {
        "wallet": addr_a, "counterpart": addr_b, "overlap": len(inter), "denom": denom, "ratio": round(ratio, 4),
        "window_days": L["window_days"], "tx_cap": L["tx_cap"], "partial": detail["partial"],
        "near_buys": near_n, "near_note": near_txt, "counterpart_why": link_why, "motive": motive,
        "detail": {
            "tokens": sorted(inter)[:12], "tokens_more": max(0, len(inter) - 12),
            "sample_a": len(A), "sample_b": len(B), "link": link_why,
            "rule": coincidence_rule(L),
        },
    }
    return hit, None, detail


def _funder_public(c, src, rows, L):
    ent = entity_of(c, src)
    confirmed = all(r.get("kind") in ("native_in", "funding") for r in rows)
    total = sum(float(r.get("amount") or 0) for r in rows)
    txs = []
    for r in sorted(rows, key=lambda x: int(x.get("ts") or 0), reverse=True)[:6]:
        txs.append({"tx": r.get("tx"), "ts": r.get("ts"), "amount": r.get("amount"), "url": tx_url(r.get("tx"))})
    return {
        "address": src, "amount": total, "n": len(rows), "ts": txs[0]["ts"] if txs else None,
        "tx": txs[0]["tx"] if txs else None, "url": txs[0]["url"] if txs else None, "txs": txs,
        "confirmed": confirmed and ent["kind"] != "ignored",
        "kind": ent["kind"] if ent["kind"] != "unidentified" else "origin",
        "label": ent.get("label"), "source": ent.get("source"), "verified": ent.get("verified", False),
        "why": ent.get("why"),
        "note": None if confirmed else "Entrada de SOL en el intervalo. Sin la transacción parseada no se confirma que sea fondeo y no una venta.",
    }


def _movement_public(c, addr, r):
    incoming = r.get("to") == addr
    other = r.get("from") if incoming else r.get("to")
    ent = entity_of(c, other) if other else {"kind": "unidentified", "label": None, "source": None}
    kind = r.get("kind") or "transfer"
    swap = r.get("swap") or {}
    return {
        "direction": "in" if incoming else "out",
        "counterparty": other, "counterparty_kind": ent["kind"], "counterparty_label": ent.get("label"),
        "counterparty_source": ent.get("source"),
        "amount": r.get("amount"), "asset": r.get("asset"),
        "token": swap.get("token") if kind.startswith("swap") else (r.get("asset") if r.get("asset") not in (NATIVE, None) else None),
        "token_amount": swap.get("token_amount"),
        "kind": kind, "verified_swap": kind in ("swap_buy", "swap_sell"),
        "ts": r.get("ts"), "tx": r.get("tx"), "url": tx_url(r.get("tx")),
    }


def _coin_events_for(rows, addr, mint):
    ev = []
    for r in rows:
        sw = r.get("swap") or {}
        if r.get("kind") in ("swap_buy", "swap_sell") and sw.get("token") == mint and addr in (r.get("from"), r.get("to"), sw.get("wallet")):
            ev.append({
                "kind": r["kind"], "verified": True, "ts": r.get("ts"), "tx": r.get("tx"), "url": tx_url(r.get("tx")),
                "token_amount": sw.get("token_amount"), "native_amount": sw.get("native_amount") or r.get("amount"),
                "label": "Compró · verificado" if r["kind"] == "swap_buy" else "Vendió · verificado",
            })
        elif r.get("asset") == mint and addr in (r.get("from"), r.get("to")) and not sw:
            incoming = r.get("to") == addr
            ev.append({
                "kind": "token_in" if incoming else "token_out", "verified": False,
                "ts": r.get("ts"), "tx": r.get("tx"), "url": tx_url(r.get("tx")),
                "token_amount": r.get("amount"), "native_amount": None,
                "label": "Recibió el token (no es una compra)" if incoming else "Envió el token (no es una venta)",
            })
    ev.sort(key=lambda e: int(e.get("ts") or 0), reverse=True)
    return ev


def _highlight(events):
    kinds = {e["kind"] for e in events}
    if "swap_buy" in kinds and "swap_sell" in kinds:
        return "Compró y vendió · verificado"
    if "swap_buy" in kinds:
        return "Compró · verificado"
    if "swap_sell" in kinds:
        return "Vendió · verificado"
    if "token_in" in kinds:
        return "Recibió token"
    if "token_out" in kinds:
        return "Envió token"
    return None


def _read_wallet(source, addr, before, L, now):
    try:
        data = source.read(addr, before=before, limit=L["tx_cap"])
    except Exception as e:
        log.info("lectura mapa %s: %s", (addr or "")[:4], str(e)[:120])
        data = {"rows": [], "truncated": False, "next_cursor": None, "error": "No se pudo leer esta wallet", "parsed": False}
    rows = data.get("rows") or []
    rows, dropped_old = apply_window(rows, now, L["window_days"])
    page_full = bool(data.get("truncated"))
    # si la página traía movimientos más viejos que la ventana, la ventana está cubierta
    truncated = page_full and dropped_old == 0
    return {
        "rows": rows, "truncated": truncated, "next_cursor": data.get("next_cursor") if truncated else None,
        "error": data.get("error"), "parsed": False if data.get("error") else bool(data.get("parsed", True)),
        "dropped_old": dropped_old,
    }


def run(c, spec, source, now=None, fetch_pool=None):
    L = limits()
    now = int(now or time.time())
    spec = dict(spec)
    notes = []
    if spec.get("rejected"):
        notes.append("Se ignoraron entradas que no son una dirección Solana (EVM incluido). Las de Solana no se pasan a minúsculas.")
    cached = source if isinstance(source, CachedSource) else CachedSource(source, c, L)
    user_wallets = list(spec.get("wallets") or [])
    reads = {}
    partial = False
    for addr in user_wallets:
        reads[addr] = _read_wallet(cached, addr, (spec.get("cursors") or {}).get(addr), L, now)
        if reads[addr]["error"]:
            notes.append(f"Lectura incompleta de una wallet pedida: {reads[addr]['error']}.")
            partial = True
        elif reads[addr]["truncated"]:
            partial = True

    entities = {}

    def ent(addr):
        if addr not in entities:
            entities[addr] = entity_of(c, addr)
        return entities[addr]

    def pack(addr, data):
        rows = [r for r in data["rows"] if ent(r.get("from")).get("kind") != "ignored" and ent(r.get("to")).get("kind") != "ignored"]
        ignored_n = len(data["rows"]) - len(rows)
        funders = []
        for src, group in _funders(rows, addr, L):
            if ent(src)["kind"] == "ignored":
                continue
            funders.append(_funder_public(c, src, group, L))
        mov_all = []
        for r in rows:
            if addr in (r.get("from"), r.get("to")):
                mov_all.append(r)
        shown, more = _movements(rows, addr, L)
        return {
            "rows": rows, "funders": funders, "movements_all": mov_all,
            "movements": [_movement_public(c, addr, r) for r in shown],
            "movements_more": more, "truncated": data["truncated"], "next_cursor": data["next_cursor"],
            "error": data["error"], "parsed": data["parsed"], "ignored_n": ignored_n,
            "swaps": _swaps(rows, addr),
        }

    packed = {addr: pack(addr, reads[addr]) for addr in user_wallets}
    expanded = []
    if int(spec.get("hops") or 1) >= 2:
        candidates = []
        for addr in user_wallets:
            for f in packed[addr]["funders"]:
                if f["confirmed"] and not _is_serviceish(ent(f["address"])) and f["address"] not in packed and f["address"] not in candidates:
                    candidates.append(f["address"])
        extra = candidates[: int(L["max_hop_lookups"])]
        if len(candidates) > len(extra):
            partial = True
            notes.append(f"Segundo salto recortado: se leen como máximo {L['max_hop_lookups']} orígenes por búsqueda.")
        for addr in extra:
            data = _read_wallet(cached, addr, None, L, now)
            reads[addr] = data
            packed[addr] = pack(addr, data)
            expanded.append(addr)
            if data["truncated"] or data["error"]:
                partial = True
    else:
        notes.append("Esta búsqueda es de un salto (el fondeo de las wallets del mapa). Para ver el origen de un origen, añádelo y usa «Buscar un salto atrás» (tope de lecturas extra).")

    # grafo
    aliases = _aliases(c)
    nodes = {}
    edges = []

    def add_node(addr, role):
        e = ent(addr)
        kind = e["kind"] if e["kind"] in ("service", "cex") else ("wallet" if role == "wallet" else "origin")
        if e["kind"] == "ignored":
            return
        prev = nodes.get(addr)
        if prev and prev["role"] == "wallet":
            role = "wallet"
        nodes[addr] = {
            "id": addr, "role": role if kind not in ("service", "cex") else kind,
            "kind": kind if kind in ("service", "cex") else ("wallet" if role == "wallet" else "origin"),
            "label": e.get("label"), "source": e.get("source"), "verified": bool(e.get("verified")),
            "why": e.get("why"), "alias": aliases.get(addr),
            "identified": e["kind"] != "unidentified",
        }

    investigated = list(user_wallets) + expanded
    for addr in user_wallets:
        add_node(addr, "wallet")
    for addr in expanded:
        add_node(addr, "wallet")
    for addr in investigated:
        info = packed[addr]
        for f in info["funders"]:
            add_node(f["address"], "origin")
            if f["address"] not in nodes:
                continue
            edges.append({
                "id": f"{f['address']}->{addr}", "from": f["address"], "to": addr,
                "kind": "funding", "amount": f["amount"], "asset": "SOL", "n": f["n"],
                "ts": f["ts"], "tx": f["tx"], "url": f["url"],
                "confirmed": f["confirmed"], "service": nodes[f["address"]]["kind"] in ("service", "cex"),
            })

    # hipótesis de origen común: fondeo confirmado de 2+ wallets del mapa, y el origen no es servicio/CEX
    funded_by = {}
    for addr in user_wallets:
        for f in packed[addr]["funders"]:
            if f["confirmed"] and not _is_serviceish(ent(f["address"])):
                funded_by.setdefault(f["address"], []).append(addr)
    for src, ws in funded_by.items():
        if len(set(ws)) >= 2 and src in nodes:
            nodes[src]["hypothesis"] = (
                f"Hipótesis: en lo revisado fondeó a {len(set(ws))} wallets de este mapa. "
                "No prueba mismo dueño ni que sea una wallet madre."
            )

    # coin
    coin_block = None
    if spec.get("coin"):
        mint = spec["coin"]
        pool = lookup_pool(c, mint, fetch=fetch_pool)
        buyer_events, buyers_note, buyers_truncated = [], None, False
        if spec.get("scope") == "first_buyers":
            data = cached.token_early(mint, L["first_buyers_tx_cap"])
            buyer_events = data.get("events") or []
            buyers_note = data.get("unavailable")
            buyers_truncated = bool(data.get("truncated"))
        elif spec.get("scope") == "interval":
            iv = spec["interval"]
            data = cached.token_interval(mint, iv["from_ts"], iv["to_ts"], L["interval_tx_cap"])
            buyer_events = data.get("events") or []
            buyers_note = data.get("unavailable")
            buyers_truncated = bool(data.get("truncated"))
        # separa verificados de recepciones; solo los buys verificados se proponen para el mapa
        verified_buyers, receipts = [], []
        seen_b, seen_r = set(), set()
        for ev in buyer_events:
            if ev["kind"] == "swap_buy" and ev["address"] not in seen_b:
                seen_b.add(ev["address"])
                verified_buyers.append(ev)
            elif ev["kind"] == "token_in" and ev["address"] not in seen_r and ev["address"] not in seen_b:
                seen_r.add(ev["address"])
                receipts.append(ev)
        verified_buyers = verified_buyers[: int(L["first_buyers_cap"])]
        for addr in investigated:
            evs = _coin_events_for(packed[addr]["rows"], addr, mint)
            packed[addr]["coin_events"] = evs
            packed[addr]["coin_label"] = _highlight(evs)
            if addr in nodes:
                nodes[addr]["coin_label"] = packed[addr]["coin_label"]
        coin_block = {
            "address": mint, "symbol": pool.get("symbol"), "pool": pool.get("pool"),
            "pool_source": pool.get("source"), "axiom": pool.get("axiom"),
            "scope": spec.get("scope"), "interval": spec.get("interval"),
            "buyers": verified_buyers, "receipts": receipts[: int(L["first_buyers_cap"])],
            "buyers_truncated": buyers_truncated, "note": buyers_note,
            "axiom_note": "Enlace solo si hay un pool devuelto por la base o por el mercado. Sin pool no se fabrica el enlace." if pool.get("axiom") else "Sin pool verificado: no hay enlace de Axiom.",
        }
        if buyers_truncated:
            partial = True
            notes.append("La lectura de la coin está cortada por el tope. No son todos los holders.")
        if buyers_note:
            notes.append(buyers_note)

    # coincidencias solo entre wallets del usuario (no contra un servicio)
    direct, fund_map = _link_sets(
        {a: packed[a] for a in user_wallets}, entities)
    popular = popular_mints({a: packed[a]["swaps"] for a in user_wallets}, L["coincidence"]["popular_min_wallets"])
    coincidences, rejected = [], []
    for i, a in enumerate(user_wallets):
        for b in user_wallets[i + 1:]:
            if _is_serviceish(ent(a)) or _is_serviceish(ent(b)):
                rejected.append({"wallet": a, "counterpart": b, "reason": "un exchange o un servicio no se trata como wallet de una persona"})
                continue
            why = None
            if b in direct.get(a, ()):
                why = "transferencia directa en lo revisado (no es un servicio ni un exchange)"
            else:
                shared = set(fund_map.get(a, {})) & set(fund_map.get(b, {}))
                if shared:
                    why = "mismo fondeador confirmado, que no está etiquetado como servicio ni como exchange"
            unav = (not packed[a]["parsed"] and not packed[a]["swaps"]) or (not packed[b]["parsed"] and not packed[b]["swaps"])
            # si el origen de prueba ya trae swaps, parsed puede ser True por defecto
            if packed[a]["error"] or packed[b]["error"]:
                unav = True
            hit, reason, _detail = judge_pair(
                a, b, packed[a]["swaps"], packed[b]["swaps"], why,
                packed[a]["truncated"], packed[b]["truncated"], unav, popular, L)
            if hit:
                coincidences.append(hit)
                coincidences.append(dict(hit, wallet=b, counterpart=a, detail=dict(hit["detail"], sample_a=hit["detail"]["sample_b"], sample_b=hit["detail"]["sample_a"])))
            else:
                rejected.append({"wallet": a, "counterpart": b, "reason": reason})
    coinc_by = {}
    for hit in coincidences:
        coinc_by.setdefault(hit["wallet"], []).append(hit["counterpart"])
    for addr, mates in coinc_by.items():
        if addr in nodes:
            nodes[addr]["coincidence"] = True
            nodes[addr]["coincidence_with"] = mates

    by_wallet = {}
    any_empty = False
    for addr in investigated:
        info = packed[addr]
        if not info["funders"] and not info["movements"] and not info["error"]:
            any_empty = True
        cov_note = empty_note(L) if not info["funders"] and not info["movements"] and not info["error"] else None
        if info["truncated"]:
            cov_note = (cov_note + " " if cov_note else "") + "Hay más movimientos que esta página; no se han leído."
        by_wallet[addr] = {
            "alias": aliases.get(addr),
            "funders": info["funders"],
            "movements": info["movements"],
            "movements_more": info["movements_more"],
            "coin_events": info.get("coin_events") or [],
            "coin_label": info.get("coin_label"),
            "parsed": info["parsed"],
            "coverage": {
                "txs": len(info["rows"]), "truncated": info["truncated"], "next_cursor": info["next_cursor"],
                "ignored_infra": info["ignored_n"], "error": info["error"], "note": cov_note,
                "from_page": spec.get("page") or 1,
            },
        }
    if any_empty:
        notes.append(empty_note(L))
    if any(ent(a)["kind"] == "ignored" for a in list(entities)):
        notes.append("Se omiten del grafo propinas e infraestructura compartida (por ejemplo Jito o comisiones de pump.fun): no identifican a un dueño.")
    notes.append("Un servicio, un puente o un exchange en gris no atribuye dueño. Que dos wallets lo usen no es una wallet en común.")
    notes.append(coincidence_rule(L))

    result = {
        "ok": True,
        "unavailable": None,
        "chain": "solana",
        "mode": spec.get("mode") or "wallets",
        "scope": spec.get("scope") or "context",
        "wallets": user_wallets,
        "expanded": expanded,
        "coin": coin_block,
        "limits": {
            "window_days": L["window_days"], "tx_cap": L["tx_cap"], "funding_cap": L["funding_cap"],
            "min_native_sol": L["min_native_sol"], "movement_cap": L["movement_cap"],
            "max_hops": L["max_hops"], "max_hop_lookups": L["max_hop_lookups"], "max_pages": L["max_pages"],
            "cache_hours": L["cache_hours"], "first_buyers_tx_cap": L["first_buyers_tx_cap"],
            "interval_tx_cap": L["interval_tx_cap"], "interval_max_days": L["interval_max_days"],
            "coincidence": L["coincidence"], "rule": coincidence_rule(L),
        },
        "coverage": {"partial": partial, "summary": coverage_text(L, partial), "notes": notes, "page": spec.get("page") or 1},
        "nodes": list(nodes.values()),
        "edges": edges,
        "by_wallet": by_wallet,
        "coincidences": [h for h in coincidences if h["wallet"] in user_wallets],
        "rejected": rejected,
        "cache": {"hits": cached.hits, "misses": cached.misses},
        "created": now,
    }
    return result


def unavailable_result(spec, code, message):
    L = limits()
    return {
        "ok": False, "unavailable": {"code": code, "message": message},
        "chain": "solana", "mode": spec.get("mode") or "wallets", "wallets": spec.get("wallets") or [],
        "nodes": [], "edges": [], "by_wallet": {}, "coincidences": [], "coin": None,
        "limits": {"window_days": L["window_days"], "tx_cap": L["tx_cap"], "min_native_sol": L["min_native_sol"], "rule": coincidence_rule(L)},
        "coverage": {"partial": False, "summary": message, "notes": [message], "page": 1},
        "cache": {"hits": 0, "misses": 0}, "created": int(time.time()),
    }


def helius_ready():
    """True/False. No devuelve ni registra la key."""
    return bool(secret("HELIUS_API_KEY"))


def save_run(c, jid, spec, status, result=None, error=None):
    c.execute(
        """INSERT INTO map_runs(id,created,spec,status,result,error) VALUES(?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET status=excluded.status, result=excluded.result, error=excluded.error""",
        (jid, int(time.time()), json.dumps(spec), status, json.dumps(result) if result is not None else None, error))
    c.commit()


def get_run(c, jid):
    row = c.execute("SELECT * FROM map_runs WHERE id=?", (jid,)).fetchone()
    if not row:
        return None
    out = {"id": row["id"], "status": row["status"], "error": row["error"], "created": row["created"]}
    if row["result"]:
        try:
            out["result"] = json.loads(row["result"])
        except ValueError:
            out["result"] = None
    try:
        out["spec"] = json.loads(row["spec"] or "{}")
    except ValueError:
        out["spec"] = {}
    return out


def run_job(c, job, progress=None):
    spec = json.loads(job["items"])
    progress = progress or (lambda _m: None)
    progress("mapa: preparando la lectura acotada")
    if not helius_ready():
        res = unavailable_result(spec, "helius_key", "El box no tiene HELIUS_API_KEY en su entorno. El mapa no inventa el grafo. La key se queda en el servidor; no va en la web.")
        save_run(c, job["id"], spec, "done", res)
        return "mapa: sin key de Helius"
    progress("mapa: leyendo fondeo y movimientos")
    try:
        res = run(c, spec, HeliusMapSource(), fetch_pool=lambda mint: __import__("wallethunter.market", fromlist=["token_market"]).token_market("solana", mint))
    except Exception as e:
        log.exception("mapa %s", job["id"])
        save_run(c, job["id"], spec, "error", error=str(e)[:300])
        raise
    res["id"] = job["id"]
    save_run(c, job["id"], spec, "done", res)
    n = len(spec.get("wallets") or [])
    extra = "cobertura parcial" if res["coverage"]["partial"] else "intervalo revisado"
    return f"mapa: {n} wallets · {extra}"


def clean_note(text, n=500):
    out = "".join(ch for ch in str(text or "") if ch == "\n" or ch >= " ")
    return out.strip()[:n]


def save_hypothesis(c, wallet, counterpart, motive, evidence):
    wallet, counterpart = parse_sol(wallet or ""), parse_sol(counterpart or "")
    if not wallet or not counterpart:
        raise ValueError("wallet o contraparte no válida")
    motive = clean_note(motive)
    if not motive:
        raise ValueError("falta el motivo de la hipótesis")
    if not isinstance(evidence, dict):
        evidence = {}
    evidence = json.loads(json.dumps(evidence)[:4000] or "{}")
    hid = hashlib.sha1(f"{wallet}|{counterpart}|{motive}".encode()).hexdigest()[:16]
    c.execute(
        """INSERT INTO map_hypotheses(id,created,chain,wallet,counterpart,motive,evidence) VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET created=excluded.created, motive=excluded.motive, evidence=excluded.evidence""",
        (hid, int(time.time()), "solana", wallet, counterpart, motive, json.dumps(evidence)))
    c.commit()
    return hid


def list_hypotheses(c, limit=50):
    out = []
    for row in c.execute("SELECT * FROM map_hypotheses ORDER BY created DESC LIMIT ?", (int(limit),)):
        try:
            ev = json.loads(row["evidence"] or "{}")
        except ValueError:
            ev = {}
        out.append({"id": row["id"], "created": row["created"], "wallet": row["wallet"], "counterpart": row["counterpart"], "motive": row["motive"], "evidence": ev, "kind": "hipótesis"})
    return out
