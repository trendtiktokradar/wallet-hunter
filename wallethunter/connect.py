"""Conexiones entre wallets (pestaña Conexiones → «Comprobar conexiones»).

Dado un grupo de 2+ wallets (estén o no en la BD) busca, con reglas fijas (sin IA):
  - transferencias directas entre ellas (SOL/nativo y tokens), en cualquier dirección.
    Solana: cada par se comprueba en TODO su historial con getTransfersByAddress(with=…) de Helius;
    EVM: dentro del historial leído de cada wallet.
  - una wallet paga las comisiones (fee payer) de transacciones firmadas por otra (Solana).
  - fondeador común directo (primer fondeo) o a 2 saltos (intermediarios compartidos) → wallets «puente»;
    los puentes que conectan varias wallets se marcan como posible «wallet madre» (si no son un servicio/hub).
  - mismo exchange como origen de fondos (hot wallets etiquetadas; misma ventana de tiempo e importe parecido = más fuerte).
  - compras de las mismas coins en una ventana corta (tempranas si se conoce el lanzamiento) y en el mismo slot/bloque.
Resultado: grafo (nodos = wallets + puentes + exchanges; aristas = tipo de conexión con pruebas: fecha, importe, tx)
y tabla de pares con score 0-100 y una explicación en español.

Créditos: todo tiene tope (config.json → "connect"): transacciones por wallet, intermediarios a 2 saltos, puentes
revisados y consultas por par. Lo que se recorta se avisa en el resultado («notes»).
Etiquetas de entidades: Labeler() combina fuentes enchufables; hoy solo la lista de exchanges (cex.py). Hay un hueco
(ArkhamLabels) para añadir Arkham cuando haya API key, sin tocar el resto."""
import json, logging, time
from collections import defaultdict
from itertools import combinations
from .config import cfg, secret
from .chains import CHAINS, WSOL, is_evm_address, is_sol_address
from . import cex
from .deltas import extract, from_rpc

