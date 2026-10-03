"""CLI de Wallet Hunter.
  python3 -m wallethunter scan-token <chain|auto> <CA> [CA...]
  python3 -m wallethunter scan-wallets <chain> <wallet> [...]
  python3 -m wallethunter recompute [chain]
  python3 -m wallethunter export
  python3 -m wallethunter set-pin            (lee el PIN de la variable NEW_PIN o pregunta sin mostrarlo)
  python3 -m wallethunter enqueue <tokens|wallets> <chain> <items...>
  python3 -m wallethunter loop               (servicio: API + túnel + cola + alertas + publicación)
  python3 -m wallethunter status
"""
import json, logging, os, sys, time, subprocess, getpass
from .config import ROOT, cfg

def setup_log():
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
                        handlers=[logging.StreamHandler(sys.stdout)])


def publish(log):
    if not cfg().get("publish") or os.environ.get("WH_PUBLISH", "1") == "0":
        return
    try:
        r = subprocess.run([os.path.join(ROOT, "scripts", "publish.sh")], capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            log.warning("publicar falló: %s", (r.stderr or r.stdout)[-300:])
    except Exception as e:
        log.warning("publicar falló: %s", e)


def loop():
    from . import db, jobs, export, watcher, server, market
    from .net import STATUS
    log = logging.getLogger("wh")
    c = db.connect()
    n = jobs.reset_stuck(c)
    if n:
        log.info("%s trabajos reanudados", n)
    server.start_server()
    tun = server.Tunnel() if os.environ.get("WH_TUNNEL", "1") == "1" else None
    last_pub, last_watch, last_sig = 0, 0, None
    from .pin import is_set
    while True:
        try:
            url = tun.ensure() if tun else None
            box = db.kv_get(c, "box", {})
            if url != box.get("url") or box.get("pin_set") != is_set():
                db.kv_set(c, "box", {"url": url, "updated": int(time.time()), "pin_set": is_set()})
                last_sig = None
            jobs.pull_github_queue(c)
            market.native_usd("solana"); market.native_usd("ethereum"); market.native_usd("bsc")
            job = jobs.next_pending(c)
            while job:
                def mid_publish():
                    nonlocal last_pub
                    if time.time() - last_pub > 90:
                        export.write(c); publish(log); last_pub = time.time()
                export.write(c); publish(log); last_pub = time.time()
                jobs.run_job(c, job, on_progress=mid_publish)
                export.write(c); publish(log); last_pub = time.time()
                job = jobs.next_pending(c)
            a = cfg()["alerts"]
            if a.get("enabled") and time.time() - last_watch > a.get("poll_minutes", 5) * 60:
                watcher.run(c); last_watch = time.time()
            STATUS.save()
            d = export.build(c)
            sig = json.dumps({k: v for k, v in d.items() if k not in ("generated", "sources", "prices")}, sort_keys=True)
            if sig != last_sig or time.time() - last_pub > 3600:
                export.write(c); publish(log); last_pub = time.time(); last_sig = sig
        except Exception:
            log.exception("vuelta del bucle")
        server.WAKE.wait(cfg().get("poll_seconds", 120))
        server.WAKE.clear()


def main(argv):
    setup_log()
    if not argv:
        print(__doc__); return 1
    cmd, args = argv[0], argv[1:]
    from . import db, export
    c = db.connect()
    if cmd == "scan-token":
        from .scan import Scanner
        sc = Scanner(c)
        for ca in args[1:]:
            print(json.dumps(sc.scan_token(args[0], ca)))
        export.write(c)
    elif cmd == "scan-wallets":
        from .scan import Scanner
        print(json.dumps(Scanner(c).scan_wallets(args[0], args[1:], force=True)))
        export.write(c)
    elif cmd == "recompute":
        from .scan import Scanner
        from .chains import CHAINS
        for ch in ([args[0]] if args else list(CHAINS)):
            Scanner(c).recompute(ch)
        export.write(c)
    elif cmd == "export":
        d = export.write(c); print(json.dumps(d["stats"]))
    elif cmd == "set-pin":
        from . import pin
        p = os.environ.get("NEW_PIN") or getpass.getpass("Nuevo PIN: ")
        pin.set_pin(p); print("PIN guardado (solo hash)")
    elif cmd == "enqueue":
        from . import jobs
        from .scan import parse_items
        print(jobs.enqueue(c, args[0], args[1], parse_items(" ".join(args[2:]))))
    elif cmd == "loop":
        loop()
    elif cmd == "status":
        print(json.dumps(export.build(c)["stats"], indent=1)); print(json.dumps(export.key_status()))
    else:
        print(__doc__); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
