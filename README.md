# 🎯 Wallet Hunter (multichain)

Clon mejorado del "Solana Wallet Hunter": le pasas CAs (o wallets sueltas) y saca las wallets que tradearon la coin
(primero los compradores tempranos), lee 30 días de actividad de cada una y calcula PnL, ROI, win rate, hold, entrada,
tamaño, saldo, edad, **score 0-100**, **etiquetas**, **bundles** y **clusters**. Todo se acumula en una base SQLite.

**Sin IA.** Reglas fijas en Python (solo librería estándar). El día a día cuesta 0 tokens.

## Arquitectura
```
 navegador (móvil/PC)                      box (Python, 24/7)                          GitHub (rama data)
┌──────────────────────┐  POST + PIN   ┌─────────────────────────────┐  data.json   ┌──────────────────┐
│ panel web estático   │ ───túnel────▶ │ API :18795 → cola (Trabajos) │ ───────────▶ │ data.json        │
│ (GitHub Pages/Vercel)│ ◀──datos───── │ escáner → SQLite → data.json │   box.json   │ box.json (URL)   │
└──────────────────────┘  en directo   └─────────────────────────────┘              └──────────────────┘
        └──────────── si el box está apagado: lee data.json de GitHub (último publicado) ──────┘
```
- El panel **lee** los datos del box en directo (túnel) o, si el box no responde, de la rama `data` de GitHub.
- **Escanear desde la web**: el formulario manda los CAs con el PIN al box (Cloudflare quick tunnel, gratis y sin cuenta).
  El box los mete en la cola (`jobs` en SQLite), los procesa uno a uno y la pestaña **Trabajos** muestra
  pendiente / en curso / hecho / error. La URL del túnel cambia en cada arranque y se publica sola en `box.json`.
- Respaldo opcional en Vercel: `web/api/queue.js` guarda la petición en `queue.json` (rama `queue`) si el box está
  apagado; el box la recoge al volver (necesita `WH_PIN` y `WH_GH_TOKEN` en Vercel).

## Fuentes
| Fuente | Uso | Límites (gratis) |
|---|---|---|
| Helius (`HELIUS_API_KEY`) | Solana: transacciones del token, historial de wallets, fondeo, saldos, precios DAS | 1M créditos/mes, 10 req/s. Si la key tiene `getTransactionsForAddress` se usa (1.000 tx = 100 créditos) |
| Etherscan V2 (`ETHERSCAN_API_KEY`) | Ethereum, Arbitrum, Polygon… | 3 llamadas/s, 100k/día. **BNB y Base NO entran en el plan gratis** |
| Blockscout PRO (`BLOCKSCOUT_API_KEY`, opcional) | Base, Robinhood Chain (Etherscan no la soporta) | key gratis en dev.blockscout.com. Sin key las instancias públicas dan ~10 peticiones cada ~15 min (inservible) |
| DexScreener / GeckoTerminal | pools, fecha de lanzamiento, precios | límite por IP (el box lo comparte con otros programas: reintenta con espera) |
| Kraken | precio SOL/ETH/BNB/POL en USD | público |

## Métricas (ventana 30 días)
- **PnL** = ventas + valor actual de lo que queda − compras (por token; tokens solo con ventas se ignoran). En nativo y en USD (× precio Kraken).
- **ROI** = PnL ÷ invertido. **Win rate** = tokens con PnL > 0 ÷ tokens (entre paréntesis nº de tokens).
- **Hold med.** = mediana (primera compra → venta). **Entrada med.** = mediana (lanzamiento → primera compra).
- **Tamaño med.** = compra media. **Edad** = primera transacción ('>' = historial demasiado largo para leerlo entero).
- **Score** 0-100 (`wallethunter/tags.py`): win rate bayesiano 30, PnL 25, ROI 15, consistencia 10, nº tokens 10, entrada temprana 10;
  ×0,6 si PnL < 0, ×0,4 si bot, −8 bundle/insider, −5 rugs, máx. 35 con datos insuficientes.
- **Etiquetas**: todas las de la app original (Activa, Comprador temprano, Scalper, Bot, Sniper, Wallet nueva, Rentable, Especialista pump.fun,
  Grupo coordinado, Miembro de bundle, Fondeada desde hub/CEX y por exchange, Historial truncado, Vende en pumps, Tamaño pequeño,
  Horario concentrado, Datos insuficientes, Insider/dev-linked, Copy-trader, Win rate alto, Beneficio consistente, Ballena,
  Usuario Raydium, Swing, One-hit wonder, Smart money, Una vez, Distribuidor, Expuesta a rugs) + **Fondeo sincronizado** (nueva).
  Cada una tiene su explicación en el panel (ratón o pulsación larga).
- **Bundles**: 2+ wallets que compran en el mismo slot/bloque en los primeros 5 slots (3+ hasta el slot 150).
- **Clusters**: mismo fondeador (también a 2 saltos), una fondea a otra, transferencias entre ellas, mismo CEX en ≤15 min con importe ±10 %,
  **fondeo sincronizado** (3+ compradores tempranos reciben fondos con ≤2 min de diferencia antes de comprar) y bundles repetidos.
- **Bot prefiltrado**: 1.000 transacciones en < 24 h → no se descarga su historial (ahorra créditos).
- **Cruce de coins** (pestaña Conexiones): wallets que estuvieron en el top 50 de compradores de 2+ tokens escaneados.
- CEX: lista inicial de hot wallets en `wallethunter/cex.py` (ampliable en `state/cex_extra.json`).

## Uso en el box
```bash
cd /workspace/solana-wallet-hunter
python3 -m wallethunter scan-token solana <CA>         # o: ethereum | bsc | base | arbitrum | polygon | robinhood | auto
python3 -m wallethunter scan-wallets solana <wallet> ...
python3 -m wallethunter set-pin                         # PIN de la web (se guarda solo el hash en state/pin.json)
python3 -m wallethunter status
python3 -m unittest discover -s tests                   # tests con datos sintéticos
python3 -m http.server 8790 -d web                      # vista local
```
Servicio (API + túnel + cola + alertas + publicación):
```bash
scripts/service.sh start     # nohup setsid scripts/loop.sh (relanza Python si se cae; lo "en curso" vuelve a la cola)
scripts/service.sh status
scripts/service.sh stop
```
Si el box se reinicia hay que volver a lanzar `scripts/service.sh start` (igual que TikTok Radar). Tras añadir una key nueva
(tarjeta segura) hay que reiniciar el servicio (`stop` + `start`) para que la vea.

Ajustes en `config.json` (máx. wallets por token, páginas de historial, umbrales de bundles/clusters, límites de cada API, alertas).

## Alertas de Telegram (apagadas por defecto)
Se activan desde la pestaña ⭐ Mis wallets. Vigilan las ⭐ cada N minutos y avisan cuando les entra ≥ X $ (o ≥ X SOL),
opcionalmente solo si viene de un exchange, de un fondeador conocido o de otra wallet de la base.
Sin `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` se guardan y se ven en el panel, pero no se envían.
Coste Helius: 1 crédito por wallet y pasada (+100 si hay transacciones nuevas).

## Privacidad
Los datos (wallets, tokens, trabajos) se publican en un repo **público** como TikTok Radar. Los ⭐, alias, ajustes y alertas
**no** se publican: viven en el box y se piden con PIN.
