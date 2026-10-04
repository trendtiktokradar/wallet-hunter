"""Smart money cruzado, vigilante (dormidas, fondeadores, entradas) y Telegram con proveedores falsos (sin APIs)."""
import os, sys, json, time, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "WH_STATE_DIR" not in os.environ:
    _tmp = tempfile.mkdtemp()
    os.environ.update(WH_STATE_DIR=_tmp, WH_DB=os.path.join(_tmp, "t.db"), WH_DATA=os.path.join(_tmp, "data.json"))
for k in ("HELIUS_API_KEY", "ETHERSCAN_API_KEY", "BLOCKSCOUT_API_KEY", "WH_PIN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    os.environ.pop(k, None)
from helpers import rpc_tx
from wallethunter import db, smartx, watcher, telegram, config, export

NOW = int(time.time())
L = 10 ** 9
S1, S2, S3, BOTW = ("SxOne" + "1" * 39, "SxTwo" + "2" * 39, "SxThree" + "3" * 37, "SxBot" + "4" * 39)
TA, TB, TC = "SxTokA" + "a" * 34 + "pump", "SxTokB" + "b" * 34 + "pump", "SxTokC" + "c" * 34 + "pump"
FAV1, FAV2 = "FavOne" + "1" * 38, "FavTwo" + "2" * 38
MOM, KID, OLD = "MomWal" + "m" * 38, "NewKid" + "k" * 38, "OldWal" + "o" * 38
BINANCE = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"
POOL = "Curve111111111111111111111111111111111111"


def reset(c):
    for t in ("favorites", "alerts", "fav_funders"):
        c.execute(f"DELETE FROM {t}")
    c.execute("DELETE FROM kv WHERE key LIKE 'watch:%' OR key LIKE 'lasttrade:%' OR key LIKE 'dormant:%' OR key LIKE 'fwatch:%' OR key LIKE 'funderlookup:%' OR key LIKE 'telegram:%'")
    c.commit()


def settings(**kw):
    config.save_settings(kw)


class FakeSol:
    """Proveedor Solana falso: firmas, gtfa y getTransfersByAddress (cuenta los créditos que costaría)."""
    def __init__(self):
        self.sigs, self.txs, self.transfers, self.credits = {}, {}, {}, 0

    def gtfa_available(self):
        return True

    def signatures(self, a, limit=50):
        self.credits += 1
        return sorted(self.sigs.get(a, []), key=lambda s: -s["blockTime"])[:limit]

    def gtfa(self, a, order="desc", limit=100, filters=None):
        self.credits += 10
        gt = ((filters or {}).get("blockTime") or {}).get("gt", 0)
        return {"data": [t for t in self.txs.get(a, []) if t["blockTime"] > gt][:limit]}

    def rpc(self, method, params, credits=0):
        self.credits += credits
        assert method == "getTransfersByAddress"
        return {"data": self.transfers.get(params[0], [])}


def buy(sig, ts, w, tok, sol=1.0):
    return rpc_tx(sig, 1000 + ts % 1000, ts, w, native={w: (100 * L, int((100 - sol) * L)), POOL: (L, int((1 + sol) * L))},
                  tokens=[(w, tok, 0, 1000), (POOL, tok, 10 ** 9, 10 ** 9 - 1000)], programs=["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"])


class TestSmartX(unittest.TestCase):
    def setUp(self):
        c = self.c = db.connect()
        for t in (TA, TB, TC):
            c.execute("INSERT OR REPLACE INTO tokens(chain,address,symbol,launch_ts,scanned_at) VALUES('solana',?,?,?,?)", (t, t[:6], NOW - 9 * 86400, NOW))
            c.execute("INSERT OR REPLACE INTO token_prices(chain,token,symbol,price_native,launch_ts) VALUES('solana',?,?,?,?)", (t, t[:6], 0.0, NOW - 9 * 86400))
        sw = []
        def trade(w, tok, rank, cost, proceeds, i):
            c.execute("INSERT OR REPLACE INTO token_buyers(chain,token,wallet,first_buy_ts,rank,native_spent,kind) VALUES('solana',?,?,?,?,?,'early')", (tok, w, NOW - 8 * 86400 + i, rank, cost))
            sw.append(("solana", w, tok, f"b{w[:6]}{tok[:6]}", NOW - 8 * 86400 + i, 1, "buy", 1000, cost, "pump"))
            sw.append(("solana", w, tok, f"s{w[:6]}{tok[:6]}", NOW - 7 * 86400 + i, 2, "sell", 1000, proceeds, "pump"))
        trade(S1, TA, 3, 1, 4, 1); trade(S1, TB, 7, 1, 3, 2); trade(S1, TC, 12, 1, 2, 3)   # 3 coins, todas en positivo
        trade(S2, TA, 5, 2, 3, 4); trade(S2, TB, 40, 1, 0.2, 5)                             # pierde en TB: solo 1 coin buena
        trade(S3, TA, 9, 1, 2, 6); trade(S3, TC, 30, 1, 1.5, 7)                             # 2 coins buenas
        trade(BOTW, TA, 1, 1, 5, 8); trade(BOTW, TB, 2, 1, 5, 9)                            # bot: fuera
        c.executemany("INSERT OR REPLACE INTO swaps(chain,wallet,token,tx,ts,slot,side,token_amount,native_amount,dex) VALUES(?,?,?,?,?,?,?,?,?,?)", sw)
        for w, tags in ((S1, []), (S2, []), (S3, ["smart"]), (BOTW, ["bot"])):
            c.execute("INSERT OR REPLACE INTO wallets(chain,address,status,tags,score,prefiltered) VALUES('solana',?,'done',?,60,0)", (w, json.dumps(tags)))
        c.commit()

    def tearDown(self):
        c = self.c
        for t in (TA, TB, TC):
            for tb in ("tokens", "token_prices"):
                c.execute(f"DELETE FROM {tb} WHERE {'address' if tb == 'tokens' else 'token'}=?", (t,))
            c.execute("DELETE FROM token_buyers WHERE token=?", (t,)); c.execute("DELETE FROM swaps WHERE token=?", (t,))
        c.execute(f"DELETE FROM wallets WHERE address IN (?,?,?,?)", (S1, S2, S3, BOTW)); c.commit()

    def test_cross(self):
        out = [r for r in smartx.build(self.c) if r["a"] in (S1, S2, S3, BOTW)]
        self.assertEqual([r["a"] for r in out], [S1, S3])           # orden: nº de coins y luego PnL
        r1 = out[0]
        self.assertEqual(r1["n"], 3); self.assertAlmostEqual(r1["pn"], 3 + 2 + 1, places=2)
        self.assertEqual([x["t"] for x in r1["coins"]], [TA, TB, TC]); self.assertEqual(r1["coins"][0]["r"], 3)
        self.assertEqual(out[1]["n"], 2)

    def test_rank_and_export(self):
        config.save_settings({}); config._cfg = None
        with mock.patch.object(smartx, "conf", return_value=dict(smartx.DEFAULTS, early_rank=10)):
            out = [r for r in smartx.build(self.c) if r["a"] in (S1, S3)]
        self.assertEqual([r["a"] for r in out], [S1])                # S3 compró TC en el puesto 30
        self.assertEqual(out[0]["n"], 2)
        d = export.build(self.c) if hasattr(export, "build") else None
        if d:
            self.assertIn("smartx", d); self.assertEqual(d["smartx_cfg"]["min_coins"], 2)


class TestWatcher(unittest.TestCase):
    def setUp(self):
        self.c = db.connect(); reset(self.c)
        settings(enabled=False, dormant_alert=True, dormant_days=7, funder_watch=False, min_inflow_native={"solana": 1.0}, min_inflow_usd=1e9, only_from_funder_or_cex=False)
        self.p = FakeSol()

    def fav(self, w):
        self.c.execute("INSERT OR REPLACE INTO favorites(chain,address,alias,added) VALUES('solana',?,NULL,?)", (w, NOW)); self.c.commit()

    def test_dormant_once_per_streak(self):
        self.fav(FAV1)
        self.p.txs[FAV1] = [buy("d1", NOW - 10 * 86400, FAV1, TA)]
        n = watcher.run(self.c, {"solana": self.p}, NOW)              # primera vez: lee su último trade (10 créditos) y ya ve que está dormida
        self.assertEqual(n, 1); self.assertEqual(watcher.last_trade(self.c, "solana", FAV1), NOW - 10 * 86400)
        self.assertEqual(self.p.credits, 10)
        self.assertEqual(watcher.run(self.c, {"solana": self.p}, NOW + 60), 0)
        a = dict(self.c.execute("SELECT * FROM alerts WHERE kind='dormant'").fetchone())
        self.assertEqual(json.loads(a["data"])["days"], 10)
        self.assertEqual(watcher.run(self.c, {"solana": self.p}, NOW + 120), 0)        # misma racha: no se repite
        # vuelve a tradear y se para otra vez -> nuevo aviso
        t2 = NOW + 200
        self.p.sigs[FAV1] = [{"signature": "d2", "blockTime": t2, "err": None}]
        self.p.txs[FAV1] = [buy("d2", t2, FAV1, TB)] + self.p.txs[FAV1]
        self.assertEqual(watcher.run(self.c, {"solana": self.p}, t2 + 100), 0)
        self.assertEqual(watcher.last_trade(self.c, "solana", FAV1), t2)
        self.assertEqual(watcher.run(self.c, {"solana": self.p}, t2 + 8 * 86400), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM alerts WHERE kind='dormant'").fetchone()[0], 2)

    def test_active_not_dormant_and_inflow(self):
        settings(enabled=True)
        self.fav(FAV2)
        self.p.txs[FAV2] = [buy("a1", NOW - 3600, FAV2, TA)]
        watcher.run(self.c, {"solana": self.p}, NOW)
        t = NOW + 30
        self.p.sigs[FAV2] = [{"signature": "in1", "blockTime": t, "err": None}]
        self.p.txs[FAV2] = [rpc_tx("in1", 5, t, BINANCE, native={BINANCE: (900 * L, 895 * L), FAV2: (L, 6 * L)}, transfers=[(BINANCE, FAV2, 5 * L)])]
        n = watcher.run(self.c, {"solana": self.p}, t + 10)
        self.assertEqual(n, 1)
        a = dict(self.c.execute("SELECT * FROM alerts").fetchone())
        self.assertEqual((a["kind"], round(a["amount_native"], 2), a["sender"]), ("inflow", 5.0, BINANCE)); self.assertIn("Binance", a["sender_label"])
        self.assertEqual(watcher.run(self.c, {"solana": self.p}, t + 20), 0)

    def test_funder_new_wallet(self):
        settings(funder_watch=True, dormant_alert=False, funder_min_native={"solana": 1.0}, funder_new_max_txs=5)
        self.fav(FAV1); self.fav(FAV2)
        self.c.execute("INSERT OR REPLACE INTO wallets(chain,address,status,funder,funder_label) VALUES('solana',?,'done',?,NULL)", (FAV1, MOM))
        self.c.execute("INSERT OR REPLACE INTO wallets(chain,address,status,funder,funder_label) VALUES('solana',?,'done',?,'CEX Binance')", (FAV2, BINANCE))
        self.c.commit()
        try:
            self.assertEqual(watcher.run(self.c, {"solana": self.p}, NOW), 0)     # primera pasada: empieza a vigilar desde ahora
            fl = {f["address"]: f for f in watcher.funder_list(self.c)}
            self.assertTrue(fl[MOM]["watch"]); self.assertEqual(fl[MOM]["children"], [FAV1])
            self.assertFalse(fl[BINANCE]["watch"]); self.assertEqual(fl[BINANCE]["why"], "exchange")
            t = NOW + 100
            self.p.sigs[MOM] = [{"signature": "f1", "blockTime": t, "err": None}, {"signature": "f2", "blockTime": t + 1, "err": None}, {"signature": "f3", "blockTime": t + 2, "err": None}]
            self.p.transfers[MOM] = [
                {"type": "transfer", "toUserAccount": KID, "uiAmount": 3.0, "blockTime": t, "signature": "f1"},
                {"type": "transfer", "toUserAccount": OLD, "uiAmount": 4.0, "blockTime": t + 1, "signature": "f2"},     # wallet vieja: no
                {"type": "transfer", "toUserAccount": "Tiny" + "t" * 40, "uiAmount": 0.1, "blockTime": t + 2, "signature": "f3"}]   # poco
            self.p.sigs[KID] = [{"signature": "k1", "blockTime": t, "err": None}]
            self.p.sigs[OLD] = [{"signature": f"o{i}", "blockTime": t - i, "err": None} for i in range(20)]
            before = self.p.credits
            self.assertEqual(watcher.run(self.c, {"solana": self.p}, t + 60), 1)
            a = dict(self.c.execute("SELECT * FROM alerts WHERE kind='funder'").fetchone())
            self.assertEqual((a["wallet"], a["sender"], a["tx"]), (KID, MOM, "funder:f1"))
            d = json.loads(a["data"]); self.assertEqual(d["children"], [FAV1]); self.assertEqual(d["txs"], 1)
            self.assertEqual(self.p.credits - before, 1 + 10 + 2)    # firmas del madre + transfers + 2 receptores comprobados
            self.assertEqual(watcher.run(self.c, {"solana": self.p}, t + 120), 0)     # ya avisada / nada nuevo
            e = watcher.estimate(self.c)
            self.assertEqual(e["funders_sol"], 1); self.assertGreater(e["funder"], 0); self.assertEqual(e["dormant"], 0)
        finally:
            self.c.execute("DELETE FROM wallets WHERE address IN (?,?)", (FAV1, FAV2)); self.c.commit()

    def test_estimate(self):
        settings(enabled=False, dormant_alert=True, dormant_poll_minutes=60, funder_watch=False)
        self.fav(FAV1); self.fav(FAV2)
        e = watcher.estimate(self.c)
        self.assertEqual(e["favorites_sol"], 2); self.assertEqual(e["dormant"], round(24 * 2 * 2.5)); self.assertEqual(e["total"], e["dormant"])


class TestTelegram(unittest.TestCase):
    def setUp(self):
        self.c = db.connect(); reset(self.c)
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:FAKE-token-for-tests"
        telegram._me.update(t=0, v=None)

    def tearDown(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None); reset(self.c)

    def test_detect_and_send(self):
        calls = []
        ups = []
        def api(method, body=None, retries=2):
            calls.append((method, body))
            if method == "getMe":
                return {"username": "Test_bot"}
            if method == "getUpdates":
                return ups
            if method == "sendMessage":
                return {"message_id": 1}
        with mock.patch.object(telegram, "_api", side_effect=api):
            self.assertIsNone(telegram.detect_chat())
            st = telegram.status(); self.assertEqual((st["token"], st["chat"], st["bot"]), (True, False, "Test_bot")); self.assertTrue(st["last_detect"])
            self.assertFalse(telegram.send("hola"))                 # sin chat: no se envía
            ups.extend([{"update_id": 1, "message": {"date": NOW, "chat": {"id": -100, "type": "group", "title": "g"}}},
                        {"update_id": 2, "message": {"date": NOW, "chat": {"id": 777, "type": "private", "first_name": "Alex"}}}])
            ch = telegram.detect_chat()
            self.assertEqual(ch["id"], "777")                        # prefiere el chat privado
            self.assertTrue(telegram.status()["chat"]); self.assertEqual(telegram.status()["chat_name"], "Alex")
            self.assertTrue(telegram.send("hola"))
            self.assertEqual(calls[-1][0], "sendMessage"); self.assertEqual(calls[-1][1]["chat_id"], "777")

    def test_watcher_retries_detection(self):
        n = []
        with mock.patch.object(telegram, "detect_chat", side_effect=lambda: n.append(1)), mock.patch.object(telegram, "bot", return_value="b"):
            settings(enabled=False, dormant_alert=False, funder_watch=False)
            last = {}
            watcher.tick(self.c, {}, last, now=1000); watcher.tick(self.c, {}, last, now=1030); watcher.tick(self.c, {}, last, now=1061)
        self.assertEqual(len(n), 2)                                   # cada 60 s mientras no haya chat


class TestSettingsApi(unittest.TestCase):
    def test_api(self):
        import urllib.request, urllib.error
        from wallethunter import server, pin
        reset(db.connect())
        server.PORT = 18799
        srv = server.start_server()
        if not pin.is_set():
            pin.set_pin("482913")
        P = "482913"
        def post(path, body):
            req = urllib.request.Request(f"http://127.0.0.1:18799{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            self.assertEqual(post("/api/settings", {"pin": "0"})[0], 401)
            code, r = post("/api/settings", {"pin": P, "alerts": {"dormant_days": 400, "funder_watch": True, "funder_poll_minutes": 1, "funder_min_native": {"solana": 2.5, "nope": 3}, "dormant_alert": False}})
            self.assertEqual(code, 200)
            a = r["alerts"]
            self.assertEqual((a["dormant_days"], a["funder_watch"], a["funder_poll_minutes"], a["dormant_alert"]), (365, True, 10, False))
            self.assertEqual(a["funder_min_native"]["solana"], 2.5); self.assertNotIn("nope", a["funder_min_native"])
            self.assertIn("total", r["estimate"]); self.assertEqual(r["telegram"]["token"], False); self.assertEqual(r["funders"], [])
            code, r = post("/api/telegram", {"pin": P, "op": "test"})
            self.assertEqual(code, 400); self.assertIn("token", r["error"])
            code, r = post("/api/favs", {"pin": P, "op": "add", "chain": "solana", "address": FAV1})
            self.assertEqual(code, 200); f = r["favs"][0]
            self.assertIn("last_trade", f); self.assertEqual(f["funders"], []); self.assertEqual(r["dormant_days"], 365)
            post("/api/favs", {"pin": P, "op": "remove", "chain": "solana", "address": FAV1})
        finally:
            srv.shutdown()
            config.save_settings({"dormant_days": 7, "funder_watch": False, "funder_poll_minutes": 15, "dormant_alert": True, "funder_min_native": {"solana": 1.0}})


if __name__ == "__main__":
    unittest.main()
