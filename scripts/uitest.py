"""Prueba de la interfaz con Playwright (sin tocar el box real: las llamadas /api/* se simulan).
Uso: python scripts/uitest.py [URL]   (por defecto la vista local http://127.0.0.1:8797/)"""
import sys, json, asyncio, time
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/"
shots = sys.argv[2] if len(sys.argv) > 2 else None
import os
NO_BOX = os.environ.get("UITEST_NO_BOX") == "1"   # usa el data.json servido junto al panel (datos de prueba)
FAKE = {}
GROUPS = []
DELS = []          # llamadas a /api/delete (simuladas: nunca llegan al box real)
PLAN = None if os.environ.get("UITEST_PLAN_NONE") == "1" else {}
CHECK = json.load(open(os.environ.get("UITEST_CHECK") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures", "connect_result.json"), encoding="utf-8"))
SVCK = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures", "connect_services.json"), encoding="utf-8"))   # resultado con servicios compartidos
CONNECTS = []      # llamadas a /api/connect (simuladas)
CHECKS = {}        # id -> nº de consultas de estado (pendiente → en curso → hecho)
CK_STEPS = [("running", "leyendo historial 2/%d"), ("running", "2 saltos: fondeador de intermediarios 3/6"), ("running", "revisando puentes 2/3")]   # respuesta simulada de plan_token; None = el box no la da (el panel usa su estimación)

SET = {"enabled": False, "min_inflow_usd": 5000, "min_inflow_native": {"solana": 20}, "only_from_funder_or_cex": False, "poll_minutes": 5,
       "dormant_alert": True, "dormant_days": 7, "dormant_poll_minutes": 60, "funder_watch": False, "funder_poll_minutes": 15, "funder_new_max_txs": 5,
       "funder_max": 20, "funder_min_native": {"solana": 1.0}}
TG = {"token": True, "chat": False, "bot": "Test_bot", "chat_name": None, "chat_type": None, "last_detect": int(time.time()) - 40}
TGOPS = []         # llamadas a /api/telegram (simuladas: no se manda nada)
FAVSRV = []        # ⭐ en el «box» simulado
FAVADDS = []       # altas de ⭐ con scan
SCANS = []         # /api/scan recibidos
TOKSCAN = {}       # escaneo simulado desde Tokens: {"t": inicio, "ca": CA}
NEWCA = "NewTokenScan" + "9" * 28 + "pump"
def tokscan_apply(dd):
    """Simula el trabajo del box: en cola → en curso → hecho (y entonces aparece la coin con 5 wallets)."""
    if not TOKSCAN.get("t"): return dd
    el = time.time() - TOKSCAN["t"]
    st, pr = ("pending", "en cola") if el < 2 else ("running", "wallets analizadas %d/120" % min(119, int(el * 12))) if el < 9 else ("done", "terminado")
    dd.setdefault("jobs", []).insert(0, {"id": "tokscan1", "created": int(TOKSCAN["t"]), "kind": "tokens", "chain": "solana", "items": [TOKSCAN["ca"]], "status": st, "progress": pr, "message": "1 token" if st == "done" else None, "started": int(TOKSCAN["t"]) + 2 if el >= 2 else None, "finished": int(time.time()) if st == "done" else None, "origin": "web"})
    if st == "done": tokscan_token(dd)
    return dd
def tokscan_token(dd):
    if any(t["a"] == NEWCA for t in dd["tokens"]): return
    dd["tokens"].append({"c": "solana", "a": NEWCA, "sy": "NEWT", "nm": "New Token Test", "lt": int(time.time()) - 7200, "mc": 123456, "sa": int(time.time()), "nb": 120, "nw": 5, "bd": 0, "st": "done"})
    for w in dd["wallets"][3:8]:
        if w["c"] == "solana": w["ct"] = list(w.get("ct") or w.get("or") or []) + [NEWCA]
MOM = "MoMfundr" + "M" * 36
KID = "NewKid11" + "K" * 36
def fav_lt(i):     # 1ª ⭐: 10 días sin tradear; resto: 1 día
    return int(time.time()) - (10 if i == 0 else 1) * 86400
def augment(dd):
    """Datos de prueba de smart money cruzado (con wallets reales del data.json)."""
    ws, t0 = dd["wallets"], (dd["tokens"][0]["a"] if dd["tokens"] else "Tok")
    F1, F2 = "FakeCoinOne" + "1" * 29 + "pump", "FakeCoinTwo" + "2" * 29 + "pump"
    def co(t, r, pn): return {"t": t, "r": r, "pn": pn, "roi": pn / 1.5, "en": 40 + r * 10, "fb": int(time.time()) - 5 * 86400, "in": 1.5, "out": 1.5 + pn, "un": 0}
    dd["smartx"] = [{"c": "solana", "a": ws[1]["a"], "n": 3, "ne": 3, "pn": 9.5, "inv": 4.5, "sc": ws[1]["sc"], "coins": [co(t0, 4, 5.0), co(F1, 9, 3.0), co(F2, 22, 1.5)]},
                    {"c": "solana", "a": ws[0]["a"], "n": 2, "ne": 3, "pn": 4.2, "inv": 3, "sc": ws[0]["sc"], "coins": [co(t0, 2, 3.2), co(F1, 17, 1.0)]},
                    {"c": "solana", "a": ws[2]["a"], "n": 2, "ne": 2, "pn": 1.1, "inv": 3, "sc": ws[2]["sc"], "coins": [co(F1, 30, 0.6), co(F2, 41, 0.5)]}]
    dd["smartx_cfg"] = {"early_rank": 50, "min_coins": 2}
    # servicios compartidos en la base (clusters) y en el detalle de una wallet
    RL = "F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe"
    dd["svc"] = {"skipped": 7, "hubs": [{"address": RL, "name": "Relay", "label": "🔁 Relay", "icon": "🔁", "auto": False, "verified": True, "why": None, "wallets": 4, "c": "solana"},
                                        {"address": "Unkhub1111111111111111111111111111111111111", "name": "servicio/hub", "label": "🕸️ servicio/hub", "icon": "🕸️", "auto": True, "verified": False, "why": "fondeó a 31 wallets de la base", "wallets": 31, "c": "solana"}]}
    for w in ws[:3]:
        w["sv"] = [{"a": RL, "n": "Relay", "i": "🔁", "k": 4, "h": "fondeó", "auto": False}]
    for w in ws:            # último trade según el data.json real: la prueba de «💤 Sin tradear» usa solo los del box simulado
        w.pop("lx", None)
    return dd

async def fake_api(route):
    req = route.request
    body = json.loads(req.post_data or "{}")
    if req.url.endswith("/api/aliases"):
        if body.get("op") == "set":
            k = body["chain"] + ":" + body["address"]
            if body.get("alias"): FAKE[k] = body["alias"]
            else: FAKE.pop(k, None)
        out = {"ok": True, "aliases": [{"chain": k.split(":")[0], "address": k.split(":", 1)[1], "alias": v} for k, v in FAKE.items()]}
    elif req.url.endswith("/api/groups"):
        if body.get("op") == "save":
            g = dict(body["group"]); g["id"] = "g%d" % (len(GROUPS) + 1); GROUPS.insert(0, g)
        out = {"ok": True, "groups": GROUPS}
    elif req.url.endswith("/api/connect"):
        CONNECTS.append(body)
        ws = [w for w in body.get("wallets", "").split() if w]
        cid = "ck%d" % len(CONNECTS); CHECKS[cid] = 0
        out = {"ok": True, "id": cid, "chain": "solana" if body.get("chain") in (None, "auto") else body["chain"], "wallets": ws}
    elif req.url.endswith("/api/checks"):
        op, cid = body.get("op"), body.get("id")
        if op == "delete":
            CHECKS.pop(cid, None)
        if op in ("list", "delete"):
            out = {"ok": True, "checks": [{"id": k, "created": int(time.time()) - 60, "chain": CHECK["chain"], "wallets": CHECK["wallets"], "status": "done" if n >= len(CK_STEPS) else "running", "progress": "", "summary": CHECK["summary"], "max_score": CHECK["pairs"][0]["score"], "credits": CHECK["credits"], "error": None} for k, n in CHECKS.items()]
                   + [{"id": "old1", "created": int(time.time()) - 86400, "chain": CHECK["chain"], "wallets": CHECK["wallets"][:2], "status": "done", "progress": "terminado", "summary": "1 de 1 pares conectados", "max_score": 60, "credits": 180, "error": None},
                      {"id": "svc1", "created": int(time.time()) - 3600, "chain": "solana", "wallets": SVCK["wallets"], "status": "done", "progress": "terminado", "summary": SVCK["summary"], "max_score": SVCK["pairs"][0]["score"], "credits": SVCK["credits"], "error": None}]}
        else:
            n = CHECKS.get(cid, len(CK_STEPS))
            if cid != "svc1": CHECKS[cid] = n + 1
            if cid == "svc1":
                out = {"ok": True, "id": cid, "status": "done", "progress": "terminado", "chain": "solana", "wallets": SVCK["wallets"], "result": SVCK}
            elif n < len(CK_STEPS):
                st, pr = CK_STEPS[n]
                out = {"ok": True, "id": cid, "status": st, "progress": pr.replace("%d", str(len(CHECK["wallets"]))), "chain": CHECK["chain"], "wallets": CHECK["wallets"]}
            else:
                out = {"ok": True, "id": cid, "status": "done", "progress": "terminado", "chain": CHECK["chain"], "wallets": CHECK["wallets"], "result": dict(CHECK, id=cid)}
    elif req.url.endswith("/api/favs"):
        op, ch, a = body.get("op"), body.get("chain"), body.get("address")
        if op == "add" and not any(f["address"] == a for f in FAVSRV):
            FAVSRV.append({"chain": ch, "address": a, "alias": body.get("alias"), "added": int(time.time())})
            if body.get("scan"): FAVADDS.append(body)
        elif op == "remove":
            FAVSRV[:] = [f for f in FAVSRV if f["address"] != a]
        out = {"ok": True, "dormant_days": SET["dormant_days"], "favs": [dict(f, last_trade=fav_lt(i), watched=True, funders=[{"address": MOM, "label": None}] if i == 0 else []) for i, f in enumerate(FAVSRV)]}
    elif req.url.endswith("/api/settings"):
        if body.get("alerts"): SET.update(body["alerts"])
        fl = [{"chain": "solana", "address": MOM, "label": None, "children": [f["address"] for f in FAVSRV[:1]], "watch": True, "why": None},
              {"chain": "solana", "address": "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9", "label": "CEX Binance", "children": [f["address"] for f in FAVSRV[1:2]], "watch": False, "why": "exchange"}] if SET["funder_watch"] else []
        out = {"ok": True, "alerts": SET, "telegram": TG, "funders": fl, "estimate": {"inflow": 0, "dormant": 125, "funder": 211 if SET["funder_watch"] else 0, "total": 125 + (211 if SET["funder_watch"] else 0),
               "favorites": len(FAVSRV), "favorites_sol": len(FAVSRV), "funders": 1, "funders_sol": 1 if SET["funder_watch"] else 0, "first_time": 20, "assumptions": "supuestos de prueba"}}
    elif req.url.endswith("/api/telegram"):
        TGOPS.append(body.get("op"))
        if body.get("op") == "detect": TG.update(chat=True, chat_name="Alex", chat_type="private")
        out = {"ok": True, "found": TG["chat"], "telegram": TG}
    elif req.url.endswith("/api/alerts"):
        n = int(time.time()); w0 = FAVSRV[0]["address"] if FAVSRV else KID
        out = {"ok": True, "alerts": [
            {"ts": n - 600, "kind": "funder", "chain": "solana", "wallet": KID, "amount_native": 3.0, "amount_usd": 450, "sender": MOM, "sender_label": None, "tx": "funder:5xSig", "data": {"funder": MOM, "children": [w0], "txs": 1}},
            {"ts": n - 3600, "kind": "dormant", "chain": "solana", "wallet": w0, "amount_native": None, "amount_usd": None, "sender": None, "sender_label": None, "tx": "dormant:x", "data": {"days": 10, "last_trade": n - 10 * 86400}},
            {"ts": n - 7200, "kind": "inflow", "chain": "solana", "wallet": w0, "amount_native": 25.0, "amount_usd": 3750, "sender": "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9", "sender_label": "CEX Binance", "tx": "abc", "data": {}}]}
    elif req.url.endswith("/api/scan"):
        SCANS.append(body)
        items = [x for x in str(body.get("items", "")).split() if x]
        if body.get("kind") == "tokens" and items == [NEWCA]: TOKSCAN.update(t=time.time(), ca=NEWCA)
        out = {"ok": True, "id": "tokscan1", "items": items}
    elif req.url.endswith("/api/delete"):
        DELS.append(body)
        if body.get("op") == "plan_token":
            if PLAN is None:
                return await route.fulfill(status=503, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body='{"error":"x"}')
            out = dict(PLAN, ok=True)
        elif body.get("op") == "wallets":
            out = {"ok": True, "result": {"requested": len(body["items"]), "deleted_wallets": len(body["items"]), "backup": "auto-test-wallets.db"}}
        else:
            pl = PLAN or {}
            out = {"ok": True, "result": {"token": body.get("token"), "deleted_wallets": pl.get("delete", 0), "kept_wallets": pl.get("keep_other_coins", 0) + pl.get("keep_favorites", 0), "backup": "auto-test-coin.db"}}
    else:
        out = {"ok": True}
    await route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(out))

async def coin_tests(pg, D, tag, mobile):
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(200)
    nopt = await pg.locator("#coinSel option").count()
    ok(nopt == len(D["tokens"]) + 1, tag + f"selector de coin ({nopt - 1} coins)")
    t = sorted(D["tokens"], key=lambda x: -(x["sa"] or 0))[0]
    exp = sum(1 for w in D["wallets"] if w["c"] == t["c"] and t["a"] in (w.get("ct") or w.get("or") or []))
    await pg.select_option("#coinSel", t["c"] + ":" + t["a"]); await pg.wait_for_timeout(400)
    head = await pg.locator("#coinHead").inner_text() if await pg.locator("#coinHead").is_visible() else ""
    ok((t["sy"] or "") in head and t["a"] in head, tag + "cabecera de la coin: " + " ".join(head.split())[:90])
    ok("✕ Cerrar vista de coin · ver ranking general" in head and "Análisis completo en Tokens" in head and "Volver a tokens" not in head, tag + "Wallets: botón «✕ Cerrar vista de coin · ver ranking general» + «Análisis completo en Tokens»")
    rows = await pg.locator("#tbl tbody tr[data-k]").count()
    ok(rows == min(exp, 300), tag + f"tabla filtrada a la coin ({rows}={exp})")
    ok(("#coin=" + t["a"]) in pg.url, tag + "URL con #coin=")
    card = await pg.locator("#cards .card").first.locator(".v").inner_text()
    ok(int(card) <= exp, tag + f"tarjetas de la coin (wallets {card})")
    chips_total = sum(int(x) for x in await pg.locator('#chips .chip[data-tag="activa"] .n').all_inner_texts()) if await pg.locator('#chips .chip[data-tag="activa"]').count() else 0
    exp_act = sum(1 for w in D["wallets"] if w["c"] == t["c"] and t["a"] in (w.get("ct") or []) and "activa" in w["tg"])
    ok(chips_total == exp_act, tag + f"conteos de etiquetas de la coin (activa {chips_total}={exp_act})")
    ok(await pg.locator("#tbl tbody .coinchip").count() > 0, tag + "coins por fila")
    await pg.locator('#coinHead [data-coin=""]').click(); await pg.wait_for_timeout(300)
    ok(not await pg.locator("#coinHead").is_visible() and "#coin=" not in pg.url, tag + "«✕ Cerrar vista de coin · ver ranking general» limpia")
    # botón Ver wallets en Tokens y Trabajos
    await pg.locator('#tabs button[data-tab="tokens"]').click(); await pg.wait_for_timeout(300)
    await pg.locator('#tokensBox [data-tcoin]').first.click(); await pg.wait_for_timeout(400)
    ok(await pg.locator("#coinHead").is_visible() and await pg.locator("#tab-wallets").is_visible() and "on" in (await pg.locator('#tabs button[data-tab="tokens"]').get_attribute("class") or ""), tag + "Tokens → la coin se abre dentro de Tokens (tabla de wallets de la coin)")
    await pg.locator('#tabs button[data-tab="jobs"]').click(); await pg.wait_for_timeout(300)
    nj = await pg.locator('#jobsBox [data-tcoin]').count()
    ok(nj >= 1, tag + f"Trabajos → botones «Abrir análisis» ({nj})")
    if nj:
        await pg.locator('#jobsBox [data-tcoin]').first.click(); await pg.wait_for_timeout(400)
        ok(await pg.locator("#coinHead").is_visible() and "#tokens/coin=" in pg.url, tag + "Trabajos → «Abrir análisis» abre la coin en Tokens")
    # enlace compartible
    url = pg.url.split("#")[0] + "#coin=" + t["a"]
    p2 = await pg.context.new_page()
    await p2.goto(url, wait_until="networkidle"); await p2.wait_for_timeout(2500)
    h2 = await p2.locator("#coinHead").inner_text() if await p2.locator("#coinHead").is_visible() else ""
    ok(t["a"] in h2, tag + "abrir enlace #coin=… selecciona la coin")
    if SHOTS:
        nm = "mobile" if mobile else "desktop"
        await p2.evaluate("document.getElementById('tip').classList.add('hide')")
        await p2.screenshot(path=f"{SHOTS}/{nm}-coin.png", full_page=not mobile)
        if mobile:
            await p2.locator("#tbl").scroll_into_view_if_needed(); await p2.wait_for_timeout(300)
            await p2.screenshot(path=f"{SHOTS}/{nm}-coin-table.png")
    await p2.close()
    await pg.goto(pg.url.split("#")[0], wait_until="networkidle")

async def tokens_tests(pg, D, tag, mobile):
    """Pestaña Tokens: buscador por CA, lista de coins y análisis por coin (reutiliza tabla, filtros, bundles, clusters, smart)."""
    import copy
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    nm = "mobile" if mobile else "desktop"
    async def shot(name, full=False):
        if SHOTS:
            await pg.evaluate("document.getElementById('tip').classList.add('hide')")
            await pg.screenshot(path=f"{SHOTS}/{nm}-{name}.png", full_page=full and not mobile)
    async def vis(sel): return await pg.locator(sel).count() > 0 and await pg.locator(sel).first.is_visible()
    TOKSCAN.clear(); SCANS.clear(); D0 = copy.deepcopy(D)
    def coin_ws(t): return [w for w in D["wallets"] if w["c"] == t["c"] and t["a"] in (w.get("ct") or w.get("or") or [])]
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.locator('#tabs button[data-tab="tokens"]').click(); await pg.wait_for_timeout(400)
    ok(await vis("#tokQ") and await vis("#tokGo"), tag + "Tokens: buscador de CA arriba")
    nrows = await pg.locator("#tokList tr.tokrow").count()
    ok(nrows == len(D["tokens"]), tag + f"lista con todas las coins escaneadas ({nrows})")
    hdr = await pg.locator("#tokList table tr").first.inner_text()
    ok(all(x in hdr for x in ("Coin", "Chain", "MC", "Escaneada", "Wallets", "Bundles", "Clusters")), tag + "columnas: coin, chain, MC, fecha, wallets, bundles, clusters")
    t = sorted(D["tokens"], key=lambda x: -(x["sa"] or 0))[0]; k = t["c"] + ":" + t["a"]; exp = len(coin_ws(t))
    cells = await pg.locator(f'#tokList tr.tokrow[data-tcoin="{k}"] td').all_inner_texts()
    ok(len(cells) >= 8 and cells[5].strip() == str(exp), tag + f"nº de wallets de la coin en la lista ({cells[5].strip() if len(cells) > 5 else '?'}={exp})")
    ok(not await pg.locator("#coinHead").is_visible(), tag + "sin cabecera de coin en la lista")
    await shot("tokens-lista", True)
    # abrir la coin pulsando la fila
    await pg.locator(f'#tokList tr.tokrow[data-tcoin="{k}"] td').first.click(); await pg.wait_for_timeout(500)
    head = " ".join((await pg.locator("#coinHead").inner_text()).split()) if await pg.locator("#coinHead").is_visible() else ""
    ok("← Volver a tokens" in head and (t["sy"] or "") in head and t["a"] in head, tag + "clic en la fila → análisis de la coin con cabecera y «← Volver a tokens»")
    ok("#tokens/coin=" + t["a"] in pg.url, tag + "URL #tokens/coin=<CA>")
    ok("on" in (await pg.locator('#tabs button[data-tab="tokens"]').get_attribute("class") or "") and await vis("#tab-wallets") and not await vis("#tab-tokens"), tag + "se queda en Tokens mostrando la tabla de wallets de la coin")
    rows = await pg.locator("#tbl tbody tr[data-k]").count()
    ok(rows == min(exp, 300), tag + f"tabla de wallets de la coin ({rows}={exp})")
    await pg.locator("#tbl tbody tr[data-k]").nth(0).locator("[data-sel]").check(); await pg.wait_for_timeout(200)
    ok(await vis("#noiseBtn") and await vis('#selBar [data-export="sel"]') and await vis("#selBar [data-delsel]") and await pg.locator("#tbl tbody [data-del]").count() > 0, tag + "Quitar ruido, exportar y borrar disponibles en la coin")
    await pg.locator("#selClear").click(); await pg.wait_for_timeout(200)
    # etiquetas 3 estados dentro de la coin
    act = sum(1 for w in coin_ws(t) if "activa" in w["tg"])
    if await pg.locator('#chips .chip[data-tag="activa"]').count():
        await pg.locator('#chips .chip[data-tag="activa"]').click(); await pg.wait_for_timeout(300)
        r1 = await pg.locator("#tbl tbody tr[data-k]").count()
        ok(r1 == min(act, 300) and "con=activa" in pg.url and "#tokens/coin=" in pg.url, tag + f"etiqueta «activa» (incluir) en la coin ({r1}={act})")
        await pg.locator('#chips .chip[data-tag="activa"]').click(); await pg.wait_for_timeout(300)
        r2 = await pg.locator("#tbl tbody tr[data-k]").count()
        ok(r2 == min(exp - act, 300) and "sin=activa" in pg.url, tag + f"etiqueta «activa» (excluir) en la coin ({r2}={exp - act})")
        await pg.locator("#clrTags").click(); await pg.wait_for_timeout(300)
    await pg.fill("#fScore", "50"); await pg.wait_for_timeout(300)
    r3 = await pg.locator("#tbl tbody tr[data-k]").count(); e3 = sum(1 for w in coin_ws(t) if (w["sc"] or 0) >= 50)
    ok(r3 == min(e3, 300), tag + f"filtro Score ≥ 50 en la coin ({r3}={e3})"); await pg.fill("#fScore", ""); await pg.wait_for_timeout(200)
    await shot("tokens-coin", True)
    if mobile:
        await pg.locator("#tbl").scroll_into_view_if_needed(); await pg.wait_for_timeout(200); await shot("tokens-coin-tabla")
        await pg.evaluate("window.scrollTo(0,0)")
    # sub-pestañas
    nb = sum(1 for b in D["bundles"] if b["c"] == t["c"] and b["t"] == t["a"])
    await pg.locator('#coinHead [data-tsub="bundles"]').click(); await pg.wait_for_timeout(400)
    bh = await pg.locator("#bundlesBox h3").first.inner_text() if await vis("#bundlesBox") else ""
    ok(await vis("#tab-bundles") and not await vis("#tab-wallets") and f"({nb})" in bh and "sub=bundles" in pg.url, tag + f"sub-pestaña Bundles de la coin ({nb})")
    await shot("tokens-bundles", True)
    await pg.locator('#coinHead [data-tsub="clusters"]').click(); await pg.wait_for_timeout(400)
    ok(await vis("#connBox") and not await vis("#connSeg") and not await vis("#connCheck") and await vis("[data-cktop]") and "sub=clusters" in pg.url, tag + "sub-pestaña Clusters / conexiones (sin el selector de Conexiones)")
    ok(await vis("#clSvc"), tag + "clusters de la coin con «Ocultar conexiones por servicios»")
    await shot("tokens-clusters", True)
    if await pg.locator('#coinHead [data-tsub="smartx"]').count():
        await pg.locator('#coinHead [data-tsub="smartx"]').click(); await pg.wait_for_timeout(400)
        esx = sum(1 for r in (D.get("smartx") or []) if r["c"] == t["c"] and any(x["t"] == t["a"] for x in r["coins"]))
        rsx = await pg.locator("#smartxBox table.sx tr").count() - 1
        ok(await vis("#tab-smartx") and rsx == esx, tag + f"sub-pestaña Smart cruzado de la coin ({rsx}={esx})")
    # Conexiones normal sigue intacta
    await pg.locator('#tabs button[data-tab="conn"]').click(); await pg.wait_for_timeout(300)
    ok(await vis("#connSeg"), tag + "la pestaña Conexiones conserva su selector")
    await pg.locator('#tabs button[data-tab="tokens"]').click(); await pg.wait_for_timeout(300)
    ok(await vis("#coinHead [data-tback]"), tag + "volver a Tokens desde otra pestaña recuerda la coin abierta")
    await pg.locator('#tabs button[data-tab="tokens"]').click(); await pg.wait_for_timeout(300)
    ok(not await vis("#coinHead") and await vis("#tokList"), tag + "pulsar Tokens otra vez vuelve a la lista")
    # enlace compartible con sub-pestaña
    p2 = await pg.context.new_page()
    await p2.goto(pg.url.split("#")[0] + "#tokens/coin=" + t["a"] + "&sub=bundles", wait_until="networkidle"); await p2.wait_for_timeout(2500)
    ok(await p2.locator("#tab-bundles").is_visible() and await p2.locator('#coinHead [data-tsub="bundles"].on').count() == 1, tag + "abrir #tokens/coin=…&sub=bundles va directo a esa vista")
    await p2.close()
    # volver
    await pg.locator(f'#tokList tr.tokrow[data-tcoin="{k}"] [data-tcoin]').click(); await pg.wait_for_timeout(400)
    await pg.locator("#coinHead [data-tback]").click(); await pg.wait_for_timeout(400)
    ok(await vis("#tokList") and not await vis("#coinHead") and pg.url.endswith("#tokens"), tag + "«← Volver a tokens» vuelve a la lista (#tokens)")
    # buscador: coin ya escaneada (link de pump.fun)
    await pg.fill("#tokQ", "https://pump.fun/coin/" + t["a"]); await pg.press("#tokQ", "Enter"); await pg.wait_for_timeout(500)
    ok(await vis("#coinHead") and "#tokens/coin=" + t["a"] in pg.url, tag + "buscador: CA ya escaneado (link) abre su análisis")
    await pg.locator("#coinHead [data-tback]").click(); await pg.wait_for_timeout(300)
    await pg.fill("#tokQ", "hola"); await pg.locator("#tokGo").click(); await pg.wait_for_timeout(200)
    ok("No veo un CA" in await pg.locator("#tokMsg").inner_text(), tag + "buscador: texto sin CA → aviso")
    # buscador: coin nueva → ofrecer escaneo con PIN → progreso → se abre sola
    await pg.fill("#tokQ", NEWCA); await pg.locator("#tokGo").click(); await pg.wait_for_timeout(400)
    pend = await pg.locator("#tokPend").inner_text()
    ok("no está escaneada" in pend and await vis("#tokScanGo") and await vis("#tokPin") and "#tokens/coin=" + NEWCA in pg.url, tag + "CA nuevo → ofrece escanearlo con el PIN")
    await shot("tokens-escanear")
    await pg.locator("#tokScanGo").click(); await pg.wait_for_timeout(600)
    sc = SCANS[-1] if SCANS else {}
    ok(sc.get("kind") == "tokens" and sc.get("items") == NEWCA and sc.get("pin") == "test-pin", tag + "lanza /api/scan (tokens + PIN)")
    if not NO_BOX:   # en directo el /api/scan es simulado pero los datos vienen del box real: el trabajo no existe
        pend2 = await pg.locator("#tokPend").inner_text()
        ok("escaneando" in pend2 and await vis("#tokPend .pbar"), tag + "tras lanzar: estado «escaneando» con barra de progreso")
        await shot("tokens-progreso")
        await pg.evaluate("localStorage.removeItem('wh_tscan')")
        await pg.goto(pg.url.split("#")[0], wait_until="networkidle"); await pg.wait_for_timeout(1500)
        TOKSCAN.clear()
    else:
        await pg.wait_for_timeout(4500)
        prog = await pg.locator("#tokPend").inner_text() if await vis("#tokPend .pbar") else ""
        ok("en curso" in prog or "en cola" in prog, tag + "muestra el progreso del trabajo: " + " ".join(prog.split())[:80])
        await shot("tokens-progreso")
        opened = False
        for _ in range(20):
            await pg.wait_for_timeout(1000)
            if await vis("#coinHead") and "NEWT" in await pg.locator("#coinHead").inner_text(): opened = True; break
        ok(opened and "#tokens/coin=" + NEWCA in pg.url and await vis("#tab-wallets"), tag + "al terminar el trabajo abre sola la coin escaneada")
        rn = await pg.locator("#tbl tbody tr[data-k]").count()
        ok(rn == 5, tag + f"wallets de la coin nueva ({rn}=5)")
        ok(await pg.evaluate("localStorage.getItem('wh_tscan')") is None, tag + "escaneo pendiente limpiado")
        await shot("tokens-escaneada")
    # Wallets: ranking global con selector de coin; botón claro de cerrar y acceso al análisis
    await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)
    ok(not await vis("#coinHead") and await pg.locator("#tbl tbody tr[data-k]").count() == min(len(D["wallets"]), 300), tag + "Wallets sigue siendo el ranking global")
    await pg.select_option("#coinSel", k); await pg.wait_for_timeout(400)
    await pg.locator("#coinHead [data-tokopen]").click(); await pg.wait_for_timeout(400)
    ok("#tokens/coin=" + t["a"] in pg.url and await vis("#coinHead [data-tback]"), tag + "Wallets → «Análisis completo en Tokens» abre la coin en Tokens")
    await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)
    ok(await vis("#coinHead .closecoin") and "#coin=" + t["a"] in pg.url, tag + "Wallets conserva su coin seleccionada")
    await pg.locator("#coinHead .closecoin").click(); await pg.wait_for_timeout(300)
    ok(not await vis("#coinHead"), tag + "«✕ Cerrar vista de coin» vuelve al ranking general")
    # deja todo como estaba para las pruebas siguientes
    TOKSCAN.clear(); D.clear(); D.update(D0)
    await pg.evaluate("localStorage.removeItem('wh_tscan')")
    await pg.goto(pg.url.split("#")[0], wait_until="networkidle"); await pg.wait_for_timeout(1500)

