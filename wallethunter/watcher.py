"""Vigilancia de tus ⭐ en el box (un solo vigilante, hilo propio; todo con topes para no gastar créditos):
 1) Entradas grandes de dinero (alerts.enabled, cada poll_minutes) — apagado por defecto.
 2) Wallets dormidas: días sin tradear de cada ⭐; aviso al pasar dormant_days (una vez por racha) — dormant_alert.
 3) Fondeadores (wallet madre) de tus ⭐ (funder_watch, apagado por defecto): si un fondeador envía ≥ X nativo a una
    wallet NUEVA (≤ funder_new_max_txs tx), aviso con enlaces y botón para añadirla a Mis wallets.
Coste (Solana): 1 crédito por wallet y pasada (getSignaturesForAddress) + 10 si hay actividad nueva (getTransactionsForAddress
o getTransfersByAddress) + 1 por cada receptor candidato. EVM: llamadas a Etherscan (gratis, con límite de ritmo)."""
import html, json, logging, threading, time
from datetime import datetime
from zoneinfo import ZoneInfo
from . import db, cex, market, telegram
from .config import cfg
from .chains import CHAINS
from .deltas import extract

log = logging.getLogger("wh")
NATIVE_SOL = "So11111111111111111111111111111111111111111"
PANEL = "https://trendtiktokradar.github.io/wallet-hunter/"
TZ = ZoneInfo("Europe/Madrid")
DEFAULTS = {"dormant_days": 7, "dormant_alert": True, "dormant_poll_minutes": 60,
            "funder_watch": False, "funder_poll_minutes": 15, "funder_new_max_txs": 5, "funder_max": 20, "funder_max_alerts_per_pass": 5,
            "funder_min_native": {"solana": 1.0, "ethereum": 0.05, "bsc": 0.2, "base": 0.05, "arbitrum": 0.05, "polygon": 100, "robinhood": 0.05},
            "max_favorites": 60}
WAKE = threading.Event()


def settings():
    a = dict(DEFAULTS)
    user = cfg()["alerts"]
    a.update(user)
    a["funder_min_native"] = dict(DEFAULTS["funder_min_native"], **(user.get("funder_min_native") or {}))
    return a


def short(a):
    return a[:4] + "…" + a[-4:] if a else "?"


