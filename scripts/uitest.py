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
PLAN = None if os.environ.get("UITEST_PLAN_NONE") == "1" else {}   # respuesta simulada de plan_token; None = el box no la da (el panel usa su estimación)

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
    elif req.url.endswith("/api/favs"):
        out = {"ok": True, "favs": []}
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
    ok(not await pg.locator("#coinHead").is_visible() and "#coin=" not in pg.url, tag + "«Ver todas las coins» limpia")
    # botón Ver wallets en Tokens y Trabajos
    await pg.locator('#tabs button[data-tab="tokens"]').click(); await pg.wait_for_timeout(300)
    await pg.locator('#tokensBox [data-coin]').first.click(); await pg.wait_for_timeout(400)
    ok(await pg.locator("#coinHead").is_visible() and await pg.locator("#tab-wallets").is_visible(), tag + "Tokens → «Ver wallets» abre Wallets filtrado")
    await pg.locator('#tabs button[data-tab="jobs"]').click(); await pg.wait_for_timeout(300)
    nj = await pg.locator('#jobsBox [data-coin]').count()
    ok(nj >= 1, tag + f"Trabajos → botones «Ver wallets» ({nj})")
    if nj:
        await pg.locator('#jobsBox [data-coin]').first.click(); await pg.wait_for_timeout(400)
        ok(await pg.locator("#coinHead").is_visible(), tag + "Trabajos → «Ver wallets» abre la coin")
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
                    else: body = open(os.environ.get("UITEST_DATA", "/tmp/whweb/data.json"), encoding="utf-8").read()
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
            if D and len(D["tokens"]) >= 1:
                await coin_tests(pg, D, tag, mobile)
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