def coin_plan(D, t):
    toks = {(x["c"], x["a"]) for x in D["tokens"]}
    dl = keep = 0
    for w in D["wallets"]:
        cs = w.get("ct") or w.get("or") or []
        if w["c"] != t["c"] or t["a"] not in cs: continue
        if any(a != t["a"] and (w["c"], a) in toks for a in cs): keep += 1
        else: dl += 1
    return dl, keep

async def delete_tests(pg, D, tag, mobile):
    global PLAN
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    async def txt(sel): return " ".join((await pg.locator(sel).inner_text()).split())
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)
    await pg.locator("#tbl").scroll_into_view_if_needed()
    rows = pg.locator("#tbl tbody tr[data-k]")
    k = await rows.nth(0).get_attribute("data-k")
    # 🗑 en la fila: abre el diálogo, no el detalle
    await pg.locator(f'#tbl tbody tr[data-k="{k}"] [data-del]').click(); await pg.wait_for_timeout(300)
    ok(await pg.locator("#modal").is_visible() and not await pg.locator("#drawer").is_visible(), tag + "🗑 en la fila abre el diálogo (no el detalle)")
    m = await txt("#modalIn")
    ok("Se borrará 1 wallet" in m and "Borrar 1 wallet" in m, tag + "diálogo en español con el nº de wallets: " + m[:80])
    ok(not await pg.locator("#delBlock").is_checked() and "No volver a añadir en futuros escaneos" in m, tag + "casilla «No volver a añadir…» desmarcada por defecto")
    ok(await pg.locator("#delPin").is_visible() and "copia de seguridad" in m, tag + "pide PIN y avisa de la copia de seguridad")
    await pg.locator("#modalIn button[data-mclose]", has_text="Cancelar").click(); await pg.wait_for_timeout(200)
    ok(not await pg.locator("#modal").is_visible(), tag + "«Cancelar» cierra sin borrar")
    await pg.locator(f'#tbl tbody tr[data-k="{k}"] [data-del]').click(); await pg.wait_for_timeout(200)
    await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
    ok(not await pg.locator("#modal").is_visible() and not DELS, tag + "Escape cierra sin llamar al box")
    # confirmar (con bloqueo)
    await pg.locator(f'#tbl tbody tr[data-k="{k}"] [data-del]').click(); await pg.wait_for_timeout(200)
    await pg.locator("#delBlock").check()
    await pg.locator("#delGo").click(); await pg.wait_for_timeout(500)
    last = DELS[-1] if DELS else {}
    c0, a0 = k.split(":", 1)
    ok(last.get("op") == "wallets" and last.get("block") is True and last.get("items") == [{"chain": c0, "address": a0}] and last.get("pin") == "test-pin", tag + "envía op=wallets + PIN + block=true")
    ok(await pg.locator(f'#tbl tbody tr[data-k="{k}"]').count() == 0 and not await pg.locator("#modal").is_visible(), tag + "la wallet desaparece de la tabla")
    t0 = await txt("#toast")
    ok("Borrado: 1 wallet" in t0 and "bloqueadas" in t0, tag + "aviso: " + t0[:90])
    await pg.wait_for_timeout(1800)   # deja que termine la recarga programada
    # selección múltiple → Borrar seleccionadas
    await pg.locator("#tbl").scroll_into_view_if_needed()
    ks = [await rows.nth(i).get_attribute("data-k") for i in (0, 1)]
    await rows.nth(0).locator("[data-sel]").check(); await rows.nth(1).locator("[data-sel]").check()
    await pg.locator("#selBar [data-delsel]").click(); await pg.wait_for_timeout(300)
    m = await txt("#modalIn")
    ok("Se borrarán 2 wallets" in m and "Borrar 2 wallets" in m, tag + "«Borrar seleccionadas» → 2 wallets")
    if SHOTS and mobile:
        await pg.evaluate("document.getElementById('tip').classList.add('hide')"); await pg.screenshot(path=f"{SHOTS}/mobile-delete.png")
    await pg.locator("#delGo").click(); await pg.wait_for_timeout(500)
    last = DELS[-1]
    ok(last.get("op") == "wallets" and last.get("block") is False and sorted(i["chain"] + ":" + i["address"] for i in last["items"]) == sorted(ks), tag + "envía las 2 seleccionadas (block=false)")
    ok(all([await pg.locator(f'#tbl tbody tr[data-k="{x}"]').count() == 0 for x in ks]) and not await pg.locator("#selBar").is_visible(), tag + "desaparecen y se vacía la selección")
    await pg.wait_for_timeout(1800)
    # botón en el detalle
    await pg.locator("#tbl").scroll_into_view_if_needed()
    await rows.nth(0).locator("td").nth(5).click(); await pg.wait_for_timeout(400)
    ok(await pg.locator("#drawer [data-del]").is_visible(), tag + "«🗑 Borrar wallet» en el detalle")
    await pg.locator("#drawer [data-del]").click(); await pg.wait_for_timeout(300)
    ok(await pg.locator("#modal").is_visible() and "1 wallet" in await txt("#modalIn"), tag + "desde el detalle abre el diálogo")
    await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
    # Borrar coin desde Tokens
    await pg.locator('#tabs button[data-tab="tokens"]').click(); await pg.wait_for_timeout(300)
    cks = [await x.get_attribute("data-delcoin") for x in await pg.locator("#tokensBox [data-delcoin]").all()]
    tl = [next(x for x in D["tokens"] if x["c"] + ":" + x["a"] == ck) for ck in cks]
    t = next((x for x in tl if coin_plan(D, x)[1] and coin_plan(D, x)[0]), tl[0])   # mejor una coin con wallets compartidas
    ck = t["c"] + ":" + t["a"]
    dl, keep = coin_plan(D, t)
    if PLAN is not None:
        PLAN = {"delete": dl, "keep_other_coins": keep, "keep_favorites": 0, "jobs": 1, "running": False}
    await pg.locator(f'#tokensBox [data-delcoin="{ck}"]').click(); await pg.wait_for_timeout(600)
    m = await txt("#modalIn")
    ok(("Borrar coin" in m) and (f"con {dl} wallet" in m) and (t["sy"] or "") in m, tag + f"Tokens → «Borrar coin» ({dl} wallets): " + m[:100])
    ok((f"Se conservan {keep} wallet" in m) if keep else ("Se conservan" not in m), tag + f"wallets conservadas por estar en otras coins ({keep})")
    ok(("comprobados en el box" in m) if PLAN is not None else ("calculados con los datos del panel" in m), tag + "origen de los números indicado")
    await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
    # desde la cabecera de la coin + confirmar
    await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(200)
    nopt = await pg.locator("#coinSel option").count()
    await pg.select_option("#coinSel", ck); await pg.wait_for_timeout(400)
    await pg.locator("#coinHead [data-delcoin]").click(); await pg.wait_for_timeout(600)
    ok(await pg.locator("#modal").is_visible() and f"con {dl} wallet" in await txt("#modalIn"), tag + "cabecera de la coin → «Borrar coin»")
    if SHOTS:
        await pg.evaluate("document.getElementById('tip').classList.add('hide')")
        await pg.screenshot(path=f"{SHOTS}/{'mobile' if mobile else 'desktop'}-delete-coin.png")
    await pg.locator("#delGo").click(); await pg.wait_for_timeout(500)
    last = DELS[-1]
    ok(last.get("op") == "token" and last.get("chain") == t["c"] and last.get("token") == t["a"] and last.get("block") is False, tag + "envía op=token con chain/token")
    ok(await pg.locator("#coinSel option").count() == nopt - 1 and not await pg.locator("#coinHead").is_visible() and "#coin=" not in pg.url, tag + "la coin desaparece del selector y se vuelve a «todas»")
    await pg.goto(pg.url.split("#")[0], wait_until="networkidle"); await pg.wait_for_timeout(1500)

