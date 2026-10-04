"""Wallets de servicios compartidos (Relay, Axiom, bots…) y autodetección «servicio/hub»: fixtures sin llamadas a APIs."""
import os, sys, json, time, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "WH_STATE_DIR" not in os.environ:
    _tmp = tempfile.mkdtemp()
    os.environ.update(WH_STATE_DIR=_tmp, WH_DB=os.path.join(_tmp, "t.db"), WH_DATA=os.path.join(_tmp, "data.json"))
for k in ("HELIUS_API_KEY", "ETHERSCAN_API_KEY", "BLOCKSCOUT_API_KEY", "WH_PIN", "ARKHAM_API_KEY"):
    os.environ.pop(k, None)
from helpers import rpc_tx
from wallethunter import connect, db, deltas, services, graph, config

P = "PPPPkWziSE1VPGUSLDqD1oCam1cogQVwFU4GpVDDYyki"
Q = "QQQQhCbbzwWsFkeLSTKkfrxVrnCPFhBdMq6i1evQcuiL"
R = "RRRRXF69bNHPp5LUMm1pUaCZvCCbQXp4ZSAynrVViF2r"
S = "SSSSwdrRevvKmfWpUCfDpd97J4BJkceVGWcthHVL8E1"
RELAY = "F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe"       # solver de Relay (docs.relay.link)
AXIOM = "7LCZckF6XXGQ1hDY6HFXBKWAtiUgL9QY5vj1C4Bn1Qjj"       # fee wallet de Axiom (DefiLlama)
UNK = "Unkhub1111111111111111111111111111111111111"         # desconocido con cientos de contrapartes → hub
LOW = "Lowfrnd111111111111111111111111111111111111"         # mucha tx pero pocas contrapartes → no es hub
TINY = "Tinyy11111111111111111111111111111111111111"        # poca actividad → ni se muestrea
NOW = int(time.time())
L = 10 ** 9


def send(sig, slot, ts, src, dst, sol):
    return rpc_tx(sig, slot, ts, src, native={src: (100 * L, int((100 - sol) * L)), dst: (L, int((1 + sol) * L))}, transfers=[(src, dst, int(sol * L))])


class Fake:
    unit = "créditos (prueba)"

    def __init__(self):
        self.credits, self.calls = 0, []
        t = NOW - 10 * 86400
        txs = [send("rp", 10, t, RELAY, P, 1.0), send("rq", 11, t + 50, RELAY, Q, 1.2),        # Relay fondeó a P y Q
               send("qa", 20, t + 900, Q, AXIOM, 0.05), send("ra", 21, t + 990, R, AXIOM, 0.05), send("sa", 22, t + 1200, S, AXIOM, 0.05),
               send("rs", 30, t + 3000, R, S, 2.0),                                              # vínculo real R → S
               send("up", 40, t + 5000, UNK, P, 0.5), send("us", 41, t + 5100, UNK, S, 0.5),
               send("lq", 50, t + 6000, LOW, Q, 0.3), send("ls", 51, t + 6100, LOW, S, 0.3),
               send("tp", 60, t + 7000, TINY, P, 0.2), send("tr", 61, t + 7100, TINY, R, 0.2)]
        self.hist = {w: [] for w in (P, Q, R, S)}
        for tx in txs:
            d = deltas.from_rpc(tx)
            for w in self.hist:
                if w in d.native:
                    self.hist[w].append(d)
        self.funders = {P: (RELAY, 1.0, "rp"), Q: (RELAY, 1.2, "rq")}

    def profile(self, w):
        self.credits += 10
        return {"deltas": self.hist[w], "truncated": False}

    def pair(self, a, b):
        self.credits += 10
        return [], False

    def funder(self, addr):
        self.credits += 10
        f = self.funders.get(addr)
        return {"address": f[0], "amount": f[1], "ts": NOW - 11 * 86400, "tx": f[2]} if f else None

    def activity(self, addr):
        self.credits += 10
        self.calls.append(("activity", addr))
        return {UNK: {"n": 400, "more": False, "span_h": 3000.0}, LOW: {"n": 500, "more": False, "span_h": 4000.0}}.get(addr, {"n": 20, "more": False, "span_h": 900.0})

    def counterparties(self, addr, pages, need):
        self.credits += 10
        self.calls.append(("cp", addr))
        return {"distinct": 320 if addr == UNK else 12, "sampled": 100}


