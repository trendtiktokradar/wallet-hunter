"""Conexiones entre wallets: análisis completo con una fuente falsa (sin llamadas a APIs) + API del box."""
import os, sys, json, time, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "WH_STATE_DIR" not in os.environ:          # (si se ejecuta solo; con discover ya lo preparó test_core)
    _tmp = tempfile.mkdtemp()
    os.environ.update(WH_STATE_DIR=_tmp, WH_DB=os.path.join(_tmp, "t.db"), WH_DATA=os.path.join(_tmp, "data.json"))
for k in ("HELIUS_API_KEY", "ETHERSCAN_API_KEY", "BLOCKSCOUT_API_KEY", "WH_PIN", "ARKHAM_API_KEY"):
    os.environ.pop(k, None)
from helpers import rpc_tx
from wallethunter import connect, db, deltas, jobs, export

A = "AAAAkWziSE1VPGUSLDqD1oCam1cogQVwFU4GpVDDYyki"
B = "BBBBhCbbzwWsFkeLSTKkfrxVrnCPFhBdMq6i1evQcuiL"
C = "CCCCXF69bNHPp5LUMm1pUaCZvCCbQXp4ZSAynrVViF2r"
D = "DDDDwdrRevvKmfWpUCfDpd97J4BJkceVGWcthHVL8E1"
MOM = "MoMxyz1111111111111111111111111111111111111"
X, Y, GRAND = "Xinter111111111111111111111111111111111111", "Yinter111111111111111111111111111111111111", "GrandMa11111111111111111111111111111111111"
HUB = "HubSvc111111111111111111111111111111111111"
BINANCE = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"
POOL = "Curve111111111111111111111111111111111111"
T1, T2 = "Tok1111111111111111111111111111111111pump", "Tok2222222222222222222222222222222222pump"
NOW = int(time.time())
L = 10 ** 9


def send(sig, slot, ts, src, dst, sol):
    return rpc_tx(sig, slot, ts, src, native={src: (100 * L, int((100 - sol) * L)), dst: (L, int((1 + sol) * L))}, transfers=[(src, dst, int(sol * L))])


def buy(sig, slot, ts, w, tok, sol=1.0):
    return rpc_tx(sig, slot, ts, w, native={w: (100 * L, int((100 - sol) * L)), POOL: (L, int((1 + sol) * L))},
                  tokens=[(w, tok, 0, 1000), (POOL, tok, 10 ** 9, 10 ** 9 - 1000)], programs=["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"])


def cosigned(sig, slot, ts, payer, signer):
    tx = rpc_tx(sig, slot, ts, payer, native={payer: (10 * L, 10 * L - 5000), signer: (L, L - 2039280)})
    for k in tx["transaction"]["message"]["accountKeys"]:
        if k["pubkey"] == signer:
            k["signer"] = True
    return tx