FAILS = []
SHOTS = None

async def tag_tests(pg, ctx, D, tag, mobile):
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    async def total(): return int((await pg.locator("#fCount").inner_text()).split()[0])
    async def state(t): return await pg.locator(f'#chips .chip[data-tag="{t}"]').get_attribute("aria-pressed")
    async def tap(t):
        el = pg.locator(f'#chips .chip[data-tag="{t}"]')
        await el.scroll_into_view_if_needed()
        if mobile:
            bb = await el.bounding_box(); await pg.touchscreen.tap(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        else:
            await el.click()
        await pg.wait_for_timeout(250)
    W = D["wallets"]; ids = {t["id"] for t in D["tags"]}
    cnt = lambda f: sum(1 for w in W if f(w["tg"]))
    inc = next(t for t in ("activa", "rentable", "temprano", "pumpfun") if t in ids and 0 < cnt(lambda g: t in g) < len(W))
    exc = next(t for t in ("bot", "sniper", "bundle", "scalper", "una_vez") if t in ids and t != inc and cnt(lambda g: inc in g and t in g) > 0)
    await pg.evaluate("window.scrollTo(0,0)")
    await tap(inc); await tap(exc); await tap(exc)
    ok(await state(inc) == "true" and await state(exc) == "mixed", tag + f"3 estados: {inc} ✓ con, {exc} ✕ sin")
    ok("exc" in (await pg.locator(f'#chips .chip[data-tag="{exc}"]').get_attribute("class")) and await pg.locator(f'#chips .chip[data-tag="{exc}"]').evaluate("e=>getComputedStyle(e).textDecorationLine") == "line-through", tag + "excluida en rojo y tachada")
    exp = cnt(lambda g: inc in g and exc not in g)
    ok(await total() == exp, tag + f"Y de incluidas + quitar excluidas ({await total()}={exp})")
    n_exc = (await pg.locator(f'#chips .chip[data-tag="{exc}"] .n').inner_text())
    ok(n_exc == "−%d" % cnt(lambda g: inc in g and exc in g), tag + f"la excluida muestra cuántas oculta ({n_exc})")
    ok(int(await pg.locator(f'#chips .chip[data-tag="{inc}"] .n').inner_text()) == exp, tag + "conteo de la incluida = filas")
    other = [t for t in ids if t not in (inc, exc)]
    bad = []
    for t in other:
        n = int(await pg.locator(f'#chips .chip[data-tag="{t}"] .n').inner_text())
        e = cnt(lambda g: inc in g and exc not in g and t in g)
        z = "zero" in await pg.locator(f'#chips .chip[data-tag="{t}"]').get_attribute("class")
        if n != e or z != (n == 0): bad.append(f"{t}:{n}/{e}/{z}")
    ok(not bad, tag + f"conteos y gris respetan con + sin ({len(other)} etiquetas)" + (": " + ", ".join(bad[:4]) if bad else ""))
    st = " ".join((await pg.locator("#tagSel").inner_text()).split())
    ok("Con:" in st and "Sin:" in st, tag + "barra resumen «Con: … · Sin: …»: " + st[:80])
    h = await pg.evaluate("decodeURIComponent(location.hash)")
    ok(f"con={inc}" in h and f"sin={exc}" in h, tag + "filtros en la URL: " + h)
    await pg.reload(wait_until="networkidle"); await pg.wait_for_timeout(2500)
    ok(await state(inc) == "true" and await state(exc) == "mixed" and await total() == exp, tag + "al recargar se recupera el filtro desde la URL")
    await pg.locator(f'#tagSel [data-untag="{exc}"]').click(); await pg.wait_for_timeout(250)
    ok(await state(exc) == "false" and await total() == cnt(lambda g: inc in g), tag + "✕ en la barra quita la excluida")
    await tap(inc); ok(await state(inc) == "mixed" and await total() == cnt(lambda g: inc not in g), tag + "2.º clic en la incluida → excluida")
    await tap(inc); ok(await state(inc) == "false" and await total() == len(W), tag + "3.º clic → sin filtro")
    h = await pg.evaluate("decodeURIComponent(location.hash)")
    ok("con=" not in h and "sin=" not in h, tag + "URL limpia sin filtros")
    # preset «Quitar ruido»
    noise = [t for t in ("bot", "sniper", "bundle", "one_hit", "insuficiente", "una_vez") if t in ids]
    await pg.locator("#noiseBtn").scroll_into_view_if_needed(); await pg.locator("#noiseBtn").click(); await pg.wait_for_timeout(300)
    xs = await pg.locator("#chips .chip.exc").evaluate_all("els=>els.map(e=>e.dataset.tag)")
    ok(sorted(xs) == sorted(noise), tag + "«Quitar ruido» excluye: " + ", ".join(xs))
    expn = cnt(lambda g: not any(t in g for t in noise))
    ok(await total() == expn and "on" in await pg.locator("#noiseBtn").get_attribute("class"), tag + f"«Quitar ruido» deja {expn} wallets")
    if shots:
        await pg.mouse.move(1, 1) if not mobile else None; await pg.evaluate("document.getElementById('toast').classList.add('hide');window.scrollTo(0,0)")
        await pg.locator("#tagSel").scroll_into_view_if_needed(); await pg.evaluate("window.scrollBy(0,-150)"); await pg.wait_for_timeout(150)
        await pg.evaluate("document.getElementById('tip').classList.add('hide')")
        await pg.screenshot(path=f"{SHOTS}/{'mobile' if mobile else 'desktop'}-tags-3estados.png")
    await pg.locator("#noiseBtn").click(); await pg.wait_for_timeout(300)
    ok(await pg.locator("#chips .chip.exc").count() == 0 and await total() == len(W), tag + "2.º clic en «Quitar ruido» lo deshace")
    if mobile:
        # pulsación larga: muestra la ayuda y NO cambia el filtro
        t3 = inc
        el = pg.locator(f'#chips .chip[data-tag="{t3}"]'); await el.scroll_into_view_if_needed(); bb = await el.bounding_box()
        x, y = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
        cdp = await ctx.new_cdp_session(pg)
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        await pg.wait_for_timeout(900)
        tipv = await pg.locator("#tip").is_visible(); tipt = await pg.locator("#tip").inner_text()
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        await pg.wait_for_timeout(400)
        ok(tipv and "Clic" in tipt, tag + "pulsación larga muestra la ayuda: " + tipt[-70:])
        ok(await state(t3) == "false" and await total() == len(W), tag + "pulsación larga no cambia el filtro")
        await tap(t3); ok(await state(t3) == "true", tag + "toque normal sí filtra (✓)")
        await tap(t3); ok(await state(t3) == "mixed", tag + "2.º toque → ✕"); await tap(t3); ok(await state(t3) == "false", tag + "3.º toque → quitar")

async def edge_point(pg, eid):
    """Punto de pantalla en mitad de una línea del grafo (para hacer clic/tocar como una persona)."""
    return await pg.evaluate("""(id) => { const p = document.querySelector('#ckSvg .ed[data-edge="' + id + '"] .eh'); p.scrollIntoView({block: 'center'});
        const L = p.getTotalLength(), q = p.getPointAtLength(L / 2), m = p.getScreenCTM(); return [q.x * m.a + q.y * m.c + m.e, q.x * m.b + q.y * m.d + m.f]; }""", eid)

async def connect_tests(pg, D, tag, mobile):
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    async def txt(sel): return " ".join((await pg.locator(sel).first.inner_text()).split())
    R = CHECK
    nm = "mobile" if mobile else "desktop"
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.locator('#tabs button[data-tab="conn"]').click(); await pg.wait_for_timeout(300)
    if mobile:   # (en escritorio la prueba de exportar ya pasó por Clusters: la pestaña recuerda la sub-sección)
        ok(await pg.locator("#ckItems").is_visible() and await pg.locator('#connSeg [data-csub="check"].on').count() == 1, tag + "Conexiones abre en «Comprobar conexiones»")
    await pg.locator('#connSeg [data-csub="check"]').click(); await pg.wait_for_timeout(200)
    ok(await pg.locator("#ckItems").is_visible() and not await pg.locator("#connBox").is_visible(), tag + "sub-sección «Comprobar conexiones»")
    await pg.locator('#connSeg [data-csub="clusters"]').click(); await pg.wait_for_timeout(300)
    ok(await pg.locator("#connBox").is_visible() and not await pg.locator("#ckItems").is_visible() and "Clusters" in await txt("#connBox"), tag + "sub-sección Clusters conservada")
    await pg.locator('#connSeg [data-csub="check"]').click(); await pg.wait_for_timeout(300)
    # formulario
    await pg.fill("#ckItems", R["wallets"][0])
    ok("añade al menos otra" in await txt("#ckCount"), tag + "aviso con 1 sola wallet")
    await pg.fill("#ckItems", "\n".join(R["wallets"]) + "\nhttps://solscan.io/account/" + R["wallets"][0])
    ok(await txt("#ckCount") == "%d wallets · Solana" % len(R["wallets"]), tag + "detecta chain y quita duplicados: " + await txt("#ckCount"))
    await pg.fill("#ckItems", R["wallets"][0] + " 0x" + "ab" * 20)
    ok("mezcla Solana y EVM" in await txt("#ckCount"), tag + "aviso al mezclar Solana y EVM")
    await pg.fill("#ckItems", "\n".join(R["wallets"]))
    n0 = len(CONNECTS)
    await pg.locator("#ckGo").click(); await pg.wait_for_timeout(700)
    ok(len(CONNECTS) == n0 + 1 and CONNECTS[-1].get("pin") == "test-pin" and CONNECTS[-1]["wallets"].split() == R["wallets"] and CONNECTS[-1]["chain"] == "auto", tag + "envía al box: wallets + chain + PIN")
    ok(await pg.locator(".ckprog").is_visible() and "Comprobando" in await txt(".ckprog"), tag + "progreso visible: " + (await txt(".ckprog"))[:70])
    if shots and not mobile:
        await pg.locator(".ckprog").screenshot(path=f"{SHOTS}/desktop-connections-progress.png")
    try:
        await pg.wait_for_selector("#ckRes .ckres", timeout=15000); await pg.wait_for_timeout(1200)   # (termina el scroll suave hasta el resultado)
    except Exception:
        pass
    ok(await pg.locator("#ckRes .ckres").count() == 1 and not await pg.locator(".ckprog").count(), tag + "resultado mostrado al terminar")
    if not await pg.locator("#ckRes .ckres").count():
        return
    nn, ne = await pg.locator("#ckSvg .nd").count(), await pg.locator("#ckSvg .ed").count()
    ok(nn == len(R["nodes"]) and ne == len(R["edges"]), tag + f"grafo: {nn} nodos, {ne} líneas")
    madre_n = sum(1 for n in R["nodes"] if n.get("madre"))
    ok(await pg.locator("#ckSvg .nd.madre").count() == madre_n, tag + f"wallets madre resaltadas en el grafo ({madre_n})")
    ok(await pg.locator("#ckSvg .nd.k-input").count() == len(R["wallets"]), tag + "tus wallets como nodos principales")
    # clic en una línea → pruebas con fecha, importe y enlace a la tx
    e = next((x for x in R["edges"] if x["type"] == "transfer"), R["edges"][0])
    x, y = await edge_point(pg, e["id"])
    if mobile: await pg.touchscreen.tap(x, y)
    else: await pg.mouse.click(x, y)
    await pg.wait_for_timeout(300)
    ev = await txt("#ckEv")
    hrefs = await pg.locator("#ckEv a.xl").evaluate_all("els=>els.map(e=>e.href)")
    tx_base = (D or {}).get("chains", {}).get(R["chain"], {}).get("tx", "https://solscan.io/tx/")
    ok(await pg.locator(f'#ckSvg .ed.on[data-edge="{e["id"]}"]').count() == 1, tag + f"clic en la línea {e['type']} la resalta")
    ok(bool(hrefs) and all(h.startswith(tx_base) for h in hrefs) and e["ev"][0]["tx"] in hrefs[0], tag + f"pruebas con enlace a la tx ({len(hrefs)}): " + (hrefs[0][:60] if hrefs else "-"))
    ok("/20" in ev and ("SOL" in ev or e["ev"][0].get("asset", "") in ev), tag + "pruebas con fecha e importe: " + ev[:90])
    if shots:
        await pg.evaluate("document.getElementById('toast').classList.add('hide');document.getElementById('tip').classList.add('hide')")
        if mobile:
            await pg.locator("#ckSvg").scroll_into_view_if_needed(); await pg.evaluate("window.scrollBy(0,-60)")
            await pg.screenshot(path=f"{SHOTS}/mobile-connections.png")
            await pg.locator("#ckEv").scroll_into_view_if_needed(); await pg.screenshot(path=f"{SHOTS}/mobile-connections-evidence.png")
        else:
            await pg.evaluate("document.getElementById('ckRes').scrollIntoView()")
            await pg.screenshot(path=f"{SHOTS}/desktop-connections.png")
            await pg.locator("#ckRes .ckres").screenshot(path=f"{SHOTS}/desktop-connections-full.png")
    # tabla de pares
    rows = pg.locator("#ckRes [data-ckpair]")
    ok(await rows.count() == len(R["pairs"]), tag + f"tabla de pares ({await rows.count()})")
    p0 = R["pairs"][0]
    r0 = " ".join((await rows.nth(0).inner_text()).split())
    ok(str(p0["score"]) in r0 and p0["reason"][:40] in r0, tag + "par con score y motivo en castellano: " + r0[:100])
    await rows.nth(0).click(); await pg.wait_for_timeout(300)
    ok(await pg.locator("#ckRes tr.on[data-ckpair]").count() == 1 and str(p0["score"]) in await txt("#ckEv") and await pg.locator("#ckSvg .nd.dim").count() > 0, tag + "clic en un par lo resalta en el grafo")
    if await pg.locator("#ckEv [data-ckedge]").count():
        await pg.locator("#ckEv [data-ckedge]").first.click(); await pg.wait_for_timeout(200)
        ok(await pg.locator("#ckEv a.xl").count() > 0, tag + "desde el par: «ver pruebas»")
    await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
    ok(await pg.locator("#ckSvg .nd.dim").count() == 0, tag + "Escape quita el resaltado")
    madres = [b for b in R["bridges"] if b["madre"]]
    brt = await txt("#ckRes .ckres")
    ok((not madres or "posible wallet madre" in brt) and all((b["label"] or b["address"][:4]) [:4] in brt for b in madres), tag + f"puentes «wallet madre» listados ({len(madres)})")
    if any(i.get("truncated") for i in R["info"].values()):
        ok(await pg.locator("#ckRes .warnbox", has_text="truncado").count() > 0, tag + "aviso de historial truncado")
    # arrastrar un nodo (escritorio)
    if not mobile:
        g = pg.locator("#ckSvg .nd.k-input").first
        t0 = await g.get_attribute("transform"); bb = await g.bounding_box()
        await pg.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2 - 4); await pg.mouse.down()
        await pg.mouse.move(bb["x"] + 60, bb["y"] + 40, steps=5); await pg.mouse.up(); await pg.wait_for_timeout(200)
        ok(await pg.locator("#ckSvg .nd.k-input").first.get_attribute("transform") != t0, tag + "arrastrar un nodo lo mueve")
    # exportar grupo (diálogo existente)
    await pg.locator('#ckRes [data-export="check"]').click(); await pg.wait_for_timeout(300)
    extra = [b["address"] for b in madres if b["address"] not in R["wallets"]]
    gm = json.loads(await pg.locator("#out-gmgn").input_value()) if await pg.locator("#modal").is_visible() else []
    ok([x["address"] for x in gm] == R["wallets"] + extra, tag + f"«Exportar grupo»: {len(R['wallets'])} wallets + {len(extra)} madre")
    await pg.keyboard.press("Escape")
    # guardadas
    ok(await pg.locator("#ckSaved [data-ckopen]").count() >= 1, tag + f"lista de comprobaciones guardadas ({await pg.locator('#ckSaved [data-ckopen]').count()})")
    await pg.locator("#ckResX").click(); await pg.wait_for_timeout(200)
    ok(await pg.locator("#ckRes .ckres").count() == 0, tag + "cerrar resultado")
    await pg.locator("#ckSaved [data-ckopen]").first.click(); await pg.wait_for_timeout(800)
    ok(await pg.locator("#ckRes .ckres").count() == 1, tag + "abrir una comprobación guardada")
    pg.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
    nb = await pg.locator("#ckSaved [data-ckdel]").count()
    await pg.locator("#ckSaved [data-ckdel]").first.click(); await pg.wait_for_timeout(600)
    ok(await pg.locator("#ckSaved [data-ckdel]").count() < nb, tag + "borrar una comprobación guardada")
    # re-render del panel (cada tick) no borra el formulario ni el resultado
    await pg.fill("#ckItems", "abc"); await pg.evaluate("document.querySelector('#tabs button[data-tab=\"conn\"]').click()"); await pg.wait_for_timeout(300)
    ok(await pg.locator("#ckItems").input_value() == "abc", tag + "el formulario no se borra al refrescar")
    # Trabajos
    await pg.locator('#tabs button[data-tab="jobs"]').click(); await pg.wait_for_timeout(300)
    if await pg.locator("#jobsBox [data-ckjob]").count():
        ok("🔗 Conexiones" in await txt("#jobsBox"), tag + "Trabajos muestra el tipo «🔗 Conexiones»")
        await pg.locator("#jobsBox [data-ckjob]").first.click(); await pg.wait_for_timeout(1000)
        ok(await pg.locator("#ckRes .ckres").is_visible(), tag + "Trabajos → «Ver resultado» abre la comprobación")
    else:
        print("--   " + tag + "no hay trabajos de conexiones en los datos: prueba de Trabajos omitida")
    # «comprobar conexiones» desde una fila y desde el detalle
    if D:
        await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)
        k = await pg.locator("#tbl tbody tr[data-k]").first.get_attribute("data-k")
        w = next(x for x in D["wallets"] if x["c"] + ":" + x["a"] == k)
        exp = [w["a"]] + [a for a in dict.fromkeys(l[0] for l in (w.get("lk") or [])) if a != w["a"]]
        await pg.locator(f'#tbl tbody tr[data-k="{k}"] [data-ck]').click(); await pg.wait_for_timeout(400)
        val = (await pg.locator("#ckItems").input_value()).split()
        ok(await pg.locator("#ckItems").is_visible() and val == exp[:10] and not await pg.locator("#drawer").is_visible(), tag + f"🔗 en la fila rellena la wallet + sus vínculos ({len(val)})")
        await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)
        await pg.locator("#tbl tbody tr[data-k]").nth(1).click(); await pg.wait_for_timeout(300)
        await pg.locator("#drawer [data-ck]").click(); await pg.wait_for_timeout(400)
        k1 = await pg.locator("#tbl tbody tr[data-k]").nth(1).get_attribute("data-k") if await pg.locator("#tbl tbody tr[data-k]").count() > 1 else ""
        ok(await pg.locator("#ckItems").is_visible() and (await pg.locator("#ckItems").input_value()).split()[0] == k1.split(":", 1)[-1] and not await pg.locator("#drawer").is_visible(), tag + "«🔗 Comprobar conexiones» en el detalle")
        if shots and not mobile:
            await pg.locator("#connCheck .box").first.screenshot(path=f"{SHOTS}/desktop-connections-prefill.png")
    await pg.fill("#ckItems", "")
    await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(200)


