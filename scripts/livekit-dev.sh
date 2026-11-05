#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/livekit-dev.yaml"
CMD="${1:-status}"

case "$CMD" in
  up)
    echo ">> Starting LiveKit dev server…"
    docker compose -f "$COMPOSE_FILE" up -d
    echo ">> Waiting for health…"
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if docker compose -f "$COMPOSE_FILE" exec -T livekit wget --spider -q http://localhost:7880 2>/dev/null; then
        echo ">> LiveKit dev ready on ws://localhost:7880"
        echo ">> Dev keys: LIVEKIT_API_KEY=devkey  LIVEKIT_API_SECRET=secret"
        echo ">> Run:      eval \"\$($0 env)\""
        exit 0
      fi
      sleep 1
    done
    echo "!! LiveKit did not become healthy within 10s — check \`docker compose logs\`"
    exit 1
    ;;
  down)
    docker compose -f "$COMPOSE_FILE" down
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  env)
    cat <<'EOF'
export LIVEKIT_URL=ws://localhost:7880
export LIVEKIT_API_KEY=devkey
export LIVEKIT_API_SECRET=secret
export LIVEKIT_MEET_URL=https://meet.livekit.io
EOF
    ;;
  *)
    echo "Usage: $0 {up|down|status|env}" >&2
    exit 2
    ;;
esac
