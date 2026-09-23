#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo 'Create .env from .env.example and set OPENAI_API_KEY before running.' >&2
  exit 1
fi
chmod 600 .env
compose=(docker compose -f docker-compose.vps.yml)
"${compose[@]}" up -d --build

# A Quick Tunnel receives a new hostname on restart. Read only this container's
# current run, then allow the exact HTTPS origin in the backend.
tunnel_id=$("${compose[@]}" ps -q tunnel)
started_at=$(docker inspect --format '{{.State.StartedAt}}' "$tunnel_id")
public_url=''
for ((attempt=0; attempt<60; attempt++)); do
  public_url=$(docker logs --since "$started_at" "$tunnel_id" 2>&1 \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n 1 || true)
  [[ -n "$public_url" ]] && break
  sleep 2
done
if [[ -z "$public_url" ]]; then
  echo 'Tunnel URL missing. Check: docker compose -f docker-compose.vps.yml logs tunnel' >&2
  exit 1
fi

PUBLIC_URL="$public_url" python3 - <<'PY'
import os
from pathlib import Path

path = Path('.env')
lines = path.read_text(encoding='utf-8-sig').splitlines()
url = os.environ['PUBLIC_URL']
origins = ['http://localhost:8080', 'http://127.0.0.1:8080', url]
for line in lines:
    if line.startswith('ALLOWED_ORIGINS='):
        for origin in line.partition('=')[2].strip().strip('"').strip("'").split(','):
            if origin and not origin.endswith('.trycloudflare.com') and origin not in origins:
                origins.append(origin)
lines = [line for line in lines if not line.startswith('ALLOWED_ORIGINS=')]
lines.append('ALLOWED_ORIGINS=' + ','.join(origins))
path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
Path('runtime').mkdir(exist_ok=True)
Path('runtime/public-url.txt').write_text(url + '\n', encoding='utf-8')
PY

"${compose[@]}" up -d api
"${compose[@]}" ps
printf '\nPublic URL: %s\n' "$public_url"
printf 'If the tunnel restarts, rerun: bash scripts/vps-up.sh\n'
