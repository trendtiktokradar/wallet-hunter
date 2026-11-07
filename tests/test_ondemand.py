"""El arranque por defecto no vigila, no publica y no vacía colas antiguas."""
import os, sys, json, time, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "WH_STATE_DIR" not in os.environ:
    _tmp = tempfile.mkdtemp()
    os.environ.update(WH_STATE_DIR=_tmp, WH_DB=os.path.join(_tmp, "t.db"), WH_DATA=os.path.join(_tmp, "data.json"))
for k in ("HELIUS_API_KEY", "ETHERSCAN_API_KEY", "BLOCKSCOUT_API_KEY", "WH_PIN", "TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN_TIKTOK_RADAR"):
    os.environ.pop(k, None)

from wallethunter import db, export, jobs, server, watcher
from wallethunter import telegram
from wallethunter.__main__ import arm_on_demand, on_demand_tick, box_link_payload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = "AAAAkWziSE1VPGUSLDqD1oCam1cogQVwFU4GpVDDYyki"


class TestOnDemand(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.c = db.connect(os.path.join(d, "od.db"))
        os.environ["WH_TUNNEL"] = "0"
        os.environ.pop("WH_MODE", None)

    def test_worker_cutoff_leaves_old_jobs(self):
        old_tok = jobs.enqueue(self.c, "tokens", "solana", ["Mint1111111111111111111111111111111111pump"])
        old_map = jobs.enqueue(self.c, "map", "solana", {"wallets": [A], "mode": "wallets", "scope": "context", "hops": 1, "page": 1, "cursors": {}, "coin": None, "interval": None, "rejected": []})
        self.c.execute("UPDATE jobs SET created=? WHERE id IN (?,?)", (1, old_tok, old_map))
        self.c.commit()
        new_map = jobs.enqueue(self.c, "map", "solana", {"wallets": [A], "mode": "wallets", "scope": "context", "hops": 1, "page": 1, "cursors": {}, "coin": None, "interval": None, "rejected": []})
        picked = jobs.next_pending(self.c, kinds=("connect", "map"), created_after=int(time.time()) - 5)
        self.assertEqual(picked["id"], new_map)
        self.assertEqual(jobs.next_pending(self.c, kinds=("tokens", "wallets"))["id"], old_tok)
        self.assertIsNone(jobs.next_pending(self.c, kinds=("tokens", "wallets"), created_after=int(time.time()) - 5))

    def test_arm_does_not_call_alerts_or_publish(self):
        calls = []
        orig_server, orig_worker, orig_watch = server.start_server, server.start_connect_worker, watcher.start_worker
        orig_detect, orig_send = telegram.detect_chat, telegram.send
        server.start_server = lambda: calls.append("api")
        server.start_connect_worker = lambda created_after=None: calls.append(("worker", created_after))
        watcher.start_worker = lambda: calls.append("watch")
        telegram.detect_chat = lambda: calls.append("telegram")
        telegram.send = lambda *a, **k: calls.append("send")
        try:
            cutoff, tun = arm_on_demand(self.c)
            self.assertIsNone(tun)
            self.assertEqual(os.environ.get("WH_MODE"), "on-demand")
            self.assertGreater(cutoff, 0)
            self.assertEqual(calls[0], "api")
            self.assertEqual(calls[1][0], "worker")
            self.assertGreaterEqual(calls[1][1], cutoff)
            self.assertNotIn("watch", calls)
            self.assertNotIn("telegram", calls)
            self.assertNotIn("send", calls)
        finally:
            server.start_server, server.start_connect_worker, watcher.start_worker = orig_server, orig_worker, orig_watch
            telegram.detect_chat, telegram.send = orig_detect, orig_send

    def test_tick_only_stores_local_link(self):
        class Tun:
            def ensure(self):
                return "https://example.trycloudflare.com"
        def boom(*a, **k):
            raise AssertionError("no debe mirar la cola ni publicar")
        orig = jobs.next_pending
        jobs.next_pending = boom
        try:
            url = on_demand_tick(self.c, Tun())
        finally:
            jobs.next_pending = orig
        self.assertEqual(url, "https://example.trycloudflare.com")
        payload = box_link_payload(self.c)
        self.assertEqual(set(payload), {"url", "updated", "pin_set", "mode"})
        self.assertEqual(payload["mode"], "on-demand")
        db.set_alias(self.c, "solana", A, "<script>alert(1)</script>")
        pub = json.dumps(export.build(self.c))
        self.assertNotIn("<script>", pub)
        self.assertNotIn(A, json.dumps(payload))

    def test_private_routes_require_pin(self):
        import urllib.request, urllib.error
        from wallethunter import pin
        if not pin.is_set():
            pin.set_pin("482913")
        server.PORT = 18811
        srv = server.start_server()
        def post(body, pin_value=None):
            if pin_value:
                body = dict(body, pin=pin_value)
            req = urllib.request.Request("http://127.0.0.1:18811/api/map", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            self.assertEqual(post({"op": "limits"})[0], 401)
            self.assertEqual(post({"op": "hypothesis", "wallet": A, "counterpart": A, "motive": "no"})[0], 401)
            self.assertIn("helius", post({"op": "limits"}, "482913")[1])
            for path in ("/api/aliases", "/api/groups"):
                req = urllib.request.Request("http://127.0.0.1:18811" + path, data=b'{"op":"list"}', headers={"Content-Type": "application/json"})
                try:
                    urllib.request.urlopen(req)
                    self.fail(path)
                except urllib.error.HTTPError as e:
                    self.assertEqual(e.code, 401)
        finally:
            srv.shutdown()

    def test_scripts_split_modes(self):
        svc = open(os.path.join(ROOT, "scripts", "service.sh"), encoding="utf-8").read()
        start = svc.split("start|ensure)", 1)[1].split(";;", 1)[0]
        full = svc.split("\n  full)", 1)[1].split(";;", 1)[0]
        self.assertIn("ondemand.sh", start)
        self.assertNotIn("loop.sh", start)
        self.assertIn("loop.sh", full)
        self.assertIn("publish-link", svc)
        box = open(os.path.join(ROOT, "scripts", "publish-box.sh"), encoding="utf-8").read()
        self.assertNotIn("--force", box)
        self.assertNotIn("data.json", box)
        self.assertIn("box.json", box)


if __name__ == "__main__":
    unittest.main()
