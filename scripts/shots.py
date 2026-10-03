import sys, asyncio
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8790/"
OUT = "/workspace/solana-wallet-hunter/screenshots"
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        errs = []
        for name, vp, mobile in [("desktop", {"width": 1440, "height": 900}, False), ("mobile", {"width": 390, "height": 844}, True)]:
            ctx = await b.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, device_scale_factor=2 if mobile else 1)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append("console:" + m.text) if m.type == "error" else None)
            await pg.goto(URL, wait_until="networkidle")
            await pg.wait_for_timeout(2500)
            await pg.screenshot(path=f"{OUT}/{name}-wallets.png", full_page=not mobile)
            # filtro de etiquetas activo: todas visibles, seleccionadas resaltadas, las de 0 en gris
            for t in ("fondeo_sync", "sniper"):
                await pg.locator(f'#chips .chip[data-tag="{t}"]').click(); await pg.wait_for_timeout(300)
            if mobile:
                await pg.locator("#tagSel").scroll_into_view_if_needed()
            await pg.mouse.move(5, 5); await pg.evaluate("document.getElementById('tip').classList.add('hide')")
            await pg.screenshot(path=f"{OUT}/{name}-tagfilter.png", full_page=not mobile)
            await pg.locator("#clrTags").click(); await pg.wait_for_timeout(300)
            if mobile:
                await pg.locator("#tbl").scroll_into_view_if_needed(); await pg.wait_for_timeout(300)
                await pg.screenshot(path=f"{OUT}/{name}-table.png")
                await pg.evaluate("window.scrollTo(0,0)")
            for tab in ["Bundles", "Tokens", "Conexiones", "Escanear", "Trabajos"]:
                loc = pg.locator("#tabs button", has_text=tab).first
                try:
                    await loc.click(timeout=3000); await pg.wait_for_timeout(700)
                    await pg.screenshot(path=f"{OUT}/{name}-{tab.lower()}.png", full_page=not mobile)
                except Exception as e:
                    errs.append(f"tab {tab}: {e}")
            if not mobile:
                await pg.locator('button[data-tab="wallets"]').click()
                await pg.wait_for_timeout(500)
                row = pg.locator("#tbl tbody tr").first
                if await row.count():
                    await row.click(); await pg.wait_for_timeout(800)
                    await pg.screenshot(path=f"{OUT}/{name}-detail.png")
            await ctx.close()
        await b.close()
        print("\n".join(errs) or "no errors")
asyncio.run(main())
