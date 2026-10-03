#!/usr/bin/env bash
# Servicio 24/7 en el box (sin IA): API + túnel + cola de escaneos + alertas + publicación.
# Si el proceso de Python se cae, se relanza a los 15 s. Lo que estaba "en curso" vuelve a la cola.
#   Arrancar:  scripts/service.sh start      Parar: scripts/service.sh stop      Estado: scripts/service.sh status
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"; mkdir -p logs
exec 9>"$ROOT/.wh.lock"
flock -n 9 || { echo "ya hay un bucle en marcha"; exit 0; }
while true; do
  echo "=== $(date '+%F %T') arranque" >> logs/wallethunter.log
  python3 -m wallethunter loop >> logs/wallethunter.log 2>&1
  echo "=== $(date '+%F %T') el proceso terminó (código $?), relanzo en 15 s" >> logs/wallethunter.log
  pkill -f "cloudflared tunnel --no-autoupdate --url http://127.0.0.1:${WH_PORT:-18795}" 2>/dev/null
  if [ "$(wc -c < logs/wallethunter.log)" -gt 5000000 ]; then tail -n 3000 logs/wallethunter.log > logs/wh.tmp && mv logs/wh.tmp logs/wallethunter.log; fi
  sleep 15
done