async def svc_tests(pg, D, tag, mobile):
    try:
        await _svc_tests(pg, D, tag, mobile)
    finally:
        await pg.evaluate("localStorage.removeItem('wh_ck_hidesvc')")
        await pg.keyboard.press("Escape")
        await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)


async def _svc_tests(pg, D, tag, mobile):
    """Servicios compartidos: nodos grises con nombre, aristas propias, leyenda, motivo «solo porque ambas usan…» y el interruptor."""
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    async def txt(sel): return " ".join((await pg.locator(sel).first.inner_text()).split())
    R = SVCK
    nm = "mobile" if mobile else "desktop"
    await pg.evaluate("localStorage.removeItem('wh_ck_hidesvc')")
    await pg.locator('#tabs button[data-tab="conn"]').click(); await pg.wait_for_timeout(300)
    await pg.locator('#connSeg [data-csub="check"]').click(); await pg.wait_for_timeout(300)
    if not await pg.locator('#ckSaved [data-ckopen="svc1"]').count():
        if await pg.locator("#ckLoad").count(): await pg.locator("#ckLoad").click(); await pg.wait_for_timeout(600)
    if not await pg.locator('#ckSaved [data-ckopen="svc1"]').count():
        ok(False, tag + "servicios: no aparece la comprobación de prueba"); return
    await pg.locator('#ckSaved [data-ckopen="svc1"]').click(); await pg.wait_for_timeout(1200)
    sv_nodes = [n for n in R["nodes"] if n["kind"] == "service"]
    sv_edges = [e for e in R["edges"] if e.get("svc")]
    ok(await pg.locator("#ckSvg .nd.k-service").count() == len(sv_nodes), tag + f"servicios: {len(sv_nodes)} nodos grises de servicio")
    labels = await pg.locator("#ckSvg .nd.k-service .nl").evaluate_all("els=>els.map(e=>e.textContent||'')")
    ok(any("🔁 Relay" in x for x in labels) and any("Axiom" in x for x in labels) and any("servicio/hub" in x for x in labels), tag + "servicios: nombre e icono en el nodo: " + " | ".join(labels))
    fill = await pg.locator("#ckSvg .nd.k-service circle").first.evaluate("e=>getComputedStyle(e).fill")
    ok(fill in ("rgb(75, 85, 99)",), tag + "servicios: nodo gris (" + fill + ")")
    ok(await pg.locator("#ckSvg .ed.svc").count() == len(sv_edges) and len(sv_edges) > 0, tag + f"servicios: {len(sv_edges)} líneas con estilo propio")
    dash = await pg.locator("#ckSvg .ed.svc .ev").first.get_attribute("stroke-dasharray")
    ok(dash == "1 5", tag + "servicios: línea punteada gris")
    lg = await txt("#ckRes .cklegend")
    ok("Vía un servicio compartido (no cuenta)" in lg and "servicio/hub (gris)" in lg, tag + "servicios: entrada en la leyenda")
    rows = pg.locator("#ckRes [data-ckpair]")
    texts = [" ".join(t.split()) for t in await rows.all_inner_texts()]
    relay_row = next((t for t in texts if "ambas usan Relay" in t), "")
    ok("posible conexión solo porque ambas usan Relay" in relay_row, tag + "servicios: motivo «posible conexión solo porque ambas usan Relay»")
    ok(await pg.locator("#ckRes tr.svcrow").count() == sum(1 for p in R["pairs"] if p["svc_only"]), tag + "servicios: pares «solo servicio» en gris")
    sc = [p["score"] for p in R["pairs"] if p["svc_only"]]
    ok(sc and max(sc) <= 5, tag + f"servicios: peso casi 0 en el score ({sc})")
    real = next(t for t in texts if "transferencia directa" in t)
    ok("Además ambas usan Axiom: no cuenta" in real, tag + "servicios: el par real lo menciona aparte («no cuenta»)")
    # clic en el nodo de servicio
    g = pg.locator("#ckSvg .nd.k-service", has_text="Relay").first
    bb = await g.bounding_box()
    if mobile: await pg.touchscreen.tap(bb["x"] + bb["width"] / 2, bb["y"] + 8)
    else: await pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + 8)
    await pg.wait_for_timeout(300)
    ev = await txt("#ckEv")
    ok("servicio compartido" in ev and "no las conecta" in ev and "verificada" in ev, tag + "servicios: detalle del nodo: " + ev[:90])
    ok("🔁 Relay" in await txt("#ckRes") and "Servicios compartidos" in await txt("#ckRes"), tag + "servicios: lista «Servicios compartidos» con su etiqueta")
    if SHOTS:
        await pg.evaluate("document.getElementById('toast').classList.add('hide');document.getElementById('tip').classList.add('hide')")
        if mobile:
            await pg.locator("#ckSvg").scroll_into_view_if_needed(); await pg.evaluate("window.scrollBy(0,-110)")
            await pg.screenshot(path=f"{SHOTS}/mobile-servicios.png")
            await pg.locator("#ckEv").scroll_into_view_if_needed(); await pg.screenshot(path=f"{SHOTS}/mobile-servicios-detalle.png")
        else:
            await pg.locator("#ckRes .ckres").screenshot(path=f"{SHOTS}/desktop-servicios.png")
    # interruptor
    await pg.keyboard.press("Escape"); await pg.wait_for_timeout(150)
    await pg.locator("#ckHideSvc").click(); await pg.wait_for_timeout(400)
    ok(await pg.locator("#ckSvg .nd.k-service").count() == 0 and await pg.locator("#ckSvg .ed.svc").count() == 0, tag + "«Ocultar conexiones por servicios» quita nodos y líneas")
    ok(await pg.locator("#ckSvg .nd.k-input").count() == len(R["wallets"]), tag + "ocultar: tus wallets siguen")
    texts2 = [" ".join(t.split()) for t in await pg.locator("#ckRes [data-ckpair]").all_inner_texts()]
    ok(sum(1 for t in texts2 if "Sin conexión real: solo comparten servicios (ocultos)" in t) == len(sc) and not any("Además ambas usan" in t for t in texts2), tag + "ocultar: motivos sin servicios")
    ok("Vía un servicio" not in await txt("#ckRes .cklegend") and "ocultos" in await txt("#ckRes"), tag + "ocultar: leyenda y lista se actualizan")
    ok(await pg.evaluate("localStorage.getItem('wh_ck_hidesvc')") == "1", tag + "ocultar: se recuerda")
    if SHOTS and not mobile:
        await pg.locator("#ckRes .ckres").screenshot(path=f"{SHOTS}/desktop-servicios-ocultos.png")
    # clusters: mismo interruptor
    await pg.locator('#connSeg [data-csub="clusters"]').click(); await pg.wait_for_timeout(300)
    ok(await pg.locator("#clHideSvc").is_checked() and await pg.locator("#connBox .svclist").count() == 0, tag + "clusters: el interruptor se comparte (oculto)")
    await pg.locator("#clHideSvc").click(); await pg.wait_for_timeout(300)
    cl = await txt("#clSvc")
    if NO_BOX:
        ok(not await pg.locator("#clHideSvc").is_checked() and "7 vínculos ignorados por servicios" in cl and await pg.locator("#connBox .svclist .ckbr").count() == 2, tag + "clusters: vínculos ignorados por servicios + lista: " + cl[:80])
        ok("🔁 Relay" in await txt("#connBox .svclist") and "autodetectado" in await txt("#connBox .svclist"), tag + "clusters: servicio conocido y hub autodetectado")
    else:   # datos reales: lo que diga data.json
        SV = (D or {}).get("svc") or {}; nh = len([x for x in SV.get("hubs") or []][:30]); sk = SV.get("skipped") or 0
        ok(not await pg.locator("#clHideSvc").is_checked() and (("%d vínculo" % sk) in cl if sk else "ningún vínculo ignorado por servicios" in cl) and await pg.locator("#connBox .svclist .ckbr").count() == nh, tag + f"clusters (datos reales): {sk} ignorados · {nh} servicios: " + cl[:80])
    if SHOTS:
        await pg.locator("#connBox .box").first.scroll_into_view_if_needed() if mobile else None
        await pg.locator("#clSvc").scroll_into_view_if_needed()
        await pg.locator("#connBox .box").nth(1).screenshot(path=f"{SHOTS}/{nm}-clusters-servicios.png")
    await pg.locator('#connSeg [data-csub="check"]').click(); await pg.wait_for_timeout(200)
    ok(not await pg.locator("#ckHideSvc").is_checked() and await pg.locator("#ckSvg .nd.k-service").count() == len(sv_nodes), tag + "volver: servicios visibles otra vez")
    # detalle de una wallet de la base con servicio compartido
    if D and D.get("svc"):
        await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)
        k = await pg.locator("#tbl tbody tr[data-k]").first.get_attribute("data-k")
        w = next((x for x in D["wallets"] if x["c"] + ":" + x["a"] == k), None)
        if w and w.get("sv"):
            await pg.locator("#tbl tbody tr[data-k]").first.click(); await pg.wait_for_timeout(400)
            dt = await txt("#drawer")
            ok("Servicios compartidos" in dt and "🔁 Relay" in dt and "No cuentan para los clusters" in dt, tag + "detalle de wallet: servicios compartidos etiquetados")
            await pg.keyboard.press("Escape"); await pg.wait_for_timeout(200)
        else:
            print("--   " + tag + "la primera wallet no tiene servicios de prueba: detalle omitido")
    await pg.evaluate("localStorage.removeItem('wh_ck_hidesvc')")


