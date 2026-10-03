import os, sys, json, time, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["WH_STATE_DIR"] = _tmp
os.environ["WH_DB"] = os.path.join(_tmp, "t.db")
os.environ["WH_DATA"] = os.path.join(_tmp, "data.json")
os.environ["WH_NO_LOGIN_ENV"] = "1"
for k in ("HELIUS_API_KEY", "ETHERSCAN_API_KEY", "BLOCKSCOUT_API_KEY", "WH_PIN"):
    os.environ.pop(k, None)
from helpers import rpc_tx, enh_tx, WSOL
from wallethunter import deltas, metrics, tags, graph, db, scan, export, market, jobs
from wallethunter.chains import CHAINS

MINT = "Mint1111111111111111111111111111111111pump"
POOL = "Curve111111111111111111111111111111111111"
A, B, C2, DEV, FUND = "WalletA111111111111111111111111111111111", "WalletB111111111111111111111111111111111", "WalletC111111111111111111111111111111111", "DevWa11et11111111111111111111111111111111", "Funder1111111111111111111111111111111111"


class TestDeltas(unittest.TestCase):
    def test_rpc_buy(self):
        tx = rpc_tx("s1", 100, 1000, A, native={A: (5 * 10**9, 3 * 10**9), POOL: (10**9, 3 * 10**9)},
                    tokens=[(A, MINT, 0, 1000), (POOL, MINT, 5000, 4000)], programs=["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"])
        d = deltas.from_rpc(tx)
        self.assertEqual(d.dex, "PUMP_FUN")
        sw, tr = deltas.extract(d, A, 150)
        self.assertEqual(len(sw), 1)
        self.assertEqual(sw[0]["side"], "buy")
        self.assertAlmostEqual(sw[0]["native_amount"], 2.0)
        self.assertAlmostEqual(sw[0]["token_amount"], 1000)
        # el pool no es firmante -> no cuenta como comprador
        eb = deltas.early_buys(d, MINT, 150)
        self.assertEqual([x[0] for x in eb], [A])

    def test_enhanced_sell_wsol(self):
        tx = enh_tx("s2", 200, 2000, A, native={A: -5000}, tokens=[(A, MINT, -500), (A, WSOL, 3.0)], source="RAYDIUM")
        d = deltas.from_enhanced(tx)
        sw, _ = deltas.extract(d, A, 150)
        self.assertEqual(sw[0]["side"], "sell")
        self.assertAlmostEqual(sw[0]["native_amount"], 3.0 - 5000 / 1e9, places=6)
        self.assertEqual(sw[0]["dex"], "RAYDIUM")

    def test_native_transfer(self):
        tx = rpc_tx("s3", 300, 3000, FUND, native={FUND: (100 * 10**9, 90 * 10**9), A: (0, 10 * 10**9)}, transfers=[(FUND, A, 10 * 10**9)])
        d = deltas.from_rpc(tx)
        sw, tr = deltas.extract(d, A)
        self.assertEqual(sw, [])
        self.assertEqual(tr[0]["counterparty"], FUND)
        self.assertEqual(tr[0]["direction"], "in")
        self.assertAlmostEqual(tr[0]["amount_native"], 10)

    def test_failed_ignored(self):
        tx = rpc_tx("s4", 1, 1, A, native={A: (2, 1)}, tokens=[(A, MINT, 0, 5)], err={"x": 1})
        self.assertEqual(deltas.extract(deltas.from_rpc(tx), A), ([], []))

    def test_parse_items(self):
        txt = "https://dexscreener.com/solana/" + MINT + " , 0xAbCdEf0123456789abcdef0123456789ABCDEF01\nbasura"
        self.assertEqual(scan.parse_items(txt), [MINT, "0xAbCdEf0123456789abcdef0123456789ABCDEF01"])