def fdate(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d/%m %H:%M") if ts else "?"


def targets(c):
    a = settings()
    rows = [(r["chain"], r["address"], r["alias"]) for r in c.execute("SELECT f.chain, f.address, COALESCE(a.alias, f.alias) alias FROM favorites f LEFT JOIN aliases a ON a.chain=f.chain AND a.address=f.address ORDER BY f.added")]
    if a.get("watch") == "favorites+smart":
        for r in c.execute("SELECT w.chain, w.address, a.alias FROM wallets w LEFT JOIN aliases a ON a.chain=w.chain AND a.address=w.address WHERE w.tags LIKE '%\"smart\"%'"):
            rows.append((r["chain"], r["address"], r["alias"]))
    return list(dict.fromkeys(rows))[:a["max_favorites"]]


def sender_label(c, chain, s):
    lab = cex.label(chain, s)
    if lab:
        return f"CEX {lab}"
    n = c.execute("SELECT COUNT(*) FROM wallets WHERE chain=? AND funder=?", (chain, s)).fetchone()[0]
    if n >= 2:
        return f"fondeador de {n} wallets"
    if c.execute("SELECT 1 FROM wallets WHERE chain=? AND address=?", (chain, s)).fetchone():
        return "wallet de la base"
    return None


def prov(providers, chain):
    if chain not in providers:
        from .scan import provider
        providers[chain] = provider(chain)
    return providers[chain]


def _h(x):
    return html.escape(str(x), quote=False)


def add_alert(c, kind, ts, chain, wallet, key, amount=None, usd=None, sender=None, label=None, data=None, msg=None):
    """Guarda la alerta (clave única = no se repite) y la manda a Telegram. Devuelve True si es nueva."""
    try:
        c.execute("INSERT INTO alerts(ts,chain,wallet,amount_native,amount_usd,sender,sender_label,tx,kind,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (ts, chain, wallet, amount, usd, sender, label, key, kind, json.dumps(data or {})))
    except Exception:
        return False   # ya avisada
    ok = telegram.send(msg) if msg else False
    c.execute("UPDATE alerts SET sent=? WHERE tx=?", (1 if ok else 0, key))
    c.commit()
    return True


# ------------------------------------------------------------------ ⭐: actividad nueva (entradas grandes + último trade)
def fetch_new(p, chain, w, last):
    """Transacciones nuevas desde `last` -> (deltas, ts más nuevo)."""
    if chain == "solana":
        sigs = [s for s in p.signatures(w, limit=50) if (s.get("blockTime") or 0) > last]
        if not sigs:
            return [], last
        newest = max(s["blockTime"] for s in sigs)
        ok = [s for s in sigs if s.get("err") is None]
        if not ok:
            return [], newest
        if p.gtfa_available():
            from .deltas import from_rpc
            r = p.gtfa(w, order="desc", limit=min(100, len(ok) + 5), filters={"status": "succeeded", "tokenAccounts": "balanceChanged", "blockTime": {"gt": last}})
            deltas = [from_rpc(t) for t in r.get("data") or []]
        else:
            deltas = p.parse_sigs([s["signature"] for s in ok][:100])
        return [d for d in deltas if d.ts and d.ts > last], newest
    txs = p.call(module="account", action="txlist", address=w, page=1, offset=25, sort="desc") or []
    internal = p.call(module="account", action="txlistinternal", address=w, page=1, offset=25, sort="desc") or []
    deltas = [d for d in p.build_deltas(w.lower(), txs, [], internal) if d.ts > last]
    return deltas, max([last] + [d.ts for d in deltas])


def initial_last_trade(c, p, chain, w):
    """Primera vez que se vigila una ⭐: su último trade real (las últimas 100 tx; 10 créditos en Solana)."""
    try:
        if chain == "solana" and p.gtfa_available():
            from .deltas import from_rpc
            r = p.gtfa(w, order="desc", limit=100, filters={"status": "succeeded", "tokenAccounts": "balanceChanged"})
            deltas = [from_rpc(t) for t in r.get("data") or []]
        elif chain != "solana":
            deltas = p.build_deltas(w.lower(), p.call(module="account", action="txlist", address=w, page=1, offset=50, sort="desc") or [], [], [])
        else:
            return None
    except Exception as e:
        log.info("último trade %s: %s", short(w), e)
        return None
    ts = [d.ts for d in deltas if d.ts and extract(d, w)[0]]
    return max(ts) if ts else None


def last_trade(c, chain, w):
    v = db.kv_get(c, f"lasttrade:{chain}:{w}")
    r = c.execute("SELECT MAX(ts) FROM swaps WHERE chain=? AND wallet=?", (chain, w)).fetchone()[0]
    xs = [x for x in (v, r) if x]
    return max(xs) if xs else None


def inflow_alerts(c, chain, w, alias, d, transfers, nusd, a):
    n = 0
    thr_native = (a.get("min_inflow_native") or {}).get(chain)
    for t in transfers:
        if t["direction"] != "in" or t["asset"] != "native":
            continue
        amt = t["amount_native"] or 0
        usd = amt * nusd
        if usd < float(a.get("min_inflow_usd") or 0) and not (thr_native and amt >= thr_native):
            continue
        lab = sender_label(c, chain, t["counterparty"])
        if a.get("only_from_funder_or_cex") and not lab:
            continue
        nat = CHAINS[chain]["native"]
        msg = (f"🚨 <b>Entrada grande</b> en {_h(alias or short(w))} ({CHAINS[chain]['name']})\n"
               f"{amt:,.2f} {nat} (~{usd:,.0f} $) desde {short(t['counterparty'])}{' · ' + lab if lab else ''}\n{CHAINS[chain]['tx']}{d.tx}")
        n += add_alert(c, "inflow", d.ts, chain, w, d.tx, amt, usd, t["counterparty"], lab, {"alias": alias}, msg)
    return n


def poll_favorites(c, providers, now, inflow=True):
    a = settings()
    sent = 0
    for chain, w, alias in targets(c):
        key = f"watch:{chain}:{w}"
        last = db.kv_get(c, key)
        try:
            p = prov(providers, chain)
            if last is None:   # primera vez: no avisar de lo antiguo; sí averiguar su último trade real
                lt = initial_last_trade(c, p, chain, w)
                if lt:
                    db.kv_set(c, f"lasttrade:{chain}:{w}", lt)
                db.kv_set(c, key, now)
                continue
            deltas, newest = fetch_new(p, chain, w, last)
        except Exception as e:
            log.warning("vigilancia %s: %s", short(w), e)
            continue
        nusd = market.native_usd(chain)
        lt = None
        for d in deltas:
            swaps, transfers = extract(d, w, nusd)
            if swaps:
                lt = max(lt or 0, d.ts)
            if inflow:
                sent += inflow_alerts(c, chain, w, alias, d, transfers, nusd, a)
        if lt:
            db.kv_set(c, f"lasttrade:{chain}:{w}", max(lt, db.kv_get(c, f"lasttrade:{chain}:{w}") or 0))
        db.kv_set(c, key, max(newest, last))
    c.commit()
    return sent


def check_dormant(c, now):
    a = settings()
    if not a.get("dormant_alert"):
        return 0
    thr, sent = float(a["dormant_days"]) * 86400, 0
    for chain, w, alias in targets(c):
        if db.kv_get(c, f"watch:{chain}:{w}") is None:
            continue   # aún sin leer su actividad reciente: el último trade guardado podría estar desfasado
        lt = last_trade(c, chain, w)
        if not lt or now - lt < thr or db.kv_get(c, f"dormant:{chain}:{w}") == lt:
            continue
        db.kv_set(c, f"dormant:{chain}:{w}", lt)   # una vez por racha: si vuelve a tradear, lt cambia
        days = int((now - lt) // 86400)
        g = CHAINS[chain].get("gmgn")
        msg = (f"💤 <b>Wallet dormida</b>: {_h(alias or short(w))} ({CHAINS[chain]['name']}) lleva <b>{days} días</b> sin tradear "
               f"(último trade {fdate(lt)}; umbral {a['dormant_days']} d)\n{CHAINS[chain]['explorer']}{w}" + (f"\nhttps://gmgn.ai/{g}/address/{w}" if g else ""))
        sent += add_alert(c, "dormant", now, chain, w, f"dormant:{chain}:{w}:{lt}", data={"days": days, "last_trade": lt, "alias": alias}, msg=msg)
    return sent


# ------------------------------------------------------------------ fondeadores (wallet madre) de las ⭐
def fav_funders(c, providers=None, lookup=True):
    """Guarda los fondeadores de cada ⭐ (tabla fav_funders). Si no se conoce, lo busca una vez (Solana: 10 créditos)."""
    providers = providers if providers is not None else {}
    for chain, w, alias in targets(c):
        found = set()
        r = c.execute("SELECT funder, funder_label FROM wallets WHERE chain=? AND address=? AND funder IS NOT NULL", (chain, w)).fetchone()
        if r:
            found.add((r[0], r[1], "escaneo"))
        for r in c.execute("SELECT funder, funder_label FROM funders WHERE chain=? AND address=? AND funder IS NOT NULL", (chain, w)):
            found.add((r[0], r[1], "fondeo"))
        if not found and lookup and db.kv_get(c, f"funderlookup:{chain}:{w}") is None \
                and not c.execute("SELECT 1 FROM fav_funders WHERE chain=? AND wallet=?", (chain, w)).fetchone():
            db.kv_set(c, f"funderlookup:{chain}:{w}", int(time.time()))
            try:
                from .connect import make_source, conf
                key = "src:" + chain
                if key not in providers:
                    providers[key] = make_source(chain, conf())
                f = providers[key].funder(w)
                if f and f.get("address"):
                    found.add((f["address"], None, "búsqueda"))
            except Exception as e:
                log.info("fondeador de %s: %s", short(w), e)
        for f, lab, src in found:
            c.execute("INSERT OR IGNORE INTO fav_funders(chain, wallet, funder, label, source, ts) VALUES(?,?,?,?,?,?)",
                      (chain, w, f, lab or (cex.label(chain, f) and "CEX " + cex.label(chain, f)), src, int(time.time())))
    c.commit()


def funder_list(c):
    """Fondeadores de tus ⭐ con sus «hijas» y si se vigilan (los exchanges no: fondean a miles de wallets)."""
    favs = {(ch, w): al for ch, w, al in targets(c)}
    out = {}
    for r in c.execute("SELECT chain, wallet, funder, label, source FROM fav_funders ORDER BY ts"):
        if (r["chain"], r["wallet"]) not in favs:
            continue
        k = (r["chain"], r["funder"])
        f = out.setdefault(k, {"chain": r["chain"], "address": r["funder"], "label": r["label"], "children": [], "watch": True, "why": None})
        f["children"].append(r["wallet"])
        lab = cex.label(r["chain"], r["funder"])
        if lab:
            f["watch"], f["why"], f["label"] = False, "exchange", "CEX " + lab
    from .connect import INFRA
    for f in out.values():
        if f["address"] in INFRA["solana" if f["chain"] == "solana" else "evm"]:
            f["watch"], f["why"] = False, "infraestructura"
    lst = sorted(out.values(), key=lambda f: (not f["watch"], -len(f["children"])))
    a = settings()
    for i, f in enumerate([x for x in lst if x["watch"]]):
        if i >= a["funder_max"]:
            f["watch"], f["why"] = False, f"tope de {a['funder_max']} fondeadores"
    return lst


def recipient_txs(p, chain, addr, cap):
    if chain == "solana":
        return len(p.signatures(addr, limit=cap) or [])
    return len(p.call(module="account", action="txlist", address=addr, page=1, offset=cap, sort="asc") or [])


def poll_funders(c, providers, now):
    a = settings()
    sent = 0
    favset = {(ch, w) for ch, w, _ in targets(c)}
    for f in [x for x in funder_list(c) if x["watch"]]:
        chain, addr = f["chain"], f["address"]
        key = f"fwatch:{chain}:{addr}"
        last = db.kv_get(c, key)
        if last is None:
            db.kv_set(c, key, now)   # empieza a vigilar desde ahora
            continue
        try:
            p = prov(providers, chain)
            rows, newest = [], last
            if chain == "solana":
                sigs = [s for s in p.signatures(addr, limit=20) if (s.get("blockTime") or 0) > last]
                if not sigs:
                    continue
                newest = max(s["blockTime"] for s in sigs)
                r = p.rpc("getTransfersByAddress", [addr, {"direction": "out", "mint": NATIVE_SOL, "sortOrder": "desc", "limit": 50}], credits=10) or {}
                for x in r.get("data") or []:
                    if x.get("type") == "transfer" and (x.get("blockTime") or 0) > last and x.get("toUserAccount"):
                        rows.append((x["toUserAccount"], float(x.get("uiAmount") or 0), x["blockTime"], x.get("signature")))
            else:
                for t in p.call(module="account", action="txlist", address=addr, page=1, offset=25, sort="desc") or []:
                    ts = int(t.get("timeStamp") or 0)
                    if ts > last and (t.get("from") or "").lower() == addr.lower() and t.get("to") and t.get("isError") == "0":
                        rows.append((t["to"], int(t.get("value") or 0) / 1e18, ts, t.get("hash")))
                        newest = max(newest, ts)
        except Exception as e:
            log.warning("fondeador %s: %s", short(addr), e)
            continue
        thr = a["funder_min_native"].get(chain, 0.05)
        from .connect import INFRA
        infra = INFRA["solana" if chain == "solana" else "evm"]
        n_alerts, extra = 0, 0
        for to, amt, ts, sig in sorted(rows, key=lambda x: x[2]):
            if amt < thr or to == addr or to in infra or cex.label(chain, to) or (chain, to) in favset:
                continue
            if c.execute("SELECT 1 FROM alerts WHERE tx=?", ("funder:" + str(sig),)).fetchone():
                continue
            try:
                ntx = recipient_txs(p, chain, to, a["funder_new_max_txs"] + 1)
            except Exception:
                continue
            if ntx > a["funder_new_max_txs"]:
                continue    # no es una wallet nueva
            if n_alerts >= a["funder_max_alerts_per_pass"]:
                extra += 1
                continue
            nat, g = CHAINS[chain]["native"], CHAINS[chain].get("gmgn")
            kids = ", ".join(short(x) for x in f["children"][:3])
            msg = (f"👩‍👧 <b>Wallet madre en marcha</b> ({CHAINS[chain]['name']})\n"
                   f"{short(addr)} (fondeó a tu ⭐ {kids}) envió <b>{amt:,.2f} {nat}</b> a una wallet NUEVA ({ntx} tx):\n<code>{to}</code>\n"
                   f"{CHAINS[chain]['explorer']}{to}" + (f"\nhttps://gmgn.ai/{g}/address/{to}" if g else "") +
                   f"\ntx: {CHAINS[chain]['tx']}{sig}\n⭐ Añadir a Mis wallets: {PANEL}#addfav={chain}:{to}")
            n_alerts += add_alert(c, "funder", ts, chain, to, "funder:" + str(sig), amt, amt * market.native_usd(chain), addr, f.get("label"),
                                  {"funder": addr, "children": f["children"], "txs": ntx}, msg)
        sent += n_alerts
        if extra:
            log.info("fondeador %s: %d wallets nuevas más sin avisar (tope por pasada)", short(addr), extra)
        db.kv_set(c, key, max(newest, last))
    return sent


# ------------------------------------------------------------------ estimación de créditos
def estimate(c):
    a = settings()
    t = targets(c)
    nsol = sum(1 for ch, _, _ in t if ch == "solana")
    fl = [f for f in funder_list(c) if f["watch"]]
    fsol = sum(1 for f in fl if f["chain"] == "solana")
    act = 0.15   # supuesto: en el 15 % de las pasadas una ⭐ tiene actividad nueva (10 créditos)
    inflow = (1440 / max(1, a["poll_minutes"])) * nsol * (1 + act * 10) if a.get("enabled") else 0
    dorm = (1440 / max(1, a["dormant_poll_minutes"])) * nsol * (1 + act * 10) if a.get("dormant_alert") and not a.get("enabled") else 0
    fund = (1440 / max(1, a["funder_poll_minutes"])) * fsol * (1 + 0.1 * 12) if a.get("funder_watch") else 0
    return {"inflow": round(inflow), "dormant": round(dorm), "funder": round(fund), "total": round(inflow + dorm + fund),
            "favorites": len(t), "favorites_sol": nsol, "funders": len(fl), "funders_sol": fsol, "first_time": 10 * nsol,
            "assumptions": "1 crédito por wallet y pasada + 10 cuando hay actividad nueva (supuesto: 15 % de las pasadas en ⭐, 10 % en fondeadores + ~2 receptores a comprobar). EVM: Etherscan, sin créditos."}


# ------------------------------------------------------------------ bucle
def tick(c, providers, last, now=None):
    a = settings()
    now = now or time.time()
    if telegram.status()["token"] and not telegram.chat_id() and now - last.get("tg", 0) >= 60:
        telegram.detect_chat(); last["tg"] = now      # sigue intentando hasta que escribas al bot
    every = min([m for m, on in ((a["poll_minutes"], a.get("enabled")), (a["dormant_poll_minutes"], a.get("dormant_alert"))) if on] or [0])
    if every and now - last.get("fav", 0) >= every * 60:
        poll_favorites(c, providers, int(now), inflow=bool(a.get("enabled")))
        check_dormant(c, int(now))
        last["fav"] = now
    if a.get("funder_watch"):
        if now - last.get("ff", 0) >= 3600 or last.get("ff_n") != len(targets(c)):
            fav_funders(c, providers); last["ff"] = now; last["ff_n"] = len(targets(c))
        if now - last.get("fund", 0) >= a["funder_poll_minutes"] * 60:
            poll_funders(c, providers, int(now)); last["fund"] = now


def run(c, providers=None, now=None):
    """Una pasada completa (pruebas / línea de comandos)."""
    a, providers, now = settings(), providers if providers is not None else {}, int(now or time.time())
    n = 0
    if a.get("enabled") or a.get("dormant_alert"):
        n += poll_favorites(c, providers, now, inflow=bool(a.get("enabled")))
        n += check_dormant(c, now)
    if a.get("funder_watch"):
        fav_funders(c, providers)
        n += poll_funders(c, providers, now)
    return n


def start_worker():
    def work():
        c, providers, last = db.connect(), {}, {}
        time.sleep(5)
        while True:
            try:
                tick(c, providers, last)
            except Exception:
                log.exception("vigilancia")
            WAKE.wait(60)
            WAKE.clear()
    t = threading.Thread(target=work, daemon=True, name="watch")
    t.start()
    return t