def pair_of(res, a, b):
    return next(p for p in res["pairs"] if {p["a"], p["b"]} == {a, b})


class TestServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = db.connect(os.path.join(os.environ["WH_STATE_DIR"], "svc_test.db"))
        cls.c.execute("DELETE FROM svc_cache")
        cls._ti = connect._token_info
        connect._token_info = lambda c, chain, toks: {}
        cls.src = Fake()
        cls.res = connect.run(cls.c, "solana", [P, Q, R, S], source=cls.src, nusd=150.0)

    @classmethod
    def tearDownClass(cls):
        connect._token_info = cls._ti

    def test_registry(self):
        e = services.known("solana", RELAY)
        self.assertEqual(e["name"], "Relay"); self.assertTrue(e["verified"]); self.assertEqual(e["icon"], "🔁"); self.assertIn("relay.link", e["source"])
        self.assertEqual(services.known("base", "0xF70DA97812CB96ACDF810712AA562DB8DFA3DBEF")["name"], "Relay")   # EVM sin importar mayúsculas
        self.assertTrue(services.ignored("solana", "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"))               # Jito: se ignora
        self.assertIn("96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", connect.INFRA["solana"])
        self.assertIsNone(services.known("solana", P))
        st = services.stats()
        self.assertGreater(st["solana"]["verified"], 100); self.assertGreater(st["solana"]["guessed"], 0); self.assertGreater(st["evm"]["verified"], 40)
        for need in ("Relay", "deBridge (DLN)", "Wormhole", "Mayan", "Across", "Allbridge", "Fomo", "Phantom (swap fee)", "Jupiter", "Photon", "BullX",
                     "Axiom", "GMGN", "Trojan", "BonkBot", "Maestro", "Banana Gun", "Moonshot", "pump.fun (comisiones)"):
            self.assertIn(need, st["solana"]["names"])
        for need in ("Relay", "LayerZero", "Stargate", "Across", "Wormhole", "Mayan", "deBridge (DLN)", "Allbridge", "Banana Gun", "Maestro"):
            self.assertIn(need, st["evm"]["names"])

    def test_extra_file(self):
        path = os.path.join(config.ROOT, "state", "services_extra.json")
        if os.path.exists(path):
            self.skipTest("hay un services_extra.json real")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            json.dump({"solana": {P: "Mi relayer"}}, open(path, "w"))
            services._extra["t"] = 0
            e = services.known("solana", P)
            self.assertEqual(e["name"], "Mi relayer"); self.assertFalse(e["verified"])
        finally:
            os.remove(path); services._extra["t"] = 0

    def test_known_service_pair(self):
        p = pair_of(self.res, P, Q)
        ev = [e for e in p["ev"] if e["type"] == "service"]
        self.assertTrue(ev and ev[0]["svc"] == "Relay" and ev[0]["w"] == 2, p["ev"])
        self.assertIn("posible conexión solo porque ambas usan Relay", p["reason"])
        self.assertTrue(p["svc_only"]); self.assertLessEqual(p["score"], 5)
        n = next(n for n in self.res["nodes"] if n["id"] == RELAY)
        self.assertEqual((n["kind"], n["label"], n["verified"]), ("service", "🔁 Relay", True))
        es = [e for e in self.res["edges"] if RELAY in (e["a"], e["b"])]
        self.assertTrue(es and all(e.get("svc") == "Relay" for e in es))
        b = next(b for b in self.res["bridges"] if b["address"] == RELAY)
        self.assertFalse(b["madre"]); self.assertTrue(b["hub"]); self.assertEqual(b["service"]["name"], "Relay")
        self.assertEqual(self.res["info"][P]["funder_label"], "🔁 Relay"); self.assertTrue(self.res["info"][P]["funder_service"])

    def test_known_services_cost_nothing(self):
        probed = {a for _, a in self.src.calls}
        self.assertNotIn(RELAY, probed); self.assertNotIn(AXIOM, probed)

    def test_fee_wallet_shared(self):
        p = pair_of(self.res, Q, R)
        self.assertTrue(any(e["type"] == "service" and e["svc"] == "Axiom" for e in p["ev"]))
        self.assertIn("ambas usan Axiom", p["reason"]); self.assertLessEqual(p["score"], 5)

    def test_real_link_plus_service(self):
        p = pair_of(self.res, R, S)
        self.assertGreaterEqual(p["score"], 55); self.assertFalse(p["svc_only"])
        self.assertIn("transferencia directa", p["reason"]); self.assertIn("Además ambas usan Axiom: no cuenta", p["reason"])

    def test_autodetected_hub(self):
        p = pair_of(self.res, P, S)
        ev = next(e for e in p["ev"] if e.get("node") == UNK)
        self.assertEqual(ev["type"], "service"); self.assertIn("un servicio/hub", ev["text"]); self.assertLessEqual(ev["w"], 2)
        n = next(n for n in self.res["nodes"] if n["id"] == UNK)
        self.assertEqual(n["kind"], "service"); self.assertTrue(n["auto"]); self.assertIn("servicio/hub", n["label"]); self.assertIn("320", n["why"])
        self.assertIn(("cp", UNK), self.src.calls)
        hit = services.cache_get(self.c, "solana", UNK)
        self.assertTrue(hit and hit[0] and hit[1]["distinct"] == 320)
        self.assertTrue(any(s_["address"] == UNK and s_["auto"] for s_ in self.res["services"]))
        self.assertTrue(any("Servicios compartidos" in x for x in self.res["notes"]))

    def test_low_diversity_is_not_hub(self):
        p = pair_of(self.res, Q, S)
        ev = next(e for e in p["ev"] if e.get("node") == LOW)
        self.assertEqual(ev["type"], "bridge"); self.assertGreaterEqual(ev["w"], 25)
        self.assertEqual(next(n for n in self.res["nodes"] if n["id"] == LOW)["kind"], "bridge")
        hit = services.cache_get(self.c, "solana", LOW)
        self.assertTrue(hit is not None and hit[0] is False)

    def test_small_wallet_not_probed(self):
        self.assertIn(("activity", TINY), self.src.calls); self.assertNotIn(("cp", TINY), self.src.calls)

    def test_cache_saves_credits(self):
        src2 = Fake()
        res2 = connect.run(self.c, "solana", [P, Q, R, S], source=src2, nusd=150.0)
        self.assertEqual([x for x in src2.calls], [])                      # todo de caché
        self.assertLess(res2["credits"], self.res["credits"])
        self.assertEqual(next(n for n in res2["nodes"] if n["id"] == UNK)["kind"], "service")
        self.assertTrue(any("caché" in x for x in res2["notes"]))

    def test_threshold_configurable(self):
        C = dict(connect.DEFAULTS, service_min_counterparties=400)
        self.assertIsNone(services.judge({"n": 400, "span_h": 3000, "distinct": 320}, C))
        self.assertIsNotNone(services.judge({"n": 400, "span_h": 3000, "distinct": 320}, connect.DEFAULTS))
        self.assertIsNotNone(services.judge({"n": 1000, "span_h": 20}, connect.DEFAULTS))

    def test_many_services_stay_near_zero(self):
        self.assertLessEqual(connect.combine([2, 2]), 4)