async def smartx_tests(pg, D, tag, mobile):
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    await pg.evaluate("window.scrollTo(0,0)")
    await pg.locator('#tabs button[data-tab="smartx"]').click(); await pg.wait_for_timeout(400)
    ok(await pg.locator("#smartxBox").is_visible() and not await pg.locator("#tab-wallets").is_visible(), tag + "pestaña 🧠 Smart cruzado")
    sx = (D or {}).get("smartx") or []
    if sx:
        rows = await pg.locator("#smartxBox table.sx tr").count() - 1
        ok(rows == len(sx), tag + f"smart cruzado: {rows} filas (esperado {len(sx)})")
        ok(await pg.locator("#smartxBox .sxc").count() == sum(len(r["coins"]) for r in sx), tag + "chips por coin (PnL · puesto · entrada)")
        first = await pg.locator("#smartxBox table.sx tr").nth(1).inner_text()
        ok("3" in first and "+9,50" in first, tag + "orden: más coins primero, PnL total " + first.split("\n")[0][:40])
        await pg.locator('#smartxBox [data-export="smartx"]').click(); await pg.wait_for_timeout(300)
        ok(len(json.loads(await pg.locator("#out-json").input_value())) == len(sx), tag + "exportar smart cruzado")
        await pg.keyboard.press("Escape")
        if SHOTS:
            await pg.evaluate("document.getElementById('tip').classList.add('hide')")
            await pg.screenshot(path=SHOTS + ("/mobile" if mobile else "/desktop") + "-smartx.png", full_page=not mobile)
        # filtro de chain sin datos -> estado vacío explicativo
        await pg.select_option("#chainSel", "ethereum"); await pg.wait_for_timeout(300)
        t = await pg.locator("#smartxBox .empty").inner_text()
        ok("al menos 2 coins" in t, tag + "estado vacío: explica que hacen falta 2+ coins")
        await pg.select_option("#chainSel", ""); await pg.wait_for_timeout(300)
    else:
        t = await pg.locator("#smartxBox .empty").inner_text() if await pg.locator("#smartxBox .empty").count() else ""
        ok("coins" in t, tag + "smart cruzado vacío con explicación: " + t[:70].replace("\n", " "))
        if SHOTS:
            await pg.screenshot(path=SHOTS + ("/mobile" if mobile else "/desktop") + "-smartx-vacio.png")
    await pg.locator('#tabs button[data-tab="wallets"]').click(); await pg.wait_for_timeout(300)

