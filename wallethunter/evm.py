"""Proveedor EVM (Ethereum, BNB, Base, Arbitrum, Polygon, Robinhood Chain...).
API compatible Etherscan: Etherscan V2 multichain (ETHERSCAN_API_KEY) o Blockscout (sin key en instancias públicas,
o Blockscout PRO con BLOCKSCOUT_API_KEY, necesaria para Robinhood Chain)."""
import logging, time
from collections import defaultdict
from .config import secret, cfg
from .chains import CHAINS, STABLES
from .net import request, RateLimiter
from .deltas import Delta

log = logging.getLogger("wh")

V4_POOL_MANAGERS = {
    "ethereum": "0x000000000004444c5dc75cb358380d2e3de08a90",
    "base": "0x498581ff718922c3f8e6a244956af099b2652b2b",
    "arbitrum": "0x360e68faccca8ca495c1b759fd9eee466db9fb32",
    "polygon": "0x67366782805870060151383f4bbff9dab53e5cd6",
    "bsc": "0x28e2ea090877bf75740558f6bfb36a5ffee9e9df",
}
LAUNCHPADS = {
    "bsc": {"0x5c952063c7fc8610ffdb798152d69f0b9550762b": "FOUR_MEME"},
}
ZERO = "0x0000000000000000000000000000000000000000"
_limiters = {}


class NoBackend(Exception):
    pass


def backend(chain):
    """Elige la API: Etherscan si hay key y la chain entra en su plan; si no, Blockscout."""
    ch = CHAINS[chain]
    ek, bk = secret("ETHERSCAN_API_KEY"), secret("BLOCKSCOUT_API_KEY")
    paid = bool(cfg().get("etherscan", {}).get("paid"))
    if ek and (ch.get("etherscan_free") or paid) and ch.get("etherscan_free") is not None:
        return ("etherscan", f"https://api.etherscan.io/v2/api?chainid={ch['chain_id']}&apikey={ek}", cfg()["etherscan"]["rps"])
    if bk:
        return ("blockscout_pro", f"https://api.blockscout.com/v2/api?chain_id={ch['chain_id']}&apikey={bk}", 4)
    if ch.get("blockscout") and not ch.get("blockscout_pro"):
        return ("blockscout", ch["blockscout"] + "?", 2)
    if ek and ch.get("etherscan_free") is False:
        raise NoBackend(f"{ch['name']} no entra en el plan gratis de Etherscan (hace falta el plan Lite o una key de Blockscout)")
    raise NoBackend(f"Falta API key para {ch['name']} (ETHERSCAN_API_KEY o BLOCKSCOUT_API_KEY)")


