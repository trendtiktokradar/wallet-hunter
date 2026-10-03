#!/usr/bin/env bash
# start | stop | status | ensure (ensure = arrancar solo si no está en marcha; útil tras reiniciar el box)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
running() { pgrep -f "$ROOT/scripts/loop.sh" >/dev/null; }
case "${1:-status}" in
  start|ensure)
    if running; then echo "ya en marcha"; exit 0; fi
    [ -n "${HELIUS_API_KEY:-}" ] || echo "aviso: HELIUS_API_KEY no está en el entorno"
    cd "$ROOT" && nohup setsid "$ROOT/scripts/loop.sh" >/dev/null 2>&1 &
    sleep 1; echo "arrancado" ;;
  stop)
    pkill -f "$ROOT/scripts/loop.sh"; pkill -f "python3 -m wallethunter loop"; pkill -f "cloudflared tunnel --no-autoupdate --url http://127.0.0.1:${WH_PORT:-18795}"; echo "parado" ;;
  status)
    running && echo "bucle: en marcha" || echo "bucle: parado"
    curl -s -m 5 "http://127.0.0.1:${WH_PORT:-18795}/health" && echo
    grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$ROOT/logs/cloudflared.log" 2>/dev/null | tail -1
    tail -n 5 "$ROOT/logs/wallethunter.log" 2>/dev/null ;;
esac
