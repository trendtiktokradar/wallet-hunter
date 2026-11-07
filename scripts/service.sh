#!/usr/bin/env bash
# start | stop | status | ensure | publish-link | full
# start/ensure = modo bajo demanda (API, map/connect nuevos, túnel). No es el bucle antiguo.
# full = bucle antiguo (cola, vigilancia, Telegram, publicación periódica). Hay que pedirlo.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ondemand() { pgrep -f "$ROOT/scripts/ondemand.sh" >/dev/null; }
full() { pgrep -f "$ROOT/scripts/loop.sh" >/dev/null; }
case "${1:-status}" in
  start|ensure)
    if ondemand || full; then echo "ya en marcha"; exit 0; fi
    [ -n "${HELIUS_API_KEY:-}" ] || echo "aviso: HELIUS_API_KEY no está en el entorno (el mapa dirá que no puede leer la cadena)"
    cd "$ROOT" && nohup setsid "$ROOT/scripts/ondemand.sh" >/dev/null 2>&1 &
    sleep 1
    echo "bajo demanda arrancado: API :${WH_PORT:-18795}, worker de map/connect nuevos, túnel si WH_TUNNEL no es 0"
    echo "no hay vigilancia, Telegram, publicación periódica ni vaciado de colas antiguas"
    echo "cuando el túnel tenga URL: scripts/service.sh publish-link" ;;
  full)
    if ondemand || full; then echo "ya en marcha"; exit 0; fi
    echo "modo completo: cola de escaneos, vigilancia (dormidas activas por defecto), Telegram si hay token, y publicación periódica"
    cd "$ROOT" && nohup setsid "$ROOT/scripts/loop.sh" >/dev/null 2>&1 &
    sleep 1; echo "bucle completo arrancado" ;;
  publish-link)
    python3 -m wallethunter publish-link ;;
  stop)
    pkill -f "$ROOT/scripts/ondemand.sh" 2>/dev/null || true
    pkill -f "$ROOT/scripts/loop.sh" 2>/dev/null || true
    pkill -f "python3 -m wallethunter serve" 2>/dev/null || true
    pkill -f "python3 -m wallethunter loop" 2>/dev/null || true
    pkill -f "cloudflared tunnel --no-autoupdate --url http://127.0.0.1:${WH_PORT:-18795}" 2>/dev/null || true
    echo "parado" ;;
  status)
    ondemand && echo "bajo demanda: en marcha" || echo "bajo demanda: parado"
    full && echo "bucle completo: en marcha" || echo "bucle completo: parado"
    curl -s -m 5 "http://127.0.0.1:${WH_PORT:-18795}/health" && echo
    grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$ROOT/logs/cloudflared.log" 2>/dev/null | tail -1
    tail -n 5 "$ROOT/logs/wallethunter.log" 2>/dev/null ;;
  *)
    echo "uso: scripts/service.sh start|ensure|stop|status|publish-link|full" >&2
    exit 2 ;;
esac
