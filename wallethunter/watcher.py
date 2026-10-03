"""Alertas de entradas grandes de dinero en wallets vigiladas (⭐). APAGADO por defecto (config alerts.enabled).
Coste en Helius: 1 crédito por wallet y pasada + 100 si hay transacciones nuevas que parsear."""
import logging, time
from . import db, cex, market, telegram
from .config import cfg
from .chains import CHAINS
from .deltas import extract

log = logging.getLogger("wh")


def targets(c):
    a = cfg()["alerts"]
    rows = [(r["chain"], r["address"], r["alias"]) for r in c.execute("SELECT f.chain, f.address, COALESCE(a.alias, f.alias) alias FROM favorites f LEFT JOIN aliases a ON a.chain=f.chain AND a.address=f.address")]
    if a.get("watch") == "favorites+smart":
        for r in c.execute("SELECT w.chain, w.address, a.alias FROM wallets w LEFT JOIN aliases a ON a.chain=w.chain AND a.address=w.address WHERE w.tags LIKE '%\"smart\"%'"):
            rows.append((r["chain"], r["address"], r["alias"]))
    return list(dict.fromkeys(rows))[:60]


def sender_label(c, chain, s):
    lab = cex.label(chain, s)
    if lab:
        return f"CEX {lab}"
    n = c.execute("SELECT COUNT(*) FROM wallets WHERE chain=? AND funder=?", (chain, s)).fetchone()[0]
    if n >= 2:
        return f"fondeador de {n} wallets"
    r = c.execute("SELECT tags FROM wallets WHERE chain=? AND address=?", (chain, s)).fetchone()
    if r:
        return "wallet de la base"
    return None


def run(c, providers=None, now=None):
    a = cfg()["alerts"]
    if not a.get("enabled"):
        return 0
    now = now or int(time.time())
    sent = 0
    providers = providers or {}
    for chain, w, alias in targets(c):
        key = f"watch:{chain}:{w}"
        last = db.kv_get(c, key)
        if last is None:
            db.kv_set(c, key, now)  # primera vez: no avisar de lo antiguo
            continue
        try:
            if chain not in providers:
                from .scan import provider
                providers[chain] = provider(chain)
            p = providers[chain]
            if chain == "solana":
                sigs = [s for s in p.signatures(w, limit=25) if (s.get("blockTime") or 0) > last and s.get("err") is None]
                deltas = p.parse_sigs([s["signature"] for s in sigs]) if sigs else []
            else:
                deltas = p.build_deltas(w.lower(), p.call(module="account", action="txlist", address=w, page=1, offset=25, sort="desc") or [], [],
                                        p.call(module="account", action="txlistinternal", address=w, page=1, offset=25, sort="desc") or [])
                deltas = [d for d in deltas if d.ts > last]
        except Exception as e:
            log.warning("vigilancia %s: %s", w[:6], e)
            continue
        nusd = market.native_usd(chain)
        thr_native = (a.get("min_inflow_native") or {}).get(chain)
        newest = last
        for d in deltas:
            newest = max(newest, d.ts)
            _, transfers = extract(d, w, nusd)
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
                try:
                    c.execute("INSERT INTO alerts(ts,chain,wallet,amount_native,amount_usd,sender,sender_label,tx) VALUES(?,?,?,?,?,?,?,?)",
                              (d.ts, chain, w, amt, usd, t["counterparty"], lab, d.tx))
                except Exception:
                    continue  # ya avisada
                nat = CHAINS[chain]["native"]
                msg = (f"🚨 <b>Entrada grande</b> en {alias or w[:6] + '…' + w[-4:]} ({CHAINS[chain]['name']})\n"
                       f"{amt:,.2f} {nat} (~{usd:,.0f} $) desde {t['counterparty'][:6]}…{t['counterparty'][-4:]}"
                       f"{' · ' + lab if lab else ''}\n{CHAINS[chain]['tx']}{d.tx}")
                ok = telegram.send(msg)
                c.execute("UPDATE alerts SET sent=? WHERE tx=?", (1 if ok else 0, d.tx))
                sent += 1
        db.kv_set(c, key, newest)
    c.commit()
    return sent
