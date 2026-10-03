"""Orquestador: escanear tokens o wallets sueltas, guardar en la BD y recalcular métricas/etiquetas."""
import json, logging, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import cfg
from .chains import CHAINS, is_evm_address, is_sol_address
from . import db, market, graph, cex
from .deltas import extract, early_buys, traders
from .metrics import wallet_metrics
from .tags import compute_tags
from .net import STATUS, request

log = logging.getLogger("wh")
DS_CHAIN = {"ethereum": "ethereum", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "polygon": "polygon", "solana": "solana", "robinhood": "robinhood"}


def provider(chain):
    if chain == "solana":
        from .sol import Helius
        return Helius()
    from .evm import EvmClient
    return EvmClient(chain)


def detect_chain(addr):
    """Para un CA EVM sin chain: pregunta a DexScreener en qué chain tiene más liquidez."""
    if is_sol_address(addr):
        return "solana"
    try:
        d = request(f"https://api.dexscreener.com/latest/dex/tokens/{addr}", source="dexscreener")
        best = {}
        for p in d.get("pairs") or []:
            ch = p.get("chainId")
            if ch in DS_CHAIN:
                best[ch] = best.get(ch, 0) + float((p.get("liquidity") or {}).get("usd") or 0)
        if best:
            return max(best, key=best.get)
    except Exception as e:
        log.warning("no pude detectar la chain de %s: %s", addr, e)
    return "ethereum"


def norm(chain, a):
    return a if chain == "solana" else a.lower()