class FakeSource:
    unit = "créditos (prueba)"

    def __init__(self, truncated=()):
        self.credits, self.truncated = 0, set(truncated)
        t = NOW - 20 * 86400
        txs = [
            send("fundA", 100, t, MOM, A, 3.0), send("fundB", 101, t + 60, MOM, B, 2.5),        # mismo fondeador (madre)
            send("a2c", 200, t + 3600, A, C, 2.0),                                                # transferencia directa
            send("x2d", 300, t + 7200, X, D, 1.5), send("y2b", 301, t + 7300, Y, B, 0.8),         # 2 saltos: GRAND→X→D, GRAND→Y→B
            send("cexC", 400, t + 9000, BINANCE, C, 1.0), send("cexD", 401, t + 9300, BINANCE, D, 1.05),   # mismo CEX, 5 min
            send("hubA", 500, t + 10000, HUB, A, 0.5), send("hubD", 501, t + 10100, HUB, D, 0.5),          # servicio/hub
            buy("buyA", 5000, t + 20000, A, T1), buy("buyD", 5000, t + 20000, D, T1, 2.0),                # mismo slot
            buy("buyB", 6000, t + 30000, B, T2), buy("buyC", 6300, t + 30120, C, T2),                      # 2 min de diferencia
            cosigned("feeBC", 7000, t + 40000, B, C),                                                      # B paga la comisión de C
            send("dust", 800, t + 50000, "Spam111111111111111111111111111111111111", A, 0.000001),         # spam: se ignora
            send("dustD", 801, t + 50001, "Spam111111111111111111111111111111111111", D, 0.000001),
        ]
        self.hist = {w: [] for w in (A, B, C, D)}
        for tx in txs:
            d = deltas.from_rpc(tx)
            for w in self.hist:
                if w in d.native or any(o == w for (o, m) in d.tokens) or w in d.signers:
                    self.hist[w].append(d)
        self.funders = {A: (MOM, 3.0, "fundA"), B: (MOM, 2.5, "fundB"), C: (BINANCE, 1.0, "cexC"), D: (X, 1.5, "x2d"),
                        X: (GRAND, 4.0, "gx"), Y: (GRAND, 2.0, "gy"), MOM: (BINANCE, 10.0, "bm"), HUB: (BINANCE, 50, "bh")}

    def profile(self, w):
        self.credits += 10
        return {"deltas": self.hist[w], "truncated": w in self.truncated}

    def pair(self, a, b):
        self.credits += 10
        rows = []
        for d in self.hist[a]:
            for s, t, amt in d.native_transfers:
                if {s, t} == {a, b}:
                    rows.append({"tx": d.tx, "ts": d.ts, "from": s, "to": t, "asset": "native", "amount": amt})
        return rows, False

    def funder(self, addr):
        self.credits += 10
        f = self.funders.get(addr)
        return {"address": f[0], "amount": f[1], "ts": NOW - 30 * 86400, "tx": f[2]} if f else None

    def activity(self, addr):
        self.credits += 10
        return {"n": 1000, "more": True, "span_h": 8.0} if addr == HUB else {"n": 12, "more": False, "span_h": 900.0}


def pair_of(res, a, b):
    return next(p for p in res["pairs"] if {p["a"], p["b"]} == {a, b})


