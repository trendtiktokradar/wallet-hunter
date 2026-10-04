"""Prueba rápida de las etiquetas de 3 estados en el panel (por defecto el EN VIVO): 1.º clic ✓ con (verde), 2.º ✕ sin (rojo,
tachada), 3.º quitar; con ratón (también doble clic rápido) y con toques en móvil. Solo lee: no llama a la API del box.
Uso: python scripts/uitest_tags.py [URL] [sha_esperado]   (con sha comprueba que app.js/style.css/config.js llevan ?v=sha)"""
import sys, asyncio
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else "https://trendtiktokradar.github.io/wallet-hunter/"
SHA = sys.argv[2] if len(sys.argv) > 2 else None
FAILS = []


def ok(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond: FAILS.append(msg)


async def run(b, mobile):
    tag = "[móvil] " if mobile else "[escritorio] "
    ctx = await b.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}, is_mobile=mobile, has_touch=mobile)
    pg = await ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(URL + ("&" if "?" in URL else "?") + "nocache=" + str(id(ctx)), wait_until="networkidle"); await pg.wait_for_timeout(2500)
    if SHA:
        build = await pg.evaluate("window.WH_BUILD")
        srcs = await pg.evaluate("[...document.querySelectorAll('link[rel=stylesheet],script[src]')].map(e=>e.getAttribute('href')||e.getAttribute('src'))")
        ok(build == SHA, tag + f"app.js cargado = despliegue {SHA} (WH_BUILD={build})")
        ok(all(("?v=" + SHA) in s for s in srcs), tag + "ficheros versionados: " + ", ".join(srcs))
    tot = lambda: pg.locator("#fCount").inner_text()
    chips = await pg.locator("#chips .chip").evaluate_all("els=>els.map(e=>[e.dataset.tag, +(e.querySelector('.n')||{}).textContent||0])")
    n_all = int((await tot()).split()[0])
    t = next((c for c, n in chips if 0 < n < n_all and c in ("activa", "rentable", "temprano", "pumpfun")), None) or next(c for c, n in chips if 0 < n < n_all)
    sel = f'#chips .chip[data-tag="{t}"]'
    async def st(): return await pg.locator(sel).get_attribute("aria-pressed")
    async def look():
        return await pg.locator(sel).evaluate("e=>{var s=getComputedStyle(e);return {cls:e.className, deco:s.textDecorationLine, color:s.color, border:s.borderColor}}")
    async def press(gap=300):
        el = pg.locator(sel); await el.scroll_into_view_if_needed()
        if mobile:
            bb = await el.bounding_box(); await pg.touchscreen.tap(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        else:
            await el.click()
        await pg.wait_for_timeout(gap)
    base = await look()
    await press(); s1, l1 = await st(), await look()
    ok(s1 == "true" and "sel" in l1["cls"], tag + f"1.º {'toque' if mobile else 'clic'} en «{t}»: ✓ con (verde) · {l1['border']}")
    await press(); s2, l2 = await st(), await look()
    ok(s2 == "mixed" and "exc" in l2["cls"] and l2["deco"] == "line-through", tag + f"2.º: ✕ sin (rojo, tachada) · color {l2['color']}")
    ok(l2["color"] != base["color"], tag + "la excluida cambia de color respecto a la normal")
    ok("sin=" + t in await pg.evaluate("decodeURIComponent(location.hash)"), tag + "URL: sin=" + t)
    await press(); ok(await st() == "false" and int((await tot()).split()[0]) == n_all, tag + "3.º: quitar (todas las wallets otra vez)")
    if not mobile:   # doble clic rápido (≈ 80 ms): también debe pasar por ✓ y quedarse en ✕
        el = pg.locator(sel); await el.click(); await pg.wait_for_timeout(80); await el.click(); await pg.wait_for_timeout(300)
        ok(await st() == "mixed", tag + "doble clic rápido → ✕ sin")
        await el.click(); await pg.wait_for_timeout(300)
    ok(not errs, tag + "sin errores JS" + (": " + errs[0] if errs else ""))
    await ctx.close()


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        for m in (False, True):
            await run(b, m)
        await b.close()
    print("\n%d fallos" % len(FAILS)); sys.exit(1 if FAILS else 0)

asyncio.run(main())