async def favs_tests(pg, D, tag, mobile):
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: FAILS.append(msg)
    FAVSRV.clear(); FAVADDS.clear(); TGOPS.clear(); TG.update(chat=False, chat_name=None)
    SET.update(dormant_days=7, funder_watch=False)
    await pg.evaluate("window.scrollTo(0,0)")
    keys = await pg.locator("#tbl tbody tr[data-k]").evaluate_all("els=>els.slice(0,2).map(e=>e.dataset.k)")
    for k in keys:
        await pg.locator(f'#tbl tbody tr[data-k="{k}"] [data-star]').click(); await pg.wait_for_timeout(400)
    ok(len(FAVSRV) == 2, tag + f"⭐ guardadas en el box ({len(FAVSRV)})")
    await pg.locator('#tabs button[data-tab="favs"]').click(); await pg.wait_for_timeout(1200)
    ths = await pg.locator("#tbl thead th").all_inner_texts()
    ok(any("Sin tradear" in h for h in ths), tag + "columna «💤 Sin tradear» en Mis wallets")
    dz = await pg.locator("#tbl tbody .dz").all_inner_texts()
    ok(sorted(x.strip() for x in dz) == ["1 d", "💤 10 d"], tag + "días sin tradear: " + ", ".join(dz))
    ok(await pg.locator("#tbl tbody .dz.on").count() == 1, tag + "💤 en rojo solo la que pasa el umbral (7 d)")
    await pg.locator("#favExtra").scroll_into_view_if_needed()
    ok("Test_bot" in await pg.locator("#favExtra").inner_text() and await pg.locator("#tgDetect").is_visible(), tag + "Telegram: falta el chat + botón «Detectar chat»")
    await pg.locator("#tgDetect").click(); await pg.wait_for_timeout(600)
    ok(TGOPS[-1:] == ["detect"] and await pg.locator("#tgTest").is_visible(), tag + "chat detectado → botón «Enviar prueba»")
    await pg.locator("#tgTest").click(); await pg.wait_for_timeout(600)
    ok(TGOPS[-1:] == ["test"] and "prueba" in await pg.locator("#toast").inner_text(), tag + "enviar prueba (simulado)")
    await pg.fill("#dzDays", "5"); await pg.locator("#fwEn").check(); await pg.fill("#fwSol", "2"); await pg.fill("#fwMin", "30")
    await pg.locator("#alSave").click(); await pg.wait_for_timeout(800)
    ok(SET["dormant_days"] == 5 and SET["funder_watch"] is True and SET["funder_min_native"]["solana"] == 2 and SET["funder_poll_minutes"] == 30, tag + "ajustes de dormidas y fondeadores guardados")
    txt = await pg.locator("#favExtra").inner_text()
    ok("👀 sí" in txt and "no: exchange" in txt, tag + "lista de fondeadores vigilados (y por qué no el exchange)")
    ok("créditos/día" in txt, tag + "coste estimado en créditos/día")
    ok(await pg.locator("#tbl tbody .dz.on").count() == 1, tag + "umbral nuevo aplicado a la columna")
    ok(await pg.locator("#alList").inner_text() != "" and await pg.locator("#alList [data-addfav]").count() == 1, tag + "alertas por tipo + «⭐ Añadir» en la de fondeador")
    hrefs = await pg.locator("#alList a.xl").evaluate_all("els=>els.map(e=>e.href)")
    ok(any("gmgn.ai" in h for h in hrefs) and any("solscan.io/tx/5xSig" in h for h in hrefs), tag + "alerta de fondeador con Solscan/GMGN/tx")
    if SHOTS:
        await pg.evaluate("document.getElementById('tip').classList.add('hide')")
        await pg.evaluate("document.querySelector('.top').style.position='static'")
        await pg.locator("#favExtra").screenshot(path=SHOTS + ("/mobile" if mobile else "/desktop") + "-alertas.png")
        await pg.evaluate("document.querySelector('.top').style.position=''")
        await pg.evaluate("window.scrollTo(0,0)"); await pg.screenshot(path=SHOTS + ("/mobile" if mobile else "/desktop") + "-mis-wallets.png")
    pg.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await pg.locator("#alList [data-addfav]").click(); await pg.wait_for_timeout(800)
    ok(FAVADDS and FAVADDS[-1]["address"] == KID and FAVADDS[-1]["scan"] is True, tag + "⭐ Añadir desde la alerta (+ análisis en cola)")
    k2 = "NewKid22" + "Q" * 36
    pg.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await pg.evaluate(f"location.hash='#addfav=solana:{k2}'"); await pg.wait_for_timeout(1200)
    ok(FAVADDS and FAVADDS[-1]["address"] == k2, tag + "enlace #addfav= de Telegram añade la ⭐")
    ok(await pg.evaluate("location.hash") == "#favs", tag + "el hash se limpia tras añadir")
    # limpiar: quitar las ⭐ de la prueba
    for a in [f["address"] for f in list(FAVSRV)]:
        await pg.evaluate("(k)=>{var s=JSON.parse(localStorage.getItem('wh_favs')||'{}');delete s[k];localStorage.setItem('wh_favs',JSON.stringify(s));}", "solana:" + a)
    FAVSRV.clear(); SET.update(dormant_days=7, funder_watch=False)
    await pg.evaluate("location.hash=''"); await pg.goto(URL, wait_until="networkidle"); await pg.wait_for_timeout(2500)