class TestConnect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = db.connect()
        connect._token_info = lambda c, chain, toks: {T1: {"sy": "UNO", "lt": NOW - 20 * 86400 + 19000}, T2: {"sy": "DOS", "lt": None}}
        cls.src = FakeSource(truncated=[D])
        cls.res = connect.run(cls.c, "solana", [A, B, C, D], source=cls.src, nusd=150.0)

    def test_direct_transfer(self):
        p = pair_of(self.res, A, C)
        self.assertGreaterEqual(p["score"], 55)
        self.assertIn("transferencia directa", p["reason"])
        e = next(e for e in self.res["edges"] if e["type"] == "transfer")
        self.assertEqual((e["a"], e["b"]), (A, C))
        self.assertEqual(e["ev"][0]["tx"], "a2c"); self.assertAlmostEqual(e["ev"][0]["amt"], 2.0); self.assertEqual(e["ev"][0]["asset"], "SOL")

    def test_common_funder_madre(self):
        p = pair_of(self.res, A, B)
        self.assertGreaterEqual(p["score"], 60)
        self.assertIn("mismo fondeador", p["reason"])
        mom = next(b for b in self.res["bridges"] if b["address"] == MOM)
        self.assertTrue(mom["madre"]); self.assertFalse(mom["hub"]); self.assertEqual(mom["connects"], [A, B])
        node = next(n for n in self.res["nodes"] if n["id"] == MOM)
        self.assertEqual(node["kind"], "bridge"); self.assertTrue(node["madre"])
        self.assertTrue(any(e["type"] == "first" and e["a"] == MOM and e["b"] == A for e in self.res["edges"]))

    def test_two_hops(self):
        p = pair_of(self.res, B, D)
        self.assertTrue(any(e["type"] == "bridge" and e.get("node") == GRAND and "2 saltos" in e["text"] for e in p["ev"]), p["ev"])
        g = next(b for b in self.res["bridges"] if b["address"] == GRAND)
        self.assertTrue(g["madre"]); self.assertIn("2 saltos", g["role"])
        self.assertTrue(any(e["type"] == "hop" and e["a"] == GRAND and e["b"] == X for e in self.res["edges"]))

    def test_same_cex(self):
        p = pair_of(self.res, C, D)
        ev = next(e for e in p["ev"] if e["type"] == "cex")
        self.assertEqual(ev["w"], 35); self.assertIn("Binance", ev["text"]); self.assertIn("5 min", ev["text"])
        self.assertTrue(any(n["id"] == "cex:Binance" and n["kind"] == "cex" for n in self.res["nodes"]))

    def test_same_slot_and_cobuy(self):
        p = pair_of(self.res, A, D)
        self.assertTrue(any(e["type"] == "slot" and "UNO" in e["text"] and "5000" in e["text"] for e in p["ev"]))
        q = pair_of(self.res, B, C)
        co = next(e for e in q["ev"] if e["type"] == "cobuy")
        self.assertIn("DOS", co["text"]); self.assertIn("2 min", co["text"])
        e = next(e for e in self.res["edges"] if e["type"] == "slot")
        self.assertEqual({e["ev"][0]["tx"], e["ev"][0]["tx2"]}, {"buyA", "buyD"})

    def test_fee_payer(self):
        q = pair_of(self.res, B, C)
        self.assertTrue(any(e["type"] == "fee" and e["w"] == 75 for e in q["ev"]))
        self.assertGreaterEqual(q["score"], 75)
        self.assertTrue(q["reason"].startswith("Muy probablemente"))

    def test_hub_and_spam(self):
        hub = next(b for b in self.res["bridges"] if b["address"] == HUB)
        self.assertTrue(hub["hub"]); self.assertFalse(hub["madre"])
        p = pair_of(self.res, A, D)
        hb = next(e for e in p["ev"] if e.get("node") == HUB)
        self.assertLess(hb["w"], 15); self.assertIn("servicio/hub", hb["text"])
        self.assertFalse(any(n["id"].startswith("Spam") for n in self.res["nodes"]))

    def test_notes_credits_and_shape(self):
        r = self.res
        self.assertTrue(any("W4" in n and "truncado" in n for n in r["notes"]))
        self.assertTrue(any("todo su historial" in n for n in r["notes"]))
        self.assertEqual(r["credits"], self.src.credits); self.assertGreater(r["credits"], 0)
        self.assertEqual(len(r["pairs"]), 6)
        self.assertEqual(r["pairs"], sorted(r["pairs"], key=lambda p: -p["score"]))
        ids = {n["id"] for n in r["nodes"]}
        for e in r["edges"]:
            self.assertIn(e["a"], ids); self.assertIn(e["b"], ids)
        for p in r["pairs"]:
            for ev in p["ev"]:
                for eid in ev["edges"]:
                    self.assertIn(eid, {e["id"] for e in r["edges"]})
        self.assertTrue(r["info"][D]["truncated"]); self.assertEqual(r["info"][A]["funder"]["address"], MOM)
        json.dumps(r)

    def test_unrelated(self):
        src = FakeSource()
        src.hist = {A: [], "ZZZZ1111111111111111111111111111111111111": []}
        src.funders = {}
        r = connect.run(None, "solana", [A, "ZZZZ1111111111111111111111111111111111111"], source=src, nusd=150.0)
        self.assertEqual(r["pairs"][0]["score"], 0)
        self.assertTrue(r["pairs"][0]["reason"].startswith("Sin conexión"))

    def test_clean_wallets(self):
        self.assertEqual(connect.clean_wallets(f"{A}\n{B}, {A}"), ("solana", [A, B]))
        with self.assertRaises(ValueError):
            connect.clean_wallets(A)
        with self.assertRaises(ValueError):
            connect.clean_wallets([A, "0x" + "a" * 40])
        self.assertEqual(connect.clean_wallets(["0x" + "A" * 40, "0x" + "b" * 40])[0], "evm")
        with self.assertRaises(ValueError):
            connect.clean_wallets(" ".join([A] * 1 + [B[:-1] + c for c in "23456789ABCD"]))
        with self.assertRaises(ValueError):
            connect.clean_wallets([A, B], "ethereum")

    def test_labeler_pluggable(self):
        lab = connect.Labeler()
        self.assertEqual(lab.label("solana", BINANCE)["name"], "Binance")
        self.assertFalse(connect.ArkhamLabels().enabled())
        class Fake:
            name = "prueba"
            def label(self, chain, a):
                return {"name": "Mi entidad", "kind": "entity", "source": "prueba"} if a == MOM else None
        self.assertEqual(connect.Labeler([Fake()]).label("solana", MOM)["name"], "Mi entidad")

    def test_job_save_and_export(self):
        connect.make_source = lambda chain, C: FakeSource()
        jid = jobs.enqueue(self.c, "connect", "solana", [A, B, C, D], origin="test")
        self.assertIsNone(jobs.next_pending(self.c) if jobs.next_pending(self.c) and jobs.next_pending(self.c)["kind"] == "connect" else None)
        j = jobs.next_pending(self.c, kinds=("connect",))
        self.assertEqual(j["id"], jid)
        self.assertEqual(jobs.run_job(self.c, j), "done")
        r = connect.get_check(self.c, jid)
        self.assertEqual(r["wallets"], [A, B, C, D]); self.assertEqual(r["id"], jid)
        lst = connect.list_checks(self.c)
        self.assertEqual(lst[0]["id"], jid); self.assertEqual(lst[0]["status"], "done"); self.assertGreaterEqual(lst[0]["max_score"], 75)
        d = export.build(self.c)
        pj = next(x for x in d["jobs"] if x["id"] == jid)
        self.assertEqual(pj["kind"], "connect"); self.assertNotIn(A, json.dumps(d["jobs"]))    # wallets completas: solo con PIN
        connect.delete_check(self.c, jid)
        self.assertIsNone(connect.get_check(self.c, jid))