class TestGraphServices(unittest.TestCase):
    def test_clusters_ignore_service_funders(self):
        c = db.connect(os.path.join(os.environ["WH_STATE_DIR"], "svc_graph.db"))
        for t in ("wallets", "svc_cache", "funders", "transfers"):
            c.execute(f"DELETE FROM {t}")
        ws = {f"G{i}" + "1" * 39: None for i in range(1, 10)}
        names = list(ws)
        HUBX = "Hubcache11111111111111111111111111111111111"
        PERS = "Personal11111111111111111111111111111111111"
        fund = {names[0]: RELAY, names[1]: RELAY, names[2]: RELAY,         # Relay: servicio conocido
                names[3]: HUBX, names[4]: HUBX,                            # hub autodetectado antes (caché)
                names[5]: PERS, names[6]: PERS}                            # fondeador personal: sí es vínculo
        for w in names:
            c.execute("INSERT INTO wallets(chain,address,status,funder) VALUES('solana',?,'done',?)", (w, fund.get(w)))
        services.cache_put(c, "solana", HUBX, True, 1000, 400, 10.0, "1000+ transacciones en 10 h")
        c.commit()
        sig, clusters, n_links, _ = graph.analyze(c, "solana")
        members = [set(cl["wallets"]) for cl in clusters]
        self.assertIn({names[5], names[6]}, members)
        self.assertFalse(any(names[0] in m for m in members)); self.assertFalse(any(names[3] in m for m in members))
        self.assertEqual(sig[names[0]]["svc"][0]["n"], "Relay"); self.assertEqual(sig[names[0]]["svc"][0]["k"], 3)
        self.assertTrue(sig[names[3]]["svc"][0]["auto"]); self.assertTrue(sig[names[0]]["funder_is_hub"])
        meta = graph.analyze.last_meta
        self.assertEqual(meta["svc_skipped"], 3 + 1)
        self.assertEqual({s["name"] for s in meta["services"]}, {"Relay", "servicio/hub"})

    def test_db_count_autodetect(self):
        c = db.connect(os.path.join(os.environ["WH_STATE_DIR"], "svc_graph2.db"))
        for t in ("wallets", "svc_cache"):
            c.execute(f"DELETE FROM {t}")
        BIG = "Bigfundr11111111111111111111111111111111111"
        cc = config.cfg()["cluster"]
        old = cc.get("service_min_funded")
        cc["service_min_funded"] = 5
        try:
            for i in range(6):
                c.execute("INSERT INTO wallets(chain,address,status,funder) VALUES('solana',?,'done',?)", (f"H{i}" + "1" * 39, BIG))
            c.commit()
            sig, clusters, _, _ = graph.analyze(c, "solana")
            self.assertEqual(clusters, [])
            self.assertTrue(services.cache_get(c, "solana", BIG)[0])
        finally:
            cc.pop("service_min_funded") if old is None else cc.__setitem__("service_min_funded", old)


class TestWatcherServices(unittest.TestCase):
    def test_service_funder_not_watched(self):
        from wallethunter import watcher
        c = db.connect(os.path.join(os.environ["WH_STATE_DIR"], "svc_watch.db"))
        c.execute("DELETE FROM favorites"); c.execute("DELETE FROM fav_funders")
        c.execute("INSERT INTO favorites(chain,address,alias,added) VALUES('solana',?,?,?)", (P, "p", NOW))
        c.execute("INSERT INTO fav_funders(chain,wallet,funder,label,source,ts) VALUES('solana',?,?,NULL,'first',?)", (P, RELAY, NOW))
        c.commit()
        f = next(x for x in watcher.funder_list(c) if x["address"] == RELAY)
        self.assertFalse(f["watch"]); self.assertEqual(f["why"], "servicio"); self.assertEqual(f["label"], "🔁 Relay")
        self.assertEqual(watcher.sender_label(c, "solana", RELAY), "servicio Relay")


if __name__ == "__main__":
    unittest.main()
