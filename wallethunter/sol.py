"""Proveedor Solana (Helius). Diseño consciente de créditos del plan gratis:
- firmas con getSignaturesForAddress (1000 por llamada, barato)
- transacciones parseadas en lotes de 100 con la Enhanced API (2 req/s en el plan gratis)
- si la key tiene getTransactionsForAddress (plan Developer+), se usa automáticamente (mucho más barato)."""
import logging, time
from collections import deque
from .config import secret, cfg
from .net import request, RateLimiter, HttpError, STATUS
from .deltas import from_rpc, from_enhanced

log = logging.getLogger("wh")


class NoKey(Exception):
    pass


class Helius:
    def __init__(self, key=None):
        self.key = key or secret("HELIUS_API_KEY")
        if not self.key:
            raise NoKey("Falta HELIUS_API_KEY")
        h = cfg()["helius"]
        self.rpc_lim = RateLimiter(h["rps"])
        self.enh_lim = RateLimiter(h["enhanced_rps"])
        self.rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.key}"
        self.enh_base = "https://api-mainnet.helius-rpc.com/v0"
        self._gtfa = None if h.get("prefer_gtfa", "auto") == "auto" else bool(h.get("prefer_gtfa"))
        self.credits = 0

    # ---- llamadas base
    def rpc(self, method, params, credits=1):
        r = request(self.rpc_url, method="POST", body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    limiter=self.rpc_lim, source="helius", credits=credits)
        if "error" in r:
            raise HttpError(r["error"].get("code", 0), str(r["error"].get("message")))
        self.credits += credits
        return r.get("result")

    def rpc_batch(self, calls, credits_each=1):
        body = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
        for _ in range(len(calls) - 1):
            self.rpc_lim.wait()
        r = request(self.rpc_url, method="POST", body=body, limiter=self.rpc_lim, source="helius", credits=credits_each * len(calls))
        self.credits += credits_each * len(calls)
        out = [None] * len(calls)
        for x in r if isinstance(r, list) else []:
            if isinstance(x, dict) and "result" in x:
                out[x["id"]] = x["result"]
        return out

    def enhanced_parse(self, sigs):
        out = []
        for i in range(0, len(sigs), 100):
            chunk = sigs[i:i + 100]
            r = request(f"{self.enh_base}/transactions?api-key={self.key}", method="POST", body={"transactions": chunk},
                        limiter=self.enh_lim, source="helius", credits=100)
            self.credits += 100
            out += r or []
        return out

    def enhanced_history(self, addr, before=None, limit=100):
        url = f"{self.enh_base}/addresses/{addr}/transactions?api-key={self.key}&limit={limit}"
        if before:
            url += f"&before={before}"
        r = request(url, limiter=self.enh_lim, source="helius", credits=100)
        self.credits += 100
        return r or []

    def gtfa_available(self):
        if self._gtfa is None:
            try:
                self.rpc("getTransactionsForAddress", ["So11111111111111111111111111111111111111112", {"transactionDetails": "signatures", "limit": 1}], credits=10)
                self._gtfa = True
            except Exception as e:
                log.info("getTransactionsForAddress no disponible (plan gratis): %s", str(e)[:80])
                self._gtfa = False
            STATUS.set("helius", gtfa=self._gtfa)
        return self._gtfa

    def gtfa(self, addr, **opts):
        params = {"transactionDetails": opts.pop("details", "full"), "limit": opts.pop("limit", 1000), "sortOrder": opts.pop("order", "desc"),
                  "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}
        if params["transactionDetails"] == "signatures":
            params.pop("encoding"); params.pop("maxSupportedTransactionVersion")
        params.update(opts)
        r = self.rpc("getTransactionsForAddress", [addr, params], credits=10)
        n = len(r.get("data") or [])
        if params["transactionDetails"] == "full":
            self.credits += max(0, (n + 99) // 100 * 10 - 10)
        return r

    def signatures(self, addr, before=None, limit=1000):
        p = {"limit": limit}
        if before:
            p["before"] = before
        return self.rpc("getSignaturesForAddress", [addr, p]) or []

    def get_txs(self, sigs):
        out = []
        for i in range(0, len(sigs), 10):
            res = self.rpc_batch([("getTransaction", [s, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}]) for s in sigs[i:i + 10]])
            out += [r for r in res if r]
        return out

    def balances(self, wallets):
        out = {}
        for i in range(0, len(wallets), 100):
            chunk = wallets[i:i + 100]
            r = self.rpc("getMultipleAccounts", [chunk, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])
            for w, acc in zip(chunk, (r or {}).get("value") or []):
                out[w] = (acc or {}).get("lamports", 0) / 1e9
        return out

    def asset_prices(self, mints):
        """Precio USD de tokens con la DAS API (getAssetBatch, 10 créditos por lote de hasta 1000)."""
        out = {}
        for i in range(0, len(mints), 1000):
            chunk = mints[i:i + 1000]
            r = self.rpc("getAssetBatch", {"ids": chunk}, credits=10) or []
            for a in r:
                if not a:
                    continue
                ti = a.get("token_info") or {}
                pi = ti.get("price_info") or {}
                sym = ti.get("symbol") or ((a.get("content") or {}).get("metadata") or {}).get("symbol")
                out[a.get("id")] = (pi.get("price_per_token"), sym)
        return out

    def parse_sigs(self, sigs):
        """Firmas -> Delta (Enhanced API; si falla, RPC getTransaction)."""
        if not sigs:
            return []
        try:
            return [from_enhanced(t) for t in self.enhanced_parse(sigs)]
        except Exception as e:
            log.warning("Enhanced API falló (%s); uso getTransaction", str(e)[:100])
            return [from_rpc(t) for t in self.get_txs(sigs)]

    # ---- token
    def token_activity(self, mint, early_n=1500, recent_n=300, max_pages=300):
        """Primeras transacciones del token (lanzamiento, creador, primeros compradores) + recientes."""
        c = cfg()
        if self.gtfa_available():
            r = self.gtfa(mint, order="asc", limit=min(1000, early_n), filters={"status": "succeeded"})
            early = [from_rpc(t) for t in r.get("data") or []]
            tok = r.get("paginationToken")
            while tok and len(early) < early_n:
                r = self.gtfa(mint, order="asc", limit=min(1000, early_n - len(early)), paginationToken=tok, filters={"status": "succeeded"})
                early += [from_rpc(t) for t in r.get("data") or []]
                tok = r.get("paginationToken")
            recent = []
            if recent_n:
                r = self.gtfa(mint, order="desc", limit=recent_n, filters={"status": "succeeded"})
                recent = [from_rpc(t) for t in r.get("data") or []]
            return {"early": early, "recent": recent, "reached_start": True, "total_sigs": None}
        # plan gratis: recorrer firmas hasta la más antigua
        tail = deque(maxlen=early_n)
        first_page = []
        before, pages, total, reached = None, 0, 0, False
        while pages < max_pages:
            page = self.signatures(mint, before)
            pages += 1
            if not page:
                reached = True
                break
            if pages == 1:
                first_page = page
            total += len(page)
            for s in page:
                tail.appendleft(s)  # tail queda ordenada de antigua a nueva al final
            before = page[-1]["signature"]
            if len(page) < 1000:
                reached = True
                break
        ok_early = [s["signature"] for s in sorted(tail, key=lambda s: (s.get("slot") or 0)) if s.get("err") is None]
        early = self.parse_sigs(ok_early[:early_n])
        recent = []
        if recent_n and total > early_n:
            rs = [s["signature"] for s in first_page if s.get("err") is None][:recent_n]
            recent = self.parse_sigs(rs)
        return {"early": early, "recent": recent, "reached_start": reached, "total_sigs": total, "pages": pages}

    # ---- wallet
    def wallet(self, w, since_ts, max_pages=10, age_pages=3, bot=(1000, 24)):
        """Historial de 30 días + edad + fondeo. Devuelve dict con deltas y metadatos."""
        res = {"deltas": [], "history_truncated": False, "age_truncated": False, "prefiltered": False, "first_tx_ts": None,
               "last_activity": None, "n_txs_30d": 0, "funder": None, "funder_amount": None, "funded_at": None}
        if self.gtfa_available():
            r = self.gtfa(w, details="signatures", order="desc", limit=1000)
            sigs = r.get("data") or []
            if sigs:
                res["last_activity"] = sigs[0].get("blockTime")
            if len(sigs) == 1000 and sigs[0]["blockTime"] - sigs[-1]["blockTime"] < bot[1] * 3600:
                res["prefiltered"] = True
            res["n_txs_30d"] = sum(1 for s in sigs if (s.get("blockTime") or 0) >= since_ts)
            if not res["prefiltered"]:
                tok, pages = None, 0
                while pages < max(1, max_pages // 10 + 1):
                    opts = {"filters": {"blockTime": {"gte": since_ts}, "status": "succeeded", "tokenAccounts": "balanceChanged"}}
                    if tok:
                        opts["paginationToken"] = tok
                    rr = self.gtfa(w, order="desc", limit=1000, **opts)
                    res["deltas"] += [from_rpc(t) for t in rr.get("data") or []]
                    tok = rr.get("paginationToken")
                    pages += 1
                    if not tok:
                        break
                res["history_truncated"] = bool(tok)
            old = self.gtfa(w, order="asc", limit=5)
            data = old.get("data") or []
            if data:
                res["first_tx_ts"] = data[0].get("blockTime")
                self._funder_from([from_rpc(t) for t in data], w, res)
            return res
        # plan gratis
        sig_pages, before, reached = [], None, False
        for i in range(age_pages):
            page = self.signatures(w, before)
            if not page:
                reached = True
                break
            sig_pages.append(page)
            before = page[-1]["signature"]
            if i == 0:
                res["last_activity"] = page[0].get("blockTime")
                if len(page) >= bot[0] and (page[0].get("blockTime") or 0) - (page[-1].get("blockTime") or 0) < bot[1] * 3600:
                    res["prefiltered"] = True
                    break
            if len(page) < 1000:
                reached = True
                break
            if (page[-1].get("blockTime") or 0) < since_ts and i >= 0 and age_pages <= 1:
                break
        allsigs = [s for p in sig_pages for s in p]
        res["n_txs_30d"] = sum(1 for s in allsigs if (s.get("blockTime") or 0) >= since_ts)
        if allsigs:
            res["first_tx_ts"] = allsigs[-1].get("blockTime")
        res["age_truncated"] = not reached
        if res["prefiltered"]:
            return res
        # historial 30 días con la Enhanced API (100 por llamada)
        before, pages = None, 0
        while pages < max_pages:
            try:
                batch = self.enhanced_history(w, before)
            except Exception as e:
                log.warning("historial enhanced falló para %s: %s", w[:6], str(e)[:100])
                ok = [s["signature"] for s in allsigs if s.get("err") is None and (s.get("blockTime") or 0) >= since_ts]
                res["deltas"] = [from_rpc(t) for t in self.get_txs(ok[:max_pages * 100])]
                res["history_truncated"] = len(ok) > max_pages * 100
                break
            pages += 1
            if not batch:
                break
            stop = False
            for t in batch:
                if (t.get("timestamp") or 0) < since_ts:
                    stop = True
                    continue
                res["deltas"].append(from_enhanced(t))
            before = batch[-1].get("signature")
            if stop or len(batch) < 100:
                break
        else:
            res["history_truncated"] = True
        if reached and allsigs:
            oldest = [s["signature"] for s in reversed(allsigs[-3:])]
            try:
                self._funder_from([from_rpc(t) for t in self.get_txs(oldest)], w, res)
            except Exception as e:
                log.debug("fondeo falló %s: %s", w[:6], e)
        return res

    def funder_of(self, addr, age_pages=3):
        """Quién fondeó a esta dirección (para vínculos de 2 saltos)."""
        res = {"funder": None, "funder_amount": None, "funded_at": None, "first_tx_ts": None}
        if self.gtfa_available():
            data = self.gtfa(addr, order="asc", limit=5).get("data") or []
            if data:
                res["first_tx_ts"] = data[0].get("blockTime")
                self._funder_from([from_rpc(t) for t in data], addr, res)
            return res
        before, last = None, []
        for _ in range(age_pages):
            page = self.signatures(addr, before)
            if not page:
                break
            last = page
            before = page[-1]["signature"]
            if len(page) < 1000:
                oldest = [s["signature"] for s in reversed(page[-3:])]
                res["first_tx_ts"] = page[-1].get("blockTime")
                self._funder_from([from_rpc(t) for t in self.get_txs(oldest)], addr, res)
                break
        return res

    @staticmethod
    def _funder_from(deltas, w, res):
        for d in sorted(deltas, key=lambda d: d.slot):
            for src, dst, amt in d.native_transfers:
                if dst == w and src != w and amt > 0:
                    res["funder"], res["funder_amount"], res["funded_at"] = src, amt, d.ts
                    return