class TestConnectApi(unittest.TestCase):
    def test_api(self):
        import urllib.request, urllib.error
        from wallethunter import server, pin
        server.PORT = 18798
        srv = server.start_server()
        if not pin.is_set():
            pin.set_pin("482913")
        P = "482913"
        def post(path, body):
            req = urllib.request.Request(f"http://127.0.0.1:18798{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        self.assertEqual(post("/api/connect", {"pin": "0000", "wallets": f"{A} {B}"})[0], 401)
        self.assertEqual(post("/api/connect", {"pin": P, "wallets": A})[0], 400)
        code, r = post("/api/connect", {"pin": P, "wallets": [A, "0x" + "a" * 40]})
        self.assertEqual(code, 400); self.assertIn("Solana y EVM", r["error"])
        code, r = post("/api/connect", {"pin": P, "wallets": f"{A}\n{B}", "chain": "auto"})
        self.assertEqual(code, 200); self.assertEqual(r["chain"], "solana"); jid = r["id"]
        code, r = post("/api/checks", {"pin": P, "op": "status", "id": jid})
        self.assertEqual(code, 200); self.assertEqual(r["status"], "pending"); self.assertEqual(r["wallets"], [A, B])
        self.assertIn(jid, [x["id"] for x in post("/api/checks", {"pin": P, "op": "list"})[1]["checks"]])
        self.assertEqual(post("/api/checks", {"pin": P, "op": "status", "id": "nope"})[0], 404)
        code, r = post("/api/checks", {"pin": P, "op": "delete", "id": jid})
        self.assertNotIn(jid, [x["id"] for x in r["checks"]])
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
