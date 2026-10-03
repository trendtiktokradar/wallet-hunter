#!/usr/bin/env bash
# Publica web/data.json + box.json en la rama "data" de GitHub (un único commit que se reemplaza, force-push SOLO de esa rama).
# El token se lee de GITHUB_TOKEN_TIKTOK_RADAR en el momento (credential helper); nunca se guarda en disco ni sale en logs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUB="$ROOT/.publish"
BRANCH="${WH_BRANCH:-data}"
REMOTE="${WH_REMOTE:-https://github.com/trendtiktokradar/wallet-hunter.git}"
TOKEN_VAR="${WH_TOKEN_VAR:-GITHUB_TOKEN_TIKTOK_RADAR}"
[ -n "${!TOKEN_VAR:-}" ] || { echo "Falta $TOKEN_VAR"; exit 1; }
CRED=(-c credential.helper= -c "credential.helper=!f() { echo username=x-access-token; echo password=\${$TOKEN_VAR}; }; f")
if [ ! -d "$PUB/.git" ]; then git init -q "$PUB"; git -C "$PUB" remote add origin "$REMOTE"; fi
git -C "$PUB" remote set-url origin "$REMOTE"
G() { git -C "$PUB" "${CRED[@]}" -c user.name="wallet-hunter-bot" -c user.email="wallet-hunter-bot@users.noreply.github.com" "$@"; }
cp "$ROOT/web/data.json" "$PUB/data.json"
python3 - "$ROOT/web/data.json" "$PUB/box.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
json.dump(d.get("box") or {}, open(sys.argv[2], "w"))
PY
printf '# Rama de datos de Wallet Hunter\nLa escribe el box automáticamente. No editar a mano.\n' > "$PUB/README.md"
mkdir -p "$PUB/web"; echo '{"git":{"deploymentEnabled":false}}' > "$PUB/web/vercel.json"; cp "$PUB/web/vercel.json" "$PUB/vercel.json"
G symbolic-ref HEAD "refs/heads/$BRANCH"
G add -A
if G rev-parse -q --verify HEAD >/dev/null; then G commit -q --amend --reset-author -m "data $(date -u +%FT%TZ)"; else G commit -q -m "data $(date -u +%FT%TZ)"; fi
G push -q --force origin "HEAD:refs/heads/$BRANCH"
echo "$(date '+%F %T') publicado en rama $BRANCH"
