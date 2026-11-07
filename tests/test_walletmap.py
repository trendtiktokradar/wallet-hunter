"""Mapa de wallets: fondeo, saltos, servicios, coin y coincidencia. Sin red y sin claves."""
import os, sys, json, time, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "WH_STATE_DIR" not in os.environ:
    _tmp = tempfile.mkdtemp()
    os.environ.update(WH_STATE_DIR=_tmp, WH_DB=os.path.join(_tmp, "t.db"), WH_DATA=os.path.join(_tmp, "data.json"))
for k in ("HELIUS_API_KEY", "ETHERSCAN_API_KEY", "BLOCKSCOUT_API_KEY", "WH_PIN", "ARKHAM_API_KEY"):
    os.environ.pop(k, None)

from helpers import rpc_tx
from wallethunter import db, deltas, export, jobs, walletmap
from wallethunter.chains import is_sol_address

A = "AAAAkWziSE1VPGUSLDqD1oCam1cogQVwFU4GpVDDYyki"
B = "BBBBhCbbzwWsFkeLSTKkfrxVrnCPFhBdMq6i1evQcuiL"
C = "CCCCXF69bNHPp5LUMm1pUaCZvCCbQXp4ZSAynrVViF2r"
D = "DDDDwdrRevvKmfWpUCfDpd97J4BJkceVGWcthHVL8E1"
X = "Xinter111111111111111111111111111111111111"
Y = "Yinter222222222222222222222222222222222222"
M = "MoMxyz1111111111111111111111111111111111111"
N = "Nfund2222222222222222222222222222222222222"
Z = "Zunkn1111111111111111111111111111111111111"
BINANCE = "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"
RELAY = "F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe"
JITO = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
MIXED = "Aa1Bb2Cc3Dd4Ee5Ff6Gg7Hh8Jj9KkMmNnPpQqRrSsTt"
POOL = "Curve111111111111111111111111111111111111"
MINT = "Mint1111111111111111111111111111111111pump"
SIG = "1" * 88
NOW = int(time.time())
L = 10 ** 9


def tok(n):
    return ("Tok" + f"{n:02d}" + ("1" * 40))[:40]


def row(tx, ts, src, dst, sol, kind="native_in", swap=None, asset="native"):
    return {"tx": tx, "ts": ts, "from": src, "to": dst, "asset": asset, "amount": sol, "kind": kind, "swap": swap}


def swap_row(tx, ts, wallet, token, side="buy", sol=0.2):
    return row(tx, ts, wallet if side == "buy" else "poolx", "poolx" if side == "buy" else wallet, sol,
               kind="swap_" + side,
               swap={"side": side, "token": token, "token_amount": 10, "native_amount": sol, "wallet": wallet})


def page(rows, truncated=False, cursor=None, parsed=True, error=None):
    return {"rows": rows, "truncated": truncated, "next_cursor": cursor, "parsed": parsed, "error": error}


class Src:
    def __init__(self, pages, early=None, interval=None):
        self.pages, self.early, self.interval = pages, early or {}, interval or {}
        self.n = 0

    def read(self, addr, before=None, limit=100):
        self.n += 1
        item = self.pages.get(addr, page([]))
        if isinstance(item, dict) and "by_cursor" in item:
            return item["by_cursor"][before or ""]
        return item

    def token_early(self, mint, limit):
        self.n += 1
        return self.early.get(mint, {"events": [], "truncated": False})

    def token_interval(self, mint, fr, to, limit):
        self.n += 1
        return self.interval.get(mint, {"events": [], "truncated": False})


def run(c, wallets, src, **kw):
    spec = walletmap.clean_request(dict(wallets=wallets, mode=kw.pop("mode", "wallets"), **{k: v for k, v in kw.items() if k in ("coin", "scope", "hops", "page", "cursors", "from_ts", "to_ts", "ca")}))
    return walletmap.run(c, spec, src, now=NOW, fetch_pool=kw.get("fetch_pool"))


