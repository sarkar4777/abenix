#!/usr/bin/env bash
# Checks this machine before a first run. Usage is bash scripts/doctor.sh [dev|cluster]
MODE="${1:-dev}"
FAILS=0
WARNS=0
good() { printf '  ok    %s\n' "$1"; }
bad() { printf '  FIX   %s\n' "$1"; FAILS=$((FAILS + 1)); }
note() { printf '  note  %s\n' "$1"; WARNS=$((WARNS + 1)); }
need() { # need <command> <how to get it>
  if command -v "$1" >/dev/null 2>&1; then good "$1 found"; else bad "$1 is missing. $2"; fi
}

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
echo "Abenix doctor, mode $MODE"

need docker "Install Docker Desktop, then open a new terminal."
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    good "Docker is running"
    mem_mb=$(( $(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0) / 1048576 ))
    want=8000
    [ "$MODE" = "cluster" ] && want=16000
    if [ "$mem_mb" -lt "$want" ]; then
      bad "Docker has ${mem_mb} MB of memory and this mode needs ${want} MB. Raise it in Docker Desktop settings."
    else
      good "Docker has ${mem_mb} MB of memory"
    fi
  else
    bad "Docker is installed but not running. Start Docker Desktop."
  fi
fi

if [ "$MODE" = "cluster" ]; then
  need minikube "brew install minikube"
  need kubectl "brew install kubernetes-cli"
  need helm "brew install helm"
  if command -v minikube >/dev/null 2>&1 && kubectl get nodes >/dev/null 2>&1; then
    rt=$(kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.containerRuntimeVersion}' 2>/dev/null)
    case "$rt" in
      docker*) good "minikube uses the Docker runtime" ;;
      *) bad "The cluster runtime is ${rt%%:*}. Recreate it with FRESH=true bash scripts/deploy.sh local" ;;
    esac
  fi
else
  py=""
  for c in python3.12 python3.13 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      py="$c"
      break
    fi
  done
  if [ -n "$py" ]; then good "$py is new enough"; else bad "Python 3.12 or newer is missing. brew install python@3.12"; fi
  if command -v node >/dev/null 2>&1; then
    node_major=$(node -p 'process.versions.node.split(".")[0]')
    if [ "$node_major" -ge 20 ]; then good "node $node_major found"; else bad "node $node_major is too old. brew install node@20"; fi
    [ "$node_major" -gt 22 ] && note "node $node_major is newer than the version 20 that CI uses."
  else
    bad "node is missing. brew install node@20"
  fi
  for p in 3000 8000 5432 6379 4222 7687; do
    if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
      note "Port $p is in use. dev-local stops its own processes and kubectl forwards, anything else must be stopped by you."
    fi
  done
  if [ -f .env ]; then
    good ".env exists"
    grep -q '^NATS_URL=nats://abenix-nats' .env && note "NATS_URL in .env is the in-cluster address. dev-local corrects it for the run."
  else
    bad ".env is missing. Run cp .env.example .env"
  fi
fi

if [ -f .env ] && ! grep -qE '^(ANTHROPIC_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY|AZURE_OPENAI_API_KEY)=.+' .env; then
  note "No model key in .env. Add ANTHROPIC_API_KEY, or run bash scripts/sync-claude-subscription.sh once the API is up."
fi

echo
if [ "$FAILS" -gt 0 ]; then
  echo "$FAILS thing(s) to fix, $WARNS note(s)."
  exit 1
fi
echo "Ready, $WARNS note(s)."