class EvmClient:
    def __init__(self, chain):
        self.chain = chain
        self.kind, self.base, rps = backend(chain)
        self.lim = _limiters.setdefault(self.kind + chain if self.kind == "blockscout" else self.kind, RateLimiter(rps))
        self.wrapped = (CHAINS[chain].get("wrapped") or "").lower()
        self.stables = STABLES.get(chain, {})
        self.calls = 0

    def call(self, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        sep = "" if self.base.endswith("?") else "&"
        for attempt in range(4):
            r = request(self.base + sep + q, limiter=self.lim, source=self.kind if self.kind != "blockscout_pro" else "blockscout", credits=1)
            self.calls += 1
            res = r.get("result")
            msg = str(r.get("message") or "")
            if r.get("status") == "1" or isinstance(res, list) and res:
                return res
            if isinstance(res, str) and ("rate limit" in res.lower() or "too many" in res.lower()):
                time.sleep(1.5 * (attempt + 1))
                continue
            if "No transactions found" in msg or "No token transfers" in msg or res == [] or msg == "OK":
                return res if res is not None else []
            if isinstance(res, str) and ("not supported" in res.lower() or "upgrade" in res.lower() or "invalid api" in res.lower()):
                raise NoBackend(res)
            if params.get("action") in ("balance", "getblocknobytime", "eth_block_number"):
                return res
            return res if isinstance(res, list) else []
        return []

    # ---- utilidades
    def block_at(self, ts):
        try:
            r = self.call(module="block", action="getblocknobytime", timestamp=int(ts), closest="after")
            if isinstance(r, dict):
                r = r.get("blockNumber")
            return int(r)
        except Exception:
            return 0

    def balances(self, wallets):
        out = {}
        for i in range(0, len(wallets), 20):
            chunk = wallets[i:i + 20]
            try:
                r = self.call(module="account", action="balancemulti", address=",".join(chunk), tag="latest")
                for x in r or []:
                    out[x["account"].lower()] = int(x["balance"]) / 1e18
            except Exception:
                for w in chunk:
                    try:
                        out[w] = int(self.call(module="account", action="balance", address=w, tag="latest") or 0) / 1e18
                    except Exception:
                        pass
        return out

    def _mint(self, contract):
        c = contract.lower()
        return "native_wrapped" if c == self.wrapped else c

    # ---- token
    def token_activity(self, token, pools, early_n=1500, recent_n=300):
        token = token.lower()
        early = []
        page = 1
        per = min(1000, early_n)
        while len(early) < early_n:
            r = self.call(module="account", action="tokentx", contractaddress=token, page=page, offset=per, sort="asc")
            if not r:
                break
            early += r
            if len(r) < per:
                break
            page += 1
        recent = []
        if recent_n and len(early) >= early_n:
            recent = self.call(module="account", action="tokentx", contractaddress=token, page=1, offset=recent_n, sort="desc") or []
        pool_set = {p.lower() for p in pools if p and p.startswith("0x") and len(p) == 42}
        if V4_POOL_MANAGERS.get(self.chain):
            pool_set.add(V4_POOL_MANAGERS[self.chain])
        pool_set |= set(LAUNCHPADS.get(self.chain, {}))
        # heurística: direcciones que envían a muchas y reciben de muchas = pool/router
        sent_to, recv_from = defaultdict(set), defaultdict(set)
        for t in early + recent:
            sent_to[t["from"].lower()].add(t["to"].lower())
            recv_from[t["to"].lower()].add(t["from"].lower())
        for a in sent_to:
            if len(sent_to[a]) >= 8 and len(recv_from.get(a, ())) >= 5 and a != ZERO:
                pool_set.add(a)
        creator, launch_block, launch_ts = None, None, None
        for t in early:
            if t["from"].lower() == ZERO and creator is None:
                creator = t["to"].lower()
            if t["from"].lower() in pool_set:
                launch_block, launch_ts = int(t["blockNumber"]), int(t["timeStamp"])
                break
        def buys(rows):
            out = []
            for t in rows:
                f, to = t["from"].lower(), t["to"].lower()
                if f in pool_set and to not in pool_set and to != ZERO:
                    out.append({"wallet": to, "ts": int(t["timeStamp"]), "slot": int(t["blockNumber"]), "idx": int(t.get("transactionIndex") or 0), "tx": t["hash"],
                                "amount": int(t["value"]) / 10 ** int(t.get("tokenDecimal") or 18)})
            return out
        def sellers(rows):
            return [t["from"].lower() for t in rows if t["to"].lower() in pool_set and t["from"].lower() not in pool_set]
        first = early[0] if early else None
        return {"early_buys": buys(early), "recent_buys": buys(recent), "recent_sellers": sellers(recent), "pools": sorted(pool_set),
                "creator": creator, "launch_block": launch_block, "launch_ts": launch_ts or (int(first["timeStamp"]) if first else None),
                "symbol": (first or {}).get("tokenSymbol"), "name": (first or {}).get("tokenName"), "reached_start": True}

    # ---- wallet
    def wallet(self, w, since_ts, max_pages=10, bot=(1000, 24)):
        w = w.lower()
        res = {"deltas": [], "history_truncated": False, "age_truncated": False, "prefiltered": False, "first_tx_ts": None,
               "last_activity": None, "n_txs_30d": 0, "funder": None, "funder_amount": None, "funded_at": None}
        b30 = self.block_at(since_ts)
        txl = self.call(module="account", action="txlist", address=w, startblock=b30, endblock=99999999, page=1, offset=1000, sort="desc") or []
        if txl:
            res["last_activity"] = int(txl[0]["timeStamp"])
        if len(txl) >= bot[0] and int(txl[0]["timeStamp"]) - int(txl[-1]["timeStamp"]) < bot[1] * 3600:
            res["prefiltered"] = True
        res["n_txs_30d"] = len(txl)
        if not res["prefiltered"]:
            toks, page = [], 1
            while page <= max_pages:
                r = self.call(module="account", action="tokentx", address=w, startblock=b30, endblock=99999999, page=page, offset=1000, sort="desc") or []
                toks += r
                if len(r) < 1000:
                    break
                page += 1
            else:
                res["history_truncated"] = True
            internal = self.call(module="account", action="txlistinternal", address=w, startblock=b30, endblock=99999999, page=1, offset=1000, sort="desc") or []
            res["deltas"] = self.build_deltas(w, txl, toks, internal)
            if toks:
                la = max(int(t["timeStamp"]) for t in toks)
                res["last_activity"] = max(res["last_activity"] or 0, la)
        # edad y fondeo: primera tx normal / interna
        first = self.call(module="account", action="txlist", address=w, startblock=0, endblock=99999999, page=1, offset=5, sort="asc") or []
        first_int = self.call(module="account", action="txlistinternal", address=w, startblock=0, endblock=99999999, page=1, offset=3, sort="asc") or []
        cands = [t for t in first + first_int if t.get("to", "").lower() == w and int(t.get("value") or 0) > 0]
        alltimes = [int(t["timeStamp"]) for t in first + first_int]
        if alltimes:
            res["first_tx_ts"] = min(alltimes)
        if cands:
            f = min(cands, key=lambda t: int(t["timeStamp"]))
            res["funder"], res["funder_amount"], res["funded_at"] = f["from"].lower(), int(f["value"]) / 1e18, int(f["timeStamp"])
        return res

    def funder_of(self, addr):
        a = addr.lower()
        res = {"funder": None, "funder_amount": None, "funded_at": None, "first_tx_ts": None}
        first = self.call(module="account", action="txlist", address=a, startblock=0, endblock=99999999, page=1, offset=5, sort="asc") or []
        fi = self.call(module="account", action="txlistinternal", address=a, startblock=0, endblock=99999999, page=1, offset=3, sort="asc") or []
        cands = [t for t in first + fi if t.get("to", "").lower() == a and int(t.get("value") or 0) > 0]
        if first + fi:
            res["first_tx_ts"] = min(int(t["timeStamp"]) for t in first + fi)
        if cands:
            f = min(cands, key=lambda t: int(t["timeStamp"]))
            res["funder"], res["funder_amount"], res["funded_at"] = f["from"].lower(), int(f["value"]) / 1e18, int(f["timeStamp"])
        return res

    def build_deltas(self, w, txl, toks, internal):
        by = {}
        def get(h, ts, blk, frm=None):
            d = by.get(h)
            if d is None:
                d = by[h] = Delta(self.chain, h, int(ts), int(blk), frm, {frm} if frm else set())
            return d
        for t in txl:
            d = get(t["hash"], t["timeStamp"], t["blockNumber"], t["from"].lower())
            d.fee_payer = t["from"].lower()
            if t.get("isError") == "1":
                d.failed = True
                continue
            v = int(t.get("value") or 0) / 1e18
            fee = int(t.get("gasUsed") or 0) * int(t.get("gasPrice") or 0) / 1e18
            if t["from"].lower() == w:
                d.native[w] = d.native.get(w, 0) - v - fee
                if v:
                    d.native_transfers.append((w, t["to"].lower(), v))
            if t["to"].lower() == w and v:
                d.native[w] = d.native.get(w, 0) + v
                d.native_transfers.append((t["from"].lower(), w, v))
        for t in internal:
            if t.get("isError") == "1":
                continue
            d = get(t["hash"], t["timeStamp"], t["blockNumber"])
            v = int(t.get("value") or 0) / 1e18
            if t["to"].lower() == w:
                d.native[w] = d.native.get(w, 0) + v
            elif t["from"].lower() == w:
                d.native[w] = d.native.get(w, 0) - v
        for t in toks:
            d = get(t["hash"], t["timeStamp"], t["blockNumber"])
            m = self._mint(t["contractAddress"])
            try:
                amt = int(t["value"]) / 10 ** int(t.get("tokenDecimal") or 18)
            except (ValueError, TypeError):
                continue
            f, to = t["from"].lower(), t["to"].lower()
            d.tokens[(to, m)] = d.tokens.get((to, m), 0) + amt
            d.tokens[(f, m)] = d.tokens.get((f, m), 0) - amt
            if m not in self.stables and m != "native_wrapped":
                d.dex = d.dex or "DEX"
        return list(by.values())