class TestMetrics(unittest.TestCase):
    def test_pnl_wr_hold_entry(self):
        now = int(time.time())
        sw = [
            {"token": "T1", "ts": now - 1000, "slot": 1, "side": "buy", "token_amount": 100, "native_amount": 1.0, "dex": "PUMP_FUN"},
            {"token": "T1", "ts": now - 400, "slot": 2, "side": "sell", "token_amount": 100, "native_amount": 3.0, "dex": "PUMP_FUN"},
            {"token": "T2", "ts": now - 900, "slot": 3, "side": "buy", "token_amount": 50, "native_amount": 2.0, "dex": "RAYDIUM"},
            {"token": "T2", "ts": now - 800, "slot": 4, "side": "sell", "token_amount": 50, "native_amount": 0.5, "dex": "RAYDIUM"},
            {"token": "T3", "ts": now - 700, "slot": 5, "side": "sell", "token_amount": 10, "native_amount": 9.0, "dex": None},  # solo venta: ignorado
        ]
        prices = {"T1": {"launch_ts": now - 1060, "price_native": 0.01}, "T2": {"launch_ts": now - 1200, "price_native": 0.0}}
        m = metrics.wallet_metrics(sw, prices, 100.0, now=now)
        self.assertEqual(m["tokens"], 2)
        self.assertEqual(m["wins"], 1)
        self.assertAlmostEqual(m["pnl_native"], 0.5)
        self.assertAlmostEqual(m["pnl_usd"], 50)
        self.assertAlmostEqual(m["roi"], 0.5 / 3)
        self.assertEqual(m["avg_hold_s"], (600 + 100) / 2)
        self.assertEqual(m["avg_entry_s"], (60 + 300) / 2)
        self.assertAlmostEqual(m["raydium_share"], 2 / 5)

    def test_unrealized(self):
        now = int(time.time())
        sw = [{"token": "T", "ts": now - 100, "slot": 1, "side": "buy", "token_amount": 1000, "native_amount": 1.0, "dex": None}]
        m = metrics.wallet_metrics(sw, {"T": {"price_native": 0.005}}, 100, now=now)
        self.assertAlmostEqual(m["pnl_native"], 4.0)
        self.assertEqual(m["win_rate"], 1.0)


class TestTags(unittest.TestCase):
    def test_tags_and_score(self):
        now = int(time.time())
        m = {"tokens": 20, "wins": 15, "win_rate": 0.75, "trades": 60, "pnl_native": 100, "pnl_usd": 15000, "roi": 1.2, "avg_hold_s": 600,
             "median_hold_s": 600, "avg_entry_s": 120, "avg_size_native": 1.0, "top_token_share": 0.3, "hour_concentration": 0.4,
             "trades_per_day": 3, "pumpfun_share": 0.8, "raydium_share": 0.1, "pump_seller_share": 0.6, "rug_share": 0.1}
        w = {"last_activity": now - 3600, "first_tx_ts": now - 100 * 86400, "funder_label": "Binance", "balance_native": 10}
        t, sc = tags.compute_tags(m, w, {"cluster_size": 0}, 150, now=now)
        for x in ("activa", "temprano", "scalper", "rentable", "pumpfun", "hub_cex", "cex_binance", "wr_alto", "consistente", "vende_pumps", "smart"):
            self.assertIn(x, t, x)
        self.assertNotIn("bot", t)
        self.assertGreaterEqual(sc, 65)
        t2, sc2 = tags.compute_tags({"tokens": 1, "wins": 0, "win_rate": 0, "pnl_native": -1, "pnl_usd": -150, "trades": 2}, {"prefiltered": 1}, {}, 150, now=now)
        self.assertIn("bot", t2); self.assertIn("una_vez", t2)
        self.assertLess(sc2, 20)
        self.assertTrue(all("help" in d and d["help"] for d in tags.tag_defs()))