log = logging.getLogger("wh")
NATIVE_SOL = "So11111111111111111111111111111111111111111"
DEFAULTS = {
    "max_wallets": 10,            # wallets por comprobación
    "max_txs_per_wallet": 1000,   # historial reciente leído por wallet (Solana: 10 créditos / 100 tx)
    "first_txs": 25,              # + sus primeras transacciones si el historial no cabe (fondeo y primeros contactos)
    "max_counterparties": 5,      # intermediarios por wallet a los que se mira su fondeador (2 saltos)
    "max_hop_lookups": 30,        # tope total de consultas de 2 saltos
    "max_bridges_checked": 10,    # puentes a los que se mira la actividad (¿servicio/hub?)
    "pair_pages": 2,              # páginas de 100 transferencias por par (Solana, historial completo)
    "min_native": {"solana": 0.01, "default": 0.002},   # importe mínimo para contar un flujo (filtra spam/dust)
    "cobuy_window_s": 600,        # compras de la misma coin con ≤ 10 min de diferencia
    "early_window_s": 3600,       # «temprana»: ≤ 1 h tras el lanzamiento (si se conoce)
    "cex_time_window_min": 30,    # retiradas del mismo exchange con ≤ 30 min de diferencia…
    "cex_amount_tolerance": 0.15, # …e importes parecidos (±15 %)
    "hub_min_txs": 1000,          # ≥ 1000 tx en ≤ 7 días = servicio/bot: no cuenta como wallet madre
    "hub_hours": 168,
    "max_nodes": 45,
}
# direcciones de infraestructura que nunca son «puente» (propinas Jito, comisiones de launchpads, autoridades de AMM)
INFRA = {
    "solana": {
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
        "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
        "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
        "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
        "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM", "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "11111111111111111111111111111111",
    },
    "evm": {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"},
}
TYPE_LABEL = {"transfer": "transferencia directa", "fee": "pagó comisiones", "fund": "envió fondos", "first": "primer fondeo",
              "hop": "fondeó (2 saltos)", "cex": "fondos desde exchange", "slot": "compra en el mismo slot/bloque", "cobuy": "compras casi a la vez"}


def conf():
    c = json.loads(json.dumps(DEFAULTS))
    c.update(cfg().get("connect") or {})
    return c


def short(a):
    return (a[:4] + "…" + a[-4:]) if a and len(a) > 12 else (a or "")


def famt(x):
    if x is None:
        return "?"
    a = abs(x)
    s = f"{x:,.0f}" if a >= 1000 else f"{x:.2f}" if a >= 1 else f"{x:.4f}".rstrip("0").rstrip(".") if a >= 0.0001 else f"{x:.2e}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fdate(ts):
    return time.strftime("%d/%m/%Y", time.localtime(ts)) if ts else "?"


def fdur(s):
    s = abs(int(s or 0))
    return f"{s} s" if s < 90 else f"{round(s / 60)} min" if s < 5400 else f"{s / 3600:.1f} h".replace(".", ",")


# ------------------------------------------------------------------ etiquetas de entidades (enchufables)
class StaticLabels:
    """Hot wallets públicas de exchanges (cex.py + state/cex_extra.json)."""
    name = "lista de exchanges"

    def label(self, chain, address):
        n = cex.label(chain, address)
        return {"name": n, "kind": "cex", "source": "lista"} if n else None


class ArkhamLabels:
    """Hueco para Arkham Intelligence. DESACTIVADO: solo se usaría con ARKHAM_API_KEY y con _fetch() implementado
    siguiendo la documentación oficial de su API (no se ha probado: no hay key). Debe devolver
    {"name": "Binance", "kind": "cex"|"entity"|"fund"|"mev"|…, "source": "arkham"} o None. Cachea: cada consulta cuesta."""
    name = "Arkham"
    implemented = False

    def __init__(self):
        self.key = secret("ARKHAM_API_KEY")
        self.cache = {}

    def enabled(self):
        return bool(self.key and self.implemented)

    def label(self, chain, address):
        if not self.enabled():
            return None
        k = (chain, address)
        if k not in self.cache:
            self.cache[k] = self._fetch(chain, address)
        return self.cache[k]

    def _fetch(self, chain, address):
        raise NotImplementedError


class Labeler:
    def __init__(self, sources=None):
        self.sources = sources if sources is not None else [s for s in (StaticLabels(), ArkhamLabels()) if not hasattr(s, "enabled") or s.enabled()]
        self.cache = {}

    def label(self, chain, address):
        if not address:
            return None
        k = (chain, address)
        if k not in self.cache:
            self.cache[k] = next((r for r in (s.label(chain, address) for s in self.sources) if r), None)
        return self.cache[k]

    def names(self):
        return [s.name for s in self.sources]


# ------------------------------------------------------------------ fuentes de datos
class SolSource:
    unit = "créditos Helius"

    def __init__(self, C):
        from .sol import Helius
        self.h, self.C, self.no_transfers_api = Helius(), C, False

    @property
    def credits(self):
        return self.h.credits

    def profile(self, w):
        cap, deltas, tok = self.C["max_txs_per_wallet"], [], None
        flt = {"status": "succeeded", "tokenAccounts": "balanceChanged"}
        if not self.h.gtfa_available():
            raise RuntimeError("hace falta getTransactionsForAddress de Helius (plan Developer o superior)")
        while len(deltas) < cap:
            opts = {"filters": flt}
            if tok:
                opts["paginationToken"] = tok
            r = self.h.gtfa(w, order="desc", limit=min(1000, cap - len(deltas)), **opts)
            deltas += [from_rpc(t) for t in r.get("data") or []]
            tok = r.get("paginationToken")
            if not tok or not r.get("data"):
                break
        truncated = bool(tok)
        if truncated and self.C["first_txs"]:
            r = self.h.gtfa(w, order="asc", limit=self.C["first_txs"], filters=flt)
            seen = {d.tx for d in deltas}
            deltas += [d for d in (from_rpc(t) for t in r.get("data") or []) if d.tx not in seen]
        return {"deltas": deltas, "truncated": truncated}

    def _transfers(self, addr, opts):
        return self.h.rpc("getTransfersByAddress", [addr, opts], credits=10) or {}

    def pair(self, a, b):
        """Todas las transferencias entre a y b (historial completo; hasta pair_pages × 100)."""
        if self.no_transfers_api:
            return None
        rows, tok = [], None
        try:
            for _ in range(self.C["pair_pages"]):
                opts = {"with": b, "limit": 100}
                if tok:
                    opts["paginationToken"] = tok
                r = self._transfers(a, opts)
                for x in r.get("data") or []:
                    if x.get("type") != "transfer":
                        continue
                    m = x.get("mint")
                    rows.append({"tx": x.get("signature"), "ts": x.get("blockTime"), "from": x.get("fromUserAccount"), "to": x.get("toUserAccount"),
                                 "asset": "native" if m in (NATIVE_SOL, WSOL) else m, "amount": float(x.get("uiAmount") or 0)})
                tok = r.get("paginationToken")
                if not tok:
                    break
        except Exception as e:
            log.info("getTransfersByAddress no disponible (%s): uso solo el historial", str(e)[:80])
            self.no_transfers_api = True
            return None
        return rows, bool(tok)

    def funder(self, addr):
        """Primer fondeo nativo (≥ 0,001 SOL) con su tx."""
        if not self.no_transfers_api:
            try:
                r = self._transfers(addr, {"direction": "in", "mint": NATIVE_SOL, "sortOrder": "asc", "limit": 10})
                for x in r.get("data") or []:
                    amt = float(x.get("uiAmount") or 0)
                    if x.get("type") == "transfer" and x.get("fromUserAccount") and x["fromUserAccount"] != addr and amt >= 0.001:
                        return {"address": x["fromUserAccount"], "amount": amt, "ts": x.get("blockTime"), "tx": x.get("signature")}
                return None
            except Exception as e:
                log.info("getTransfersByAddress no disponible (%s)", str(e)[:80])
                self.no_transfers_api = True
        f = self.h.funder_of(addr)
        return {"address": f["funder"], "amount": f["funder_amount"], "ts": f["funded_at"], "tx": None} if f.get("funder") else None

    def activity(self, addr):
        r = self.h.gtfa(addr, details="signatures", order="desc", limit=1000)
        d = r.get("data") or []
        span = ((d[0].get("blockTime") or 0) - (d[-1].get("blockTime") or 0)) / 3600 if len(d) > 1 else None
        return {"n": len(d), "more": bool(r.get("paginationToken")), "span_h": span}


class EvmSource:
    unit = "llamadas a la API"

    def __init__(self, chain, C):
        from .evm import EvmClient
        self.cl, self.C, self.chain = EvmClient(chain), C, chain

    @property
    def credits(self):
        return self.cl.calls

    def profile(self, w):
        w, cap = w.lower(), min(self.C["max_txs_per_wallet"], 10000)
        q = dict(address=w, startblock=0, endblock=99999999, page=1, sort="desc")
        txl = self.cl.call(module="account", action="txlist", offset=cap, **q) or []
        toks = self.cl.call(module="account", action="tokentx", offset=cap, **q) or []
        internal = self.cl.call(module="account", action="txlistinternal", offset=min(cap, 500), **q) or []
        truncated = len(txl) >= cap or len(toks) >= cap
        if truncated and self.C["first_txs"]:
            seen = {t["hash"] for t in txl}
            txl += [t for t in (self.cl.call(module="account", action="txlist", offset=self.C["first_txs"], **dict(q, sort="asc")) or []) if t["hash"] not in seen]
        return {"deltas": self.cl.build_deltas(w, txl, toks, internal), "truncated": truncated}

    def pair(self, a, b):
        return None   # Etherscan no filtra por contraparte: las directas salen del historial leído

    def funder(self, addr):
        a = addr.lower()
        q = dict(address=a, startblock=0, endblock=99999999, page=1, sort="asc")
        rows = (self.cl.call(module="account", action="txlist", offset=5, **q) or []) + (self.cl.call(module="account", action="txlistinternal", offset=3, **q) or [])
        c = [t for t in rows if (t.get("to") or "").lower() == a and int(t.get("value") or 0) > 0]
        if not c:
            return None
        f = min(c, key=lambda t: int(t["timeStamp"]))
        return {"address": f["from"].lower(), "amount": int(f["value"]) / 1e18, "ts": int(f["timeStamp"]), "tx": f.get("hash")}

    def activity(self, addr):
        d = self.cl.call(module="account", action="txlist", address=addr.lower(), startblock=0, endblock=99999999, page=1, offset=1000, sort="desc") or []
        span = (int(d[0]["timeStamp"]) - int(d[-1]["timeStamp"])) / 3600 if len(d) > 1 else None
        return {"n": len(d), "more": len(d) >= 1000, "span_h": span}


def detect_evm_chain(wallets):
    """Chain EVM con actividad para más wallets (1 llamada barata por wallet y chain)."""
    from .evm import EvmClient, NoBackend
    best, best_n = "ethereum", -1
    for ch in ("ethereum", "base", "arbitrum", "polygon", "bsc"):
        try:
            cl = EvmClient(ch)
        except NoBackend:
            continue
        n = 0
        for w in wallets[:4]:
            try:
                if cl.call(module="account", action="txlist", address=w.lower(), startblock=0, endblock=99999999, page=1, offset=1, sort="desc"):
                    n += 1
            except Exception:
                pass
        if n > best_n:
            best, best_n = ch, n
    return best


def make_source(chain, C):
    return SolSource(C) if chain == "solana" else EvmSource(chain, C)


def clean_wallets(items, chain="auto"):
    """Valida la lista: 2..max_wallets, todas de la misma familia (Solana o EVM). Devuelve (chain, wallets)."""
    from .scan import parse_items, norm
    C = conf()
    ws = parse_items(items if isinstance(items, str) else " ".join(items or []))
    ws = list(dict.fromkeys(norm("x", w) for w in ws))
    if len(ws) < 2:
        raise ValueError("Pega al menos 2 wallets")
    if len(ws) > C["max_wallets"]:
        raise ValueError(f"Máximo {C['max_wallets']} wallets por comprobación")
    sol, evm = [w for w in ws if is_sol_address(w)], [w for w in ws if is_evm_address(w)]
    if sol and evm:
        raise ValueError("Mezclas wallets de Solana y EVM: compruébalas por separado")
    if chain in (None, "", "auto", "evm"):
        chain = "solana" if sol else "evm"
    elif chain not in CHAINS:
        raise ValueError("chain no válida")
    elif (chain == "solana") != bool(sol):
        raise ValueError("Las wallets no son de la chain elegida")
    return chain, ws


# ------------------------------------------------------------------ análisis
def _profile(chain, w, raw, nusd):
    P = {"address": w, "transfers": [], "buys": defaultdict(list), "fee_by": defaultdict(list), "n": 0, "truncated": bool(raw.get("truncated")),
         "oldest": None, "newest": None, "error": raw.get("error"), "db": False, "funder": None}
    seen, txs = set(), set()
    for d in raw.get("deltas") or []:
        if d.failed:
            continue
        txs.add(d.tx)
        if d.ts:
            P["oldest"] = min(P["oldest"] or d.ts, d.ts); P["newest"] = max(P["newest"] or 0, d.ts)
        sw, tr = extract(d, w, nusd)
        for s in sw:
            if s["side"] == "buy":
                P["buys"][s["token"]].append({"ts": s["ts"], "slot": s.get("slot"), "tx": s["tx"], "amt": s["native_amount"]})
        for t in tr:
            k = (t["tx"], t["counterparty"], t["asset"], t["direction"])
            if k not in seen and t["counterparty"]:
                seen.add(k)
                P["transfers"].append({"tx": t["tx"], "ts": t["ts"], "cp": t["counterparty"], "dir": t["direction"], "asset": t["asset"], "amount": t["amount"]})
        if chain == "solana" and d.fee_payer and d.fee_payer != w and w in d.signers:
            P["fee_by"][d.fee_payer].append({"tx": d.tx, "ts": d.ts})
    P["n"] = len(txs)
    P["_seen"] = seen
    return P


def _merge_db(c, chain, w, P):
    """Si la wallet ya está en la BD, se suman sus transferencias/compras guardadas (sin coste)."""
    if c is None:
        return
    r = c.execute("SELECT funder, funder_amount, funded_at FROM wallets WHERE chain=? AND address=?", (chain, w)).fetchone()
    if not r:
        return
    P["db"] = True
    if r["funder"]:
        P["db_funder"] = {"address": r["funder"], "amount": r["funder_amount"], "ts": r["funded_at"], "tx": None}
    for t in c.execute("SELECT tx, ts, counterparty, direction, asset, amount FROM transfers WHERE chain=? AND wallet=?", (chain, w)):
        k = (t["tx"], t["counterparty"], t["asset"], t["direction"])
        if t["counterparty"] and k not in P["_seen"]:
            P["_seen"].add(k)
            P["transfers"].append({"tx": t["tx"], "ts": t["ts"], "cp": t["counterparty"], "dir": t["direction"], "asset": t["asset"], "amount": t["amount"]})
    have = {x["tx"] for v in P["buys"].values() for x in v}
    for s in c.execute("SELECT token, ts, slot, tx, native_amount FROM swaps WHERE chain=? AND wallet=? AND side='buy'", (chain, w)):
        if s["tx"] not in have:
            P["buys"][s["token"]].append({"ts": s["ts"], "slot": s["slot"], "tx": s["tx"], "amt": s["native_amount"]})


def _token_info(c, chain, tokens):
    out = {}
    if not tokens:
        return out
    if c is not None:
        for t in tokens:
            r = c.execute("SELECT symbol, launch_ts FROM tokens WHERE chain=? AND address=?", (chain, t)).fetchone() or \
                c.execute("SELECT symbol, launch_ts FROM token_prices WHERE chain=? AND token=?", (chain, t)).fetchone()
            if r and (r["symbol"] or r["launch_ts"]):
                out[t] = {"sy": r["symbol"], "lt": r["launch_ts"]}
    miss = [t for t in tokens if t not in out or not out[t].get("lt")]
    if miss:
        try:
            from . import market
            info = market.dexscreener_tokens(chain, miss[:90])
            info.pop("_failed", None)
            for t in miss:
                d = info.get(t) or info.get(t.lower())
                if d:
                    out[t] = {"sy": d.get("symbol") or (out.get(t) or {}).get("sy"), "lt": d.get("launch_ts")}
        except Exception as e:
            log.debug("dexscreener tokens: %s", e)
    return out


def combine(ws):
    p = 1.0
    for w in ws:
        p *= 1 - max(0.0, min(95.0, w)) / 100
    return int(round(100 * (1 - p)))


def level(s):
    return ("Muy probablemente la misma persona o grupo" if s >= 75 else "Conexión fuerte" if s >= 50 else
            "Conexión posible" if s >= 25 else "Indicios débiles" if s > 0 else "Sin conexión encontrada")


def run(c, chain, wallets, progress=None, source=None, labeler=None, nusd=None):
    progress = progress or (lambda m: None)
    C = conf()
    t_start = time.time()
    if chain in ("auto", "evm", "", None):
        if all(is_sol_address(w) for w in wallets):
            chain = "solana"
        else:
            progress("detectando la chain EVM…")
            chain = detect_evm_chain(wallets)
    if chain != "solana":
        wallets = [w.lower() for w in wallets]
    src = source or make_source(chain, C)
    lab = labeler or Labeler()
    nat = CHAINS[chain]["native"]
    if nusd is None:
        try:
            from . import market
            nusd = market.native_usd(chain)
        except Exception:
            nusd = None
    inputs, n = list(dict.fromkeys(wallets)), len(wallets)
    I = set(inputs)
    idx = {w: i + 1 for i, w in enumerate(inputs)}
    infra = INFRA["solana"] if chain == "solana" else INFRA["evm"]
    min_nat = C["min_native"].get(chain, C["min_native"].get("default", 0.002))
    notes, credits0 = [], src.credits

    def name(a):
        return f"W{idx[a]}" if a in idx else short(a)

    # ---- 1) historial de cada wallet
    prof = {}
    for i, w in enumerate(inputs, 1):
        progress(f"leyendo historial {i}/{n}: {short(w)}")
        try:
            raw = src.profile(w)
        except Exception as e:
            log.warning("historial %s: %s", w[:6], e)
            raw = {"deltas": [], "truncated": False, "error": str(e)[:160]}
        P = _profile(chain, w, raw, nusd)
        _merge_db(c, chain, w, P)
        try:
            P["funder"] = src.funder(w) or P.get("db_funder")
        except Exception as e:
            log.debug("fondeador %s: %s", w[:6], e)
            P["funder"] = P.get("db_funder")
        prof[w] = P
        if P["truncated"]:
            notes.append(f"W{i} ({short(w)}): historial truncado; solo se leyeron sus últimas {C['max_txs_per_wallet']} transacciones (desde {fdate(P['oldest'])})"
                         + (f" y sus {C['first_txs']} primeras" if C["first_txs"] else "") + ".")
        if P["error"]:
            notes.append(f"W{i} ({short(w)}): no se pudo leer el historial ({P['error']}).")

    edges, ev_pairs = {}, defaultdict(list)

    def edge(u, v, typ, ev, label=None, directed=True):
        k = (u, v, typ) if directed else tuple(sorted((u, v))) + (typ,)
        e = edges.get(k)
        if e is None:
            e = edges[k] = {"id": f"e{len(edges) + 1}", "a": k[0], "b": k[1], "type": typ, "label": label or TYPE_LABEL[typ], "ev": [], "n": 0}
        if ev and not any(x.get("tx") == ev.get("tx") and x.get("note") == ev.get("note") for x in e["ev"]):
            e["n"] += 1
            if len(e["ev"]) < 25:
                e["ev"].append(ev)
        return e["id"]

    def asset_name(a, toks):
        return nat if a in ("native", None) else ((toks.get(a) or {}).get("sy") or short(a))

    # ---- 2) transferencias directas entre las wallets (y comisiones pagadas)
    direct = defaultdict(dict)    # par -> {(tx, from, to, asset): row}
    pair_checked, pair_capped = 0, []
    pairs = list(combinations(inputs, 2))
    for k, (a, b) in enumerate(pairs, 1):
        progress(f"transferencias directas {k}/{len(pairs)}")
        try:
            res = src.pair(a, b)
        except Exception as e:
            log.debug("pair: %s", e)
            res = None
        if res is None:
            break
        rows, more = res
        pair_checked += 1
        if more:
            pair_capped.append(f"W{idx[a]}–W{idx[b]}")
        for r in rows:
            if r["from"] in I and r["to"] in I:
                direct[(a, b)][(r["tx"], r["from"], r["to"], r["asset"])] = r
    for w, P in prof.items():
        for t in P["transfers"]:
            if t["cp"] in I and t["cp"] != w:
                fr, to = (w, t["cp"]) if t["dir"] == "out" else (t["cp"], w)
                key = tuple(sorted((w, t["cp"]), key=lambda x: idx[x]))
                direct[key].setdefault((t["tx"], fr, to, t["asset"]), {"tx": t["tx"], "ts": t["ts"], "from": fr, "to": to, "asset": t["asset"], "amount": t["amount"]})
    if pair_checked:
        notes.append(f"Transferencias directas: cada par se comprobó en todo su historial ({pair_checked} consultas a Helius getTransfersByAddress).")
    elif chain != "solana":
        notes.append("Transferencias directas: buscadas dentro del historial leído de cada wallet (Etherscan no permite filtrar por contraparte).")
    if pair_capped:
        notes.append(f"Más de {C['pair_pages'] * 100} transferencias directas en {', '.join(pair_capped)}: solo se miraron las más recientes.")
    all_tokens = set()
    for rows in direct.values():
        all_tokens |= {r["asset"] for r in rows.values() if r["asset"] != "native"}
    for w, P in prof.items():
        all_tokens |= set(P["buys"])
    shared_tokens = set()
    for a, b in pairs:
        shared_tokens |= set(prof[a]["buys"]) & set(prof[b]["buys"])
    progress("datos de las coins compartidas…")
    toks = _token_info(c, chain, sorted(shared_tokens | {t for rows in direct.values() for t in (r["asset"] for r in rows.values()) if t != "native"}))

    for (a, b), rows in direct.items():
        rows = sorted(rows.values(), key=lambda r: r["ts"] or 0)
        native_tot = sum(r["amount"] or 0 for r in rows if r["asset"] == "native")
        dirs = {(r["from"], r["to"]) for r in rows}
        eids = []
        for r in rows:
            eids.append(edge(r["from"], r["to"], "transfer", {"ts": r["ts"], "tx": r["tx"], "amt": r["amount"], "asset": asset_name(r["asset"], toks),
                                                             "note": f"{name(r['from'])} → {name(r['to'])}"}))
        w = 55 + (15 if len(rows) >= 3 or native_tot >= 1 else 0) + (10 if len(dirs) > 1 else 0)
        first = rows[0]
        what = f"{name(first['from'])} envió {famt(first['amount'])} {asset_name(first['asset'], toks)} a {name(first['to'])}"
        txt = (f"1 transferencia directa: el {fdate(first['ts'])} {what}" if len(rows) == 1 else
               f"{len(rows)} transferencias directas" + (f" ({famt(native_tot)} {nat} en total)" if native_tot else "") + (", en los dos sentidos" if len(dirs) > 1 else "")
               + f"; la primera el {fdate(first['ts'])}: {what}")
        ev_pairs[(a, b)].append({"type": "transfer", "w": min(w, 80), "text": txt, "edges": sorted(set(eids))})
    for w, P in prof.items():
        for payer, evs in P["fee_by"].items():
            if payer in I:
                key = tuple(sorted((w, payer), key=lambda x: idx[x]))
                eid = None
                for e in evs[:25]:
                    eid = edge(payer, w, "fee", {"ts": e["ts"], "tx": e["tx"], "note": f"{name(payer)} pagó la comisión de una tx firmada por {name(w)}"})
                ev_pairs[key].append({"type": "fee", "w": 75, "text": f"{name(payer)} pagó las comisiones de {len(evs)} transacción{'es' if len(evs) > 1 else ''} firmada{'s' if len(evs) > 1 else ''} por {name(w)}", "edges": [eid]})

    # ---- 3) flujos con intermediarios (fondeo, envíos, comisiones) y exchanges
    flows = defaultdict(list)        # (origen, destino) -> evidencias (solo nativo ≥ mínimo)
    first_f = {}                     # wallet -> su primer fondeador
    fees = defaultdict(list)         # (pagador, wallet)
    cex_in = defaultdict(list)       # wallet -> [{name, address, ts, amount, tx, hops}]
    labels = {}

    def lab_of(a):
        if a not in labels:
            labels[a] = lab.label(chain, a)
        return labels[a]

    def is_cex(a):
        l = lab_of(a)
        return bool(l and l.get("kind") == "cex")

    for w, P in prof.items():
        for t in P["transfers"]:
            cp = t["cp"]
            if cp in I or cp in infra or t["asset"] != "native" or (t["amount"] or 0) < min_nat:
                continue
            ev = {"ts": t["ts"], "tx": t["tx"], "amt": t["amount"], "asset": nat}
            if is_cex(cp):
                if t["dir"] == "in":
                    cex_in[w].append({"name": lab_of(cp)["name"], "address": cp, "ts": t["ts"], "amount": t["amount"], "tx": t["tx"], "hops": 1})
                continue
            if t["dir"] == "in":
                flows[(cp, w)].append(ev)
            else:
                flows[(w, cp)].append(ev)
        F = P["funder"]
        if F and F.get("address") and F["address"] not in infra:
            fa = F["address"]
            if is_cex(fa):
                cex_in[w].append({"name": lab_of(fa)["name"], "address": fa, "ts": F.get("ts"), "amount": F.get("amount"), "tx": F.get("tx"), "hops": 1, "first": True})
            elif fa not in I:
                first_f[w] = fa
                ev = {"ts": F.get("ts"), "tx": F.get("tx"), "amt": F.get("amount"), "asset": nat, "note": "primer fondeo"}
                if not any(x.get("tx") == ev["tx"] and ev["tx"] for x in flows[(fa, w)]):
                    flows[(fa, w)].append(ev)
        for payer, evs in P["fee_by"].items():
            if payer not in I and payer not in infra and not is_cex(payer):
                fees[(payer, w)] += evs

    # ---- 4) 2 saltos: fondeador de los intermediarios más relevantes
    cands = []
    for w, P in prof.items():
        tot = defaultdict(float)
        for (s, d), evs in flows.items():
            if d == w and s not in I:
                tot[s] += sum(e["amt"] or 0 for e in evs)
        top = sorted(tot, key=lambda x: -tot[x])
        mine = ([first_f[w]] if w in first_f else []) + top
        cands += [x for x in dict.fromkeys(mine)][:C["max_counterparties"]]
    shared = defaultdict(set)
    for (s, d) in list(flows) + list(fees):
        if s in I and d not in I:
            shared[d].add(s)
        elif d in I and s not in I:
            shared[s].add(d)
    cands = list(dict.fromkeys([x for x in shared if len(shared[x]) >= 2] + cands))
    possible = len(cands)
    cands = cands[:C["max_hop_lookups"]]
    if possible > len(cands):
        notes.append(f"2 saltos: se miró el fondeador de {len(cands)} intermediarios de {possible} posibles (límite para ahorrar créditos).")
    hop_of = {}
    for k, x in enumerate(cands, 1):
        progress(f"2 saltos: fondeador de intermediarios {k}/{len(cands)}")
        try:
            f = src.funder(x)
        except Exception as e:
            log.debug("funder 2 saltos: %s", e)
            f = None
        if not f or not f.get("address") or f["address"] == x or f["address"] in infra:
            continue
        hop_of[x] = f
        fa = f["address"]
        if is_cex(fa):
            for d in [d for d in inputs if first_f.get(d) == x]:     # solo por el primer fondeador de la wallet
                cex_in[d].append({"name": lab_of(fa)["name"], "address": fa, "ts": f.get("ts"), "amount": f.get("amount"), "tx": f.get("tx"), "hops": 2, "via": x})
            continue
        ev = {"ts": f.get("ts"), "tx": f.get("tx"), "amt": f.get("amount"), "asset": nat, "note": "primer fondeo"}
        if not any(e.get("tx") == ev["tx"] and ev["tx"] for e in flows[(fa, x)]):
            flows[(fa, x)].append(ev)

    # ---- 5) grafo no dirigido entre intermediarios y distancias (≤ 2) a cada wallet
    adj = defaultdict(set)
    for (s, d) in list(flows) + list(fees):
        if s != d:
            adj[s].add(d); adj[d].add(s)
    dist = defaultdict(dict)     # nodo -> {wallet: (dist, intermedio)}
    for w in inputs:
        for x in adj[w]:
            if x in I:
                continue
            dist[x][w] = (1, None)
        for x in list(adj[w]):
            if x in I:
                continue
            for y in adj[x]:
                if y in I or y == w:
                    continue
                if w not in dist[y] or dist[y][w][0] > 2:
                    dist[y][w] = (2, x)
    bridges = {x: d for x, d in dist.items() if len(d) >= 2}
    # ¿servicio/hub? (mucha actividad) para los puentes más importantes
    act = {}
    order = sorted(bridges, key=lambda x: (-len(bridges[x]), sum(v[0] for v in bridges[x].values())))
    for k, x in enumerate(order[:C["max_bridges_checked"]], 1):
        progress(f"revisando puentes {k}/{min(len(order), C['max_bridges_checked'])}")
        try:
            act[x] = src.activity(x)
        except Exception as e:
            log.debug("actividad: %s", e)
    if len(order) > C["max_bridges_checked"]:
        notes.append(f"Se revisó la actividad (¿servicio/hub?) de {C['max_bridges_checked']} puentes de {len(order)}.")

    def is_hub(x):
        a = act.get(x)
        return bool(a and a["n"] >= C["hub_min_txs"] and a.get("span_h") is not None and a["span_h"] <= C["hub_hours"])

    def flow_edge(s, d):
        typ = "first" if (d in first_f and first_f[d] == s) or (d in hop_of and hop_of[d]["address"] == s) else "fund"
        if d in hop_of and hop_of[d]["address"] == s and d not in I:
            typ = "hop"
        eid = None
        for ev in flows[(s, d)][:25] or [None]:
            eid = edge(s, d, typ, ev)
        return eid

    def link_edges(x, w):
        """Aristas del camino x … w (1 o 2 saltos)."""
        d, mid = bridges[x][w] if x in bridges else dist[x][w]
        out = []
        hops = [(x, w)] if d == 1 else [(x, mid), (mid, w)]
        for u, v in hops:
            if (u, v) in flows:
                out.append(flow_edge(u, v))
            if (v, u) in flows:
                out.append(flow_edge(v, u))
            if (u, v) in fees:
                for e in fees[(u, v)][:25]:
                    out.append(edge(u, v, "fee", {"ts": e["ts"], "tx": e["tx"], "note": f"{name(u)} pagó la comisión"}))
            if (v, u) in fees:
                for e in fees[(v, u)][:25]:
                    out.append(edge(v, u, "fee", {"ts": e["ts"], "tx": e["tx"], "note": f"{name(v)} pagó la comisión"}))
        return [e for e in out if e]

    used_nodes = set()
    for x, dd in bridges.items():
        hub = is_hub(x)
        for a, b in combinations(sorted(dd, key=lambda w: idx[w]), 2):
            (da, ma), (db, mb) = dd[a], dd[b]
            if (ma and ma == mb) or any(m and is_hub(m) for m in (ma, mb)):
                continue        # mismo intermediario (ya es puente él) o camino a través de un servicio/hub: no aporta
            nm = short(x)
            if da == 1 and db == 1:
                fa, fb = first_f.get(a) == x, first_f.get(b) == x
                ina, inb, outa, outb = (x, a) in flows, (x, b) in flows, (a, x) in flows, (b, x) in flows
                fea, feb = (x, a) in fees, (x, b) in fees
                if fa and fb:
                    w, txt = 60, f"mismo fondeador: {nm} hizo el primer fondeo de las dos"
                elif fea and feb:
                    w, txt = 50, f"{nm} pagó comisiones de las dos"
                elif (outa and inb) or (outb and ina):
                    s, t = (a, b) if outa and inb else (b, a)
                    w, txt = 45, f"flujo {name(s)} → {nm} → {name(t)}"
                elif ina and inb:
                    w, txt = 40 if (fa or fb) else 35, f"las dos recibieron {nat} de {nm}" + (" (para una fue su primer fondeo)" if fa or fb else "")
                elif outa and outb:
                    w, txt = 30, f"las dos enviaron {nat} a {nm}"
                else:
                    w, txt = 25, f"las dos tienen movimientos con {nm}"
            elif min(da, db) == 1:
                near, far = (a, b) if da == 1 else (b, a)
                mid = (mb if da == 1 else ma)
                w, txt = 28, f"a 2 saltos: {nm} conecta con {name(near)} directamente y con {name(far)} a través de {short(mid)}"
                if (x, mid) in flows and (mid, far) in flows and (x, near) in flows:
                    w, txt = 32, f"fondeador común a 2 saltos: {nm} fondeó a {name(near)} y a {short(mid)}, que fondeó a {name(far)}"
            else:
                w, txt = 25, f"fondeador común a 2 saltos: {nm} (vía {short(ma)} y {short(mb)})"
            if hub:
                w, txt = round(w * 0.25), txt + " — ojo: es un servicio/hub con mucha actividad"
            used_nodes.add(x)
            eids = link_edges(x, a) + link_edges(x, b)
            for p in (ma, mb):
                if p:
                    used_nodes.add(p)
            ev_pairs[(a, b)].append({"type": "bridge", "w": w, "text": txt, "edges": sorted(set(eids)), "node": x})

    # ---- 6) mismo exchange
    for a, b in pairs:
        A, B = cex_in.get(a, []), cex_in.get(b, [])
        for nm_ in sorted({x["name"] for x in A} & {x["name"] for x in B}):
            xa, xb = [x for x in A if x["name"] == nm_], [x for x in B if x["name"] == nm_]
            best = None
            for p in xa:
                for q in xb:
                    if p["hops"] == 1 and q["hops"] == 1 and p["tx"] != q["tx"] and p["ts"] and q["ts"] and abs(p["ts"] - q["ts"]) <= C["cex_time_window_min"] * 60 and p["amount"] and q["amount"] \
                            and abs(p["amount"] - q["amount"]) / max(p["amount"], q["amount"]) <= C["cex_amount_tolerance"]:
                        if best is None or abs(p["ts"] - q["ts"]) < abs(best[0]["ts"] - best[1]["ts"]):
                            best = (p, q)
            cid = "cex:" + nm_
            eids = []
            for x, w_ in [(x, a) for x in xa] + [(x, b) for x in xb]:
                eids.append(edge(cid, w_, "cex", {"ts": x["ts"], "tx": x["tx"], "amt": x["amount"], "asset": nat,
                                                  "note": f"desde {nm_} ({short(x['address'])})" + (" · a 2 saltos vía " + short(x["via"]) if x.get("via") else "") + (" · primer fondeo" if x.get("first") else "")}, label=f"fondos desde {nm_}"))
            if best:
                p, q = best
                ev_pairs[(a, b)].append({"type": "cex", "w": 35, "edges": sorted(set(eids)),
                                         "text": f"retiradas de {nm_} con {fdur(p['ts'] - q['ts'])} de diferencia e importes parecidos ({famt(p['amount'])} y {famt(q['amount'])} {nat})"})
            elif any(x["hops"] == 1 for x in xa) and any(x["hops"] == 1 for x in xb):
                ev_pairs[(a, b)].append({"type": "cex", "w": 12, "edges": sorted(set(eids)), "text": f"las dos recibieron fondos de {nm_} (exchange muy usado: indicio débil)"})
            elif not any(p.get("via") and p.get("via") == q.get("via") for p in xa for q in xb):   # mismo intermediario = ya es un puente
                ev_pairs[(a, b)].append({"type": "cex", "w": 6, "edges": sorted(set(eids)), "text": f"fondos de {nm_} a 1-2 saltos en las dos (indicio muy débil)"})

    # ---- 7) compras de las mismas coins (mismo slot/bloque o casi a la vez)
    unit = "slot" if chain == "solana" else "bloque"
    for a, b in pairs:
        same, co = [], []
        for t in sorted(set(prof[a]["buys"]) & set(prof[b]["buys"])):
            ba, bb = prof[a]["buys"][t], prof[b]["buys"][t]
            sa = {x["slot"]: x for x in ba if x["slot"] is not None}
            hit = next(((sa[x["slot"]], x) for x in bb if x["slot"] is not None and x["slot"] in sa), None)
            sy = (toks.get(t) or {}).get("sy") or short(t)
            if hit:
                same.append((t, sy, hit))
                continue
            fa, fb = min(ba, key=lambda x: x["ts"] or 0), min(bb, key=lambda x: x["ts"] or 0)
            if fa["ts"] and fb["ts"] and abs(fa["ts"] - fb["ts"]) <= C["cobuy_window_s"]:
                lt = (toks.get(t) or {}).get("lt")
                early = bool(lt and max(fa["ts"], fb["ts"]) - lt <= C["early_window_s"] and min(fa["ts"], fb["ts"]) >= lt - 600)
                co.append((t, sy, fa, fb, early))
        for k, (t, sy, (x, y)) in enumerate(same):
            eid = edge(a, b, "slot", {"ts": x["ts"], "tx": x["tx"], "tx2": y["tx"], "asset": sy, "amt": x["amt"], "amt2": y["amt"],
                                      "note": f"{name(a)} y {name(b)} compraron {sy} en el mismo {unit} ({x['slot']})"}, directed=False)
            if k < 4:
                ev_pairs[(a, b)].append({"type": "slot", "w": 45 if k == 0 else 20, "edges": [eid],
                                         "text": f"compraron {sy} en el mismo {unit} ({x['slot']}, {fdate(x['ts'])})"})
        for k, (t, sy, x, y, early) in enumerate(co):
            eid = edge(a, b, "cobuy", {"ts": x["ts"], "tx": x["tx"], "tx2": y["tx"], "asset": sy, "amt": x["amt"], "amt2": y["amt"],
                                       "note": f"{sy}: compras con {fdur(x['ts'] - y['ts'])} de diferencia" + (" · en la primera hora del lanzamiento" if early else "")}, directed=False)
            if k < 4:
                ev_pairs[(a, b)].append({"type": "cobuy", "w": 18 if early else 12, "edges": [eid],
                                         "text": f"compraron {sy} con {fdur(x['ts'] - y['ts'])} de diferencia" + (" (compra temprana)" if early else "")})
        if len(co) > 4:
            ev_pairs[(a, b)].append({"type": "cobuy", "w": 0, "edges": [], "text": f"y {len(co) - 4} coins más compradas casi a la vez"})

    # ---- 8) pares, puentes y wallets madre
    out_pairs = []
    for a, b in pairs:
        evs = sorted(ev_pairs.get((a, b), []), key=lambda e: -e["w"])
        # varios puentes del mismo tipo: se suman con rendimientos decrecientes
        ws, nb = [], 0
        for e in evs:
            if e["type"] == "bridge":
                nb += 1
                ws.append(e["w"] if nb <= 2 else e["w"] * 0.3)
            else:
                ws.append(e["w"])
        s = combine(ws)
        top = ([e["text"] for e in evs if e["w"] >= 10] or [e["text"] for e in evs if e["w"] > 0])[:3]
        reason = level(s) + (": " + "; ".join(top) + "." if top else ". No hay transferencias, fondeadores ni compras en común en lo leído.")
        out_pairs.append({"a": a, "b": b, "score": s, "level": level(s), "reason": reason[0].upper() + reason[1:], "ev": evs})
    out_pairs.sort(key=lambda p: -p["score"])

    sends = defaultdict(set)     # quién envió dinero (o pagó comisiones) a qué wallets
    for (s, d) in list(flows) + list(fees):
        if d in I:
            sends[s].add(d)
    for (a, b), rows in direct.items():
        for r in rows.values():
            sends[r["from"]].add(r["to"])
    out_bridges = []
    for x in sorted(used_nodes & set(bridges), key=lambda x: (-len(bridges[x]), x)):
        if not any(e.get("node") == x for evs in ev_pairs.values() for e in evs):
            continue
        conn = sorted(bridges[x], key=lambda w: idx[w])
        hub = is_hub(x)
        direct_to = sorted(sends[x] & I, key=lambda w: idx[w])
        hop_to = sorted([w for w in conn if bridges[x][w][0] == 2 and (x, bridges[x][w][1]) in flows], key=lambda w: idx[w])
        recv = sorted([w for w in conn if (w, x) in flows], key=lambda w: idx[w])
        role = []
        if direct_to:
            role.append("envió fondos a " + ", ".join(name(w) for w in direct_to))
        if hop_to:
            role.append("fondeó a 2 saltos a " + ", ".join(name(w) for w in hop_to))
        if recv:
            role.append("recibió fondos de " + ", ".join(name(w) for w in recv))
        a = act.get(x)
        funded = set(direct_to) | set(hop_to)
        out_bridges.append({"address": x, "connects": conn, "madre": not hub and len(funded) >= 2, "hub": hub, "role": "; ".join(role) or "movimientos con " + ", ".join(name(w) for w in conn),
                            "txs": a["n"] if a else None, "txs_more": a.get("more") if a else None, "span_h": round(a["span_h"], 1) if a and a.get("span_h") is not None else None,
                            "label": (lab_of(x) or {}).get("name")})
    nat_to = defaultdict(set)     # wallet madre entre las propias wallets: envió SOL/nativo (≥ mínimo) o fue el primer fondeo de ≥ 2
    for (a, b), rows in direct.items():
        for r in rows.values():
            if r["asset"] == "native" and (r["amount"] or 0) >= min_nat:
                nat_to[r["from"]].add(r["to"])
    for w, f in first_f.items():
        if f in I:
            nat_to[f].add(w)
    madre_inputs = {w: sorted(nat_to[w] & I - {w}, key=lambda v: idx[v]) for w in inputs if len(nat_to[w] & I - {w}) >= 2}

    # nodos del grafo
    nodes = []
    for w in inputs:
        P = prof[w]
        nodes.append({"id": w, "kind": "input", "i": idx[w], "label": f"W{idx[w]}", "madre": w in madre_inputs,
                      "role": ("envió fondos a " + ", ".join(name(v) for v in madre_inputs[w])) if w in madre_inputs else None})
    keep = set(inputs) | {b["address"] for b in out_bridges}
    for e in edges.values():
        keep.add(e["a"]); keep.add(e["b"])
    for b in out_bridges:
        nodes.append({"id": b["address"], "kind": "bridge", "label": short(b["address"]), "madre": b["madre"], "hub": b["hub"], "role": b["role"]})
    have = {n_["id"] for n_ in nodes}
    for x in sorted(keep - have):
        if x.startswith("cex:"):
            nodes.append({"id": x, "kind": "cex", "label": x[4:]})
        else:
            nodes.append({"id": x, "kind": "hop", "label": short(x)})
    if len(nodes) > C["max_nodes"]:
        notes.append(f"El grafo muestra {C['max_nodes']} nodos de {len(nodes)}.")
        allowed = {n_["id"] for n_ in nodes[:C["max_nodes"]]}
        nodes = nodes[:C["max_nodes"]]
        edges = {k: e for k, e in edges.items() if e["a"] in allowed and e["b"] in allowed}

    info = {}
    for w in inputs:
        P = prof[w]
        info[w] = {"i": idx[w], "n": P["n"], "truncated": P["truncated"], "oldest": P["oldest"], "newest": P["newest"], "error": P["error"], "db": P["db"],
                   "funder": P["funder"], "funder_label": (lab_of(P["funder"]["address"]) or {}).get("name") if P["funder"] else None,
                   "buys": len(P["buys"]), "transfers": len(P["transfers"])}
    used = src.credits - credits0
    conn = [p for p in out_pairs if p["score"] >= 25]
    best = out_pairs[0] if out_pairs else None
    summary = (f"{len(conn)} de {len(out_pairs)} pares conectados (score ≥ 25)" + (f"; el más fuerte: W{idx[best['a']]}–W{idx[best['b']]} con {best['score']}/100" if best and best["score"] else "")
               + (f"; {nm_} posible{'s' if nm_ > 1 else ''} wallet{'s' if nm_ > 1 else ''} madre" if (nm_ := sum(1 for b in out_bridges if b['madre']) + len(madre_inputs)) else ""))
    return {"version": 1, "chain": chain, "created": int(time.time()), "wallets": inputs, "nodes": nodes, "edges": list(edges.values()),
            "pairs": out_pairs, "bridges": out_bridges, "madre_inputs": madre_inputs, "info": info, "notes": notes, "summary": summary,
            "credits": used, "unit": src.unit, "labels": lab.names(), "seconds": round(time.time() - t_start, 1),
            "limits": {k: C[k] for k in ("max_txs_per_wallet", "first_txs", "max_counterparties", "max_hop_lookups", "max_bridges_checked", "cobuy_window_s")}}


# ------------------------------------------------------------------ guardado (privado: lo sirve el box con PIN)
def save(c, cid, chain, wallets, status, result=None, error=None):
    c.execute("""INSERT INTO checks(id,created,chain,wallets,status,result,credits,summary,max_score,error) VALUES(?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(id) DO UPDATE SET chain=excluded.chain, status=excluded.status, result=excluded.result, credits=excluded.credits,
                 summary=excluded.summary, max_score=excluded.max_score, error=excluded.error""",
              (cid, int(time.time()), chain, json.dumps(wallets), status, json.dumps(result, separators=(",", ":")) if result else None,
               (result or {}).get("credits"), (result or {}).get("summary"), max([p["score"] for p in (result or {}).get("pairs") or []] or [None]), error))
    c.commit()


def list_checks(c, limit=100):
    out = []
    for r in c.execute("""SELECT j.id, j.created, j.chain, j.items, j.status jstatus, j.progress, k.status, k.summary, k.max_score, k.credits, k.chain kchain, k.error
                          FROM jobs j LEFT JOIN checks k ON k.id=j.id WHERE j.kind='connect' ORDER BY j.created DESC LIMIT ?""", (limit,)):
        out.append({"id": r["id"], "created": r["created"], "chain": r["kchain"] or r["chain"], "wallets": json.loads(r["items"] or "[]"), "status": r["jstatus"],
                    "progress": r["progress"], "summary": r["summary"], "max_score": r["max_score"], "credits": r["credits"], "error": r["error"]})
    return out


def get_check(c, cid):
    r = c.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone()
    if not r or not r["result"]:
        return None
    d = json.loads(r["result"])
    d["id"] = cid
    return d


def delete_check(c, cid):
    c.execute("DELETE FROM checks WHERE id=?", (cid,))
    c.execute("DELETE FROM jobs WHERE id=? AND kind='connect'", (cid,))
    c.commit()


def run_job(c, job, prog):
    items = json.loads(job["items"])
    res = run(c, job["chain"], items, progress=prog)
    res["id"] = job["id"]
    save(c, job["id"], res["chain"], items, "done", res)
    best = res["pairs"][0]["score"] if res["pairs"] else 0
    return f"{len(items)} wallets ({CHAINS[res['chain']]['name']}): {res['summary'] or 'sin conexiones'} · máx. {best}/100 · {res['credits']} {res['unit']}"