class TestMap(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.c = db.connect(os.path.join(d, "map.db"))

    def test_case_sensitive_solana_and_rejects_evm(self):
        self.assertTrue(is_sol_address(MIXED))
        self.assertNotEqual(MIXED, MIXED.lower())
        spec = walletmap.clean_request({"wallets": MIXED + " " + MIXED.lower() + "\n" + MIXED})
        self.assertEqual(spec["wallets"][0], MIXED)
        self.assertIn(MIXED.lower(), spec["wallets"])
        self.assertEqual(len(spec["wallets"]), 2)
        with self.assertRaises(ValueError):
            walletmap.clean_request({"wallets": "0x" + "ab" * 20})
        self.assertEqual(walletmap.clean_request({"mode": "coin", "coin": MIXED, "wallets": A})["coin"], MIXED)
        src = Src({MIXED: page([row(SIG, NOW - 100, Z, MIXED, 1.5)])})
        res = walletmap.run(self.c, walletmap.clean_request({"wallets": MIXED}), src, now=NOW)
        self.assertIn(MIXED, {n["id"] for n in res["nodes"]})
        self.assertNotIn(MIXED.lower(), {n["id"] for n in res["nodes"]})
        self.assertEqual(res["by_wallet"][MIXED]["funders"][0]["url"], "https://solscan.io/tx/" + SIG)

    def test_multiple_and_direct_funders(self):
        src = Src({A: page([
            row(SIG, NOW - 500, M, A, 3.0),
            row("shorttx", NOW - 400, N, A, 1.25),
            row("dust", NOW - 300, Z, A, 0.001),
        ])})
        res = run(self.c, [A], src)
        funds = res["by_wallet"][A]["funders"]
        self.assertEqual([f["address"] for f in funds], [M, N])
        self.assertAlmostEqual(funds[0]["amount"], 3.0)
        self.assertAlmostEqual(funds[1]["amount"], 1.25)
        self.assertTrue(funds[0]["confirmed"])
        self.assertEqual(funds[0]["url"], "https://solscan.io/tx/" + SIG)
        self.assertIsNone(funds[1]["url"])
        self.assertTrue(any(e["from"] == M and e["to"] == A and e["amount"] == 3.0 for e in res["edges"]))
        self.assertNotIn("sin origen", json.dumps(res["by_wallet"][A]).lower())

    def test_shared_funder_is_hypothesis_not_owner(self):
        src = Src({
            A: page([row("a1", NOW - 50, M, A, 2)]),
            B: page([row("b1", NOW - 40, M, B, 2)]),
        })
        res = run(self.c, [A, B], src)
        node = next(n for n in res["nodes"] if n["id"] == M)
        self.assertIn("Hipótesis", node["hypothesis"])
        self.assertIn("No prueba mismo dueño", node["hypothesis"])
        self.assertNotEqual(node["kind"], "service")
        self.assertFalse(any(h for h in res["coincidences"]))

    def test_service_and_cex_are_not_owners(self):
        src = Src({
            A: page([row("a1", NOW - 50, BINANCE, A, 2), row("a2", NOW - 40, RELAY, A, 1), row("a3", NOW - 30, JITO, A, 0.2)]),
            B: page([row("b1", NOW - 50, BINANCE, B, 2), row("b2", NOW - 40, RELAY, B, 1)]),
        })
        res = run(self.c, [A, B], src, hops=2)
        kinds = {n["id"]: n["kind"] for n in res["nodes"]}
        self.assertEqual(kinds[BINANCE], "cex")
        self.assertEqual(kinds[RELAY], "service")
        self.assertNotIn(JITO, kinds)
        self.assertIsNone(next(n for n in res["nodes"] if n["id"] == BINANCE).get("hypothesis"))
        self.assertTrue(all(e["service"] for e in res["edges"] if e["from"] in (BINANCE, RELAY)))
        self.assertEqual(res["coincidences"], [])
        self.assertTrue(res["rejected"])
        self.assertTrue(all("mismo dueño" not in (n.get("hypothesis") or "") for n in res["nodes"] if n["kind"] in ("cex", "service")))
        self.assertNotIn(BINANCE, res["expanded"])
        self.assertEqual(src.n, 2)

    def test_unknown_stays_unidentified_and_empty_is_not_proof(self):
        src = Src({
            A: page([row("z1", NOW - 20, Z, A, 0.8)]),
            B: page([]),
        })
        res = run(self.c, [A, B], src)
        z = next(n for n in res["nodes"] if n["id"] == Z)
        self.assertEqual(z["kind"], "origin")
        self.assertIsNone(z["label"])
        self.assertFalse(z["identified"])
        self.assertIsNone(z["source"])
        note = res["by_wallet"][B]["coverage"]["note"]
        self.assertIn("no apareció", note)
        self.assertIn("no demuestra", note)
        self.assertNotIn("sin origen", note.lower())
        self.assertEqual(res["by_wallet"][B]["funders"], [])

    def test_unclassified_sol_in_is_not_confirmed_funding(self):
        src = Src({A: page([row("u1", NOW - 20, Z, A, 1.0, kind="sol_in_unclassified")], parsed=False)})
        res = run(self.c, [A], src, hops=2)
        f = res["by_wallet"][A]["funders"][0]
        self.assertFalse(f["confirmed"])
        self.assertIn("no se confirma", f["note"])
        self.assertEqual(res["expanded"], [])
        self.assertNotIn(Z, {n["id"] for n in res["nodes"] if n.get("hypothesis")})

    def test_two_hop_cap(self):
        src = Src({
            A: page([row("ax", NOW - 30, X, A, 1), row("an", NOW - 20, N, A, 0.5)]),
            X: page([row("xy", NOW - 80, Y, X, 4)]),
            N: page([row("nz", NOW - 80, Z, N, 4)]),
            Y: page([row("yz", NOW - 90, Z, Y, 9)]),
        })
        one_src = Src(src.pages)
        one = run(self.c, [A], one_src, hops=1)
        self.assertEqual(one_src.n, 1)
        self.assertIn(X, {n["id"] for n in one["nodes"]})
        self.assertNotIn(Y, {n["id"] for n in one["nodes"]})
        two = run(self.c, [A], src, hops=2)
        self.assertIn(Y, {n["id"] for n in two["nodes"]})
        self.assertTrue(any(e["from"] == Y and e["to"] == X for e in two["edges"]))
        self.assertTrue(any(e["from"] == Z and e["to"] == N for e in two["edges"]))
        # Y no se lee: el fondeador de Y no entra. X y N sí.
        self.assertNotIn(Z, {e["from"] for e in two["edges"] if e["to"] == Y})
        self.assertCountEqual(two["expanded"], [X, N])
        orig = walletmap.limits
        Lims = orig()
        Lims["max_hop_lookups"] = 1
        walletmap.limits = lambda: Lims
        try:
            capped = Src(src.pages)
            res = run(self.c, [A], capped, hops=2)
            self.assertEqual(len(res["expanded"]), 1)
            self.assertTrue(res["coverage"]["partial"])
            self.assertLess(capped.n, 1 + 2)
        finally:
            walletmap.limits = orig

    def test_pagination_and_cache(self):
        p1 = page([row("p1", NOW - 10, M, A, 1)], truncated=True, cursor="cursor_page_2")
        p2 = page([row(SIG, NOW - 20, N, A, 0.6)], truncated=False)
        src = Src({A: {"by_cursor": {"": p1, "cursor_page_2": p2}}})
        first = run(self.c, [A], src, page=1)
        self.assertEqual(first["by_wallet"][A]["funders"][0]["address"], M)
        self.assertEqual(first["by_wallet"][A]["coverage"]["next_cursor"], "cursor_page_2")
        self.assertTrue(first["coverage"]["partial"])
        second = run(self.c, [A], src, page=2, cursors={A: "cursor_page_2"})
        self.assertEqual(second["by_wallet"][A]["funders"][0]["address"], N)
        self.assertEqual(src.n, 2)
        again = run(self.c, [A], src, page=1)
        self.assertEqual(src.n, 2)
        self.assertGreater(again["cache"]["hits"], 0)
        with self.assertRaises(ValueError):
            walletmap.clean_request({"wallets": A, "page": 4})
        with self.assertRaises(ValueError):
            walletmap.clean_request({"wallets": A, "page": 2})

    def test_token_receipt_is_not_a_swap(self):
        buy = rpc_tx("buy1", 10, NOW - 100, A, native={A: (5 * L, 4 * L), POOL: (L, 2 * L)},
                     tokens=[(A, MINT, 0, 1000), (POOL, MINT, 5000, 4000)])
        recv = rpc_tx("recv1", 11, NOW - 90, C, native={C: (L, L), A: (L, L)},
                      tokens=[(C, MINT, 50, 0), (A, MINT, 0, 50)])
        d_buy, d_recv = deltas.from_rpc(buy), deltas.from_rpc(recv)
        rows = walletmap.rows_from_deltas(A, [d_buy, d_recv])
        src = Src({A: page(rows)})
        res = run(self.c, [A], src, mode="coin", coin=MINT)
        kinds = [e["kind"] for e in res["by_wallet"][A]["coin_events"]]
        self.assertIn("swap_buy", kinds)
        self.assertIn("token_in", kinds)
        buy_ev = next(e for e in res["by_wallet"][A]["coin_events"] if e["kind"] == "swap_buy")
        rec_ev = next(e for e in res["by_wallet"][A]["coin_events"] if e["kind"] == "token_in")
        self.assertTrue(buy_ev["verified"])
        self.assertFalse(rec_ev["verified"])
        self.assertIn("no es una compra", rec_ev["label"])
        self.assertEqual(res["by_wallet"][A]["coin_label"], "Compró · verificado")
        self.assertIsNone(res["coin"]["axiom"])
        self.assertIn("Sin pool", res["coin"]["axiom_note"])

    def test_axiom_only_with_pool_and_first_buyers_are_bounded(self):
        self.c.execute("INSERT INTO tokens(chain,address,symbol,pools,status) VALUES('solana',?,'DEMO',?,'ok')",
                       (MINT, json.dumps([{"address": POOL, "liq": 10}])))
        self.c.commit()
        early = {"events": [
            {"address": A, "kind": "swap_buy", "verified": True, "ts": NOW - 100, "tx": SIG, "url": "https://solscan.io/tx/" + SIG, "token_amount": 3, "native_amount": 0.4},
            {"address": B, "kind": "token_in", "verified": False, "ts": NOW - 90, "tx": "recv", "url": None, "token_amount": 1, "native_amount": None},
        ], "truncated": True, "unavailable": None}
        src = Src({A: page([])}, early={MINT: early})
        res = run(self.c, [A], src, mode="coin", coin=MINT, scope="first_buyers")
        self.assertEqual(res["coin"]["axiom"], "https://axiom.trade/meme/" + POOL)
        self.assertEqual(res["coin"]["pool_source"], "base local (escaneo previo)")
        self.assertEqual([b["address"] for b in res["coin"]["buyers"]], [A])
        self.assertEqual([r["address"] for r in res["coin"]["receipts"]], [B])
        self.assertTrue(res["coin"]["buyers_truncated"])
        self.assertIn("no son todos los holders", " ".join(res["coverage"]["notes"]).lower())
        with self.assertRaises(ValueError):
            walletmap.clean_request({"mode": "coin", "coin": MINT, "scope": "interval", "from_ts": NOW - 30 * 86400, "to_ts": NOW, "wallets": []})

    def test_overlap_threshold(self):
        def swaps(addr, tokens, ts=NOW - 1000):
            return [swap_row(f"{addr[:2]}{i}", ts + i, addr, t) for i, t in enumerate(tokens)]

        shared = [tok(i) for i in range(1, 9)]
        pop = tok(99)
        # A y B: 8 coins propias iguales + directa. Badge.
        direct = row("ab", NOW - 30, A, B, 0.4, kind="native_out")
        src = Src({
            A: page(swaps(A, shared) + [direct]),
            B: page(swaps(B, shared, ts=NOW - 800) + [row("ba", NOW - 30, A, B, 0.4, kind="native_in")]),
        })
        res = run(self.c, [A, B], src)
        hit = next(h for h in res["coincidences"] if h["wallet"] == B)
        self.assertGreaterEqual(hit["overlap"], 5)
        self.assertGreaterEqual(hit["ratio"], 0.35)
        self.assertIn("coins distintas", hit["motive"])
        self.assertIn("no una prueba de mismo dueño", hit["motive"])
        self.assertIn("transferencia directa", hit["counterpart_why"])
        node = next(n for n in res["nodes"] if n["id"] == B)
        self.assertTrue(node["coincidence"])

        def fresh():
            self.c.execute("DELETE FROM map_cache")
            self.c.commit()

        # una sola coin en común, aunque la muestra sea grande: no hay badge
        fresh()
        only = [tok(i) for i in range(1, 9)]
        src2 = Src({
            A: page(swaps(A, only) + [direct]),
            B: page(swaps(B, [only[0]] + [tok(i) for i in range(20, 27)]) + [row("ba", NOW - 30, A, B, 0.4, kind="native_in")]),
        })
        res2 = run(self.c, [A, B], src2)
        self.assertEqual(res2["coincidences"], [])
        self.assertTrue(any("no basta" in r["reason"] or "no llega" in r["reason"] for r in res2["rejected"]))

        # muestra corta: no hay badge
        fresh()
        src3 = Src({
            A: page(swaps(A, shared[:3]) + [direct]),
            B: page(swaps(B, shared[:3]) + [row("ba", NOW - 30, A, B, 0.4, kind="native_in")]),
        })
        res3 = run(self.c, [A, B], src3)
        self.assertEqual(res3["coincidences"], [])
        self.assertTrue(any("insuficiente" in r["reason"] for r in res3["rejected"]))

        # coin popular compartida por 4 wallets, sin otro solape: no hay badge
        fresh()
        four = {
            A: page(swaps(A, [pop] + [tok(i) for i in range(30, 38)]) + [row("ab", NOW - 10, A, B, 0.5, kind="native_out")]),
            B: page(swaps(B, [pop] + [tok(i) for i in range(40, 48)]) + [row("ba", NOW - 10, A, B, 0.5, kind="native_in")]),
            C: page(swaps(C, [pop] + [tok(i) for i in range(50, 58)])),
            D: page(swaps(D, [pop] + [tok(i) for i in range(60, 68)])),
        }
        res4 = run(self.c, [A, B, C, D], Src(four))
        self.assertFalse(any(h["wallet"] == A and h["counterpart"] == B for h in res4["coincidences"]))

        # mismo fondeador no-servicio + solape suficiente sí; el CEX aunque haya solape no
        fresh()
        good = {
            A: page(swaps(A, shared) + [row("ma", NOW - 20, M, A, 1)]),
            B: page(swaps(B, shared) + [row("mb", NOW - 20, M, B, 1)]),
        }
        res5 = run(self.c, [A, B], Src(good))
        self.assertTrue(any(h["counterpart"] == B and "fondeador" in h["counterpart_why"] for h in res5["coincidences"]))
        fresh()
        cex = {
            A: page(swaps(A, shared) + [row("ca", NOW - 20, BINANCE, A, 1)]),
            B: page(swaps(B, shared) + [row("cb", NOW - 20, BINANCE, B, 1)]),
        }
        res6 = run(self.c, [A, B], Src(cex))
        self.assertEqual(res6["coincidences"], [])
        self.assertTrue(any("contraparte" in r["reason"] for r in res6["rejected"]))

        # sin fechas de compra no se fabrica el conteo de compras próximas
        fresh()
        bare = [dict(swap_row(f"na{i}", None, A, t), ts=None) for i, t in enumerate(shared)]
        for s in bare:
            s["swap"]["ts"] = None
        src7 = Src({
            A: page(bare + [row("ab", NOW - 5, A, B, 0.4, kind="native_out")]),
            B: page(swaps(B, shared) + [row("ba", NOW - 5, A, B, 0.4, kind="native_in")]),
        })
        res7 = run(self.c, [A, B], src7)
        hit = next(h for h in res7["coincidences"] if h["wallet"] == A)
        self.assertIsNone(hit["near_buys"])
        self.assertIn("no calculables", hit["near_note"])

    def test_alias_and_group_survive_leaving_the_map(self):
        db.set_alias(self.c, "solana", A, "<b>Wallet A</b>")
        db.save_group(self.c, {"name": "equipo", "emoji": "🗺", "chain": "solana", "wallets": [A, B], "source": "mapa"})
        src = Src({A: page([row("a", NOW - 5, M, A, 1)]), B: page([])})
        res = run(self.c, [A], src)
        self.assertEqual(res["by_wallet"][A]["alias"], "<b>Wallet A</b>")
        self.assertEqual(db.aliases(self.c)[0]["address"], A)
        # quitar A del mapa es no volver a pedirlo; la base no se toca
        run(self.c, [B], src)
        self.assertEqual(db.aliases(self.c)[0]["alias"], "<b>Wallet A</b>")
        self.assertEqual(db.groups(self.c)[0]["wallets"], [A, B])
        hid = walletmap.save_hypothesis(self.c, A, B, res["coverage"]["summary"], {"overlap": 0})
        self.assertEqual(walletmap.list_hypotheses(self.c)[0]["id"], hid)
        self.assertEqual(walletmap.list_hypotheses(self.c)[0]["kind"], "hipótesis")

    def test_job_is_private_and_unavailable_without_key(self):
        spec = walletmap.clean_request({"wallets": [A, B], "hops": 1})
        jid = jobs.enqueue(self.c, "map", "solana", spec, origin="test")
        self.assertIsNone(jobs.next_pending(self.c))
        picked = jobs.next_pending(self.c, kinds=("map",))
        self.assertEqual(picked["id"], jid)
        self.assertEqual(jobs.run_job(self.c, picked), "done")
        stored = walletmap.get_run(self.c, jid)
        self.assertEqual(stored["result"]["unavailable"]["code"], "helius_key")
        self.assertEqual(stored["result"]["nodes"], [])
        pub = export.build(self.c)
        job = next(j for j in pub["jobs"] if j["id"] == jid)
        self.assertIsInstance(job["items"], list)
        blob = json.dumps(job)
        self.assertNotIn(A, blob)
        self.assertNotIn(B, blob)
        self.assertNotIn("HELIUS", blob)

    def test_ui_contract_and_tag_filters_still_present(self):
        root = os.path.join(os.path.dirname(__file__), "..", "web")
        with open(os.path.join(root, "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("function cycleTag", js)
        self.assertIn("function toggleNoise", js)
        self.assertIn("noiseBtn", js)
        self.assertIn("xtags", js)
        with open(os.path.join(root, "map.js"), encoding="utf-8") as f:
            mp = f.read()
        self.assertNotIn(".toLowerCase()", mp)
        self.assertIn("0,05", mp)
        self.assertIn("Coincidencia alta", mp)
        with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Mapa de Wallets", html)
        self.assertIn("map.js", html)
        Lims = walletmap.limits()
        self.assertEqual(Lims["window_days"], 30)
        self.assertEqual(Lims["min_native_sol"], 0.05)
        self.assertEqual(Lims["coincidence"]["min_distinct_tokens"], 8)
        self.assertEqual(Lims["coincidence"]["min_overlap_tokens"], 5)
        self.assertGreaterEqual(Lims["max_hops"], 2)
        rule = walletmap.coincidence_rule()
        self.assertIn("no es un score", rule.lower())
        self.assertIn("mismo dueño", rule.lower())


if __name__ == "__main__":
    unittest.main()