class FakeHelius:
    """Proveedor falso: simula Helius con transacciones sintéticas."""
    def __init__(self):
        now = int(time.time())
        self.now = now
        L = now - 5 * 86400
        self.L = L
        mk = lambda sig, slot, ts, w, sol, tok: rpc_tx(sig, slot, ts, w, native={w: (100 * 10**9, int((100 - sol) * 10**9)), POOL: (10**9, int((1 + sol) * 10**9))},
                                                        tokens=[(w, MINT, 0, tok), (POOL, MINT, 10**9, 10**9 - tok)], programs=["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"])
        self.early = [deltas.from_rpc(rpc_tx("create", 1000, L, DEV, native={DEV: (10**10, 9 * 10**9)}, tokens=[(DEV, MINT, 0, 1)])),
                      deltas.from_rpc(mk("b1", 1000, L, A, 1.0, 1000)), deltas.from_rpc(mk("b2", 1001, L + 1, B, 2.0, 1500)),
                      deltas.from_rpc(mk("b3", 1001, L + 1, C2, 2.0, 1400))]

    def token_activity(self, mint, *a, **k):
        return {"early": self.early, "recent": [], "reached_start": True, "total_sigs": 4}

    def wallet(self, w, since, *a, **k):
        res = {"deltas": [], "history_truncated": False, "age_truncated": False, "prefiltered": False, "first_tx_ts": self.L - 86400,
               "last_activity": self.now - 100, "n_txs_30d": 4, "funder": None, "funder_amount": None, "funded_at": None}
        if w in (B, C2):
            res["funder"], res["funder_amount"], res["funded_at"] = FUND, 5.0, self.L - 86400
        if w == DEV:
            res["funder"] = FUND
        for d in self.early:
            if w in d.signers:
                res["deltas"].append(d)
        sell = rpc_tx("sell-" + w[:7], 2000, self.L + 600, w, native={w: (10**9, 4 * 10**9)}, tokens=[(w, MINT, 1000, 0)])
        if w == A:
            res["deltas"].append(deltas.from_rpc(sell))
        return res

    def balances(self, ws):
        return {w: 12.5 for w in ws}


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.c = db.connect()
        self.fake = FakeHelius()
        scan.provider = lambda chain: self.fake
        market.native_usd = lambda chain: 150.0
        market.token_market = lambda chain, t: {"symbol": "TEST", "name": "Test", "price_usd": 0.0001, "launch_ts": self.fake.L, "pools": [], "liq": 20000}
        market.dexscreener_tokens = lambda chain, ts: {t: {"price_usd": 0.0001, "launch_ts": self.fake.L, "liq": 20000, "is_pumpfun": 1, "symbol": "TEST"} for t in ts}

    def test_scan_token_end_to_end(self):
        r = scan.Scanner(self.c, progress=lambda m: None).scan_token("solana", MINT)
        self.assertEqual(r["early_buyers"], 4)  # incluye la compra del dev en la creación
        rows = {x["address"]: dict(x) for x in self.c.execute("SELECT * FROM wallets")}
        self.assertEqual(set(rows), {A, B, C2, DEV})
        a = json.loads(rows[A]["metrics"])
        self.assertAlmostEqual(a["pnl_native"], 3.0 - 1.0 + 0, places=3)
        tb = json.loads(rows[B]["tags"])
        self.assertIn("bundle", tb)        # B y C compraron en el mismo slot
        self.assertIn("insider", tb)       # mismo fondeador que el dev
        self.assertEqual(rows[B]["cluster_id"], rows[C2]["cluster_id"])
        self.assertIn("sniper", json.loads(rows[A]["tags"]))
        d = export.write(self.c)
        self.assertEqual(d["stats"]["total"], 4)
        self.assertEqual(d["stats"]["bundles"], 1)
        self.assertGreaterEqual(d["stats"]["clusters"], 1)
        self.assertTrue(os.path.exists(os.environ["WH_DATA"]))
        wa = next(w for w in d["wallets"] if w["a"] == A)
        self.assertNotIn("al", wa)                      # alias privados: nunca en el json público
        self.assertIn("lf", wa); self.assertIn("tr", wa); self.assertIn("fa", wa)
        self.assertEqual(d["chains"]["solana"]["exn"], "Solscan"); self.assertEqual(d["chains"]["ethereum"]["gmgn"], "eth")

    def test_jobs(self):
        jid = jobs.enqueue(self.c, "tokens", "solana", [MINT], origin="test")
        j = jobs.next_pending(self.c)
        self.assertEqual(j["id"], jid)
        self.assertEqual(jobs.run_job(self.c, j), "done")
        self.assertEqual(self.c.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0], "done")


