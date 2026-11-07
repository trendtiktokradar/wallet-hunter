#!/usr/bin/env bash
# Publica SOLO box.json en la rama data (la URL del túnel). No reescribe el JSON del panel ni hace force-push
# y no arranca vigilancia ni la cola. El JSON ya viene escrito por `python3 -m wallethunter publish-link`.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:?falta la ruta del JSON}"
PUB="$ROOT/.publish"
BRANCH="${WH_BRANCH:-data}"
REMOTE="${WH_REMOTE:-https://github.com/trendtiktokradar/wallet-hunter.git}"
TOKEN_VAR="${WH_TOKEN_VAR:-GITHUB_TOKEN_TIKTOK_RADAR}"
[ -n "${!TOKEN_VAR:-}" ] || { echo "Falta $TOKEN_VAR"; exit 1; }
python3 - "$SRC" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
if set(d) - {"url", "updated", "pin_set", "mode"}:
    raise SystemExit("box.json con campos de más")
if not str(d.get("url", "")).startswith("https://") or d.get("mode") != "on-demand":
    raise SystemExit("enlace no válido")
PY
CRED=(-c credential.helper= -c "credential.helper=!f() { echo username=x-access-token; echo password=\${$TOKEN_VAR}; }; f")
if [ ! -d "$PUB/.git" ]; then git init -q "$PUB"; git -C "$PUB" remote add origin "$REMOTE"; fi
git -C "$PUB" remote set-url origin "$REMOTE"
G() { git -C "$PUB" "${CRED[@]}" -c user.name="wallet-hunter-bot" -c user.email="wallet-hunter-bot@users.noreply.github.com" "$@"; }
G fetch -q origin "$BRANCH"
G checkout -q -B "$BRANCH" "origin/$BRANCH"
cp "$SRC" "$PUB/box.json"
G add box.json
if G diff --cached --quiet; then echo "box.json sin cambios"; exit 0; fi
G commit -q -m "box $(date -u +%FT%TZ)"
G push -q origin "HEAD:refs/heads/$BRANCH"
echo "$(date '+%F %T') enlace publicado en $BRANCH/box.json"
