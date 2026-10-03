"""Prueba de la interfaz con Playwright (sin tocar el box real: las llamadas /api/* se simulan).
Uso: python scripts/uitest.py [URL]   (por defecto la vista local http://127.0.0.1:8797/)"""
import sys, json, asyncio, time
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/"
shots = sys.argv[2] if len(sys.argv) > 2 else None
FAKE = {}
GROUPS = []

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
    else:
        out = {"ok": True}
    await route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(out))

async def main():
    fails, errs = [], []
    def ok(cond, msg):
        print(("OK   " if cond else "FAIL ") + msg)
        if not cond: fails.append(msg)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        for mobile in (False, True):
            ctx = await b.new_context(accept_downloads=True, viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}, is_mobile=mobile, has_touch=mobile)
            await ctx.add_init_script("localStorage.setItem('wh_pin','test-pin')")
            await ctx.route("**/api/**", fake_api)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append("console: " + m.text) if m.type == "error" else None)
            await pg.goto(URL, wait_until="networkidle"); await pg.wait_for_timeout(2500)
            tag = "[móvil] " if mobile else "[escritorio] "
            D = await pg.evaluate("fetch('data.json').then(r=>r.json()).catch(()=>null)") if "127.0.0.1" in URL else None
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
                await pg.locator(f'#tbl tbody tr[data-k="{first}"] button.edit').click(); await pg.wait_for_timeout(800)
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
                await pg.locator('#connBox [data-export^="cluster:"]').first.click(); await pg.wait_for_timeout(300)
                n1 = len(json.loads(await pg.locator("#out-gmgn").input_value()))
                if D: ok(n1 == D["clusters"][0]["n"], tag + f"exportar cluster ({n1} wallets)")
                await pg.keyboard.press("Escape")
                await pg.locator('#tabs button[data-tab="bundles"]').click(); await pg.wait_for_timeout(300)
                await pg.locator('#bundlesBox [data-export^="bundle:"]').first.click(); await pg.wait_for_timeout(300)
                n2 = len(json.loads(await pg.locator("#out-axiom").input_value()))
                ok(n2 >= 2, tag + f"exportar bundle ({n2} wallets)")
                if shots: await pg.screenshot(path=shots + "/desktop-export.png")
                await pg.keyboard.press("Escape")
                await pg.locator('#bundlesBox [data-export^="btok:"]').first.click(); await pg.wait_for_timeout(300)
                ok(len(json.loads(await pg.locator("#out-json").input_value())) >= n2, tag + "exportar todos los bundlers del token")
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
            await ctx.close()
        await b.close()
    ok(not errs, "sin errores JS" + ("" if not errs else ": " + " | ".join(errs[:5])))
    print("\n%d fallos" % len(fails)); sys.exit(1 if fails else 0)
asyncio.run(main())
