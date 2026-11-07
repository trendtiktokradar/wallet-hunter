#!/usr/bin/env bash
# Modo bajo demanda: API + worker de map/connect nuevos + túnel.
# No vigilancia, no Telegram, no publicación periódica, no cola antigua.
# Si el proceso cae, se relanza. El corte de trabajos se recalcula: lo anterior sigue sin ejecutarse.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"; mkdir -p logs
exec 9>"$ROOT/.wh-ondemand.lock"
flock -n 9 || { echo "el modo bajo demanda ya está en marcha"; exit 0; }
while true; do
  echo "=== $(date '+%F %T') bajo demanda" >> logs/wallethunter.log
  python3 -m wallethunter serve >> logs/wallethunter.log 2>&1
  echo "=== $(date '+%F %T') bajo demanda terminó (código $?), relanzo en 15 s" >> logs/wallethunter.log
  pkill -f "cloudflared tunnel --no-autoupdate --url http://127.0.0.1:${WH_PORT:-18795}" 2>/dev/null
  sleep 15
done