class Scanner:
    def __init__(self, conn=None, progress=None):
        self.c = conn or db.connect()
        self.progress = progress or (lambda msg: log.info(msg))
        self.C = cfg()

    # ------------------------------------------------------------ tokens
    def scan_token(self, chain, token):
        token = norm(chain, token)
        if chain in ("evm", "auto", None, ""):
            chain = detect_chain(token)
        now = int(time.time())
        nusd = market.native_usd(chain)
        self.progress(f"{CHAINS[chain]['name']}: datos de mercado de {token[:6]}…")
        mk = market.token_market(chain, token) or {}
        prov = provider(chain)
        C = self.C
        self.progress("buscando las primeras transacciones del token…")
        buyers, recent, creator, launch_ts, launch_slot = [], [], None, mk.get("launch_ts"), None
        symbol, name = mk.get("symbol"), mk.get("name")
        if chain == "solana":
            act = prov.token_activity(token, C["early_tx_to_parse"], C["recent_tx_to_parse"] if C["include_recent_traders"] else 0, C["max_sig_pages_token"])
            early = sorted([d for d in act["early"] if not d.failed], key=lambda d: d.slot)
            if early and act["reached_start"]:
                launch_ts, launch_slot, creator = early[0].ts, early[0].slot, early[0].fee_payer
            seen = set()
            for d in early:
                for w, spent, amt in early_buys(d, token, nusd):
                    if w not in seen:
                        seen.add(w)
                        buyers.append({"wallet": w, "ts": d.ts, "slot": d.slot, "spent": spent})
            for d in act["recent"]:
                for w in traders(d, token):
                    if w not in seen and w not in recent:
                        recent.append(w)
            info = {"total_sigs": act.get("total_sigs"), "reached_start": act["reached_start"]}
        else:
            pools = [p.get("address") for p in mk.get("pools") or []]
            act = prov.token_activity(token, pools, C["early_tx_to_parse"], C["recent_tx_to_parse"] if C["include_recent_traders"] else 0)
            creator, launch_slot = act["creator"], act["launch_block"]
            launch_ts = min([x for x in (act["launch_ts"], launch_ts) if x] or [None]) if (act["launch_ts"] or launch_ts) else None
            symbol, name = symbol or act["symbol"], name or act["name"]
            seen = set()
            for b in act["early_buys"]:
                if b["wallet"] not in seen:
                    seen.add(b["wallet"])
                    buyers.append({"wallet": b["wallet"], "ts": b["ts"], "slot": b["slot"], "spent": None})
            for b in act["recent_buys"]:
                if b["wallet"] not in seen and b["wallet"] not in recent:
                    recent.append(b["wallet"])
            for w in act["recent_sellers"]:
                if w not in seen and w not in recent:
                    recent.append(w)
            info = {"pools": act["pools"][:20]}
        self.c.execute("""INSERT INTO tokens(chain,address,symbol,name,launch_ts,launch_slot,creator,pools,price_usd,price_native,mc,liq,scanned_at,status,info)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chain,address) DO UPDATE SET symbol=excluded.symbol,name=excluded.name,
                          launch_ts=COALESCE(excluded.launch_ts,launch_ts),launch_slot=COALESCE(excluded.launch_slot,launch_slot),creator=COALESCE(excluded.creator,creator),
                          pools=excluded.pools,price_usd=excluded.price_usd,price_native=excluded.price_native,mc=excluded.mc,liq=excluded.liq,scanned_at=excluded.scanned_at,status=excluded.status,info=excluded.info""",
                       (chain, token, symbol, name, launch_ts, launch_slot, creator, json.dumps((mk.get("pools") or [])[:10]), mk.get("price_usd"),
                        (mk.get("price_usd") or 0) / nusd if mk.get("price_usd") else None, mk.get("mc"), mk.get("liq"), now, "scanning", json.dumps(info)))
        for rank, b in enumerate(buyers, 1):
            self.c.execute("INSERT OR REPLACE INTO token_buyers(chain,token,wallet,first_buy_ts,first_buy_slot,rank,native_spent,kind) VALUES(?,?,?,?,?,?,?,'early')",
                           (chain, token, b["wallet"], b["ts"], b["slot"], rank, b["spent"]))
        self.c.commit()
        cap = C["max_wallets_per_token"]
        targets = [b["wallet"] for b in buyers][:cap]
        if creator and creator not in targets:
            targets.append(creator)
        for w in recent:
            if len(targets) >= cap + 1:
                break
            if w not in targets:
                targets.append(w)
        for w in targets:
            db.upsert_wallet(self.c, chain, w)
            db.add_origin(self.c, chain, w, token)
        self.c.commit()
        self.progress(f"{len(buyers)} compradores tempranos encontrados; analizando {len(targets)} wallets…")
        self.scan_wallets(chain, targets, prov=prov)
        n = self.c.execute("SELECT COUNT(*) FROM token_buyers WHERE chain=? AND token=?", (chain, token)).fetchone()[0]
        self.c.execute("UPDATE tokens SET status='ok', n_wallets=? WHERE chain=? AND address=?", (len(targets), chain, token))
        self.c.commit()
        return {"chain": chain, "token": token, "symbol": symbol, "early_buyers": len(buyers), "wallets": len(targets), "buyers_total": n}

    # ------------------------------------------------------------ wallets
    def scan_wallets(self, chain, wallets, prov=None, force=False):
        if chain in ("evm", "auto", None, ""):
            chain = "ethereum"
        wallets = [norm(chain, w) for w in wallets]
        prov = prov or provider(chain)
        C = self.C
        now = int(time.time())
        since = now - C["window_days"] * 86400
        rescan = C.get("rescan_hours", 12) * 3600
        todo = []
        for w in dict.fromkeys(wallets):
            db.upsert_wallet(self.c, chain, w)
            r = self.c.execute("SELECT last_scanned, status FROM wallets WHERE chain=? AND address=?", (chain, w)).fetchone()
            if force or not r["last_scanned"] or now - r["last_scanned"] > rescan or r["status"] in ("pending", "error"):
                todo.append(w)
        self.c.commit()
        nusd = market.native_usd(chain)
        done = 0
        bot = (C["bot_prefilter"]["sigs"], C["bot_prefilter"]["hours"])
        def work(w):
            if chain == "solana":
                return w, prov.wallet(w, since, C["max_history_pages_per_wallet"], C["max_sig_pages_age"], bot)
            return w, prov.wallet(w, since, C["max_history_pages_per_wallet"], bot)
        wrapped = None
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(work, w) for w in todo]
            for f in as_completed(futs):
                done += 1
                try:
                    w, res = f.result()
                except Exception as e:
                    log.warning("wallet falló: %s", e)
                    continue
                try:
                    self._store_wallet(chain, w, res, nusd, wrapped)
                except Exception as e:
                    log.exception("guardar wallet %s", w)
                    db.upsert_wallet(self.c, chain, w, status="error", error=str(e)[:200])
                if done % 5 == 0 or done == len(todo):
                    self.c.commit()
                    self.progress(f"wallets analizadas {done}/{len(todo)}")
                    STATUS.save()
        self.c.commit()
        # saldos
        try:
            bals = prov.balances(list(dict.fromkeys(wallets)))
            for w, b in bals.items():
                self.c.execute("UPDATE wallets SET balance_native=? WHERE chain=? AND address=?", (b, chain, norm(chain, w)))
            self.c.commit()
        except Exception as e:
            log.warning("saldos fallaron: %s", e)
        self.progress("fondeadores de 2º nivel…")
        try:
            self.resolve_funders(chain, prov)
        except Exception as e:
            log.warning("fondeadores 2º nivel: %s", e)
        self.progress("precios de los tokens tradeados…")
        self.refresh_prices(chain)
        self.progress("calculando bundles, clusters, métricas y etiquetas…")
        self.recompute(chain)
        STATUS.save()
        return {"chain": chain, "wallets": len(wallets), "scanned": len(todo)}

    def _store_wallet(self, chain, w, res, nusd, wrapped):
        swaps, transfers = [], []
        for d in res["deltas"]:
            s, t = extract(d, w, nusd, wrapped=wrapped)
            swaps += s
            transfers += t
        self.c.execute("DELETE FROM swaps WHERE chain=? AND wallet=? AND ts>=?", (chain, w, int(time.time()) - self.C["window_days"] * 86400))
        db.insert_swaps(self.c, swaps)
        db.insert_transfers(self.c, transfers)
        fl = cex.label(chain, res.get("funder"))
        db.upsert_wallet(self.c, chain, w, status="bot" if res["prefiltered"] else "ok", error=None, last_scanned=int(time.time()),
                         funder=res.get("funder"), funder_label=fl, funder_amount=res.get("funder_amount"), funded_at=res.get("funded_at"),
                         first_tx_ts=res.get("first_tx_ts"), age_truncated=int(bool(res.get("age_truncated"))),
                         history_truncated=int(bool(res.get("history_truncated"))), last_activity=res.get("last_activity"),
                         n_txs_30d=res.get("n_txs_30d"), prefiltered=int(bool(res["prefiltered"])))
        # precio de entrada del comprador temprano (Solana ya lo trae; EVM se completa aquí)
        for s in swaps:
            if s["side"] == "buy":
                self.c.execute("UPDATE token_buyers SET native_spent=COALESCE(native_spent, ?) WHERE chain=? AND token=? AND wallet=?", (s["native_amount"], chain, s["token"], w))

    def resolve_funders(self, chain, prov, limit=None):
        """Fondeador del fondeador (no CEX) para detectar grupos que se fondean en cadena."""
        limit = limit or self.C["cluster"].get("max_funder_lookups", 250)
        rows = [r[0] for r in self.c.execute("""SELECT DISTINCT w.funder FROM wallets w LEFT JOIN funders f ON f.chain=w.chain AND f.address=w.funder
                 WHERE w.chain=? AND w.funder IS NOT NULL AND w.funder_label IS NULL AND f.address IS NULL""", (chain,))]
        rows = [a for a in rows if not cex.label(chain, a)][:limit]
        if not rows:
            return 0
        def work(a):
            return a, prov.funder_of(a)
        with ThreadPoolExecutor(max_workers=4) as ex:
            for f in as_completed([ex.submit(work, a) for a in rows]):
                try:
                    a, r = f.result()
                except Exception as e:
                    log.debug("funder_of: %s", e)
                    continue
                self.c.execute("INSERT OR REPLACE INTO funders VALUES(?,?,?,?,?,?,?,?)", (chain, a, r["funder"], cex.label(chain, r["funder"]),
                               r["funder_amount"], r["funded_at"], r["first_tx_ts"], int(time.time())))
        self.c.commit()
        return len(rows)

    # ------------------------------------------------------------ precios
    def refresh_prices(self, chain, max_age=6 * 3600):
        now = int(time.time())
        toks = [r[0] for r in self.c.execute("""SELECT DISTINCT s.token FROM swaps s LEFT JOIN token_prices p ON p.chain=s.chain AND p.token=s.token
                 WHERE s.chain=? AND (p.updated IS NULL OR p.updated < ?)""", (chain, now - max_age))]
        if not toks:
            return
        nusd = market.native_usd(chain)
        info = market.dexscreener_tokens(chain, toks[:3000])
        failed = info.pop("_failed", set())
        das = {}
        if chain == "solana":
            missing = [t for t in toks[:3000] if t not in info]
            if missing:
                try:
                    das = provider("solana").asset_prices(missing)
                except Exception as e:
                    log.warning("DAS precios falló: %s", e)
        rows = []
        for t in toks[:3000]:
            d = info.get(norm(chain, t))
            if not d and t in das:
                px, sym = das[t]
                rows.append((chain, t, sym, (px / nusd) if px else None, px, None, None, 1 if t.endswith("pump") else 0, now))
                continue
            if not d and norm(chain, t) in failed:
                continue  # DexScreener no respondió: se reintenta en la próxima pasada (no marcar como muerto)
            if d:
                rows.append((chain, t, d.get("symbol"), (d["price_usd"] / nusd) if d.get("price_usd") else None, d.get("price_usd"), d.get("launch_ts"), d.get("liq"), d.get("is_pumpfun", 0), now))
            else:
                # sin pares en DexScreener: probablemente muerto/rug (precio 0)
                rows.append((chain, t, None, 0.0, 0.0, None, 0.0, 1 if t.endswith("pump") else 0, now))
        self.c.executemany("INSERT OR REPLACE INTO token_prices(chain,token,symbol,price_native,price_usd,launch_ts,liq,is_pumpfun,updated) VALUES(?,?,?,?,?,?,?,?,?)", rows)
        self.c.commit()

    # ------------------------------------------------------------ recálculo local (sin llamadas)
    def recompute(self, chain):
        nusd = market.native_usd(chain)
        sig, clusters, n_links, bundles = graph.analyze(self.c, chain, self.C["window_days"])
        prices = {r["token"]: dict(r) for r in self.c.execute("SELECT * FROM token_prices WHERE chain=?", (chain,))}
        # la fecha de lanzamiento propia (escaneo) tiene prioridad
        for r in self.c.execute("SELECT address, launch_ts FROM tokens WHERE chain=? AND launch_ts IS NOT NULL", (chain,)):
            prices.setdefault(r[0], {})["launch_ts"] = r[1]
        swaps_by = {}
        for r in self.c.execute("SELECT wallet, token, ts, slot, side, token_amount, native_amount, dex FROM swaps WHERE chain=?", (chain,)):
            swaps_by.setdefault(r["wallet"], []).append(dict(r))
        for row in self.c.execute("SELECT * FROM wallets WHERE chain=?", (chain,)).fetchall():
            w = dict(row)
            if w["status"] == "pending":
                continue
            m = wallet_metrics(swaps_by.get(w["address"], []), prices, nusd, window_days=self.C["window_days"])
            g = sig.get(w["address"], {})
            tags, sc = compute_tags(m, w, g, nusd)
            m.pop("per_token", None)
            m["bundles"] = g.get("bundles", [])
            m["copy_of"] = g.get("copy_of")
            m["links"] = g.get("links", [])[:10]
            m["early_rank_min"] = g.get("early_rank_min")
            self.c.execute("UPDATE wallets SET metrics=?, tags=?, score=?, cluster_id=? WHERE chain=? AND address=?",
                           (json.dumps(m), json.dumps(tags), sc, g.get("cluster"), chain, w["address"]))
        db.kv_set(self.c, f"graph:{chain}", {"clusters": clusters, "links": n_links, "bundles": len(bundles), "updated": int(time.time())})
        self.c.commit()


def parse_items(text):
    """Separa CAs/wallets pegadas (comas, espacios, saltos de línea) y valida el formato."""
    import re
    out = []
    for x in re.split(r"[\s,;]+", text or ""):
        x = x.strip()
        if not x:
            continue
        m = re.search(r"(0x[a-fA-F0-9]{40})", x) or re.search(r"([1-9A-HJ-NP-Za-km-z]{32,44})$", x.split("/")[-1].split("?")[0])
        if m:
            out.append(m.group(1))
    return list(dict.fromkeys(out))
