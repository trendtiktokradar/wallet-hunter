"""Etiquetas (con explicación en español) y score 0-100. Todo reglas fijas y ajustables aquí."""
import math, time

# id -> (texto, explicación, color)
TAGS = {
    "activa": ("Activa", "Ha operado en los últimos 3 días.", "green"),
    "temprano": ("Comprador temprano", "Entra de media en los primeros 10 minutos desde el lanzamiento, o estuvo entre los primeros 50 compradores de un token escaneado.", "teal"),
    "scalper": ("Scalper/flipper", "Mantiene las posiciones muy poco tiempo (mediana < 15 min) con al menos 8 tokens.", "orange"),
    "bot": ("Bot", "Actividad imposible para un humano: > 150 swaps al día, > 1000 transacciones en < 24 h o hold mediano < 20 s.", "red"),
    "sniper": ("Sniper", "Compró en los primeros 3 slots/bloques tras el lanzamiento de algún token escaneado, o su entrada mediana es < 30 s.", "red"),
    "nueva": ("Wallet nueva", "Su primera transacción tiene menos de 7 días.", "lime"),
    "rentable": ("Rentable", "PnL positivo en la ventana (realizado + no realizado).", "green"),
    "pumpfun": ("Especialista pump.fun", "Al menos el 60 % de los tokens que tradea son de pump.fun.", "violet"),
    "grupo": ("Grupo coordinado", "Pertenece a un cluster de 3 o más wallets vinculadas (fondeo común, transferencias entre ellas o bundles repetidos).", "amber"),
    "bundle": ("Miembro de bundle", "Compró en el mismo slot/bloque que otras wallets al principio de un token (típico de bundles/Jito).", "purple"),
    "hub_cex": ("Fondeada desde hub/CEX", "Su primer fondeo viene de un exchange conocido o de un 'hub' que ha fondeado a varias wallets de la base.", "orange"),
    "truncado": ("Historial truncado", "Tiene tanta actividad que no se pudo leer todo (historial de 30 días o fecha de creación incompletos). Las métricas son aproximadas.", "gray"),
    "vende_pumps": ("Vende en pumps", "En la mitad o más de los tokens que vende, vende a 2x o más de su precio medio de compra.", "teal"),
    "pequena": ("Tamaño pequeño", "Compra media por debajo de 75 $.", "gray"),
    "horario": ("Horario concentrado", "El 70 % o más de sus operaciones caen en la misma franja de 6 horas (UTC).", "gray"),
    "insuficiente": ("Datos insuficientes", "Menos de 3 tokens con compra en la ventana: las métricas no son fiables.", "gray"),
    "insider": ("Insider/dev-linked", "Vinculada al creador de un token escaneado: fondeada por el dev, fondeó al dev, mismo fondeador que el dev o compró en el mismo slot de la creación.", "red"),
    "copy": ("Copy-trader", "Compra repetidamente justo después (1-3 slots/bloques) de la misma wallet en 3 o más tokens.", "amber"),
    "wr_alto": ("Win rate alto", "Win rate ≥ 60 % con al menos 10 tokens.", "green"),
    "consistente": ("Beneficio consistente", "Rentable, win rate ≥ 55 % con 8+ tokens y ningún token aporta más del 50 % del beneficio.", "green"),
    "ballena": ("Ballena", "Saldo ≥ 50.000 $ o compra media ≥ 2.000 $.", "blue"),
    "raydium": ("Usuario Raydium", "Al menos el 30 % de sus swaps pasan por Raydium.", "blue"),
    "swing": ("Swing", "Hold mediano entre 1 y 30 días.", "blue"),
    "one_hit": ("One-hit wonder", "Más del 70 % de su beneficio viene de un único token y su win rate es < 40 %.", "amber"),
    "smart": ("Smart money", "Score ≥ 65, PnL ≥ 5.000 $, win rate ≥ 50 % con 8+ tokens y sin señales de bot.", "green"),
    "una_vez": ("Una vez", "Solo ha tradeado 1 token en la ventana.", "gray"),
    "distribuidor": ("Distribuidor", "Ha enviado fondos a 5 o más wallets distintas (fuera de swaps): posible wallet madre que reparte.", "amber"),
    "fondeo_sync": ("Fondeo sincronizado", "Recibió fondos casi a la vez (≤ 2 min) que otros 3+ compradores tempranos, poco antes de comprar el mismo token: patrón típico de grupo/pump coordinado.", "red"),
    "rugs": ("Expuesta a rugs", "En el 30 % o más de sus tokens el precio cayó más de un 90 % desde su entrada.", "red"),
}
CEX_TAGS = ["Binance", "MEXC", "Gate.io", "Coinbase", "Bitget", "KuCoin", "OKX", "Bybit", "Kraken"]
for cx in CEX_TAGS:
    TAGS["cex_" + cx.lower().replace(".", "")] = (f"Fondeada desde {cx}", f"Su primer fondeo vino de una hot wallet conocida de {cx}.", "orange")


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def compute_tags(m, w, g, native_usd, now=None):
    """m: métricas, w: fila wallet (dict), g: señales de grafo (dict)."""
    now = now or int(time.time())
    t = set()
    n = m.get("tokens") or 0
    wr = m.get("win_rate")
    la = w.get("last_activity")
    if la and now - la < 3 * 86400:
        t.add("activa")
    ae = m.get("avg_entry_s")
    if (ae is not None and ae <= 600 and n >= 2) or g.get("early_rank_min") is not None and g["early_rank_min"] <= 50:
        t.add("temprano")
    mh = m.get("median_hold_s")
    if mh is not None and mh < 900 and n >= 8:
        t.add("scalper")
    if w.get("prefiltered") or (m.get("trades_per_day") or 0) > 150 or (mh is not None and mh < 20 and n >= 15):
        t.add("bot")
    if g.get("sniper") or (ae is not None and ae < 30 and n >= 3):
        t.add("sniper")
    ft = w.get("first_tx_ts")
    if ft and not w.get("age_truncated") and now - ft < 7 * 86400:
        t.add("nueva")
    if (m.get("pnl_native") or 0) > 0 and n:
        t.add("rentable")
    if n >= 3 and (m.get("pumpfun_share") or 0) >= 0.6:
        t.add("pumpfun")
    if (g.get("cluster_size") or 0) >= 3:
        t.add("grupo")
    if g.get("bundles"):
        t.add("bundle")
    fl = w.get("funder_label")
    if fl or g.get("funder_is_hub"):
        t.add("hub_cex")
    if fl:
        key = "cex_" + fl.lower().replace(".", "")
        if key in TAGS:
            t.add(key)
    if w.get("history_truncated") or w.get("age_truncated"):
        t.add("truncado")
    if (m.get("pump_seller_share") or 0) >= 0.5 and n >= 3:
        t.add("vende_pumps")
    size_usd = (m.get("avg_size_native") or 0) * native_usd
    if m.get("avg_size_native") is not None and size_usd < 75:
        t.add("pequena")
    if (m.get("hour_concentration") or 0) >= 0.7 and (m.get("trades") or 0) >= 15:
        t.add("horario")
    if n < 3 and not w.get("prefiltered"):
        t.add("insuficiente")
    if g.get("insider"):
        t.add("insider")
    if g.get("copy_of"):
        t.add("copy")
    if wr is not None and wr >= 0.6 and n >= 10:
        t.add("wr_alto")
    ts = m.get("top_token_share")
    if (m.get("pnl_native") or 0) > 0 and wr is not None and wr >= 0.55 and n >= 8 and ts is not None and ts <= 0.5:
        t.add("consistente")
    if (w.get("balance_native") or 0) * native_usd >= 50000 or size_usd >= 2000:
        t.add("ballena")
    if (m.get("raydium_share") or 0) >= 0.3:
        t.add("raydium")
    if mh is not None and 86400 <= mh <= 30 * 86400:
        t.add("swing")
    if ts is not None and ts > 0.7 and wr is not None and wr < 0.4 and n >= 3:
        t.add("one_hit")
    if n == 1:
        t.add("una_vez")
    if (g.get("distinct_out") or 0) >= 5:
        t.add("distribuidor")
    if g.get("fund_sync"):
        t.add("fondeo_sync")
    if (m.get("rug_share") or 0) >= 0.3 and n >= 3:
        t.add("rugs")
    sc = score(m, t)
    if sc >= 65 and (m.get("pnl_usd") or 0) >= 5000 and wr is not None and wr >= 0.5 and n >= 8 and "bot" not in t:
        t.add("smart")
    order = list(TAGS)
    return sorted(t, key=order.index), sc


def score(m, tags):
    n = m.get("tokens") or 0
    if n == 0:
        return 0
    wins = m.get("wins") or 0
    wr_b = (wins + 1) / (n + 2)
    s = 30 * _clamp((wr_b - 0.3) / 0.5)
    pnl_usd = m.get("pnl_usd") or 0
    s += 25 * _clamp(math.log10(max(pnl_usd, 0) + 1) / 5)
    roi = m.get("roi") or 0
    s += 15 * _clamp(roi / 1.5)
    ts = m.get("top_token_share")
    if ts is not None and n >= 5:
        s += 10 * (1 - ts)
    s += 10 * _clamp(n / 25)
    ae = m.get("avg_entry_s")
    s += 10 * _clamp(1 - ae / 3600) if ae is not None else 3
    if pnl_usd < 0:
        s *= 0.6
    if "bot" in tags:
        s *= 0.4
    if "insider" in tags or "bundle" in tags:
        s -= 8
    if "rugs" in tags:
        s -= 5
    if "insuficiente" in tags:
        s = min(s, 35)
    return int(round(_clamp(s, 0, 100)))


def tag_defs():
    return [{"id": k, "label": v[0], "help": v[1], "color": v[2]} for k, v in TAGS.items()]