class TestEvm(unittest.TestCase):
    def test_build_deltas_buy_sell(self):
        os.environ["ETHERSCAN_API_KEY"] = "x" * 34
        from wallethunter.evm import EvmClient
        cl = EvmClient("ethereum")
        os.environ.pop("ETHERSCAN_API_KEY")
        w, tok, pool, router = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40, "0x" + "d" * 40
        txl = [{"hash": "h1", "timeStamp": "1000", "blockNumber": "10", "from": w, "to": router, "value": str(10**18), "gasUsed": "100000", "gasPrice": str(10**10), "isError": "0"},
               {"hash": "h2", "timeStamp": "2000", "blockNumber": "20", "from": w, "to": router, "value": "0", "gasUsed": "100000", "gasPrice": str(10**10), "isError": "0"}]
        toks = [{"hash": "h1", "timeStamp": "1000", "blockNumber": "10", "from": pool, "to": w, "value": str(500 * 10**18), "tokenDecimal": "18", "contractAddress": tok},
                {"hash": "h2", "timeStamp": "2000", "blockNumber": "20", "from": w, "to": pool, "value": str(500 * 10**18), "tokenDecimal": "18", "contractAddress": tok}]
        internal = [{"hash": "h2", "timeStamp": "2000", "blockNumber": "20", "from": router, "to": w, "value": str(3 * 10**18), "isError": "0"}]
        ds = {d.tx: d for d in cl.build_deltas(w, txl, toks, internal)}
        s1, _ = deltas.extract(ds["h1"], w, 3000)
        s2, _ = deltas.extract(ds["h2"], w, 3000)
        self.assertEqual(s1[0]["side"], "buy"); self.assertAlmostEqual(s1[0]["native_amount"], 1.001)
        self.assertEqual(s2[0]["side"], "sell"); self.assertAlmostEqual(s2[0]["native_amount"], 2.999)

    def test_backend_choice(self):
        from wallethunter import evm
        os.environ.pop("ETHERSCAN_API_KEY", None)
        self.assertEqual(evm.backend("base")[0], "blockscout")
        with self.assertRaises(evm.NoBackend):
            evm.backend("bsc")
        with self.assertRaises(evm.NoBackend):
            evm.backend("robinhood")


class TestServer(unittest.TestCase):
    def test_pin_and_scan(self):
        import urllib.request, urllib.error
        from wallethunter import server, pin
        os.environ["WH_PORT"] = "18797"
        server.PORT = 18797
        srv = server.start_server()
        def post(path, body):
            req = urllib.request.Request(f"http://127.0.0.1:18797{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        self.assertEqual(post("/api/check", {"pin": "1234"})[0], 403)  # sin PIN configurado
        pin.set_pin("482913")
        self.assertEqual(post("/api/check", {"pin": "0000"})[0], 401)
        self.assertEqual(post("/api/check", {"pin": "482913"})[0], 200)
        code, r = post("/api/scan", {"pin": "482913", "kind": "tokens", "chain": "solana", "items": MINT})
        self.assertEqual(code, 200); self.assertEqual(r["items"], [MINT])
        code, r = post("/api/favs", {"pin": "482913", "op": "add", "chain": "solana", "address": A, "alias": "ballena 1"})
        self.assertEqual(r["favs"][0]["alias"], "ballena 1")
        code, r = post("/api/aliases", {"pin": "0000", "op": "set", "chain": "solana", "address": B, "alias": "x"})
        self.assertEqual(code, 401)
        code, r = post("/api/aliases", {"pin": "482913", "op": "set", "chain": "solana", "address": B, "alias": "  insider dev  "})
        self.assertEqual(code, 200); self.assertIn({"chain": "solana", "address": B, "alias": "insider dev"}, [{k: a[k] for k in ("chain", "address", "alias")} for a in r["aliases"]])
        self.assertIn(A, [a["address"] for a in r["aliases"]])   # el alias del favorito también queda guardado
        code, r = post("/api/aliases", {"pin": "482913", "op": "set", "chain": "solana", "address": B, "alias": ""})
        self.assertNotIn(B, [a["address"] for a in r["aliases"]])
        code, r = post("/api/settings", {"pin": "482913", "alerts": {"min_inflow_usd": 5000, "enabled": False}})
        self.assertEqual(r["alerts"]["min_inflow_usd"], 5000)
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