async def main():
    global SHOTS
    SHOTS = shots
    fails, errs = FAILS, []
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: fails.append(msg)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        for mobile in (False, True):
            ctx = await b.new_context(accept_downloads=True, viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}, is_mobile=mobile, has_touch=mobile)
            await ctx.add_init_script("localStorage.setItem('wh_pin','test-pin')")
            await ctx.route("**/api/**", fake_api)
            if NO_BOX:
                async def fake_box(route):
                    u = route.request.url
                    if "/api/" in u: return await fake_api(route)
                    if "/health" in u: body = json.dumps({"ok": True, "pin_set": True, "t": int(time.time())})
                    else:
                        dd = json.load(open(os.environ.get("UITEST_DATA", "/tmp/whweb/data.json"), encoding="utf-8"))
                        dd.setdefault("jobs", []).insert(0, {"id": "old1", "created": int(time.time()) - 3600, "kind": "connect", "chain": "solana", "items": [w[:4] + "…" + w[-4:] for w in CHECK["wallets"]], "status": "done", "progress": "terminado", "message": "%d wallets (Solana)" % len(CHECK["wallets"]), "started": int(time.time()) - 3600, "finished": int(time.time()) - 3550, "origin": "web"})
                        body = json.dumps(tokscan_apply(augment(dd)))
                    await route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=body)
                await ctx.route("http://127.0.0.1:18795/**", fake_box)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
            await pg.goto(URL, wait_until="networkidle"); await pg.wait_for_timeout(2500)
            tag = "[móvil] " if mobile else "[escritorio] "
            D = await pg.evaluate("fetch('data.json').then(r=>r.json()).catch(()=>null)") if "127.0.0.1" in URL else None
            if D is None:
                D = await pg.evaluate("fetch(window.WH_CONFIG.dataUrl+'?t='+Date.now()).then(r=>r.json()).catch(()=>null)")
            if D and not D["wallets"]:
                D = None
            if D and NO_BOX: augment(D)
            ntags = await pg.locator("#chips .chip").count()
            total_tags = len(D["tags"]) if D else ntags
            ok(ntags == total_tags and ntags > 0, tag + f"todas las etiquetas visibles ({ntags}/{total_tags})")
            # 1) seleccionar dos etiquetas: todas siguen visibles, seleccionadas resaltadas, las de 0 en gris, resumen visible
            await pg.locator('#chips .chip[data-tag="fondeo_sync"]').click(); await pg.wait_for_timeout(300)
            await pg.locator('#chips .chip[data-tag="sniper"]').click(); await pg.wait_for_timeout(300)
            ok(await pg.locator("#chips .chip").count() == total_tags, tag + "tras filtrar siguen todas las etiquetas")
            ok(await pg.locator("#chips .chip.sel").count() == 2, tag + "2 etiquetas resaltadas")
            nz = await pg.locator("#chips .chip.zero").count()
            ok(nz > 0, tag + f"etiquetas con 0 resultados en gris ({nz})")
            ok(await pg.locator("#tagSel").is_visible(), tag + "resumen de etiquetas activas visible")
            rows = await pg.locator("#tbl tbody tr[data-k]").count()
            sel_n = await pg.locator('#chips .chip[data-tag="sniper"] .n').inner_text()
            ok(int(sel_n) == rows, tag + f"conteo de la etiqueta = filas filtradas ({sel_n}={rows})")
            if D:
                exp = sum(1 for w in D["wallets"] if "fondeo_sync" in w["tg"] and "sniper" in w["tg"])
                ok(rows == exp, tag + f"semántica Y correcta ({rows}={exp})")
            await pg.locator("#clrTags").click(); await pg.wait_for_timeout(300)
            ok(await pg.locator("#chips .chip.sel").count() == 0 and not await pg.locator("#tagSel").is_visible(), tag + "«Quitar filtros de etiquetas» limpia")
            if D: await tag_tests(pg, ctx, D, tag, mobile)
            if not mobile:
                # 2) hoja 🌱
                leaves = await pg.locator("#tbl tbody .leaf").count()
                if D:
                    now = time.time()
                    fr = sum(1 for w in D["wallets"][:300] if ((w["ft"] and not w["at"]) and now - w["ft"] <= 7 * 86400) or (not w["ft"] and w.get("fa") and now - w["fa"] <= 7 * 86400))
                    ok(abs(leaves - fr) <= 2, tag + f"🌱 en wallets frescas ({leaves}, esperado ~{fr})")
                await pg.locator("#fFresh").check(); await pg.wait_for_timeout(300)
                r2 = await pg.locator("#tbl tbody tr[data-k]").count(); l2 = await pg.locator("#tbl tbody .leaf").count()
                ok(r2 == l2 and r2 > 0, tag + f"filtro «Solo frescas» ({r2})"); await pg.locator("#fFresh").uncheck()
                # 3) Trades: ordenar y filtrar
                await pg.locator('th[data-sort="tr"]').click(); await pg.wait_for_timeout(300)
                k0 = await pg.locator("#tbl tbody tr[data-k]").first.get_attribute("data-k")
                if D:
                    mx = max(D["wallets"], key=lambda w: w["tr"] or -1)
                    ok(k0 == mx["c"] + ":" + mx["a"], tag + f"ordenar por Trades (máx {mx['tr']})")
                await pg.fill("#fTrades", "100"); await pg.wait_for_timeout(300)
                r3 = await pg.locator("#tbl tbody tr[data-k]").count()
                if D: ok(r3 == sum(1 for w in D["wallets"] if (w["tr"] or 0) >= 100), tag + f"filtro Trades ≥ 100 ({r3})")
                await pg.fill("#fTrades", "")
                # 4) fondeo reciente
                await pg.fill("#fFund", "24"); await pg.wait_for_timeout(300)
                r4 = await pg.locator("#tbl tbody tr[data-k]").count()
                if D: ok(r4 == sum(1 for w in D["wallets"] if w.get("lf") and time.time() - w["lf"] <= 24 * 3600), tag + f"filtro «Fondeada hace < 24 h» ({r4})")
                await pg.fill("#fFund", "")
                # enlaces
                hrefs = await pg.locator("#tbl tbody tr[data-k]").first.locator("a.xl").evaluate_all("els=>els.map(e=>e.href)")
                ok(any("gmgn.ai" in h for h in hrefs) and any(("solscan" in h) or ("etherscan" in h) for h in hrefs), tag + "enlaces explorador + GMGN: " + ", ".join(h.split("/")[2] for h in hrefs))
                # alias (PIN, simulado)
                first = await pg.locator("#tbl tbody tr[data-k]").first.get_attribute("data-k")
                pg.once("dialog", lambda d: asyncio.ensure_future(d.accept("Ballena prueba")))
                await pg.locator(f'#tbl tbody tr[data-k="{first}"] button[data-alias]').click(); await pg.wait_for_timeout(800)
                ok(FAKE.get(first) == "Ballena prueba", tag + "alias enviado al box con PIN")
                ok("Ballena prueba" in await pg.locator(f'#tbl tbody tr[data-k="{first}"]').inner_text(), tag + "alias visible en la tabla")
                ok(not await pg.locator("#drawer").is_visible(), tag + "editar alias no abre el detalle")
                await pg.fill("#fSearch", "ballena"); await pg.wait_for_timeout(300)
                ok(await pg.locator("#tbl tbody tr[data-k]").count() == 1, tag + "buscar por alias")
                await pg.fill("#fSearch", "")
                # Exportar grupo: selección manual con casillas
                await pg.locator("#tbl tbody tr[data-k] [data-sel]").nth(0).check()
                await pg.locator("#tbl tbody tr[data-k] [data-sel]").nth(1).check()
                await pg.locator("#tbl tbody tr[data-k] [data-sel]").nth(2).check()
                ok(await pg.locator("#selBar").is_visible() and "3" in await pg.locator("#selBar").inner_text(), tag + "barra de selección (3)")
                ok(not await pg.locator("#drawer").is_visible(), tag + "marcar casilla no abre el detalle")
                await pg.locator('#selBar [data-export="sel"]').click(); await pg.wait_for_timeout(300)
                ok(await pg.locator("#modal").is_visible(), tag + "diálogo de exportar abierto")
                await pg.fill("#gName", "insiders bob"); await pg.locator('[data-emo="🐸"]').click(); await pg.wait_for_timeout(200)
                ax = json.loads(await pg.locator("#out-axiom").input_value()); gm = json.loads(await pg.locator("#out-gmgn").input_value())
                csv = await pg.locator("#out-csv").input_value()
                ok(len(ax) == 3 and set(ax[0]) == {"trackedWalletAddress", "name", "emoji", "alertsOn"} and ax[0]["name"] == "insiders bob 1" and ax[0]["emoji"] == "🐸", tag + "formato Axiom: " + json.dumps(ax[0], ensure_ascii=False))
                ok(len(gm) == 3 and set(gm[0]) == {"address", "name", "emoji"} and gm[2]["name"] == "insiders bob 3", tag + "formato GMGN: " + json.dumps(gm[0], ensure_ascii=False))
                ok(csv.splitlines()[0] == "address,name" and csv.splitlines()[1].endswith(",🐸 insiders bob 1"), tag + "CSV: " + csv.splitlines()[1][-30:])
                ok(await pg.locator("#gPrev").inner_text() == "🐸 insiders bob 1", tag + "vista previa de etiqueta")
                async with pg.expect_download() as dl:
                    await pg.locator('[data-dl="gmgn"]').click()
                d = await dl.value
                ok(d.suggested_filename == "gmgn-insiders-bob.json", tag + "descarga " + d.suggested_filename)
                await pg.locator('[data-cpout="axiom"]').click(); await pg.wait_for_timeout(300)
                ok("Copiado" in await pg.locator("#toast").inner_text(), tag + "copiar al portapapeles")
                await pg.locator("#grpSave").click(); await pg.wait_for_timeout(800)
                ok(GROUPS and GROUPS[0]["name"] == "insiders bob" and len(GROUPS[0]["wallets"]) == 3, tag + "grupo guardado en el box (PIN)")
                await pg.locator("[data-mclose]").click()
                ok(await pg.locator("#tbl tbody .gem").count() == 3, tag + "emoji del grupo en la tabla")
                await pg.fill("#fSearch", "insiders"); await pg.wait_for_timeout(300)
                ok(await pg.locator("#tbl tbody tr[data-k]").count() == 3, tag + "buscar por nombre de grupo"); await pg.fill("#fSearch", "")
                await pg.locator("#selClear").click()
                # desde un cluster y un bundle
                await pg.locator('#tabs button[data-tab="conn"]').click(); await pg.wait_for_timeout(300)
                await pg.locator('#connSeg [data-csub="clusters"]').click(); await pg.wait_for_timeout(300)
                if await pg.locator('#connBox [data-export^="cluster:"]').count():
                    await pg.locator('#connBox [data-export^="cluster:"]').first.click(); await pg.wait_for_timeout(300)
                    n1 = len(json.loads(await pg.locator("#out-gmgn").input_value()))
                    if D: ok(n1 == D["clusters"][0]["n"], tag + f"exportar cluster ({n1} wallets)")
                    await pg.keyboard.press("Escape")
                await pg.locator('#tabs button[data-tab="bundles"]').click(); await pg.wait_for_timeout(300)
                if await pg.locator('#bundlesBox [data-export^="bundle:"]').count():
                    await pg.locator('#bundlesBox [data-export^="bundle:"]').first.click(); await pg.wait_for_timeout(300)
                    n2 = len(json.loads(await pg.locator("#out-axiom").input_value()))
                    ok(n2 >= 2, tag + f"exportar bundle ({n2} wallets)")
                    await pg.keyboard.press("Escape")
                    await pg.locator('#bundlesBox [data-export^="btok:"]').first.click(); await pg.wait_for_timeout(300)
                    ok(len(json.loads(await pg.locator("#out-json").input_value())) >= n2, tag + "exportar todos los bundlers del token")
                    await pg.keyboard.press("Escape")
                else:
                    print("--   " + tag + "sin bundles en los datos: prueba de exportar bundle omitida")
                await pg.locator('#tabs button[data-tab="conn"]').click(); await pg.wait_for_timeout(300)
                if await pg.locator('#connBox [data-export^="cluster:"]').count():
                    await pg.locator('#connBox [data-export^="cluster:"]').first.click(); await pg.wait_for_timeout(400)
                    if shots: await pg.screenshot(path=shots + "/desktop-export.png")
                    await pg.keyboard.press("Escape")
                await pg.locator('#tabs button[data-tab="wallets"]').click()
            else:
                await pg.locator("#tbl").scroll_into_view_if_needed()
                await pg.locator("#tbl tbody tr[data-k] [data-sel]").nth(0).check()
                await pg.locator("#tbl tbody tr[data-k] [data-sel]").nth(1).check()
                await pg.locator('#selBar [data-export="sel"]').click(); await pg.wait_for_timeout(400)
                ok(await pg.locator("#modal").is_visible(), tag + "diálogo de exportar en móvil")
                if shots:
                    await pg.evaluate("document.getElementById('tip').classList.add('hide')"); await pg.screenshot(path=shots + "/mobile-export.png")
                await pg.keyboard.press("Escape")
            await connect_tests(pg, D, tag, mobile)
            await svc_tests(pg, D, tag, mobile)
            await smartx_tests(pg, D, tag, mobile)
            if D and NO_BOX: await favs_tests(pg, D, tag, mobile)
            if D and len(D["tokens"]) >= 1:
                await coin_tests(pg, D, tag, mobile)
                await tokens_tests(pg, D, tag, mobile)
            if D and not mobile and shots:
                await pg.locator("#tbl tbody tr[data-k]").nth(0).locator("[data-sel]").check()
                await pg.locator("#tbl tbody tr[data-k]").nth(1).locator("[data-sel]").check()
                await pg.locator("#tbl tbody tr[data-k]").nth(2).locator("[data-sel]").check()
                await pg.locator("#selBar [data-delsel]").click(); await pg.wait_for_timeout(300)
                await pg.evaluate("document.getElementById('tip').classList.add('hide')"); await pg.screenshot(path=shots + "/desktop-delete.png")
                await pg.keyboard.press("Escape"); await pg.locator("#selClear").click()
            if D:
                DELS.clear()
                await delete_tests(pg, D, tag, mobile)
            await ctx.close()
        await b.close()
    net = [e for e in errs if "Failed to load resource" in e]
    errs = [e for e in errs if e not in net]
    if net: print("--   avisos de red (no son errores JS): %d × %s" % (len(net), net[0][:110]))
    ok(not errs, "sin errores JS" + ("" if not errs else ": " + " | ".join(errs[:5])))
    print("\n%d fallos" % len(fails)); sys.exit(1 if fails else 0)
asyncio.run(main())
